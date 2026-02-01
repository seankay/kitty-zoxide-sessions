#!/usr/bin/env python3   
from __future__ import annotations

import argparse
import atexit
import logging
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


LOGGER = logging.getLogger("kitty-zoxide-sessions")

def close_launcher_window(window_id: str | None) -> None:
    if not window_id:
        return
    subprocess.run(
        ["kitty", "@", "close-window", "--match", f"id:{window_id}"],
        check=False,
    )


def setup_logging(log_dir: Path) -> None:
    if LOGGER.handlers:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kitty-zoxide-sessions.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.propagate = False


def emit(message: str, *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    print(message, file=stream)
    if stderr:
        LOGGER.error(message)
    else:
        LOGGER.info(message)


def log(message: str, enabled: bool) -> None:
    if enabled:
        LOGGER.debug(message)


def resolve_session_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base_dir / "kitty-sessions"


def select_item(candidates: str, prompt: str) -> tuple[str, int]:
    try:
        proc = subprocess.run(
            ["fzf", "--ansi", "--reverse", "--no-sort", "--prompt", prompt],
            input=candidates,
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        emit("kitty-zoxide-sessions: fzf command not found", stderr=True)
        return "", 1

    if proc.returncode != 0:
        return "", 2

    return proc.stdout.strip(), 0


def list_session_files(session_dir: Path) -> list[Path]:
    if not session_dir.exists():
        return []

    return sorted(session_dir.glob("*.kitty-session"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kitty-zoxide-sessions",
        description="Launch a kitty session from zoxide entries.",
        epilog=(
            "For more information about kitty sessions visit: "
            "https://sw.kovidgoyal.net/kitty/sessions/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("-e", "--edit", action="store_true", help="Edit session file")
    parser.add_argument("-D", "--delete", action="store_true", help="Delete a session file")
    parser.add_argument("--delete-all", action="store_true", help="Delete all session files")
    parser.add_argument(
        "-c",
        "--auto-close",
        action="store_true",
        help="Close window on selection",
    )
    parser.add_argument(
        "-t",
        "--template",
        help="Path to a custom kitty session template",
    )
    return parser


def parse_args(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace | int:
    try:
        return parser.parse_args(argv[1:])
    except SystemExit:
        return 1


@dataclass(frozen=True)
class AppContext:
    session_dir: Path
    parser: argparse.ArgumentParser
    debug: bool
    template_path: Path | None
    launcher_window_id: str | None


class Operation:
    def __init__(self, context: AppContext) -> None:
        self.context = context

    def run(self) -> int:
        raise NotImplementedError


class DeleteAllSessions(Operation):
    def confirm_delete_all(self) -> bool:
        emit("This will delete all kitty session files.")
        try:
            response = input("Type 'yes' to continue: ").strip().lower()
        except EOFError:
            return False

        return response == "yes"


    def run(self) -> int:
        session_files = list_session_files(self.context.session_dir)
        if not session_files:
            emit("kitty-zoxide-sessions: no session files to delete", stderr=True)
            return 1



        if not self.confirm_delete_all():
            emit("Delete all cancelled", stderr=True)
            return 1

        failed = False
        for session_file in session_files:
            try:
                session_file.unlink()
            except OSError as exc:
                emit(
                    f"kitty-zoxide-sessions: failed to delete session file '{session_file}' ({exc})",
                    stderr=True,
                )
                failed = True

        if failed:
            return 1

        msg = "Deleted all sessions files"
        emit(msg)
        log(msg, self.context.debug)
        return 0


class DeleteSession(Operation):
    def run(self) -> int:
        session_files = list_session_files(self.context.session_dir)
        if not session_files:
            emit("kitty-zoxide-sessions: no session files to delete", stderr=True)
            return 1

        candidates = "\n".join(path.stem for path in session_files)
        session_name, selection_status = select_item(candidates, "💣 delete session > ")
        if selection_status != 0:
            return selection_status

        if not session_name:
            emit("No session selected", stderr=True)
            emit(self.context.parser.format_help(), stderr=True)
            return 1

        session_file = self.context.session_dir / f"{session_name}.kitty-session"
        try:
            session_file.unlink()
        except OSError as exc:
            emit(
                f"kitty-zoxide-sessions: failed to delete session file '{session_file}' ({exc})",
                stderr=True,
            )
            return 1

        emit(f"Deleted session: {session_name}")
        log(f"Deleted session file: {session_file}", self.context.debug)
        return 0


class SessionSelection(Operation):
    def __init__(self, context: AppContext, *, editing: bool) -> None:
        super().__init__(context)
        self.editing = editing

    def handle_session(self, _session_file: Path) -> int:
        raise NotImplementedError

    def session_data(
        self,
        session_path: str,
        session_name: str,
        template_path: Path | None,
    ) -> str | int:
        default_template = Path(__file__).with_name("default.kitty-session")

        template = None
        for candidate in [template_path, default_template]:
            try:
                template = candidate.read_text(encoding="utf-8")
                break
            except OSError as exc:
                emit(
                    f"kitty-zoxide-sessions: failed to read template file '{candidate}' ({exc})",
                    stderr=True,
                )

        if template is None:
            return 1

        return template.replace("@@session-path@@", session_path).replace("@@session@@", session_name)


    def ensure_session_file(
        self,
        session_dir: Path,
        session_name: str,
        session_path: str,
        debug: bool,
        template_path: Path | None,
    ) -> Path | int:
        session_file = session_dir / f"{session_name}.kitty-session"

        if session_file.exists():
            return session_file

        data = self.session_data(session_path, session_name, template_path)
        if isinstance(data, int):
            return data

        try:
            session_file.write_text(data, encoding="utf-8")
        except OSError as exc:
            emit(f"kitty-zoxide-sessions: failed to write session file ({exc})", stderr=True)
            return 1

        log(f"Creating session file: {session_file}", debug)
        return session_file

    def run_zoxide(self) -> str | None:
        try:
            result = subprocess.run(
                ["zoxide", "query", "-l"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            emit("kitty-zoxide-sessions: zoxide command not found", stderr=True)
            return None
        except subprocess.CalledProcessError as exc:
            emit(f"kitty-zoxide-sessions: failed to query zoxide (exit code {exc.returncode})", stderr=True)
            return None

        return result.stdout


    def run(self) -> int:
        candidates = self.run_zoxide()
        if candidates is None:
            return 1

        session_path, selection_status = select_item(candidates, "⚡ session > ")
        if selection_status != 0:
            return selection_status

        if not session_path:
            emit("No session selected", stderr=True)
            emit(self.context.parser.format_help(), stderr=True)
            return 1

        session_name = Path(session_path).name

        log(f"Variables set: session={session_name} path={session_path}", self.context.debug)

        try:
            self.context.session_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            emit(f"kitty-zoxide-sessions: failed to create session directory ({exc})", stderr=True)
            return 1

        session_file = self.ensure_session_file(
            self.context.session_dir,
            session_name,
            session_path,
            self.context.debug,
            self.context.template_path,
        )
        if isinstance(session_file, int):
            return session_file

        log(
            f"Opening:{session_file} editing={'yes' if self.editing else ''}",
            self.context.debug,
        )

        return self.handle_session(session_file)


class EditSession(SessionSelection):
    def __init__(self, context: AppContext) -> None:
        super().__init__(context, editing=True)

    def launch_editor(self, session_file: Path) -> int:
        default_editor = "nvim"
        editor = os.environ.get("EDITOR", default_editor)
        editor_parts = shlex.split(editor) if editor else [default_editor]
        editor_parts.append(str(session_file))
        try:
            result = subprocess.run(editor_parts)
            return result.returncode
        except FileNotFoundError:
            emit(f"kitty-zoxide-sessions: editor '{editor_parts[0]}' not found", stderr=True)
            return 1


    def handle_session(self, session_file: Path) -> int:
        return self.launch_editor(session_file)


class LaunchSession(SessionSelection):
    def __init__(self, context: AppContext) -> None:
        super().__init__(context, editing=False)


    def handle_session(self, session_file: Path) -> int:
        try:
            result = subprocess.run(
                ["kitten", "@", "action", "goto_session", str(session_file)],
                check=False,
            )
        except FileNotFoundError:
            emit("kitty-zoxide-sessions: kitten command not found", stderr=True)
            return 1

        return result.returncode


def main(argv: list[str]) -> int:
    session_dir = resolve_session_dir()
    setup_logging(session_dir)

    parser = build_parser()
    parsed = parse_args(parser, argv)
    if isinstance(parsed, int):
        return parsed

    editing = parsed.edit
    deleting = parsed.delete
    delete_all = parsed.delete_all
    debug = parsed.debug
    auto_close = parsed.auto_close
    template_path = Path(parsed.template).expanduser() if parsed.template else None
    launcher_window_id = os.environ.get("KITTY_WINDOW_ID")

    if editing and (deleting or delete_all):
        emit("kitty-zoxide-sessions: cannot use --edit with delete options", stderr=True)
        return 1

    if deleting and delete_all:
        emit("kitty-zoxide-sessions: cannot use --delete with --delete-all", stderr=True)
        return 1

    if auto_close:
        atexit.register(close_launcher_window, launcher_window_id)

    context = AppContext(
        session_dir=session_dir,
        parser=parser,
        debug=debug,
        template_path=template_path,
        launcher_window_id=launcher_window_id,
    )

    if delete_all:
        op = DeleteAllSessions(context)
    elif deleting:
        op = DeleteSession(context)
    elif editing:
        op = EditSession(context)
    else:
        op = LaunchSession(context)

    return op.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))

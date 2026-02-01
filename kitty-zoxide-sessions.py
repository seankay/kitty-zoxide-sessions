#!/usr/bin/env python3   
from __future__ import annotations

import argparse
import atexit
import logging
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


LOGGER = logging.getLogger("kitty-zoxide-sessions")
SESSION_ENTRY="session"
PATH_ENTRY="path"

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


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def log(message: str, enabled: bool) -> None:
    if enabled:
        LOGGER.debug(message)


def resolve_session_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base_dir / "kitty-sessions"


def select_item(candidates: str, prompt: str, *, ansi: bool) -> tuple[str, int]:
    try:
        fzf_command = ["fzf", "--reverse", "--no-sort", "--prompt", prompt]
        if ansi:
            fzf_command.insert(1, "--ansi")
        proc = subprocess.run(
            fzf_command,
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
    parser.add_argument("--ansi", action="store_true", help="Enable ANSI formatting in fzf")
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
    ansi: bool
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
        session_name, selection_status = select_item(
            candidates,
            "delete session > ",
            ansi=self.context.ansi,
        )
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
        for candidate in [path for path in (template_path, default_template) if path]:
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

        print(session_file)
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

    def label(self, label_text: str, ansi: bool) -> str:
        return f"\x1b[1m{label_text}\x1b[0m" if ansi else label_text

    def run(self) -> int:
        zoxide_output = self.run_zoxide()
        if zoxide_output is None:
            return 1

        zoxide_paths = [path for path in zoxide_output.splitlines() if path]
        zoxide_by_name: dict[str, str] = {}
        for path in zoxide_paths:
            zoxide_by_name.setdefault(Path(path).name, path)

        try:
            self.context.session_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            emit(f"kitty-zoxide-sessions: failed to create session directory ({exc})", stderr=True)
            return 1

        session_files = list_session_files(self.context.session_dir)
        session_names = {session_file.stem for session_file in session_files}
        filtered_zoxide = [path for path in zoxide_paths if Path(path).name not in session_names]
        entries: list[tuple[str, str, str]] = []
        session_label = self.label("[session]", self.context.ansi)
        path_label = self.label("[zoxide]", self.context.ansi)
        for session_file in session_files:
            entries.append(
                (f"{session_label} {session_file.stem}", SESSION_ENTRY, str(session_file))
            )
        for path in filtered_zoxide:
            entries.append((f"{path_label} {path}", PATH_ENTRY, path))

        candidates = "\n".join(label for label, _, _ in entries)
        if not candidates:
            emit("kitty-zoxide-sessions: no sessions found", stderr=True)
            return 1

        selection, selection_status = select_item(candidates, "session > ", ansi=self.context.ansi)
        if selection_status != 0:
            return selection_status

        if not selection:
            emit("No session selected", stderr=True)
            emit(self.context.parser.format_help(), stderr=True)
            return 1

        selection_plain = strip_ansi(selection)
        entry = next(
            (entry for entry in entries if strip_ansi(entry[0]) == selection_plain),
            None,
        )
        if entry is None:
            emit("kitty-zoxide-sessions: selection could not be resolved", stderr=True)
            return 1

        _, entry_type, entry_value = entry
        session_path_from_zoxide = None
        if entry_type == SESSION_ENTRY:
            resolved_session_file: Path | int = Path(entry_value)
            session_name = resolved_session_file.stem
            session_path_from_zoxide = zoxide_by_name.get(session_name)
        else:
            session_name = Path(entry_value).name
            session_path_from_zoxide = entry_value
            resolved_session_file = self.ensure_session_file(
                self.context.session_dir,
                session_name,
                session_path_from_zoxide,
                self.context.debug,
                self.context.template_path,
            )

        log(
            f"Variables set: session={session_name} path={session_path_from_zoxide or 'n/a'}",
            self.context.debug,
        )

        if isinstance(resolved_session_file, int):
            return resolved_session_file

        log(
            f"Opening:{resolved_session_file} editing={'yes' if self.editing else ''}",
            self.context.debug,
        )

        return self.handle_session(resolved_session_file)


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
    ansi = parsed.ansi
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
        ansi=ansi,
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

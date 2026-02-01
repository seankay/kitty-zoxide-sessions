#!/usr/bin/env python3   
from __future__ import annotations

import argparse
import atexit
import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path


def close_launcher_window(window_id: str | None) -> None:
    if not window_id:
        return
    subprocess.run(
        ["kitty", "@", "close-window", "--match", f"id:{window_id}"],
        check=False,
    )

LOGGER = logging.getLogger("kitty-zoxide-sessions")


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
        print(message)
        LOGGER.debug(message)


def resolve_session_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base_dir / "kitty-sessions"


def run_zoxide() -> str | None:
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


def select_session(candidates: str) -> tuple[str, int]:
    try:
        proc = subprocess.run(
            ["fzf", "--ansi", "--reverse", "--no-sort", "--prompt", "⚡ session > "],
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



def session_data(session_path: str, session_name: str) -> str | int:
    template_path = Path(__file__).with_name("default.kitty-session")
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        emit(f"kitty-zoxide-sessions: failed to read template file ({exc})", stderr=True)
        return 1

    return (
        template.replace("@@session-path@@", session_path)
        .replace("@@session@@", session_name)
    )


def ensure_session_file(
    session_dir: Path, session_name: str, session_path: str, debug: bool
) -> Path | int:
    session_file = session_dir / f"{session_name}.kitty-session"

    if session_file.exists():
        return session_file

    data = session_data(session_path, session_name)
    if isinstance(data, int):
        return data

    try:
        session_file.write_text(data, encoding="utf-8")
    except OSError as exc:
        emit(f"kitty-zoxide-sessions: failed to write session file ({exc})", stderr=True)
        return 1

    log(f"Creating session file: {session_file}", debug)
    return session_file


def launch_editor(session_file: Path) -> int:
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


def goto_session(session_file: Path) -> int:
    try:
        result = subprocess.run(
            ["kitten", "@", "action", "goto_session", str(session_file)],
            check=False,
        )
    except FileNotFoundError:
        emit("kitty-zoxide-sessions: kitten command not found", stderr=True)
        return 1

    return result.returncode


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
    parser.add_argument(
        "-c",
        "--auto-close",
        action="store_true",
        help="Close window on selection",
    )
    return parser


def parse_args(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace | int:
    try:
        return parser.parse_args(argv[1:])
    except SystemExit:
        return 1


def main(argv: list[str]) -> int:
    session_dir = resolve_session_dir()
    setup_logging(session_dir)

    parser = build_parser()
    parsed = parse_args(parser, argv)
    if isinstance(parsed, int):
        return parsed

    editing = parsed.edit
    debug = parsed.debug
    auto_close = parsed.auto_close
    launcher_window_id = os.environ.get("KITTY_WINDOW_ID")

    if auto_close:
        atexit.register(close_launcher_window, launcher_window_id)

    candidates = run_zoxide()
    if candidates is None:
        return 1

    session_path, selection_status = select_session(candidates)
    if selection_status != 0:
        return selection_status

    if not session_path:
        emit("No session selected", stderr=True)
        emit(parser.format_help(), stderr=True)
        return 1

    session_name = Path(session_path).name

    log(f"Variables set: session={session_name} path={session_path}", debug)

    try:
        session_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        emit(f"kitty-zoxide-sessions: failed to create session directory ({exc})", stderr=True)
        return 1

    ensured = ensure_session_file(session_dir, session_name, session_path, debug)
    if isinstance(ensured, int):
        return ensured

    session_file = ensured

    log(f"Opening:{session_file} editing={'yes' if editing else ''}", debug)

    if editing:
        return launch_editor(session_file)

    return goto_session(session_file)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

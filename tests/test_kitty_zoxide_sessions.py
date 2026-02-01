import importlib.util
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "kitty-zoxide-sessions.py"


@pytest.fixture
def module():
    name = f"kitty_zoxide_sessions_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DummySelection:
    def __init__(self, base):
        self._base = base

    def __getattr__(self, name):
        return getattr(self._base, name)

    def handle_session(self, _session_file):
        return 0


def build_context(module, session_dir, template_path=None):
    return module.AppContext(
        session_dir=session_dir,
        parser=module.build_parser(),
        debug=False,
        template_path=template_path,
        launcher_window_id=None,
    )


def test_close_launcher_window_noop(module, monkeypatch):
    called = []

    def fake_run(*_args, **_kwargs):
        called.append(True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.close_launcher_window(None)
    assert called == []


def test_close_launcher_window_executes(module, monkeypatch):
    calls = []

    def fake_run(args, check=False):
        calls.append((args, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.close_launcher_window("123")
    assert calls == [(["kitty", "@", "close-window", "--match", "id:123"], False)]


def test_resolve_session_dir_uses_xdg_data_home(module, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert module.resolve_session_dir() == tmp_path / "kitty-sessions"


def test_list_session_files_sorted(module, tmp_path):
    (tmp_path / "b.kitty-session").write_text("", encoding="utf-8")
    (tmp_path / "a.kitty-session").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    files = module.list_session_files(tmp_path)
    assert [path.name for path in files] == ["a.kitty-session", "b.kitty-session"]


def test_parse_args_invalid_returns_one(module):
    parser = module.build_parser()
    result = module.parse_args(parser, ["prog", "--nope"])
    assert result == 1


def test_select_item_fzf_missing(module, monkeypatch, capsys):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    selection, code = module.select_item("a", "prompt> ")
    assert selection == ""
    assert code == 1
    assert "fzf command not found" in capsys.readouterr().err


def test_select_item_nonzero_return(module, monkeypatch):
    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=2, stdout="choice")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    selection, code = module.select_item("a", "prompt> ")
    assert selection == ""
    assert code == 2


def test_ensure_session_file_creates_file(module, tmp_path):
    template_path = tmp_path / "template.kitty-session"
    template_path.write_text("path=@@session-path@@ name=@@session@@", encoding="utf-8")
    context = build_context(module, tmp_path, template_path=template_path)
    selection = DummySelection(module.SessionSelection(context, editing=False))
    session_file = selection.ensure_session_file(
        tmp_path,
        "proj",
        "/path/to/proj",
        False,
        template_path,
    )
    assert isinstance(session_file, Path)
    assert session_file.read_text(encoding="utf-8") == "path=/path/to/proj name=proj"


def test_delete_session_deletes_file(module, monkeypatch, tmp_path):
    session_file = tmp_path / "demo.kitty-session"
    session_file.write_text("data", encoding="utf-8")
    context = build_context(module, tmp_path)

    def fake_select_item(_candidates, _prompt):
        return "demo", 0

    monkeypatch.setattr(module, "select_item", fake_select_item)
    op = module.DeleteSession(context)
    result = op.run()
    assert result == 0
    assert not session_file.exists()


def test_delete_all_sessions_cancel(module, monkeypatch, tmp_path):
    session_file = tmp_path / "demo.kitty-session"
    session_file.write_text("data", encoding="utf-8")
    context = build_context(module, tmp_path)
    op = module.DeleteAllSessions(context)

    monkeypatch.setattr(op, "confirm_delete_all", lambda: False)
    result = op.run()
    assert result == 1
    assert session_file.exists()


def test_edit_session_launch_editor_uses_env(module, monkeypatch, tmp_path):
    context = build_context(module, tmp_path)
    op = module.EditSession(context)
    calls = []

    def fake_run(args):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("EDITOR", "vim -p")
    session_file = tmp_path / "demo.kitty-session"
    assert op.launch_editor(session_file) == 0
    assert calls == [["vim", "-p", str(session_file)]]


def test_edit_session_launch_editor_missing_binary(module, monkeypatch, tmp_path, capsys):
    context = build_context(module, tmp_path)
    op = module.EditSession(context)

    def fake_run(_args):
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("EDITOR", "missing-editor")
    session_file = tmp_path / "demo.kitty-session"
    assert op.launch_editor(session_file) == 1
    assert "editor 'missing-editor' not found" in capsys.readouterr().err


def test_launch_session_missing_kitten(module, monkeypatch, tmp_path, capsys):
    context = build_context(module, tmp_path)
    op = module.LaunchSession(context)

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    session_file = tmp_path / "demo.kitty-session"
    assert op.handle_session(session_file) == 1
    assert "kitten command not found" in capsys.readouterr().err


def test_run_zoxide_missing_binary(module, monkeypatch, capsys):
    context = build_context(module, Path("/tmp"))
    selection = DummySelection(module.SessionSelection(context, editing=False))

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert selection.run_zoxide() is None
    assert "zoxide command not found" in capsys.readouterr().err

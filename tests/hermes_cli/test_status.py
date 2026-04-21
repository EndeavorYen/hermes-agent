from types import SimpleNamespace

from hermes_loop.store import LoopStore
from hermes_cli.status import show_status


def test_show_status_includes_tavily_key(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-1...cdef")

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "Tavily" in output
    assert "tvly...cdef" in output


def test_show_status_termux_gateway_section_skips_systemctl(monkeypatch, capsys, tmp_path):
    from hermes_cli import status as status_mod
    import hermes_cli.auth as auth_mod
    import hermes_cli.gateway as gateway_mod

    monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(status_mod, "get_env_path", lambda: tmp_path / ".env", raising=False)
    monkeypatch.setattr(status_mod, "get_hermes_home", lambda: tmp_path, raising=False)
    monkeypatch.setattr(status_mod, "load_config", lambda: {"model": "gpt-5.4"}, raising=False)
    monkeypatch.setattr(status_mod, "resolve_requested_provider", lambda requested=None: "openai-codex", raising=False)
    monkeypatch.setattr(status_mod, "resolve_provider", lambda requested=None, **kwargs: "openai-codex", raising=False)
    monkeypatch.setattr(status_mod, "provider_label", lambda provider: "OpenAI Codex", raising=False)
    monkeypatch.setattr(auth_mod, "get_nous_auth_status", lambda: {}, raising=False)
    monkeypatch.setattr(auth_mod, "get_codex_auth_status", lambda: {}, raising=False)
    monkeypatch.setattr(gateway_mod, "find_gateway_pids", lambda exclude_pids=None: [], raising=False)

    def _unexpected_systemctl(*args, **kwargs):
        raise AssertionError("systemctl should not be called in the Termux status view")

    monkeypatch.setattr(status_mod.subprocess, "run", _unexpected_systemctl)

    status_mod.show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "Manager:      Termux / manual process" in output
    assert "Start with:   hermes gateway" in output
    assert "systemd (user)" not in output


def test_show_status_includes_loop_summary(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-inactive",
        session_key="telegram:u2:c2",
        payload={"goal": "Stopped loop", "active": False, "updated_at": "2026-04-21T00:00:00+00:00"},
    )
    store.write_checkpoint(
        session_id="sess-active",
        session_key="telegram:u1:c1",
        payload={
            "goal": "Continue autonomously until a real stop condition is reached.",
            "active": True,
            "remaining_auto_turns": 2,
            "updated_at": "2026-04-21T01:00:00+00:00",
        },
    )

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "◆ Autonomous Loops" in output
    assert "Persisted:    2" in output
    assert "Active:       1" in output
    assert "Latest:       sess-active" in output
    assert "Remaining:  2" in output


def test_show_status_loop_summary_fails_closed_when_store_errors(monkeypatch, capsys, tmp_path):
    from hermes_cli import status as status_mod

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    class _BrokenLoopStore:
        def list_checkpoints(self, active_only=False):
            raise OSError("boom")

    monkeypatch.setattr(status_mod, "LoopStore", _BrokenLoopStore)

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "◆ Autonomous Loops" in output
    assert "Persisted:    (unavailable)" in output
    assert "Active:       (unavailable)" in output

"""Desktop/CLI create reuses the Bot Chat stored row when merge is on."""
import types

from tui_gateway import server


class _FakeDB:
    def __init__(self, row=None, messages=None):
        self.row = row
        self.messages = messages or []
        self.closed = False

    def get_session(self, session_id):
        if self.row and self.row.get("id") == session_id:
            return dict(self.row)
        return None

    def find_latest_session_for_session_key(self, session_key):
        if self.row and (
            self.row.get("session_key") == session_key or self.row.get("id") == session_key
        ):
            return dict(self.row)
        return None

    def get_messages_as_conversation(self, session_id, repair_alternation=False):
        return list(self.messages)

    def close(self):
        self.closed = True


def _quiet_create(monkeypatch):
    monkeypatch.setattr(server, "_schedule_agent_build", lambda *a, **k: None)
    monkeypatch.setattr(server, "_start_agent_build", lambda *a, **k: None)
    monkeypatch.setattr(server, "_completion_cwd", lambda params=None: ".")
    monkeypatch.setattr(
        server.threading,
        "Timer",
        lambda *a, **k: types.SimpleNamespace(daemon=False, start=lambda: None),
    )


def test_create_without_merge_keeps_unique_stored_id(monkeypatch):
    monkeypatch.delenv("HERMES_BOT_CHANNEL_MERGE", raising=False)
    _quiet_create(monkeypatch)
    first = server._methods["session.create"]("r1", {"source": "desktop"})
    second = server._methods["session.create"]("r2", {"source": "desktop"})
    try:
        assert first["result"]["stored_session_id"] != second["result"]["stored_session_id"]
        assert first["result"]["stored_session_id"] != "agent:main:bot"
    finally:
        server._sessions.pop(first["result"]["session_id"], None)
        server._sessions.pop(second["result"]["session_id"], None)


def test_create_with_merge_reuses_slack_transcript(monkeypatch):
    monkeypatch.setenv("HERMES_BOT_CHANNEL_MERGE", "1")
    _quiet_create(monkeypatch)
    unique = "slack-unique-from-dm"
    db = _FakeDB(
        row={"id": "agent:main:bot", "session_key": "agent:main:bot", "source": "slack"},
        messages=[{"role": "user", "content": unique, "channel": "slack"}],
    )
    monkeypatch.setattr(server, "_get_db", lambda: db)
    resp = server._methods["session.create"]("r1", {"source": "desktop"})
    sid = resp["result"]["session_id"]
    try:
        assert resp["result"]["stored_session_id"] == "agent:main:bot"
        texts = [m.get("text") for m in resp["result"]["messages"]]
        assert unique in texts
        channels = [m.get("channel") for m in resp["result"]["messages"]]
        assert "slack" in channels
    finally:
        server._sessions.pop(sid, None)

"""Desktop/CLI create/resume reuses the Bot Chat SessionDB survivor when merge is on."""
import types

from hermes_state import SessionDB
from tui_gateway import server


SLACK_UNIQUE = "slack-unique-from-dm"
UNFINISHED = "進行中：寫季報"


class _FakeDB:
    def __init__(self, row=None, messages=None, rows=None):
        self.row = row
        self.messages = messages or []
        self.rows = list(rows or ([row] if row else []))
        self.closed = False
        self.retargeted = []
        self.backfilled = []

    def get_session(self, session_id):
        for row in self.rows:
            if row and row.get("id") == session_id:
                return dict(row)
        if self.row and self.row.get("id") == session_id:
            return dict(self.row)
        return None

    def find_latest_session_for_session_key(self, session_key):
        for row in self.rows:
            if row and (
                row.get("session_key") == session_key or row.get("id") == session_key
            ):
                return dict(row)
        if self.row and (
            self.row.get("session_key") == session_key or self.row.get("id") == session_key
        ):
            return dict(self.row)
        return None

    def find_bot_channel_survivor(self, session_key):
        for row in self.rows:
            if not row:
                continue
            if (
                row.get("session_key") == session_key
                or row.get("id") == session_key
                or str(row.get("session_key") or "").startswith("agent:main:slack:dm")
            ):
                return dict(row)
        return self.find_latest_session_for_session_key(session_key)

    def get_messages_as_conversation(self, session_id, repair_alternation=False):
        return list(self.messages)

    def retarget_session_key(self, session_id, session_key):
        self.retargeted.append((session_id, session_key))
        for row in self.rows:
            if row and row.get("id") == session_id:
                row["session_key"] = session_key

    def backfill_message_channel(self, session_id, channel):
        self.backfilled.append((session_id, channel))

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


def _seed_legacy_slack(db: SessionDB, *, session_id="20260101_010101_slackdm") -> str:
    db.create_session(
        session_id=session_id,
        source="slack",
        user_id="U1",
        session_key="agent:main:slack:dm:D999",
        chat_id="D999",
        chat_type="dm",
    )
    db.append_message(
        session_id,
        role="user",
        content=SLACK_UNIQUE,
        platform_message_id="1717.1",
        channel="slack",
        timestamp=1_700_000_000,
    )
    db.append_message(
        session_id,
        role="assistant",
        content="收到。",
        timestamp=1_700_000_010,
    )
    db.append_message(
        session_id,
        role="user",
        content=UNFINISHED,
        channel="slack",
        timestamp=1_700_000_050,
    )
    return session_id


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
    db = _FakeDB(
        row={"id": "agent:main:bot", "session_key": "agent:main:bot", "source": "slack"},
        messages=[{"role": "user", "content": SLACK_UNIQUE, "channel": "slack"}],
    )
    monkeypatch.setattr(server, "_get_db", lambda: db)
    resp = server._methods["session.create"]("r1", {"source": "desktop"})
    sid = resp["result"]["session_id"]
    try:
        assert resp["result"]["stored_session_id"] == "agent:main:bot"
        texts = [m.get("text") for m in resp["result"]["messages"]]
        assert SLACK_UNIQUE in texts
        channels = [m.get("channel") for m in resp["result"]["messages"]]
        assert "slack" in channels
    finally:
        server._sessions.pop(sid, None)


def test_create_with_merge_reuses_legacy_slack_dm_sessiondb_row(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_BOT_CHANNEL_MERGE", "1")
    _quiet_create(monkeypatch)
    db = SessionDB(db_path=tmp_path / "state.db")
    slack_id = _seed_legacy_slack(db)
    db.create_session(
        session_id="agent:main:bot",
        source="desktop",
        session_key="agent:main:bot",
    )
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_profile_home", lambda profile=None: None)
    resp = server._methods["session.create"]("r1", {"source": "desktop"})
    sid = resp["result"]["session_id"]
    try:
        assert resp["result"]["stored_session_id"] == slack_id
        assert db.get_session(slack_id)["session_key"] == "agent:main:bot"
        texts = [m.get("text") for m in resp["result"]["messages"]]
        blob = "\n".join(str(t) for t in texts)
        assert SLACK_UNIQUE in blob
        assert UNFINISHED in blob
        assert any(m.get("channel") == "slack" for m in resp["result"]["messages"])
        history = db.get_messages_as_conversation(slack_id)
        assert any(m.get("channel") == "slack" for m in history)
    finally:
        server._sessions.pop(sid, None)


def test_resume_timestamp_pin_remaps_to_slack_survivor(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_BOT_CHANNEL_MERGE", "1")
    db = SessionDB(db_path=tmp_path / "state.db")
    slack_id = _seed_legacy_slack(db)
    pin = "20260826_120000_abc123"
    db.create_session(session_id=pin, source="desktop", session_key=pin)
    db.append_message(pin, role="user", content="older-desktop-pin", timestamp=1_500_000_000)
    remapped = server._bot_channel_resume_target(db, pin, None)
    assert remapped == slack_id
    assert db.get_session(slack_id)["session_key"] == "agent:main:bot"
    canonical = server._bot_channel_resume_target(db, "agent:main:bot", None)
    assert canonical == slack_id


def test_history_to_messages_uses_stored_channel_without_source():
    history = [
        {
            "role": "user",
            "content": SLACK_UNIQUE,
            "channel": "slack",
            "message_id": "1717.1",
        }
    ]
    labeled = server._history_to_messages(history)
    assert labeled == [
        {"role": "user", "text": SLACK_UNIQUE, "channel": "slack"}
    ]
    assert "source" not in labeled[0]

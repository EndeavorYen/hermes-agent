"""P7 / contract rule 6: Slack, Desktop, and CLI share one Bot Chat row."""
from datetime import datetime, timedelta
from unittest.mock import patch

from gateway.config import GatewayConfig, Platform
from gateway.session import (
    SessionEntry,
    SessionSource,
    SessionStore,
    bot_channel_session_key,
    build_session_key,
    is_bot_channel_session_key,
    legacy_bot_channel_session_key,
)
from hermes_state import SessionDB


SLACK_UNIQUE = "slack-unique-p7-02"
DESKTOP_UNIQUE = "desktop-unique-p7-03"
UNFINISHED = "進行中：寫季報，先從目錄開始"


def _src(**kw) -> SessionSource:
    kw.setdefault("chat_type", "dm")
    return SessionSource(**kw)


def _store(tmp_path, db=None, **cfg_kw) -> SessionStore:
    config = GatewayConfig(**cfg_kw)
    with patch("gateway.session.SessionStore._ensure_loaded"):
        store = SessionStore(sessions_dir=tmp_path, config=config)
    store._db = db
    store._loaded = True
    return store


def _session_db(tmp_path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _seed_slack_row(
    db: SessionDB,
    *,
    session_id: str = "20260101_010101_deadbeef",
    session_key: str = "agent:main:slack:dm:D999",
    unique: str = SLACK_UNIQUE,
    extra_user: str | None = None,
) -> str:
    db.create_session(
        session_id=session_id,
        source="slack",
        user_id="U1",
        session_key=session_key,
        chat_id="D999",
        chat_type="dm",
    )
    db.append_message(
        session_id,
        role="user",
        content=unique,
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
    if extra_user:
        db.append_message(
            session_id,
            role="user",
            content=extra_user,
            channel="slack",
            timestamp=1_700_000_100,
        )
    return session_id


class TestBotChannelSessionKey:
    def test_slack_desktop_cli_share_bot_id_key(self):
        slack = _src(platform=Platform.SLACK, chat_id="D123")
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        cli = _src(platform=Platform.CLI, chat_id="cli")
        local = _src(platform=Platform.LOCAL, chat_id="cli")
        assert build_session_key(slack) == "agent:main:bot"
        assert build_session_key(desktop) == build_session_key(slack)
        assert build_session_key(cli) == build_session_key(slack)
        assert build_session_key(local) == build_session_key(slack)
        assert "slack" not in build_session_key(slack)
        assert "desktop" not in build_session_key(desktop)
        assert is_bot_channel_session_key(build_session_key(slack))

    def test_named_profile_uses_bot_id_namespace(self):
        slack = _src(platform=Platform.SLACK, chat_id="D123")
        assert build_session_key(slack, profile="imagine") == "agent:imagine:bot"
        assert bot_channel_session_key("imagine") == "agent:imagine:bot"

    def test_groups_keep_platform_segment(self):
        group = _src(
            platform=Platform.SLACK,
            chat_id="C1",
            chat_type="group",
            user_id="U1",
        )
        key = build_session_key(group)
        assert "slack" in key
        assert "group" in key
        assert key != bot_channel_session_key()

    def test_telegram_dm_stays_platform_scoped(self):
        telegram = _src(platform=Platform.TELEGRAM, chat_id="99")
        slack = _src(platform=Platform.SLACK, chat_id="D123")
        assert build_session_key(telegram) == "agent:main:telegram:dm:99"
        assert build_session_key(telegram) != build_session_key(slack)

    def test_legacy_slack_dm_key_is_preserved_for_migration(self):
        slack = _src(platform=Platform.SLACK, chat_id="D123")
        assert (
            legacy_bot_channel_session_key(slack)
            == "agent:main:slack:dm:D123"
        )


class TestBotChannelStoreMerge:
    """G-P7-02 / G-P7-03 / G-P7-04: one SessionDB session_id, not dict aliases."""

    def test_g_p7_02_slack_string_lands_on_same_sessiondb_row_as_desktop(self, tmp_path):
        db = _session_db(tmp_path)
        slack_id = _seed_slack_row(db)
        store = _store(tmp_path, db=db)
        slack = _src(platform=Platform.SLACK, chat_id="D999", user_id="U1")
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        slack_entry = store.get_or_create_session(slack)
        desktop_entry = store.get_or_create_session(desktop)
        assert slack_entry.session_id == slack_id
        assert desktop_entry.session_id == slack_id
        assert slack_entry.session_id == desktop_entry.session_id
        assert slack_entry.session_key == desktop_entry.session_key == "agent:main:bot"
        assert db.get_session(slack_id)["session_key"] == "agent:main:bot"
        history = db.get_messages_as_conversation(desktop_entry.session_id)
        assert any(SLACK_UNIQUE in str(m.get("content")) for m in history)
        assert any(m.get("channel") == "slack" for m in history)
        assert desktop_entry.session_id == slack_id

    def test_g_p7_03_desktop_string_visible_from_slack_on_same_row(self, tmp_path):
        db = _session_db(tmp_path)
        slack_id = _seed_slack_row(db)
        store = _store(tmp_path, db=db)
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        slack = _src(platform=Platform.SLACK, chat_id="D999", user_id="U1")
        desktop_entry = store.get_or_create_session(desktop)
        assert desktop_entry.session_id == slack_id
        db.append_message(
            desktop_entry.session_id,
            role="user",
            content=DESKTOP_UNIQUE,
            timestamp=1_700_000_200,
        )
        slack_entry = store.get_or_create_session(slack)
        assert slack_entry.session_id == desktop_entry.session_id == slack_id
        slack_history = db.get_messages_as_conversation(slack_entry.session_id)
        desktop_history = db.get_messages_as_conversation(desktop_entry.session_id)
        assert slack_history is not desktop_history
        texts = [str(m.get("content")) for m in slack_history]
        assert DESKTOP_UNIQUE in texts
        assert SLACK_UNIQUE in texts
        assert [str(m.get("content")) for m in desktop_history] == texts

    def test_g_p7_04_unfinished_work_continues_on_the_same_sessiondb_row(self, tmp_path):
        db = _session_db(tmp_path)
        slack_id = _seed_slack_row(db, extra_user=UNFINISHED)
        store = _store(tmp_path, db=db)
        slack = _src(platform=Platform.SLACK, chat_id="D999")
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        slack_entry = store.get_or_create_session(slack)
        db.append_message(
            slack_entry.session_id,
            role="assistant",
            content="",
            tool_calls=[{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}],
            timestamp=1_700_000_150,
        )
        desktop_entry = store.get_or_create_session(desktop)
        assert desktop_entry.session_id == slack_entry.session_id == slack_id
        history = db.get_messages_as_conversation(desktop_entry.session_id)
        contents = [str(m.get("content")) for m in history]
        assert UNFINISHED in contents
        assert any(m.get("tool_calls") for m in history)

    def test_legacy_slack_key_is_aliased_not_orphaned(self, tmp_path):
        store = _store(tmp_path)
        slack = _src(platform=Platform.SLACK, chat_id="D123")
        legacy_key = legacy_bot_channel_session_key(slack)
        old_id = "20260101_010101_deadbeef"
        store._entries[legacy_key] = SessionEntry(
            session_key=legacy_key,
            session_id=old_id,
            created_at=datetime.now() - timedelta(days=2),
            updated_at=datetime.now() - timedelta(hours=1),
            origin=slack,
            platform=Platform.SLACK,
            chat_type="dm",
        )
        with patch.object(store, "_save"):
            entry = store.get_or_create_session(slack)
        assert entry.session_id == old_id
        assert entry.session_key == "agent:main:bot"
        assert store._entries[legacy_key].session_id == old_id
        assert store._entries["agent:main:bot"].session_id == old_id

    def test_empty_canonical_does_not_win_over_slack_transcript(self, tmp_path):
        db = _session_db(tmp_path)
        slack_id = _seed_slack_row(db)
        db.create_session(
            session_id="agent:main:bot",
            source="desktop",
            session_key="agent:main:bot",
        )
        store = _store(tmp_path, db=db)
        now = datetime.now()
        store._entries["agent:main:bot"] = SessionEntry(
            session_key="agent:main:bot",
            session_id="agent:main:bot",
            created_at=now,
            updated_at=now,
            origin=_src(platform=Platform.DESKTOP, chat_id="desktop"),
            platform=Platform.DESKTOP,
            chat_type="dm",
        )
        slack = _src(platform=Platform.SLACK, chat_id="D999", user_id="U1")
        with patch.object(store, "_save"):
            entry = store.get_or_create_session(slack)
        assert entry.session_id == slack_id
        assert entry.session_id != "agent:main:bot"
        assert db.get_session(slack_id)["session_key"] == "agent:main:bot"
        history = db.get_messages_as_conversation(entry.session_id)
        assert any(SLACK_UNIQUE in str(m.get("content")) for m in history)

    def test_desktop_timestamp_pin_binds_onto_slack_survivor(self, tmp_path):
        db = _session_db(tmp_path)
        slack_id = _seed_slack_row(db)
        pin = "20260826_120000_abc123"
        db.create_session(
            session_id=pin,
            source="desktop",
            session_key=pin,
        )
        db.append_message(pin, role="user", content="draft-from-desktop", timestamp=1_600_000_000)
        store = _store(tmp_path, db=db)
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        with patch.object(store, "_save"):
            entry = store.get_or_create_session(desktop)
        assert entry.session_id == slack_id
        assert db.get_session(slack_id)["session_key"] == "agent:main:bot"
        assert SLACK_UNIQUE in [
            str(m.get("content")) for m in db.get_messages_as_conversation(entry.session_id)
        ]

    def test_channel_survives_get_messages_as_conversation(self, tmp_path):
        db = _session_db(tmp_path)
        sid = _seed_slack_row(db)
        history = db.get_messages_as_conversation(sid)
        assert history[0]["channel"] == "slack"
        assert history[0]["message_id"] == "1717.1"
        assert "source" not in history[0]

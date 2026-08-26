"""P7 / contract rule 6: Slack, Desktop, and CLI share one Bot Chat key."""
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


def _src(**kw) -> SessionSource:
    kw.setdefault("chat_type", "dm")
    return SessionSource(**kw)


def _store(tmp_path, **cfg_kw) -> SessionStore:
    config = GatewayConfig(**cfg_kw)
    with patch("gateway.session.SessionStore._ensure_loaded"):
        store = SessionStore(sessions_dir=tmp_path, config=config)
    store._db = None
    store._loaded = True
    return store


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
    """G-P7-02 / G-P7-03 / G-P7-04: one stored transcript, live work on that row."""

    def test_g_p7_02_slack_string_lands_on_same_store_as_desktop(self, tmp_path):
        store = _store(tmp_path)
        transcripts: dict[str, list[str]] = {}
        slack = _src(platform=Platform.SLACK, chat_id="D999", user_id="U1")
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        slack_entry = store.get_or_create_session(slack)
        unique = "slack-unique-p7-02"
        transcripts.setdefault(slack_entry.session_id, []).append(unique)
        desktop_entry = store.get_or_create_session(desktop)
        assert slack_entry.session_id == desktop_entry.session_id
        assert slack_entry.session_key == desktop_entry.session_key == "agent:main:bot"
        assert unique in transcripts[desktop_entry.session_id]
        assert len(store._entries) >= 1
        ids = {entry.session_id for entry in store._entries.values()}
        assert ids == {slack_entry.session_id}

    def test_g_p7_03_desktop_string_visible_from_slack_channel(self, tmp_path):
        store = _store(tmp_path)
        transcripts: dict[str, list[str]] = {}
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        slack = _src(platform=Platform.SLACK, chat_id="D999", user_id="U1")
        desktop_entry = store.get_or_create_session(desktop)
        unique = "desktop-unique-p7-03"
        transcripts.setdefault(desktop_entry.session_id, []).append(unique)
        slack_entry = store.get_or_create_session(slack)
        assert slack_entry.session_id == desktop_entry.session_id
        assert unique in transcripts[slack_entry.session_id]

    def test_g_p7_04_unfinished_work_continues_from_other_surface(self, tmp_path):
        store = _store(tmp_path)
        slack = _src(platform=Platform.SLACK, chat_id="D999")
        desktop = _src(platform=Platform.DESKTOP, chat_id="desktop")
        live_work: dict[str, str] = {}
        slack_entry = store.get_or_create_session(slack)
        live_work[slack_entry.session_id] = "進行中：寫季報"
        desktop_entry = store.get_or_create_session(desktop)
        assert desktop_entry.session_id == slack_entry.session_id
        assert live_work[desktop_entry.session_id] == "進行中：寫季報"

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

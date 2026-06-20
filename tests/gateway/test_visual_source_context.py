from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_gateway_turn_sets_and_clears_visual_source_context():
    from agent.visual.source_context import (
        VisualSourceContext,
        clear_visual_source_context,
        get_visual_source_context,
    )
    from gateway.config import GatewayConfig, Platform, PlatformConfig
    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.run import GatewayRunner
    from gateway.session import SessionEntry, SessionSource, build_session_key

    clear_visual_source_context()
    source = SessionSource(
        platform=Platform.SLACK,
        chat_id="D123",
        chat_type="dm",
        user_id="U123",
        user_name="Test User",
        thread_id="1710000000.000100",
    )
    event = MessageEvent(
        text="make a clean product visual package",
        message_type=MessageType.TEXT,
        source=source,
        message_id="1710000000.000200",
    )
    session_key = build_session_key(source)
    now = datetime.now()
    session_entry = SessionEntry(
        session_key=session_key,
        session_id="sess-visual",
        created_at=now - timedelta(seconds=10),
        updated_at=now,
        platform=Platform.SLACK,
        chat_type="dm",
    )
    seen_contexts: list[VisualSourceContext | None] = []

    class Store:
        def get_or_create_session(self, _source):
            return session_entry

        def load_transcript(self, _session_id):
            return []

        def has_any_sessions(self):
            return True

        def append_to_transcript(self, *_args, **_kwargs):
            return None

        def update_session(self, *_args, **_kwargs):
            return None

        def clear_resume_pending(self, *_args, **_kwargs):
            return None

    async def fake_run_agent(**_kwargs):
        seen_contexts.append(get_visual_source_context())
        return {
            "final_response": "ok",
            "messages": [
                {"role": "user", "content": "make a clean product visual package"},
                {"role": "assistant", "content": "ok"},
            ],
            "api_calls": 1,
            "tools": [],
            "history_offset": 0,
        }

    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner.config = GatewayConfig(
        platforms={Platform.SLACK: PlatformConfig(enabled=True, token="test")}
    )
    runner.hooks = SimpleNamespace(emit=AsyncMock())
    runner.session_store = Store()
    runner._session_db = None
    runner._show_reasoning = False
    runner._recover_telegram_topic_thread_id = lambda _source: None
    runner._is_telegram_topic_lane = lambda _source: False
    runner._cache_session_source = lambda *_args, **_kwargs: None
    runner._set_session_env = lambda _context: []
    runner._clear_session_env = lambda _tokens: None
    runner._prepare_inbound_message_text = AsyncMock(return_value=event.text)
    runner._bind_adapter_run_generation = lambda *_args, **_kwargs: None
    runner._run_agent = fake_run_agent
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    runner._clear_restart_failure_count = lambda *_args, **_kwargs: None
    runner._sync_telegram_topic_binding = lambda *_args, **_kwargs: None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._format_session_info = lambda: ""

    response = await GatewayRunner._handle_message_with_agent(
        runner,
        event,
        source,
        session_key,
        1,
    )

    assert response == "ok"
    assert seen_contexts == [
        VisualSourceContext(
            platform="slack",
            channel_id="D123",
            thread_id="1710000000.000100",
            user_id="U123",
            message_id="1710000000.000200",
            conversation_id="slack:D123",
        )
    ]
    assert get_visual_source_context() is None

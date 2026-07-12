"""Regression for #49225 — codex app-server turns must reach the session DB
exactly once.

The codex app-server runtime (``run_codex_app_server_turn``) is an early-return
path that bypasses ``conversation_loop`` and therefore never runs the loop's
per-step ``_persist_session()`` flushes. Before the fix, the projected
assistant/tool messages were persisted *nowhere* (state.db got only
session_meta rows), leaving ``session_search`` (FTS) and conversation-distill
blind to real gateway conversations.

The fix has the codex runtime flush its own projected messages via
``_flush_messages_to_session_db()`` (idempotent through the intrinsic
``_DB_PERSISTED_MARKER``) and return ``agent_persisted=True`` so the gateway
skips its own ``append_to_transcript`` DB write. This is critical: the inbound
user turn is already flushed at turn start (``turn_context._persist_session``),
and ``append_message`` is a raw INSERT with no dedup — a gateway re-write would
duplicate the user turn (#860 / #42039). This test locks in:

1. ``run_codex_app_server_turn`` flushes projected messages and returns
   ``agent_persisted=True``.
2. Exactly-once persistence: the already-flushed user turn is NOT re-written,
   and the new projected assistant message lands once.
3. The gateway resolution expression preserves standard-runtime behaviour.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import hermes_cli.plugins

from agent.codex_runtime import run_codex_app_server_turn
from hermes_state import SessionDB
from run_agent import AIAgent


def _make_turn():
    return SimpleNamespace(
        interrupted=False,
        error=None,
        thread_id="thread-1",
        turn_id="turn-1",
        projected_messages=[{"role": "assistant", "content": "CODEX_ASSISTANT"}],
        tool_iterations=0,
        final_text="CODEX_ASSISTANT",
        should_retire=False,
    )


def _make_agent(session_db=None, session_id="sess-codex"):
    agent = MagicMock()
    # Pre-seed the session so run_codex_app_server_turn skips the spawn block.
    agent._codex_session = MagicMock()
    agent._codex_session.run_turn.return_value = _make_turn()
    agent.tool_progress_callback = None
    agent._iters_since_skill = 0
    agent._skill_nudge_interval = 0
    agent.valid_tool_names = set()
    agent._session_db = session_db
    agent._session_db_created = True
    agent.session_id = session_id
    return agent


def test_codex_success_flushes_and_reports_persisted():
    """Codex success turn must self-persist and return agent_persisted=True."""
    agent = _make_agent(session_db=None)  # no DB -> flush is a no-op, still True
    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=[{"role": "user", "content": "hello"}],
        effective_task_id="task-1",
    )
    assert result["completed"] is True
    # With the agent as sole persister, the gateway must SKIP its DB write.
    assert result["agent_persisted"] is True


def test_codex_runtime_honors_explicit_binary(monkeypatch):
    import agent.transports.codex_app_server_session as session_module

    captured = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_turn(self, **_kwargs):
            return _make_turn()

    monkeypatch.setenv("HERMES_CODEX_BIN", "/opt/codex/current/bin/codex")
    monkeypatch.setattr(session_module, "CodexAppServerSession", FakeSession)

    agent = _make_agent(session_db=None)
    agent._codex_session = None
    agent.session_cwd = "/tmp"
    agent.model = "gpt-5.6-sol"
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.platform = "cli"

    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=[{"role": "user", "content": "hello"}],
        effective_task_id="task-1",
    )

    assert result["completed"] is True
    assert captured["codex_bin"] == "/opt/codex/current/bin/codex"


def test_codex_runtime_makes_cron_threads_ephemeral(monkeypatch):
    """Cron turns are implementation details, not user-visible Codex tasks."""
    import agent.transports.codex_app_server_session as session_module

    captured = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_turn(self, **_kwargs):
            return _make_turn()

    monkeypatch.setattr(session_module, "CodexAppServerSession", FakeSession)

    agent = _make_agent(session_db=None)
    agent._codex_session = None
    agent.session_cwd = "/tmp"
    agent.model = "gpt-5.6-sol"
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.platform = "cron"

    result = run_codex_app_server_turn(
        agent,
        user_message="say hello",
        original_user_message="say hello",
        messages=[{"role": "user", "content": "say hello"}],
        effective_task_id="cron-job-1",
    )

    assert result["completed"] is True
    assert captured["ephemeral"] is True


def test_codex_success_runs_api_and_output_hooks(monkeypatch):
    calls = []

    def invoke_hook(name, **kwargs):
        calls.append((name, kwargs))
        if name == "transform_llm_output":
            return ["TRANSFORMED_CODEX_ASSISTANT"]
        return []

    monkeypatch.setattr(hermes_cli.plugins, "has_hook", lambda _name: True)
    monkeypatch.setattr(hermes_cli.plugins, "invoke_hook", invoke_hook)
    agent = _make_agent(session_db=None)
    agent.model = "gpt-5.5"
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.platform = "cli"

    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=[{"role": "user", "content": "hello"}],
        effective_task_id="task-1",
        turn_id="turn-1",
    )

    names = [name for name, _kwargs in calls]
    assert names == [
        "pre_api_request",
        "post_api_request",
        "transform_llm_output",
        "post_llm_call",
    ]
    assert result["final_response"] == "TRANSFORMED_CODEX_ASSISTANT"
    pre_api = calls[0][1]
    post_api = calls[1][1]
    assert pre_api["api_request_id"] == post_api["api_request_id"]
    assert post_api["response_model"] == "gpt-5.5"
    assert calls[3][1]["assistant_response"] == "TRANSFORMED_CODEX_ASSISTANT"


def test_codex_runtime_receives_pre_llm_plugin_context(monkeypatch):
    import agent.conversation_loop as conversation_loop

    captured = {}
    agent = SimpleNamespace(api_mode="codex_app_server")

    def fake_build_turn_context(*_args, **_kwargs):
        return SimpleNamespace(
            user_message="hello",
            original_user_message="hello",
            messages=[{"role": "user", "content": "hello"}],
            conversation_history=[],
            active_system_prompt="",
            effective_task_id="task-1",
            turn_id="turn-1",
            current_turn_user_idx=0,
            should_review_memory=False,
            plugin_user_context="PLUGIN_CONTEXT",
            ext_prefetch_cache="",
        )

    def fake_codex_turn(**kwargs):
        captured.update(kwargs)
        return {"final_response": "ok"}

    agent._run_codex_app_server_turn = fake_codex_turn
    monkeypatch.setattr(conversation_loop, "build_turn_context", fake_build_turn_context)

    result = conversation_loop.run_conversation(agent, "hello")

    assert result["final_response"] == "ok"
    assert captured["user_message"] == "hello\n\nPLUGIN_CONTEXT"
    assert captured["original_user_message"] == "hello"
    assert captured["messages"] == [{"role": "user", "content": "hello"}]


def test_codex_turn_persists_each_message_exactly_once():
    """The user turn (flushed at turn start) must not be duplicated; the
    projected assistant message must land once.  Uses a real SessionDB and the
    real AIAgent._flush_messages_to_session_db to prove no #860/#42039
    duplicate-write regression on the codex path."""
    tmp = tempfile.mkdtemp(prefix="codex_persist_")
    try:
        db = SessionDB(Path(tmp) / "state.db")
        sid = "sess-codex-once"
        db.create_session(session_id=sid, source="telegram", model="codex")

        # Real agent bound to this DB/session, minimal construction.
        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            session_db=db,
            session_id=sid,
        )
        agent._session_db_created = True
        agent._codex_session = MagicMock()
        agent._codex_session.run_turn.return_value = _make_turn()
        agent.tool_progress_callback = None

        # Model the real flow: the inbound user turn is flushed at turn start
        # (turn_context._persist_session) on the SAME `messages` list the codex
        # path later reuses. That flush stamps _DB_PERSISTED_MARKER on the user
        # dict, so the codex-path flush skips it — no duplicate.
        user_msg = {"role": "user", "content": "USER_TURN"}
        messages = [user_msg]
        agent._flush_messages_to_session_db(messages)  # turn-start flush

        result = run_codex_app_server_turn(
            agent,
            user_message="USER_TURN",
            original_user_message="USER_TURN",
            messages=messages,
            effective_task_id="task-1",
        )
        assert result["agent_persisted"] is True

        rows = db.get_messages(sid, include_inactive=True)
        contents = [r["content"] for r in rows]
        # Exactly one user turn, exactly one assistant turn — no duplicates.
        assert contents.count("USER_TURN") == 1, contents
        assert contents.count("CODEX_ASSISTANT") == 1, contents
        # session_search can now see the codex conversation.
        hits = {r["session_id"] for r in db.search_messages("CODEX_ASSISTANT")}
        assert sid in hits
    finally:
        import shutil

        shutil.rmtree(tmp)


class TestGatewayPersistedResolution:
    """The gateway default must preserve standard-runtime skip-db behaviour."""

    @staticmethod
    def _resolve_persistence_block(agent_result, session_db_present):
        # gateway/run.py persistence block:
        #   agent_persisted = agent_result.get("agent_persisted", self._session_db is not None)
        return agent_result.get("agent_persisted", session_db_present)

    @staticmethod
    def _resolve_passthrough(result_holder0):
        # gateway/run.py result_holder passthrough:
        #   result_holder[0].get("agent_persisted", True) if result_holder[0] else True
        return result_holder0.get("agent_persisted", True) if result_holder0 else True

    def test_codex_result_keeps_gateway_skip(self):
        # Codex now self-persists → gateway must SKIP (agent_persisted True).
        codex = {"agent_persisted": True}
        assert self._resolve_persistence_block(codex, True) is True
        assert self._resolve_persistence_block(codex, False) is True
        assert self._resolve_passthrough(codex) is True

    def test_standard_runtime_preserves_skip_db(self):
        # Standard runtime omits the key → old behaviour: skip iff DB present.
        standard = {"final_response": "ok"}
        assert self._resolve_persistence_block(standard, True) is True
        assert self._resolve_persistence_block(standard, False) is False
        assert self._resolve_passthrough(standard) is True

    def test_missing_result_holder_defaults_persisted(self):
        assert self._resolve_passthrough(None) is True

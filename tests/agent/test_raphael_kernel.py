from __future__ import annotations

from unittest.mock import patch

from agent.raphael.kernel import prepare_raphael_turn
from agent.raphael.runtime_contract import (
    RaphaelTurnOrigin,
    resolve_raphael_runtime_contract,
)
from agent.raphael.state import read_state


def _enabled_config():
    return {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        },
        "model": {"provider": "openai-codex", "default": "gpt-5.5"},
    }


def test_prepare_foreground_turn_records_canonical_decision(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(
        _enabled_config(),
        live_provider="openai-codex",
        live_model="gpt-5.6-terra",
        live_api_mode="codex_app_server",
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = prepare_raphael_turn(
            turn_id="turn-1",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="請修復 gateway bug 並跑測試",
            conversation_history=[],
        )
        state = read_state()

    assert decision is not None
    assert decision.mode == "tool_task"
    assert decision.runtime_contract.base_model == "gpt-5.6-terra"
    assert decision.route.base_llm_model == "gpt-5.6-terra"
    assert decision.completion_policy == "mutation"
    assert state.last_decision is not None
    assert state.last_decision["turn_id"] == "turn-1"
    assert state.last_decision["mode"] == "tool_task"


def test_background_turn_does_not_create_or_record_foreground_decision(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(_enabled_config())

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = prepare_raphael_turn(
            turn_id="turn-background",
            origin=RaphaelTurnOrigin.BACKGROUND_REVIEW,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="Review the conversation above and update skills",
            conversation_history=[],
        )
        state = read_state()

    assert decision is None
    assert state.last_decision is None


def test_disabled_raphael_does_not_prepare_decision(tmp_path):
    config = {"plugins": {"enabled": []}, "raphael": {"enabled": False}}
    runtime_contract = resolve_raphael_runtime_contract(config)

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = prepare_raphael_turn(
            turn_id="turn-disabled",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=config,
            user_message="hello",
            conversation_history=[],
        )

    assert decision is None

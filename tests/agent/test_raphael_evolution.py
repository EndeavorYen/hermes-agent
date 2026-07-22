from __future__ import annotations

import os
import multiprocessing
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import agent.raphael.evolution as evolution_module
from agent.raphael.evolution import (
    append_evolution_record,
    append_evolution_status_record,
    build_evolution_action_proposal,
    build_raphael_evolution_review_prompt,
    decide_raphael_evolution,
    read_evolution_records,
    record_evolution_action_proposal,
    summarize_learning_outcome,
)
from agent.raphael.mission import create_mission
from agent.raphael.models import RaphaelState, RiskLevel
from agent.raphael.state import read_state, write_state


def _config(**raphael_overrides):
    raphael = {
        "enabled": True,
        "mode": "advisor",
        "skill_writes_enabled": True,
        "memory_writes_enabled": True,
        "evolution": {
            "enabled": True,
            "skill_review_enabled": True,
            "memory_review_enabled": True,
        },
    }
    raphael.update(raphael_overrides)
    return {"plugins": {"enabled": ["raphael"], "disabled": []}, "raphael": raphael}


def _home_env(path: Path):
    return patch.dict(os.environ, {"HERMES_HOME": str(path)})


def _crossprocess_control_writer(
    home: str,
    control_write_started,
    evolution_read_seen,
    errors,
) -> None:
    os.environ["HERMES_HOME"] = home
    import agent.raphael.state as state_module

    original_atomic_write = state_module.atomic_json_write

    def delayed_atomic_write(*args, **kwargs):
        control_write_started.set()
        evolution_read_seen.wait(timeout=0.5)
        return original_atomic_write(*args, **kwargs)

    state_module.atomic_json_write = delayed_atomic_write
    try:
        state_module.record_control_decision(
            {
                "mode": "text_reasoning",
                "goal": {"target_artifact": "release", "phase": "verify"},
                "next_action": "run tests",
                "evidence": {},
                "confidence": 0.9,
            },
            turn_id="turn-crossprocess-control",
        )
    except BaseException as exc:  # noqa: BLE001 - child errors must reach parent.
        errors.put(repr(exc))


def _crossprocess_evolution_writer(
    home: str,
    proof_record: dict,
    control_write_started,
    evolution_read_seen,
    errors,
) -> None:
    os.environ["HERMES_HOME"] = home
    import agent.raphael.evolution as child_evolution_module

    original_read_state = child_evolution_module.read_state

    def tracked_read_state():
        evolution_read_seen.set()
        return original_read_state()

    child_evolution_module.read_state = tracked_read_state
    try:
        if not control_write_started.wait(timeout=5):
            raise TimeoutError("control writer never reached its state write")
        child_evolution_module.record_evolution_action_proposal(
            _independent_pair(proof_record)
        )
    except BaseException as exc:  # noqa: BLE001 - child errors must reach parent.
        errors.put(repr(exc))


def _outcome_metadata(
    occurrence_id: str,
    *,
    cluster: str = "proof-gate:missing-proof",
    component: str = "raphael.proof_gate",
    replay_command: str = "pytest tests/agent/test_raphael_finalization.py -q",
) -> dict[str, str]:
    return {
        "origin": "foreground",
        "failure_cluster_id": cluster,
        "component": component,
        "owner": "raphael-control",
        "occurrence_id": occurrence_id,
        "signal_kind": "reproduced_failure",
        "replay_command": replay_command,
        "baseline_metric": "failure_count=1",
        "target_metric": "failure_count=0",
        "approval_class": "R2",
    }


def _independent_pair(record: dict) -> list[dict]:
    first = {**record, "metadata": dict(record.get("metadata") or {})}
    second = {
        **record,
        "metadata": {
            **dict(record.get("metadata") or {}),
            "occurrence_id": "turn-outcome-2",
        },
    }
    return [first, second]


def test_learning_outcome_summary_requires_artifact_and_rollback():
    summary = summarize_learning_outcome(
        {
            "skill_name": "hermes-upgrade-operations",
            "source": "current conversation",
            "saved": True,
            "rollback": "archive the skill with hermes curator restore or delete the pending proposal",
        }
    )

    assert "hermes-upgrade-operations" in summary
    assert "current conversation" in summary
    assert "rollback" in summary.lower()


def test_disabled_raphael_never_schedules_evolution_review():
    decision = decide_raphael_evolution(
        user_message="不對，這個 workflow 要記住",
        final_response="ok",
        messages=[],
        turn_exit_reason="text_response",
        config={"raphael": {"enabled": False}},
    )

    assert decision.should_review is False
    assert decision.review_skills is False
    assert decision.review_memory is False
    assert decision.mode == "disabled"


def test_plugin_disabled_raphael_never_schedules_evolution_review():
    decision = decide_raphael_evolution(
        user_message="不對，這個 workflow 要記住",
        final_response="ok",
        messages=[],
        turn_exit_reason="text_response",
        config={
            "plugins": {"enabled": ["raphael"], "disabled": ["raphael"]},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "skill_writes_enabled": True,
                "memory_writes_enabled": True,
                "evolution": {"enabled": True},
            },
        },
    )

    assert decision.should_review is False
    assert decision.review_skills is False
    assert decision.review_memory is False
    assert decision.mode == "disabled"


def test_user_correction_triggers_active_skill_evolution_review():
    decision = decide_raphael_evolution(
        user_message="不對，拉斐爾模式不是這樣，要像賢者之王一樣主動進化技能",
        final_response="我會修正",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
    )

    assert decision.should_review is True
    assert decision.review_skills is True
    assert decision.review_memory is True
    assert decision.mode == "active_evolution"
    assert "user_correction" in decision.reason_codes
    assert decision.review_label == "Raphael evolution review"


def test_casual_raphael_or_skill_questions_do_not_trigger_evolution_review():
    for user_message in ("你是大賢者嗎？", "What skills are available?"):
        decision = decide_raphael_evolution(
            user_message=user_message,
            final_response="簡短回答",
            messages=[],
            turn_exit_reason="text_response",
            config=_config(),
        )

        assert decision.should_review is False
        assert decision.mode == "observe"
        assert decision.reason_codes == ()


def test_assistant_memory_wording_does_not_trigger_durable_evolution():
    decision = decide_raphael_evolution(
        user_message="請簡短回答這個問題",
        final_response="我會記住，下次保持簡短。",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
    )

    assert decision.should_review is False
    assert decision.review_memory is False
    assert decision.mode == "observe"
    assert decision.reason_codes == ()


def test_visual_provider_failure_triggers_skill_evolution_not_generic_success():
    messages = [
        {
            "role": "tool",
            "name": "visual_agent_generate",
            "content": (
                '{"success": false, "failure_layer": "provider_health", '
                '"error": "Grok Web Imagine browser automation timed out"}'
            ),
        }
    ]

    decision = decide_raphael_evolution(
        user_message="幫我做 image + video",
        final_response="候選圖未通過",
        messages=messages,
        turn_exit_reason="direct_visual_agent_handoff",
        config=_config(),
    )

    assert decision.should_review is True
    assert decision.review_skills is True
    assert "visual_or_provider_failure" in decision.reason_codes
    assert "provider_health" in decision.evidence_summary
    assert decision.metadata["affected_capability"] == "visual.agent_mode"
    assert "promotion_gate" in decision.metadata
    assert "rollback_condition" in decision.metadata


def test_story_video_validation_block_does_not_trigger_visual_evolution():
    messages = [
        {
            "role": "tool",
            "name": "terminal",
            "content": (
                '{"success": false, "failure_layer": "delivery", "output": '
                '"STORY_VIDEO_GATE: BLOCKED\\n'
                'FAIL schema: v1 checklist cannot certify final after render-contract gates"}'
            ),
        },
        {
            "role": "tool",
            "name": "terminal",
            "content": (
                '{"success": false, "failure_layer": "delivery", "output": '
                '"STORY_VIDEO_RENDER_CONTRACT: BLOCKED\\n'
                'FAIL tts_contract: expected structured tts_contract"}'
            ),
        },
    ]

    decision = decide_raphael_evolution(
        user_message="只檢查這個 story-video 專案是否可以稱 final，不要生成影片",
        final_response="BLOCKED：舊 v1 checklist 缺 render-contract evidence。",
        messages=messages,
        turn_exit_reason="text_response(finish_reason=stop)",
        config=_config(),
    )

    assert decision.should_review is False
    assert decision.mode == "observe"
    assert "visual_or_provider_failure" not in decision.reason_codes


def test_story_video_validation_with_recovered_terminal_error_does_not_trigger_visual_evolution():
    messages = [
        {
            "role": "tool",
            "name": "terminal",
            "content": '{"success": false, "output": "/bin/bash: line 2: python: command not found"}',
        },
        {
            "role": "tool",
            "name": "terminal",
            "content": (
                '{"success": false, "output": "STORY_VIDEO_GATE: BLOCKED\\n'
                'FAIL schema: v1 checklist cannot certify final after render-contract gates"}'
            ),
        },
        {
            "role": "tool",
            "name": "terminal",
            "content": (
                '{"success": false, "output": "STORY_VIDEO_RENDER_CONTRACT: BLOCKED\\n'
                'FAIL tts_contract: expected structured tts_contract"}'
            ),
        },
    ]

    decision = decide_raphael_evolution(
        user_message="只檢查這個 story-video 專案是否可以稱 final，不要生成影片",
        final_response=(
            "BLOCKED\n"
            "阻塞原因：舊 v1 checklist 缺 render-contract evidence。\n"
            "下一步：migrate to v2."
        ),
        messages=messages,
        turn_exit_reason="text_response(finish_reason=stop)",
        config=_config(),
    )

    assert decision.should_review is False
    assert decision.mode == "observe"
    assert "visual_or_provider_failure" not in decision.reason_codes


def test_llm_only_narrative_mentions_visual_tool_without_visual_failure_evidence():
    messages = [
        {
            "role": "user",
            "content": (
                "拉斐爾，請 LLM-only 分析 routing bug，不要呼叫工具、不要產圖；"
                "檢查 visual_agent_generate 是否被誤觸發。"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "解析完成：visual_agent_generate 只是被提到的錯誤路線，"
                "本回合 tool calls = 0。"
            ),
        },
    ]

    decision = decide_raphael_evolution(
        user_message=messages[0]["content"],
        final_response=messages[1]["content"],
        messages=messages,
        turn_exit_reason="text_response(finish_reason=stop)",
        config=_config(),
    )

    assert decision.should_review is False
    assert decision.mode == "observe"
    assert "visual_or_provider_failure" not in decision.reason_codes


def test_direct_visual_handoff_text_failure_triggers_visual_evolution():
    decision = decide_raphael_evolution(
        user_message="幫我做 image + video",
        final_response="視覺生成失敗：候選圖未通過。",
        messages=[{"role": "user", "content": "幫我做 image + video"}],
        turn_exit_reason="direct_visual_agent_handoff",
        config=_config(),
    )

    assert decision.should_review is True
    assert decision.review_skills is True
    assert "visual_or_provider_failure" in decision.reason_codes
    assert "候選圖未通過" in decision.evidence_summary


def test_failed_proof_gate_triggers_proof_evolution_signal():
    final_response = (
        "狀態：還不能判定完成，Raphael proof gate 沒看到足夠證據。\n"
        "風險：這是工具/runtime 任務，但目前缺少 focused_tests。\n"
        "下一步：先執行必要測試或 runtime smoke，再回報具體證據。"
    )

    decision = decide_raphael_evolution(
        user_message="請修復 Hermes runtime bug 並驗證到能上線",
        final_response=final_response,
        messages=[{"role": "assistant", "content": final_response}],
        turn_exit_reason="text_response",
        config=_config(),
    )

    assert decision.should_review is True
    assert decision.review_skills is True
    assert "failed_proof" in decision.reason_codes
    assert "proof gate" in decision.evidence_summary.lower()
    assert decision.metadata["affected_capability"] == "raphael.proof_gate"
    assert "promotion_gate" in decision.metadata


def test_high_risk_mutation_stays_proposal_only_without_background_writes():
    decision = decide_raphael_evolution(
        user_message="之後自動修改 cron、發布到 Slack、安裝工具，不用再問我",
        final_response="我不能直接這樣做",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
    )

    assert decision.should_review is False
    assert decision.review_skills is False
    assert decision.review_memory is False
    assert decision.proposal_only is True
    assert decision.mode == "proposal_only"
    assert "high_risk_mutation" in decision.reason_codes


def test_review_prompt_frames_raphael_as_sage_king_skill_evolver():
    decision = decide_raphael_evolution(
        user_message="不要再只做被動 advisor，要主動進化",
        final_response="收到",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
    )

    prompt = build_raphael_evolution_review_prompt(decision)

    assert "Raphael Sage King Evolution Review" in prompt
    assert "not a passive advisor" in prompt
    assert "skill_manage" in prompt
    assert "auditable" in prompt
    assert "rollback" in prompt
    assert "user_correction" in prompt


def test_evolution_records_are_redacted_and_round_trip(tmp_path):
    home = tmp_path / "hermes-home"
    decision = decide_raphael_evolution(
        user_message="我的 token 是 sk-secret，請記住不要外洩；不對，這要成為技能",
        final_response="ok",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
    )

    with _home_env(home):
        append_evolution_record(decision, status="scheduled")
        records = read_evolution_records(limit=5)

    assert len(records) == 1
    assert records[0]["status"] == "scheduled"
    assert records[0]["reason_codes"] == list(decision.reason_codes)
    assert "sk-secret" not in str(records[0])
    assert "[redacted]" in str(records[0])


def test_evolution_record_preview_redacts_private_paths_and_large_payloads(tmp_path):
    home = tmp_path / "hermes-home"
    decision = decide_raphael_evolution(
        user_message=(
            "不對，請記住 /Users/example/private/ref.png 和 "
            "data:image/png;base64,"
            + "a" * 120
        ),
        final_response="ok",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
    )

    with _home_env(home):
        append_evolution_record(decision, status="scheduled")
        records = read_evolution_records(limit=1)

    serialized = str(records[0])
    assert "/Users/example/private/ref.png" not in serialized
    assert "data:image/png;base64" not in serialized
    assert "a" * 80 not in serialized
    assert "[redacted-path]" in serialized


def test_evolution_metadata_is_sanitized_auditable_and_persisted(tmp_path):
    home = tmp_path / "hermes-home"
    decision = decide_raphael_evolution(
        user_message="不對，視覺 fallback 要學會分類，不要污染 durable policy",
        final_response="我會讓拉斐爾記錄可回滾的技能改進",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
        metadata={
            "affected_capability": "visual.agent_mode.provider_recovery",
            "proposed_change": "x" * 300 + " sk-secret",
            "confidence": 1.7,
            "promotion_gate": "focused tests plus live LLM smoke",
            "rollback_condition": "disable if stale artifacts reappear",
            "raw_prompt": "must not be stored",
        },
    )

    assert decision.metadata["affected_capability"] == (
        "visual.agent_mode.provider_recovery"
    )
    assert len(decision.metadata["proposed_change"]) <= 240
    assert decision.metadata["confidence"] == 1.0
    assert "raw_prompt" not in decision.metadata
    assert "sk-secret" not in str(decision.metadata)

    with _home_env(home):
        append_evolution_record(
            decision,
            status="scheduled",
            metadata={
                "confidence": 0.42,
                "rollback_condition": "revert if user says 不對 again",
                "private_log": "drop me",
            },
        )
        records = read_evolution_records(limit=1)

    assert records[0]["metadata"]["affected_capability"] == (
        "visual.agent_mode.provider_recovery"
    )
    assert records[0]["metadata"]["confidence"] == 0.42
    assert records[0]["metadata"]["rollback_condition"] == (
        "revert if user says 不對 again"
    )
    assert "private_log" not in records[0]["metadata"]


def test_evolution_metadata_redacts_real_tokens_without_redacting_skill_words():
    decision = decide_raphael_evolution(
        user_message="不對，請強化 skill routing 並遮蔽 sk-secret",
        final_response="ok",
        messages=[],
        turn_exit_reason="text_response",
        config=_config(),
        metadata={
            "proposed_change": "Improve skill routing while hiding sk-secret.",
            "confidence": 0.7,
        },
    )

    assert "skill routing" in decision.metadata["proposed_change"]
    assert "sk-secret" not in decision.metadata["proposed_change"]
    assert "[redacted]" in decision.metadata["proposed_change"]


def test_evolution_status_metadata_keeps_auditable_summary_without_raw_details(tmp_path):
    home = tmp_path / "hermes-home"

    with _home_env(home):
        append_evolution_status_record(
            status="background_failed",
            metadata={
                "review_label": "Raphael evolution review",
                "actions": ["skill_manage.patch", "memory.write"],
                "session_id": "session-private-123",
                "error": "RuntimeError: /Users/example/private/log.txt failed",
                "raw_prompt": "drop me",
            },
        )
        records = read_evolution_records(limit=1)

    metadata = records[0]["metadata"]
    assert metadata["review_label"] == "Raphael evolution review"
    assert metadata["action_count"] == 2
    assert metadata["action_types"] == ["memory.write", "skill_manage.patch"]
    assert metadata["error_class"] == "RuntimeError"
    assert "session_hash" in metadata
    assert "session-private-123" not in str(metadata)
    assert "/Users/example/private/log.txt" not in str(metadata)
    assert "raw_prompt" not in metadata


def test_repeated_evolution_pattern_builds_approval_gated_skill_patch_proposal():
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "Raphael proof gate blocked an unverified completion claim",
        "metadata": {
            **_outcome_metadata("turn-proof-1"),
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof-gate next-action summaries",
            "promotion_gate": "focused tests plus LLM smoke",
            "rollback_condition": "user says 不對 again",
        },
    }
    visual_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["visual_or_provider_failure"],
        "evidence_summary": "single visual lesson",
        "metadata": {
            **_outcome_metadata(
                "turn-visual-1",
                cluster="artifact-quality:weak-candidate",
                component="visual.artifact_quality",
                replay_command="pytest tests/visual/test_agent_mode_handoff.py -q",
            ),
            "affected_capability": "visual.agent_mode",
            "proposed_change": "prefer image-first video repair loop",
            "promotion_gate": "visual E2E evidence",
            "rollback_condition": "artifact quality gets worse",
        },
    }

    proposal = build_evolution_action_proposal(
        [*_independent_pair(proof_record), visual_record]
    )

    assert proposal is not None
    assert proposal.action_type == "skill_patch"
    assert proposal.risk == RiskLevel.R2
    assert proposal.requires_approval is True
    assert proposal.proposal_id.startswith("evolution-")
    assert "Raphael proof gate" in proposal.summary
    assert "2 recurring signals" in proposal.summary
    assert "tighten proof-gate next-action summaries" in proposal.summary
    assert "focused tests plus LLM smoke" in proposal.summary
    assert "user says 不對 again" in proposal.summary
    assert "visual agent mode" not in proposal.summary
    assert "evolution:raphael.proof_gate" in proposal.evidence_refs
    assert "pattern_count:2" in proposal.evidence_refs


def test_repeated_signal_without_replay_does_not_create_patch_proposal():
    signal = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "proof failed",
        "metadata": {
            "origin": "foreground",
            "occurrence_id": "turn-1",
            "failure_cluster_id": "proof-gate:missing-focused-tests",
            "component": "raphael.proof_gate",
            "owner": "raphael-control",
            "baseline_metric": "unsupported_completion_rate=1",
            "target_metric": "unsupported_completion_rate=0",
            "approval_class": "R2",
        },
    }
    second = {**signal, "metadata": {**signal["metadata"], "occurrence_id": "turn-2"}}

    assert build_evolution_action_proposal((signal, second)) is None


def test_user_correction_plus_repro_creates_outcome_contract():
    shared = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "evidence_summary": "proof gate completion mismatch",
        "metadata": {
            "origin": "foreground",
            "failure_cluster_id": "proof-gate:missing-focused-tests",
            "component": "raphael.proof_gate",
            "owner": "raphael-control",
            "replay_command": "pytest tests/agent/test_raphael_finalization.py -q",
            "baseline_metric": "unsupported_completion_rate=1",
            "target_metric": "unsupported_completion_rate=0",
            "approval_class": "R2",
            "proposed_change": "tighten finalizer proof enforcement",
            "promotion_gate": "focused finalizer tests pass",
            "rollback_condition": "verified completions become blocked",
        },
    }
    correction = {
        **shared,
        "reason_codes": ["user_correction"],
        "metadata": {
            **shared["metadata"],
            "occurrence_id": "turn-correction",
            "signal_kind": "user_correction",
        },
    }
    reproduced = {
        **shared,
        "reason_codes": ["failed_proof"],
        "metadata": {
            **shared["metadata"],
            "occurrence_id": "turn-repro",
            "signal_kind": "reproduced_failure",
        },
    }

    proposal = build_evolution_action_proposal((correction, reproduced))

    assert proposal is not None
    assert proposal.metadata["replay_command"]
    assert proposal.metadata["baseline_metric"]
    assert proposal.metadata["target_metric"]
    assert proposal.metadata["failure_cluster_id"] == (
        "proof-gate:missing-focused-tests"
    )


def test_repeated_evolution_skill_patch_proposal_includes_rollout_plan():
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "Raphael proof gate blocked an unverified completion claim",
        "metadata": {
            **_outcome_metadata("turn-proof-1"),
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof-gate next-action summaries",
            "promotion_gate": "focused tests plus LLM smoke",
            "rollback_condition": "user says 不對 again",
        },
    }

    proposal = build_evolution_action_proposal(_independent_pair(proof_record))

    assert proposal is not None
    assert proposal.metadata["affected_capability"] == "raphael.proof_gate"
    assert proposal.metadata["recurring_signal_count"] == 2
    assert proposal.metadata["rollout_plan"] == {
        "status": "pending_approval",
        "risk": "R2",
        "manual_steps": [
            "Review the scoped local proposal for raphael.proof_gate.",
            "Apply the proposed skill or strategy change only after approval.",
            "Run the promotion gate before enabling the change.",
        ],
        "verification_commands": [
            "pytest tests/agent/test_raphael_finalization.py -q",
            "pytest tests/agent/test_raphael_evolution.py -q",
            "hermes raphael readiness --readiness-profile llm --check",
        ],
        "promotion_gate": "focused tests plus LLM smoke",
        "rollback_condition": "user says 不對 again",
    }


def test_record_evolution_action_proposal_is_deduplicated_and_preserves_state(tmp_path):
    home = tmp_path / "hermes-home"
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "Raphael proof gate blocked an unverified completion claim",
        "metadata": {
            **_outcome_metadata("turn-proof-1"),
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof-gate next-action summaries",
            "promotion_gate": "focused tests plus LLM smoke",
            "rollback_condition": "user says 不對 again",
        },
    }

    with _home_env(home):
        first = record_evolution_action_proposal(_independent_pair(proof_record))
        second = record_evolution_action_proposal(_independent_pair(proof_record))
        state = read_state()

    assert first is not None
    assert second is not None
    assert second.proposal_id == first.proposal_id
    assert len(state.action_proposals) == 1
    assert state.action_proposals[0].proposal_id == first.proposal_id
    assert state.action_proposals[0].requires_approval is True


def test_record_evolution_action_proposal_preserves_active_mission(tmp_path):
    home = tmp_path / "hermes-home"
    now = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)
    mission = create_mission(
        mission_id="mission-active",
        goal="Harden the Hermes upgrade",
        success_conditions=("focused tests pass",),
        phase="execute",
        next_action="run focused tests",
        selected_strategy="tdd",
        required_proofs=("focused_tests",),
        now=now,
    )
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "proof gate blocked completion",
        "metadata": {
            **_outcome_metadata("turn-proof-1"),
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof checks",
            "promotion_gate": "focused tests",
            "rollback_condition": "proof quality regresses",
        },
    }

    with _home_env(home):
        write_state(
            RaphaelState(
                status_cards=(),
                action_proposals=(),
                updated_at=now,
                active_mission=mission,
            )
        )
        record_evolution_action_proposal(_independent_pair(proof_record))
        stored = read_state()

    assert stored.active_mission == mission
    assert len(stored.action_proposals) == 1


def test_persistent_error_is_force_redacted_single_line_and_bounded():
    secret = "sk-" + "secret1234567890"
    error = RuntimeError(
        f"provider failed at /Users/example/private/trace.json with {secret}\n"
        + "x" * 500
    )

    sanitizer = getattr(evolution_module, "sanitize_persistent_error", None)
    assert callable(sanitizer), "persistent error sanitizer is required"
    sanitized = sanitizer(error)

    assert secret not in sanitized
    assert "/Users/example/private/trace.json" not in sanitized
    assert "\n" not in sanitized
    assert len(sanitized) <= 240


def test_concurrent_control_and_evolution_rmw_preserve_both_updates(
    tmp_path,
    monkeypatch,
):
    import agent.raphael.evolution as evolution_module
    import agent.raphael.state as state_module

    home = tmp_path / "hermes-home"
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "proof gate blocked completion",
        "metadata": {
            **_outcome_metadata("turn-proof-1"),
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof checks",
            "promotion_gate": "focused tests",
            "rollback_condition": "proof quality regresses",
        },
    }
    control_write_started = threading.Event()
    evolution_read_seen = threading.Event()
    original_atomic_write = state_module.atomic_json_write
    original_read_state = state_module.read_state

    def delayed_atomic_write(*args, **kwargs):
        if threading.current_thread().name == "control-writer":
            control_write_started.set()
            evolution_read_seen.wait(timeout=0.25)
        return original_atomic_write(*args, **kwargs)

    def tracked_evolution_read():
        evolution_read_seen.set()
        return original_read_state()

    monkeypatch.setattr(state_module, "atomic_json_write", delayed_atomic_write)
    monkeypatch.setattr(evolution_module, "read_state", tracked_evolution_read)

    def write_control():
        state_module.record_control_decision(
            {
                "mode": "text_reasoning",
                "goal": {"target_artifact": "release", "phase": "verify"},
                "next_action": "run tests",
                "evidence": {},
                "confidence": 0.9,
            },
            turn_id="turn-control",
        )

    def write_evolution():
        assert control_write_started.wait(timeout=1)
        evolution_module.record_evolution_action_proposal(
                _independent_pair(proof_record)
            )

    with _home_env(home):
        control_thread = threading.Thread(target=write_control, name="control-writer")
        evolution_thread = threading.Thread(target=write_evolution, name="evolution-writer")
        control_thread.start()
        evolution_thread.start()
        control_thread.join(timeout=2)
        evolution_thread.join(timeout=2)
        stored = read_state()

    assert not control_thread.is_alive()
    assert not evolution_thread.is_alive()
    assert len(stored.status_cards) == 1
    assert len(stored.action_proposals) == 1


def test_crossprocess_control_and_evolution_rmw_preserve_state(tmp_path):
    home = tmp_path / "hermes-home"
    now = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)
    mission = create_mission(
        mission_id="mission-crossprocess",
        goal="Harden the Hermes upgrade",
        success_conditions=("focused tests pass",),
        phase="execute",
        next_action="run focused tests",
        selected_strategy="tdd",
        required_proofs=("focused_tests",),
        now=now,
    )
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "proof gate blocked completion",
        "metadata": {
            **_outcome_metadata("turn-proof-1"),
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof checks",
            "promotion_gate": "focused tests",
            "rollback_condition": "proof quality regresses",
        },
    }
    with _home_env(home):
        write_state(
            RaphaelState(
                status_cards=(),
                action_proposals=(),
                updated_at=now,
                active_mission=mission,
            )
        )

    context = multiprocessing.get_context("spawn")
    control_write_started = context.Event()
    evolution_read_seen = context.Event()
    errors = context.Queue()
    control_process = context.Process(
        target=_crossprocess_control_writer,
        args=(
            str(home),
            control_write_started,
            evolution_read_seen,
            errors,
        ),
    )
    evolution_process = context.Process(
        target=_crossprocess_evolution_writer,
        args=(
            str(home),
            proof_record,
            control_write_started,
            evolution_read_seen,
            errors,
        ),
    )

    control_process.start()
    evolution_process.start()
    control_process.join(timeout=10)
    evolution_process.join(timeout=10)
    if control_process.is_alive():
        control_process.terminate()
        control_process.join()
    if evolution_process.is_alive():
        evolution_process.terminate()
        evolution_process.join()

    child_errors = []
    while not errors.empty():
        child_errors.append(errors.get())
    with _home_env(home):
        stored = read_state()

    assert control_process.exitcode == 0
    assert evolution_process.exitcode == 0
    assert child_errors == []
    assert len(stored.status_cards) == 1
    assert len(stored.action_proposals) == 1
    assert stored.active_mission == mission


def test_append_evolution_record_promotes_repeated_pattern_to_pending_proposal(tmp_path):
    home = tmp_path / "hermes-home"
    final_response = (
        "狀態：還不能判定完成，Raphael proof gate 沒看到足夠證據。\n"
        "下一步：先執行必要測試或 runtime smoke，再回報具體證據。"
    )
    decision = decide_raphael_evolution(
        user_message="請修復 Hermes runtime bug 並驗證到能上線",
        final_response=final_response,
        messages=[{"role": "assistant", "content": final_response}],
        turn_exit_reason="text_response",
        config=_config(),
        metadata={
            **_outcome_metadata("turn-proof-1"),
            "proposed_change": "tighten proof-gate next-action summaries",
            "promotion_gate": "focused tests plus LLM smoke",
            "rollback_condition": "user says 不對 again",
        },
    )
    second_decision = replace(
        decision,
        metadata={**dict(decision.metadata or {}), "occurrence_id": "turn-proof-2"},
    )

    with _home_env(home):
        append_evolution_record(second_decision, status="scheduled")
        assert read_state().action_proposals == ()
        append_evolution_record(decision, status="scheduled")
        state = read_state()

    assert len(state.action_proposals) == 1
    proposal = state.action_proposals[0]
    assert proposal.action_type == "skill_patch"
    assert proposal.requires_approval is True
    assert "Raphael proof gate" in proposal.summary
    assert "2 recurring signals" in proposal.summary

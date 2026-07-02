import hashlib
from datetime import datetime, timedelta, timezone

from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel, StatusCard
from agent.raphael.status import active_cards, render_status


NOW = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)


def _card(card_id: str, *, title: str, expires_at: datetime) -> StatusCard:
    return StatusCard(
        card_id=card_id,
        severity="warning",
        title=title,
        summary=f"{title} summary.",
        observed_at=NOW - timedelta(minutes=15),
        expires_at=expires_at,
        source="raphael-test",
        confidence=0.84,
        evidence_refs=(f"evidence:{card_id}",),
    )


def _proposal(proposal_id: str) -> ActionProposal:
    return ActionProposal(
        proposal_id=proposal_id,
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch a skill draft after approval.",
        evidence_refs=("card-1",),
        created_at=NOW,
    )


def _state(
    *,
    cards: tuple[StatusCard, ...] = (),
    proposals: tuple[ActionProposal, ...] = (),
) -> RaphaelState:
    return RaphaelState(
        status_cards=cards,
        action_proposals=proposals,
        updated_at=NOW,
    )


def test_active_cards_filters_expired_cards_and_preserves_order():
    expired = _card("card-1", title="Expired card", expires_at=NOW)
    active_one = _card("card-2", title="First active", expires_at=NOW + timedelta(minutes=1))
    active_two = _card("card-3", title="Second active", expires_at=NOW + timedelta(hours=1))
    state = _state(cards=(expired, active_one, active_two))

    assert active_cards(state, now=NOW) == [active_one, active_two]


def test_empty_status_render_names_sage_king_evolution_mode():
    output = render_status(_state(), now=NOW)

    assert "Raphael Sage King" in output
    assert "Mode: proactive evolution control layer." in output
    assert "賢者總覽:" in output
    assert "No active status cards." in output
    assert "No pending action proposals." in output
    assert "Skill Evolution:" in output
    assert "gated background review" in output
    assert "auditable" in output
    assert "rollback" in output
    assert "cron, tools, and public delivery require explicit approval" in output


def test_render_status_starts_with_sage_king_brief_before_detail_sections():
    card = StatusCard(
        card_id="card-proof",
        severity="warning",
        title="Raphael control decision",
        summary=(
            "mode=tool_task; target=runtime_state; phase=plan_execute_verify; "
            "next_action=run required proofs before completion claim; "
            "failure_layer=proof_gate"
        ),
        observed_at=NOW - timedelta(minutes=15),
        expires_at=NOW + timedelta(hours=1),
        source="general_tool_proof_gate",
        confidence=0.72,
        evidence_refs=("turn:proof",),
    )
    proposal = _proposal("proposal-brief")
    output = render_status(
        _state(cards=(card,), proposals=(proposal,)),
        now=NOW,
        mission_state={
            "mission_id": "mission-abc123",
            "goal": "修復 runtime bug",
            "phase": "strategy_selected",
            "next_action": "plan_execute_verify",
            "proof_status": "pending",
        },
        evolution_records=[
            {
                "status": "scheduled",
                "mode": "active_evolution",
                "should_review": True,
                "reason_codes": ["failed_proof"],
                "evidence_summary": (
                    "Raphael proof gate blocked an unverified completion claim"
                ),
                "metadata": {"affected_capability": "raphael.proof_gate"},
            }
        ],
    )

    assert output.index("賢者總覽:") < output.index("Status Cards:")
    assert "- 當前任務：修復 runtime bug" in output
    assert "- 主要狀態：warning 1 類" in output
    assert "- 待核准行動：1 件" in output
    assert "- 下一步：先規劃，再執行，最後用證據驗證" in output
    assert "- 演化狀態：主動進化審核中，需通過證據門檻" in output
    assert "mission-abc123" not in output
    assert "strategy_selected" not in output
    assert "plan_execute_verify" not in output


def test_render_includes_active_warning_card_and_pending_r2_proposal():
    card = _card("card-1", title="Gateway warning", expires_at=NOW + timedelta(hours=1))
    proposal = _proposal("proposal-1")
    output = render_status(_state(cards=(card,), proposals=(proposal,)), now=NOW)
    proposal_ref = hashlib.sha256(proposal.proposal_id.encode("utf-8")).hexdigest()[:12]

    assert "warning" in output
    assert "Gateway warning" in output
    assert "raphael-test" in output
    assert "0.84" in output
    assert "proposal-1" not in output
    assert "Patch a skill draft after approval." in output
    assert "R2" in output
    assert "requires approval" in output
    assert f"Approve: hermes raphael proposal approve {proposal_ref}" in output
    assert f"Reject: hermes raphael proposal reject {proposal_ref}" in output


def test_render_status_shows_pending_skill_patch_rollout_plan_without_raw_keys():
    proposal = ActionProposal(
        proposal_id="evolution-private-id",
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch Raphael proof gate after repeated failed-proof signals.",
        evidence_refs=("evolution:raphael.proof_gate", "pattern_count:2"),
        created_at=NOW,
        metadata={
            "affected_capability": "raphael.proof_gate",
            "rollout_plan": {
                "status": "pending_approval",
                "verification_commands": [
                    "pytest tests/agent/test_raphael_evolution.py -q",
                    "hermes raphael readiness --readiness-profile llm --check",
                ],
                "promotion_gate": "focused tests plus runtime, replay, or LLM smoke",
                "rollback_condition": "next evidence or user feedback shows worse behavior",
            },
        },
    )

    output = render_status(_state(proposals=(proposal,)), now=NOW)

    assert "Patch Raphael proof gate after repeated failed-proof signals." in output
    assert "Rollout: pending approval" in output
    assert (
        "Verify: pytest tests/agent/test_raphael_evolution.py -q; "
        "hermes raphael readiness --readiness-profile llm --check"
        in output
    )
    assert "Promote: focused tests plus runtime, replay, or LLM smoke" in output
    assert "Rollback: next evidence or user feedback shows worse behavior" in output
    assert "evolution-private-id" not in output
    assert "rollout_plan" not in output
    assert "verification_commands" not in output
    assert "pending_approval" not in output
    assert "affected_capability" not in output


def test_render_status_shows_safe_proposal_resolution_commands():
    proposal_id = "evolution-private-id"
    proposal = ActionProposal(
        proposal_id=proposal_id,
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch Raphael proof gate after repeated failed-proof signals.",
        evidence_refs=("evolution:raphael.proof_gate", "pattern_count:2"),
        created_at=NOW,
        metadata={
            "rollout_plan": {
                "status": "pending_approval",
                "verification_commands": [
                    "pytest tests/agent/test_raphael_evolution.py -q",
                ],
            },
        },
    )
    proposal_ref = hashlib.sha256(proposal_id.encode("utf-8")).hexdigest()[:12]

    output = render_status(_state(proposals=(proposal,)), now=NOW)

    assert f"Approve: hermes raphael proposal approve {proposal_ref}" in output
    assert f"Reject: hermes raphael proposal reject {proposal_ref}" in output
    assert proposal_id not in output


def test_render_status_does_not_show_applied_rollout_for_pending_proposal():
    proposal = ActionProposal(
        proposal_id="evolution-private-id",
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch Raphael proof gate after repeated failed-proof signals.",
        evidence_refs=("evolution:raphael.proof_gate", "pattern_count:2"),
        created_at=NOW,
        status="pending",
        metadata={
            "rollout_plan": {
                "status": "applied",
                "verification_commands": [
                    "pytest tests/agent/test_raphael_evolution.py -q",
                ],
            },
        },
    )

    output = render_status(_state(proposals=(proposal,)), now=NOW)

    assert "Pending Action Proposals:" in output
    assert "Rollout: pending approval" in output
    assert "Rollout: applied" not in output


def test_render_status_shows_approved_manual_rollout_without_raw_id():
    proposal_id = "evolution-private-id"
    proposal = ActionProposal(
        proposal_id=proposal_id,
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch Raphael proof gate after repeated failed-proof signals.",
        evidence_refs=("evolution:raphael.proof_gate", "pattern_count:2"),
        created_at=NOW,
        status="approved",
        metadata={
            "rollout_plan": {
                "status": "approved",
                "verification_commands": [
                    "pytest tests/agent/test_raphael_evolution.py -q",
                    "hermes raphael readiness --readiness-profile llm --check",
                ],
                "promotion_gate": "focused tests plus runtime, replay, or LLM smoke",
                "rollback_condition": "next evidence or user feedback shows worse behavior",
            },
        },
    )

    output = render_status(_state(proposals=(proposal,)), now=NOW)

    assert "Approved Manual Rollouts:" in output
    assert "Patch Raphael proof gate after repeated failed-proof signals." in output
    assert "Next manual rollout:" in output
    assert "Rollout: approved" in output
    assert (
        "Verify: pytest tests/agent/test_raphael_evolution.py -q; "
        "hermes raphael readiness --readiness-profile llm --check"
        in output
    )
    assert "Apply: manual only after verification; approval did not mutate durable policy." in output
    assert proposal_id not in output


def test_render_status_redacts_private_rollout_metadata_values():
    proposal = ActionProposal(
        proposal_id="evolution-private-id",
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch Raphael proof gate after repeated failed-proof signals.",
        evidence_refs=("evolution:raphael.proof_gate", "pattern_count:2"),
        created_at=NOW,
        metadata={
            "rollout_plan": {
                "status": "pending_approval",
                "verification_commands": [
                    "TOKEN=sk-secret123 pytest /Users/simon/private/test.py -q",
                ],
                "promotion_gate": "check /Users/simon/private/log.txt",
                "rollback_condition": "remove xoxb-secret123 if leaked",
            },
        },
    )

    output = render_status(_state(proposals=(proposal,)), now=NOW)

    assert "Verify: TOKEN=[redacted]" in output
    assert "[redacted-path]" in output
    assert "sk-secret123" not in output
    assert "xoxb-secret123" not in output
    assert "/Users/simon/private/test.py" not in output
    assert "/Users/simon/private/log.txt" not in output


def test_render_status_humanizes_legacy_control_card_fields():
    card = StatusCard(
        card_id="card-control",
        severity="info",
        title="Raphael control decision",
        summary=(
            "mode=visual_agent_generation; target=new_visual_package; "
            "phase=route_and_handoff; next_action=call_visual_agent_generate; "
            "blockers=missing_ref3; failure_layer=handoff_failure"
        ),
        observed_at=NOW - timedelta(minutes=15),
        expires_at=NOW + timedelta(hours=1),
        source="direct_visual_agent_handoff",
        confidence=0.91,
        evidence_refs=("turn:abc",),
    )

    output = render_status(_state(cards=(card,)), now=NOW)

    assert "視覺生成" in output
    assert "新視覺作品" in output
    assert "路由與交接" in output
    assert "呼叫 visual agent 生成" in output
    assert "需要 ref3" in output
    assert "handoff failure" in output
    assert "visual agent handoff" in output
    assert "mode=" not in output
    assert "target=" not in output
    assert "phase=" not in output
    assert "next_action=" not in output
    assert "blockers=" not in output
    assert "failure_layer=" not in output
    assert "direct_visual_agent_handoff" not in output


def test_render_status_humanizes_proof_gate_next_action():
    card = StatusCard(
        card_id="card-proof",
        severity="warning",
        title="Raphael control decision",
        summary=(
            "mode=tool_task; target=runtime_state; phase=plan_execute_verify; "
            "next_action=run required proofs before completion claim; "
            "failure_layer=proof_gate"
        ),
        observed_at=NOW - timedelta(minutes=15),
        expires_at=NOW + timedelta(hours=1),
        source="general_tool_proof_gate",
        confidence=0.72,
        evidence_refs=("turn:proof",),
    )

    output = render_status(_state(cards=(card,)), now=NOW)

    assert "下一步：先補齊必要證據，再宣稱完成" in output
    assert "run required proofs before completion claim" not in output


def test_render_status_humanizes_legacy_humanized_proof_gate_next_action():
    card = StatusCard(
        card_id="card-proof-legacy",
        severity="warning",
        title="Raphael control decision",
        summary=(
            "模式：工具任務；目標：runtime or repo state；階段：規劃、執行、驗證；"
            "下一步：run required proofs before completion claim；失敗層：proof gate"
        ),
        observed_at=NOW - timedelta(minutes=15),
        expires_at=NOW + timedelta(hours=1),
        source="general_tool_proof_gate",
        confidence=0.72,
        evidence_refs=("turn:proof",),
    )

    output = render_status(_state(cards=(card,)), now=NOW)

    assert "下一步：先補齊必要證據，再宣稱完成" in output
    assert "run required proofs before completion claim" not in output


def test_render_status_collapses_duplicate_status_cards():
    summary = (
        "mode=tool_task; target=runtime_state; phase=plan_execute_verify; "
        "next_action=run required proofs before completion claim; "
        "failure_layer=proof_gate"
    )
    cards = (
        StatusCard(
            card_id="proof-1",
            severity="warning",
            title="Raphael control decision",
            summary=summary,
            observed_at=NOW - timedelta(minutes=15),
            expires_at=NOW + timedelta(hours=1),
            source="general_tool_proof_gate",
            confidence=0.72,
            evidence_refs=("turn:1",),
        ),
        StatusCard(
            card_id="proof-2",
            severity="warning",
            title="Raphael control decision",
            summary=summary,
            observed_at=NOW - timedelta(minutes=10),
            expires_at=NOW + timedelta(hours=1),
            source="general_tool_proof_gate",
            confidence=0.90,
            evidence_refs=("turn:2",),
        ),
        StatusCard(
            card_id="proof-3",
            severity="warning",
            title="Raphael control decision",
            summary=summary,
            observed_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(hours=1),
            source="general_tool_proof_gate",
            confidence=0.80,
            evidence_refs=("turn:3",),
        ),
    )

    output = render_status(_state(cards=cards), now=NOW)

    assert output.count("- [warning] Raphael control decision") == 1
    assert output.count("下一步：先補齊必要證據，再宣稱完成") == 1
    assert "同類事件：3 次" in output
    assert "Confidence: 0.90" in output


def test_render_status_respects_max_cards():
    cards = (
        _card("card-1", title="First card", expires_at=NOW + timedelta(hours=1)),
        _card("card-2", title="Second card", expires_at=NOW + timedelta(hours=1)),
        _card("card-3", title="Third card", expires_at=NOW + timedelta(hours=1)),
    )

    output = render_status(_state(cards=cards), now=NOW, max_cards=2)

    assert "First card" in output
    assert "Second card" in output
    assert "Third card" not in output


def test_render_status_includes_recent_evolution_records():
    output = render_status(
        _state(),
        now=NOW,
        evolution_records=[
            {
                "status": "scheduled",
                "mode": "active_evolution",
                "reason_codes": ["user_correction"],
                "evidence_summary": "user corrected Raphael behavior",
                "metadata": {
                    "affected_capability": "raphael.skill_evolution",
                    "confidence": 0.66,
                    "promotion_gate": "focused tests plus smoke",
                    "rollback_condition": "user says 不對 again",
                },
            }
        ],
    )

    assert "Recent Evolution:" in output
    assert "已排程" in output
    assert "主動進化" in output
    assert "使用者修正" in output
    assert "user corrected Raphael behavior" in output
    assert "能力：Raphael skill evolution" in output
    assert "信心：0.66" in output
    assert "上線條件：focused tests plus smoke" in output
    assert "回滾條件：user says 不對 again" in output
    assert "reasons=" not in output
    assert "capability=" not in output
    assert "confidence=" not in output
    assert "promotion=" not in output
    assert "rollback=" not in output
    assert "user_correction" not in output
    assert "raphael.skill_evolution" not in output


def test_render_status_collapses_duplicate_recent_evolution_records():
    record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "reason_codes": ["failed_proof"],
        "evidence_summary": "Raphael proof gate blocked an unverified completion claim",
        "metadata": {
            "affected_capability": "raphael.proof_gate",
            "confidence": 0.66,
            "promotion_gate": (
                "Promote only after focused tests and a runtime, replay, "
                "or LLM smoke prove the next run improves."
            ),
            "rollback_condition": (
                "Rollback if user feedback or proof records show worse routing, "
                "recovery, delivery, or privacy behavior."
            ),
        },
    }

    output = render_status(
        _state(),
        now=NOW,
        evolution_records=[record, dict(record), dict(record)],
    )

    assert output.count("已排程 [主動進化]") == 1
    assert output.count("proof gate 擋下未驗證宣稱") == 1
    assert "proof gate 擋下未驗證完成宣稱" in output
    assert "同類演化：3 次" in output
    assert "Raphael proof gate blocked an unverified completion claim" not in output


def test_render_status_turns_latest_evolution_into_self_correction_plan():
    output = render_status(
        _state(),
        now=NOW,
        evolution_records=[
            {
                "status": "applied",
                "mode": "active_evolution",
                "reason_codes": ["quality_failure"],
                "evidence_summary": "older visual lesson",
                "metadata": {
                    "affected_capability": "visual.agent_mode",
                    "proposed_change": "prefer image-first video repair loop",
                    "confidence": 0.72,
                    "promotion_gate": "visual E2E evidence",
                    "rollback_condition": "artifact quality gets worse",
                },
            },
            {
                "status": "blocked",
                "mode": "proposal_only",
                "proposal_only": True,
                "reason_codes": ["failed_proof", "user_correction"],
                "evidence_summary": "proof gate blocked an unverified completion claim",
                "metadata": {
                    "affected_capability": "raphael.proof_gate",
                    "proposed_change": "tighten proof-gate next-action summaries",
                    "confidence": 0.61,
                    "promotion_gate": "focused tests plus LLM smoke",
                    "rollback_condition": "user says 不對 again",
                },
            },
        ],
    )

    assert "Active Self-Correction:" in output
    assert "能力：Raphael proof gate" in output
    assert "狀態：只提出建議，尚未寫入 durable policy" in output
    assert "修正方向：tighten proof-gate next-action summaries" in output
    assert "上線門檻：focused tests plus LLM smoke" in output
    assert "回滾條件：user says 不對 again" in output
    assert (
        "下一步：先通過 focused tests plus LLM smoke，再考慮套用 durable 變更"
        in output
    )
    assert "older visual lesson" not in output.split("Active Self-Correction:", 1)[1].split(
        "Recent Evolution:",
        1,
    )[0]
    assert "proposal_only" not in output
    assert "failed_proof" not in output
    assert "raphael.proof_gate" not in output


def test_render_status_prioritizes_repeated_evolution_pattern_over_latest_record():
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "Raphael proof gate blocked an unverified completion claim",
        "metadata": {
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof-gate next-action summaries",
            "confidence": 0.66,
            "promotion_gate": "focused tests plus LLM smoke",
            "rollback_condition": "user says 不對 again",
        },
    }
    latest_single_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["quality_failure"],
        "evidence_summary": "single visual lesson",
        "metadata": {
            "affected_capability": "visual.agent_mode",
            "proposed_change": "prefer image-first video repair loop",
            "confidence": 0.62,
            "promotion_gate": "visual E2E evidence",
            "rollback_condition": "artifact quality gets worse",
        },
    }

    output = render_status(
        _state(),
        now=NOW,
        evolution_records=[proof_record, dict(proof_record), latest_single_record],
    )
    active_section = output.split("Active Self-Correction:", 1)[1].split(
        "Recent Evolution:",
        1,
    )[0]

    assert "能力：Raphael proof gate" in active_section
    assert "修正方向：tighten proof-gate next-action summaries" in active_section
    assert "同類演化：2 次" in active_section
    assert "visual agent mode" not in active_section
    assert "single visual lesson" not in active_section


def test_sage_king_brief_prioritizes_repeated_evolution_pattern_over_latest_record():
    proof_record = {
        "status": "scheduled",
        "mode": "active_evolution",
        "should_review": True,
        "reason_codes": ["failed_proof"],
        "evidence_summary": "Raphael proof gate blocked an unverified completion claim",
        "metadata": {
            "affected_capability": "raphael.proof_gate",
            "proposed_change": "tighten proof-gate next-action summaries",
            "confidence": 0.66,
            "promotion_gate": "focused tests plus LLM smoke",
            "rollback_condition": "user says 不對 again",
        },
    }
    latest_single_record = {
        "status": "scheduled",
        "mode": "proposal_only",
        "proposal_only": True,
        "reason_codes": ["high_risk_mutation"],
        "evidence_summary": "single high-risk request",
        "metadata": {
            "affected_capability": "raphael.approval_policy",
            "proposed_change": "keep cron and delivery mutations approval-gated",
        },
    }

    output = render_status(
        _state(),
        now=NOW,
        evolution_records=[proof_record, dict(proof_record), latest_single_record],
    )
    brief_section = output.split("賢者總覽:", 1)[1].split("Status Cards:", 1)[0]

    assert "- 演化狀態：主動進化審核中，需通過證據門檻" in brief_section
    assert "只提出建議，尚未寫入 durable policy" not in brief_section


def test_render_status_humanizes_default_evolution_gate_language():
    output = render_status(
        _state(),
        now=NOW,
        evolution_records=[
            {
                "status": "scheduled",
                "mode": "active_evolution",
                "should_review": True,
                "reason_codes": ["failed_proof"],
                "evidence_summary": (
                    "Raphael proof gate blocked an unverified completion claim"
                ),
                "metadata": {
                    "affected_capability": "raphael.proof_gate",
                    "proposed_change": (
                        "Review the affected Raphael capability and update the "
                        "smallest skill, policy, or control path supported by "
                        "current evidence."
                    ),
                    "promotion_gate": (
                        "Promote only after focused tests and a runtime, replay, "
                        "or LLM smoke prove the next run improves."
                    ),
                    "rollback_condition": (
                        "Rollback if user feedback or proof records show worse "
                        "routing, recovery, delivery, or privacy behavior."
                    ),
                },
            }
        ],
    )

    assert "修正方向：檢查受影響的 Raphael 能力" in output
    assert "上線門檻：聚焦測試 + runtime/replay/LLM smoke 證明下一輪有改善" in output
    assert "回滾條件：使用者回饋或 proof records 顯示路由、復原、交付或隱私變差" in output
    assert (
        "下一步：先通過 聚焦測試 + runtime/replay/LLM smoke 證明下一輪有改善，"
        "再考慮套用 durable 變更。"
        in output
    )
    assert "Promote only after" not in output
    assert "Rollback if user feedback" not in output
    assert "Review the affected Raphael capability" not in output


def test_render_status_includes_current_mission_state():
    output = render_status(
        _state(),
        now=NOW,
        mission_state={
            "mission_id": "mission-abc123",
            "goal": "修復 runtime bug",
            "phase": "strategy_selected",
            "next_action": "plan_execute_verify",
            "proof_status": "pending",
        },
    )

    assert "Current Mission:" in output
    assert "mission-abc123" not in output
    assert "任務：修復 runtime bug" in output
    assert "已選定策略" in output
    assert "先規劃，再執行，最後用證據驗證" in output
    assert "待補證據" in output


def test_render_status_translates_current_mission_internal_ids_for_users():
    output = render_status(
        _state(),
        now=NOW,
        mission_state={
            "mission_id": "mission-abc123",
            "goal": "修復 runtime bug",
            "phase": "strategy_selected",
            "next_action": "plan_execute_verify",
            "proof_status": "pending",
            "required_proofs": [
                "focused_tests",
                "runtime_smoke_when_live_wiring",
            ],
        },
    )

    assert "狀態：已選定策略" in output
    assert "下一步：先規劃，再執行，最後用證據驗證" in output
    assert "證據狀態：待補證據" in output
    assert "必要證據：聚焦測試通過、live runtime smoke 通過" in output
    assert "mission-abc123" not in output
    assert "phase:" not in output
    assert "next_action:" not in output
    assert "proof_status:" not in output
    assert "required_proofs:" not in output
    assert "strategy_selected" not in output
    assert "plan_execute_verify" not in output
    assert "focused_tests" not in output
    assert "runtime_smoke_when_live_wiring" not in output


def test_render_status_humanizes_empty_required_proofs_for_users():
    output = render_status(
        _state(),
        now=NOW,
        mission_state={
            "goal": "整理拉斐爾 release evidence",
            "phase": "strategy_selected",
            "next_action": "plan_execute_verify",
            "proof_status": "pending",
            "required_proofs": [],
        },
    )

    assert "必要證據：未記錄" in output
    assert "必要證據：none" not in output


def test_render_status_hides_internal_evolution_review_prompt_from_current_mission():
    output = render_status(
        _state(),
        now=NOW,
        mission_state={
            "mission_id": "mission-internal-review",
            "goal": (
                "Raphael Sage King Evolution Review\n\n"
                "You are Raphael's proactive skill-evolution loop, not a passive "
                "advisor. Use memory and skill_manage only when the evidence is "
                "strong and auditable."
            ),
            "phase": "strategy_selected",
            "next_action": "plan_execute_verify",
            "proof_status": "pending",
            "required_proofs": ["focused_tests"],
        },
    )

    assert "Current Mission:" in output
    assert "任務：背景演化審核：整理可審計的技能/記憶改進" in output
    assert "Raphael Sage King Evolution Review" not in output
    assert "proactive skill-evolution loop" not in output
    assert "passive advisor" not in output
    assert "skill_manage" not in output
    assert "mission-internal-review" not in output


def test_render_status_humanizes_remaining_legacy_status_surface_text():
    card = StatusCard(
        card_id="card-legacy-runtime",
        severity="warning",
        title="Raphael control decision",
        summary=(
            "模式：工具任務；目標：runtime or repo state；階段：規劃、執行、驗證；"
            "下一步：先補齊必要證據，再宣稱完成；失敗層：proof gate"
        ),
        observed_at=NOW - timedelta(minutes=15),
        expires_at=NOW + timedelta(hours=1),
        source="general_tool_proof_gate",
        confidence=0.72,
        evidence_refs=("turn:legacy",),
    )

    output = render_status(
        _state(cards=(card,)),
        now=NOW,
        evolution_records=[
            {
                "status": "background_completed_no_action",
                "mode": "background_review",
                "reason_codes": [],
                "evidence_summary": "Raphael background review outcome.",
            }
        ],
    )

    assert "目標：runtime / repo 狀態" in output
    assert "背景審核完成，無需變更 [背景審核]" in output
    assert "背景審核結果" in output
    assert "理由：未記錄" in output
    assert "上線門檻：聚焦測試 + runtime 或 LLM smoke 證據" in output
    assert "runtime or repo state" not in output
    assert "background completed no action" not in output
    assert "[background review]" not in output
    assert "focused tests plus runtime or LLM smoke evidence" not in output
    assert "Raphael background review outcome." not in output
    assert "理由：none" not in output

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from typing import Any

from agent.raphael.evolution import summarize_learning_outcome
from agent.raphael.invocation import (
    format_raphael_proof_text,
    format_raphael_route_text,
)
from agent.raphael.labels import (
    format_status_card_source,
    format_status_card_summary,
)
from agent.raphael.models import RaphaelState, StatusCard, action_proposal_ref
from agent.raphael.redaction import REDACTED_VALUE, redact_trace_payload

_SECRET_VALUE_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{3,}|xox[baprs]-[A-Za-z0-9_\-]{3,}|"
    r"gh[pousr]_[A-Za-z0-9_\-]{3,}|ya29\.[A-Za-z0-9_\-]{3,}|"
    r"AIza[A-Za-z0-9_\-]{3,})\b"
)
_PRIVATE_PATH_RE = re.compile(
    r"(?:(?:/Users|/private/tmp|/private/var|/tmp)/[^\s,;:'\")\]}]+)"
)
_DATA_URI_RE = re.compile(r"data:[a-z0-9.+/-]+;base64,[a-z0-9+/=_-]+", re.I)
_LONG_BASE64ISH_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{80,}\b")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def active_cards(
    state: RaphaelState, *, now: datetime | None = None
) -> list[StatusCard]:
    cutoff = _ensure_utc(now) if now is not None else _utc_now()
    return [card for card in state.status_cards if card.expires_at > cutoff]


def render_status(
    state: RaphaelState,
    *,
    now: datetime | None = None,
    max_cards: int = 20,
    evolution_records: Sequence[Mapping[str, Any]] | None = None,
    mission_state: Mapping[str, Any] | None = None,
    curator_health: Mapping[str, Any] | None = None,
) -> str:
    cards = active_cards(state, now=now)
    card_groups = _collapse_status_cards(cards)[: max(0, max_cards)]
    pending_proposals = [
        proposal
        for proposal in state.action_proposals
        if proposal.status == "pending"
    ]
    approved_proposals = [
        proposal
        for proposal in state.action_proposals
        if proposal.status == "approved"
    ]
    records = [
        record for record in evolution_records or [] if isinstance(record, Mapping)
    ]

    lines = [
        "Raphael Sage King",
        "Mode: proactive evolution control layer.",
        "",
        "賢者總覽:",
        *_format_sage_king_brief(
            card_groups,
            pending_proposals,
            mission_state,
            records,
        ),
        "",
        "Status Cards:",
    ]

    if card_groups:
        for card, count, confidence, summary, source in card_groups:
            lines.extend(
                [
                    f"- [{card.severity}] {card.title}",
                    f"  Summary: {summary}",
                    f"  Source: {source}",
                    f"  Confidence: {confidence:.2f}",
                ]
            )
            if count > 1:
                lines.append(f"  同類事件：{count} 次")
    else:
        lines.append("No active status cards.")

    lines.extend(["", "Pending Action Proposals:"])
    if pending_proposals:
        for proposal in pending_proposals:
            risk = proposal.risk.value
            approval = (
                "requires approval"
                if proposal.requires_approval
                else "auto-allow"
            )
            lines.append(f"- [{risk}] {proposal.summary} ({approval})")
            lines.extend(_format_action_proposal_rollout_lines(proposal))
    else:
        lines.append("No pending action proposals.")

    lines.extend(["", "Approved Manual Rollouts:"])
    if approved_proposals:
        for proposal in approved_proposals[:5]:
            lines.append(f"- {proposal.summary}")
            lines.extend(format_action_proposal_resolution_guidance(proposal))
    else:
        lines.append("No approved manual rollouts.")

    lines.extend(["", "Current Mission:"])
    if isinstance(mission_state, Mapping):
        required_proofs = mission_state.get("required_proofs") or []
        required_proof_text = _format_required_proofs(required_proofs)
        lines.extend(
            [
                f"- 任務：{_format_mission_goal(mission_state.get('goal'))}",
                f"- 狀態：{_format_mission_phase(mission_state.get('phase'))}",
                (
                    "- 下一步："
                    f"{format_raphael_route_text(str(mission_state.get('next_action') or 'unknown'))}"
                ),
                (
                    "- 證據狀態："
                    f"{_format_proof_status(mission_state.get('proof_status'))}"
                ),
                f"- 必要證據：{required_proof_text}",
            ]
        )
    else:
        lines.append("No active mission.")

    lines.extend(["", "Skill Library Health:"])
    lines.extend(_format_curator_health_lines(curator_health))

    lines.extend(["", "Skill Evolution:"])
    lines.append(
        "Enabled through gated background review when Raphael detects durable "
        "learning evidence."
    )
    lines.append(
        "Records are auditable and scoped; strategy changes should include rollback "
        "conditions."
    )

    lines.extend(["", "Active Self-Correction:"])
    if records:
        focus_record, focus_count = _select_active_self_correction(records)
        lines.extend(_format_active_self_correction(focus_record, count=focus_count))
    else:
        lines.append("No active self-correction signal yet.")

    lines.extend(["", "Recent Evolution:"])
    if records:
        for record, count in _collapse_evolution_records(records)[:5]:
            status = str(record.get("status") or "unknown")
            mode = str(record.get("mode") or "unknown")
            reasons = record.get("reason_codes") or []
            if isinstance(reasons, list):
                reason_text = (
                    "、".join(_format_evolution_reason(reason) for reason in reasons)
                    or "未記錄"
                )
            else:
                reason_text = _format_evolution_reason(reasons)
            evidence = str(record.get("evidence_summary") or "").strip()
            metadata = record.get("metadata")
            metadata_parts: list[str] = []
            if isinstance(metadata, Mapping):
                capability = str(metadata.get("affected_capability") or "").strip()
                if capability:
                    metadata_parts.append(f"能力：{_format_capability_text(capability)}")
                confidence = metadata.get("confidence")
                if isinstance(confidence, int | float):
                    metadata_parts.append(f"信心：{confidence:.2f}")
                promotion = str(metadata.get("promotion_gate") or "").strip()
                if promotion:
                    metadata_parts.append(
                        "上線條件："
                        f"{_format_evolution_metadata_text('promotion_gate', promotion)}"
                    )
                rollback = str(metadata.get("rollback_condition") or "").strip()
                if rollback:
                    metadata_parts.append(
                        "回滾條件："
                        f"{_format_evolution_metadata_text('rollback_condition', rollback)}"
                    )
                learning_outcome = metadata.get("learning_outcome")
                if isinstance(learning_outcome, Mapping):
                    metadata_parts.append(
                        summarize_learning_outcome(learning_outcome)
                    )
            metadata_suffix = (
                "（" + "；".join(metadata_parts) + "）" if metadata_parts else ""
            )
            count_suffix = f"（同類演化：{count} 次）" if count > 1 else ""
            suffix = f" — {_format_evolution_evidence(evidence)}" if evidence else ""
            lines.append(
                f"- {_format_evolution_status(status)} "
                f"[{_format_evolution_mode(mode)}] "
                f"理由：{reason_text}{metadata_suffix}{count_suffix}{suffix}"
            )
    else:
        lines.append("No evolution records yet.")

    lines.extend(
        [
            "",
            "Safety: skill and memory evolution use Hermes gates; cron, tools, "
            "and public delivery require explicit approval.",
        ]
    )
    return "\n".join(lines)


def _format_curator_health_lines(
    curator_health: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(curator_health, Mapping):
        return ["curator: not checked"]
    enabled = curator_health.get("enabled") is True
    consolidate = curator_health.get("consolidate") is True
    agent_created = _format_count(curator_health.get("agent_created_skills"))
    stale = _format_count(curator_health.get("stale"))
    archived = _format_count(curator_health.get("archived"))
    return [
        f"curator: {'enabled' if enabled else 'disabled'}",
        f"agent-created skills: {agent_created}",
        f"stale: {stale}; archived: {archived}",
        f"consolidation: {'on' if consolidate else 'off'}",
        "review: run --dry-run before any archive or consolidation",
    ]


def _format_count(value: Any) -> str:
    if isinstance(value, bool):
        return "0"
    try:
        count = int(value)
    except (TypeError, ValueError):
        return "0"
    return str(max(0, count))


def collect_curator_health() -> dict[str, Any]:
    """Read skill-library health without running curator mutations."""
    try:
        from hermes_constants import get_hermes_home

        if not (get_hermes_home() / "skills").exists():
            return _empty_curator_health()
        from agent import curator
        from tools import skill_usage

        state = curator.load_state()
        rows = skill_usage.agent_created_report()
        paused = bool(state.get("paused", False)) if isinstance(state, Mapping) else False
        by_state = {"active": 0, "stale": 0, "archived": 0}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            state_name = str(row.get("state") or "active")
            by_state[state_name] = by_state.get(state_name, 0) + 1
        return {
            "enabled": bool(curator.is_enabled()),
            "paused": paused,
            "consolidate": bool(curator.get_consolidate()),
            "agent_created_skills": len(rows),
            "active": by_state.get("active", 0),
            "stale": by_state.get("stale", 0),
            "archived": by_state.get("archived", 0),
        }
    except Exception:
        return _empty_curator_health()


def _empty_curator_health() -> dict[str, Any]:
    return {
        "enabled": False,
        "paused": False,
        "consolidate": False,
        "agent_created_skills": 0,
        "active": 0,
        "stale": 0,
        "archived": 0,
    }


def _format_sage_king_brief(
    card_groups: Sequence[tuple[StatusCard, int, float, str, str]],
    pending_proposals: Sequence[Any],
    mission_state: Mapping[str, Any] | None,
    records: Sequence[Mapping[str, Any]],
) -> list[str]:
    if isinstance(mission_state, Mapping):
        mission_goal = _format_mission_goal(mission_state.get("goal"))
        next_action = format_raphael_route_text(
            str(mission_state.get("next_action") or "unknown")
        )
    else:
        mission_goal = "待命，等待任務目標"
        next_action = "等待使用者交付任務或阻塞點"
    return [
        f"- 當前任務：{mission_goal}",
        f"- 主要狀態：{_format_status_group_summary(card_groups)}",
        f"- 待核准行動：{len(pending_proposals)} 件",
        f"- 下一步：{next_action}",
        f"- 演化狀態：{_format_brief_evolution_state(records)}",
    ]


def _format_action_proposal_rollout_lines(proposal: Any) -> list[str]:
    metadata = proposal.metadata if isinstance(proposal.metadata, Mapping) else {}
    rollout_plan = metadata.get("rollout_plan")
    lines: list[str] = []
    for label, key in (
        ("Cluster", "failure_cluster_id"),
        ("Component", "component"),
        ("Owner", "owner"),
        ("Replay", "replay_command"),
        ("Baseline", "baseline_metric"),
        ("Target", "target_metric"),
    ):
        value = _redacted_status_text(metadata.get(key))
        if value:
            lines.append(f"  {label}: {value}")
    if proposal.status == "pending":
        if isinstance(rollout_plan, Mapping):
            lines.append("  Rollout: pending approval")
        proposal_ref = action_proposal_ref(str(proposal.proposal_id))
        lines.append(f"  Approve: hermes raphael proposal approve {proposal_ref}")
        lines.append(f"  Reject: hermes raphael proposal reject {proposal_ref}")
    elif isinstance(rollout_plan, Mapping):
        status = _redacted_status_text(rollout_plan.get("status"))
        if status:
            lines.append(f"  Rollout: {_format_rollout_status(status)}")
    if not isinstance(rollout_plan, Mapping):
        return lines
    commands = rollout_plan.get("verification_commands")
    if isinstance(commands, Sequence) and not isinstance(
        commands,
        (str, bytes, bytearray),
    ):
        command_text = "; ".join(
            _redacted_status_text(command)
            for command in commands
            if str(command).strip()
        )
        if command_text:
            lines.append(f"  Verify: {command_text}")
    promotion_gate = _redacted_status_text(rollout_plan.get("promotion_gate"))
    if promotion_gate:
        lines.append(
            "  Promote: "
            f"{_format_evolution_metadata_text('promotion_gate', promotion_gate)}"
        )
    rollback_condition = _redacted_status_text(
        rollout_plan.get("rollback_condition")
    )
    if rollback_condition:
        lines.append(
            "  Rollback: "
            f"{_format_evolution_metadata_text('rollback_condition', rollback_condition)}"
        )
    return lines


def format_action_proposal_resolution_guidance(proposal: Any) -> list[str]:
    status = str(getattr(proposal, "status", "") or "").strip().lower()
    if status != "approved":
        return []
    lines = ["Next manual rollout:"]
    lines.extend(_format_action_proposal_rollout_lines(proposal))
    lines.append(
        "  Apply: manual only after verification; approval did not mutate durable policy."
    )
    return lines


def _redacted_status_text(value: Any, *, limit: int = 240) -> str:
    redacted = redact_trace_payload(value, max_string_length=limit)
    text = " ".join(str(redacted or "").split())
    text = _SECRET_VALUE_RE.sub(REDACTED_VALUE, text)
    text = _DATA_URI_RE.sub("[redacted-media]", text)
    text = _PRIVATE_PATH_RE.sub("[redacted-path]", text)
    return _LONG_BASE64ISH_RE.sub("[redacted-payload]", text)


def _format_rollout_status(status: str) -> str:
    return {
        "pending_approval": "pending approval",
        "approved": "approved",
        "rejected": "rejected",
        "applied": "applied",
    }.get(status, _format_capability_text(status))


def _format_status_group_summary(
    card_groups: Sequence[tuple[StatusCard, int, float, str, str]],
) -> str:
    if not card_groups:
        return "沒有 active status card"
    counts: dict[str, int] = {}
    for card, *_ in card_groups:
        counts[card.severity] = counts.get(card.severity, 0) + 1
    return "、".join(
        f"{severity} {count} 類" for severity, count in sorted(counts.items())
    )


def _format_brief_evolution_state(records: Sequence[Mapping[str, Any]]) -> str:
    if not records:
        return "等待可審計學習訊號"
    focus_record, _ = _select_active_self_correction(records)
    return _format_evolution_posture(focus_record)


def _collapse_status_cards(
    cards: Sequence[StatusCard],
) -> list[tuple[StatusCard, int, float, str, str]]:
    groups: dict[tuple[str, str, str, str], tuple[StatusCard, int, float, str, str]] = {}
    order: list[tuple[str, str, str, str]] = []
    for card in cards:
        summary = format_status_card_summary(card.summary)
        source = format_status_card_source(card.source)
        key = (card.severity, card.title, summary, source)
        if key not in groups:
            groups[key] = (card, 1, float(card.confidence), summary, source)
            order.append(key)
            continue
        first_card, count, confidence, _, _ = groups[key]
        groups[key] = (
            first_card,
            count + 1,
            max(confidence, float(card.confidence)),
            summary,
            source,
        )
    return [groups[key] for key in order]


def _collapse_evolution_records(
    records: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], int]]:
    groups: dict[tuple[Any, ...], tuple[Mapping[str, Any], int]] = {}
    order: list[tuple[Any, ...]] = []
    for record in records:
        key = _evolution_record_key(record)
        if key not in groups:
            groups[key] = (record, 1)
            order.append(key)
            continue
        first_record, count = groups[key]
        groups[key] = (first_record, count + 1)
    return [groups[key] for key in order]


def _select_active_self_correction(
    records: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], int]:
    grouped = _collapse_evolution_records(records)
    if not grouped:
        return {}, 0
    return max(enumerate(grouped), key=lambda item: (item[1][1], item[0]))[1]


def _evolution_record_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    reasons = record.get("reason_codes") or []
    if isinstance(reasons, Sequence) and not isinstance(
        reasons,
        (str, bytes, bytearray),
    ):
        reason_key = tuple(str(reason) for reason in reasons)
    else:
        reason_key = (str(reasons),)
    return (
        str(record.get("status") or ""),
        str(record.get("mode") or ""),
        reason_key,
        str(record.get("evidence_summary") or ""),
        str(metadata.get("affected_capability") or ""),
        str(metadata.get("confidence") or ""),
        str(metadata.get("promotion_gate") or ""),
        str(metadata.get("rollback_condition") or ""),
    )


def _format_active_self_correction(
    record: Mapping[str, Any],
    *,
    count: int = 1,
) -> list[str]:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    capability = str(metadata.get("affected_capability") or "").strip()
    proposed_change = str(metadata.get("proposed_change") or "").strip()
    promotion_gate = str(metadata.get("promotion_gate") or "").strip()
    rollback_condition = str(metadata.get("rollback_condition") or "").strip()
    evidence = str(record.get("evidence_summary") or "").strip()

    lines = [
        f"- 能力：{_format_capability_text(capability or 'raphael.control_layer')}",
        f"- 狀態：{_format_evolution_posture(record)}",
    ]
    if count > 1:
        lines.append(f"- 同類演化：{count} 次")
    if proposed_change:
        lines.append(
            "- 修正方向："
            f"{_format_evolution_metadata_text('proposed_change', proposed_change)}"
        )
    elif evidence:
        lines.append(f"- 修正方向：根據證據修正：{_format_evolution_evidence(evidence)}")
    else:
        lines.append("- 修正方向：等待更多可審計證據。")

    if promotion_gate:
        lines.append(
            "- 上線門檻："
            f"{_format_evolution_metadata_text('promotion_gate', promotion_gate)}"
        )
    else:
        lines.append("- 上線門檻：聚焦測試 + runtime 或 LLM smoke 證據。")

    if rollback_condition:
        lines.append(
            "- 回滾條件："
            f"{_format_evolution_metadata_text('rollback_condition', rollback_condition)}"
        )
    else:
        lines.append("- 回滾條件：下一輪證據或使用者回饋顯示行為變差。")

    lines.append(f"- 下一步：{_format_evolution_next_action(record, metadata)}")
    return lines


def _format_evolution_posture(record: Mapping[str, Any]) -> str:
    mode = str(record.get("mode") or "")
    if record.get("proposal_only") is True or mode == "proposal_only":
        return "只提出建議，尚未寫入 durable policy"
    if mode == "audit_only":
        return "審計模式，僅保存可回滾證據"
    if record.get("should_review") is True or mode == "active_evolution":
        return "主動進化審核中，需通過證據門檻"
    if mode == "background_review":
        return "背景審核完成，保留審計紀錄"
    return _format_evolution_mode(mode or "unknown")


def _format_evolution_next_action(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> str:
    promotion_gate = str(metadata.get("promotion_gate") or "").strip()
    if promotion_gate:
        gate = _format_evolution_metadata_text("promotion_gate", promotion_gate)
        return f"先通過 {gate}，再考慮套用 durable 變更。"
    if record.get("proposal_only") is True:
        return "保持 proposal-only，等明確授權與證據門檻都成立後再升級。"
    if str(record.get("status") or "") == "blocked":
        return "先補齊阻塞證據，再重新排程進化審核。"
    return "用下一輪證據驗證是否真的改善，再決定是否保留。"


def _format_required_proofs(required_proofs: Any) -> str:
    if isinstance(required_proofs, Sequence) and not isinstance(
        required_proofs,
        (str, bytes, bytearray),
    ):
        proof_items = tuple(str(item) for item in required_proofs if str(item).strip())
        return format_raphael_proof_text(proof_items) if proof_items else "未記錄"
    text = str(required_proofs or "").strip()
    return format_raphael_proof_text((text,)) if text else "未記錄"


def _format_mission_goal(goal: Any) -> str:
    text = " ".join(str(goal or "").split())
    lowered = text.lower()
    if (
        "raphael sage king evolution review" in lowered
        or "raphael evolution review" in lowered
        or "proactive skill-evolution loop" in lowered
        or "skill_manage" in lowered
    ):
        return "背景演化審核：整理可審計的技能/記憶改進"
    return text or "unknown"


def _format_mission_phase(phase: Any) -> str:
    return {
        "strategy_selected": "已選定策略",
        "blocked": "等待釐清",
        "awaiting_mission_target": "等待任務目標",
    }.get(str(phase or ""), str(phase or "unknown"))


def _format_proof_status(status: Any) -> str:
    return {
        "pending": "待補證據",
        "blocked": "證據阻塞",
        "passed": "證據通過",
        "complete": "證據通過",
    }.get(str(status or ""), str(status or "unknown"))


def _format_evolution_status(status: Any) -> str:
    return {
        "scheduled": "已排程",
        "applied": "已套用",
        "blocked": "等待證據",
        "rejected": "已拒絕",
        "background_completed_no_action": "背景審核完成，無需變更",
        "background completed no action": "背景審核完成，無需變更",
    }.get(str(status or ""), _format_capability_text(status))


def _format_evolution_mode(mode: Any) -> str:
    return {
        "active_evolution": "主動進化",
        "audit_only": "審計模式",
        "proposal_only": "只提出建議",
        "background_review": "背景審核",
        "background review": "背景審核",
    }.get(str(mode or ""), _format_capability_text(mode))


def _format_evolution_reason(reason: Any) -> str:
    return {
        "user_correction": "使用者修正",
        "failed_proof": "proof gate 擋下未驗證宣稱",
        "proof_gap": "證據缺口",
        "quality_failure": "品質未達標",
        "provider_failure": "provider 失敗",
    }.get(str(reason or ""), _format_capability_text(reason))


def _format_evolution_evidence(evidence: Any) -> str:
    text = " ".join(str(evidence or "").split())
    return {
        "Raphael background review outcome.": "背景審核結果",
        "Raphael proof gate blocked an unverified completion claim": (
            "proof gate 擋下未驗證完成宣稱"
        ),
    }.get(text, text)


def _format_evolution_metadata_text(kind: str, value: Any) -> str:
    text = " ".join(str(value or "").split())
    if kind == "proposed_change" and text == (
        "Review the affected Raphael capability and update the smallest skill, "
        "policy, or control path supported by current evidence."
    ):
        return "檢查受影響的 Raphael 能力，最小幅更新 skill/policy/control path。"
    if kind == "promotion_gate" and text == (
        "Promote only after focused tests and a runtime, replay, or LLM smoke "
        "prove the next run improves."
    ):
        return "聚焦測試 + runtime/replay/LLM smoke 證明下一輪有改善"
    if kind == "rollback_condition" and text == (
        "Rollback if user feedback or proof records show worse routing, recovery, "
        "delivery, or privacy behavior."
    ):
        return "使用者回饋或 proof records 顯示路由、復原、交付或隱私變差"
    return text


def _format_capability_text(value: Any) -> str:
    text = str(value or "unknown").replace(".", " ").replace("_", " ").strip()
    if not text:
        return "unknown"
    if text.startswith("raphael "):
        return "Raphael " + text.removeprefix("raphael ")
    if text.startswith("visual "):
        return "visual " + text.removeprefix("visual ")
    return text


__all__ = ["active_cards", "collect_curator_health", "render_status"]

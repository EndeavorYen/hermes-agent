from __future__ import annotations

import json
import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent.redact import redact_sensitive_text
from agent.raphael.config import cfg_get, raphael_effective_enabled
from agent.raphael.learning import normalize_learning_outcome_contract
from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel
from agent.raphael.redaction import REDACTED_VALUE, redact_trace_payload
from agent.raphael.state import (
    get_raphael_state_dir,
    raphael_state_lock,
    read_state,
    write_state,
)

EVOLUTION_RECORD_SCHEMA_VERSION = "raphael.evolution_record.v1"
REVIEW_LABEL = "Raphael evolution review"
EVOLUTION_METADATA_TEXT_LIMIT = 240

_ALLOWED_EVOLUTION_METADATA_KEYS = frozenset(
    {
        "affected_capability",
        "proposed_change",
        "confidence",
        "error",
        "learning_outcome",
        "promotion_gate",
        "rollback_condition",
    }
)

_TEXT_EVOLUTION_METADATA_KEYS = (
    "affected_capability",
    "proposed_change",
    "promotion_gate",
    "rollback_condition",
    "origin",
    "failure_cluster_id",
    "component",
    "owner",
    "occurrence_id",
    "signal_kind",
    "replay_command",
    "baseline_metric",
    "target_metric",
    "approval_class",
    "failure_class",
)

_CAPABILITY_BY_REASON_CODE = {
    "user_correction": "raphael.skill_evolution",
    "visual_or_provider_failure": "visual.agent_mode",
    "execution_loop_failure": "raphael.execution_loop",
    "high_risk_mutation": "raphael.approval_policy",
    "failed_proof": "raphael.proof_gate",
}

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

_USER_CORRECTION_MARKERS = (
    "不對",
    "不是這樣",
    "錯了",
    "不要再",
    "別再",
    "你應該",
    "請記住",
    "記住",
    "remember",
    "主動進化",
)

_HIGH_RISK_MARKERS = (
    "不用問",
    "不要問",
    "自動發布",
    "自動修改 cron",
    "修改 cron",
    "install tool",
    "安裝工具",
    "public delivery",
    "發布到 slack",
    "send public",
)

_VISUAL_FAILURE_MARKERS = (
    "failure_layer",
    "provider_health",
    "browser_automation",
    "artifact_quality",
    "prompt_moderation",
    "delivery",
    "候選圖未通過",
    "stale",
    "duplicate",
    "visual_agent_generate",
    "grok web imagine",
)

_PROOF_GATE_FAILURE_TERMS = (
    "blocked",
    "cannot verify",
    "can't verify",
    "insufficient",
    "missing",
    "not enough",
    "proof failed",
    "還不能判定完成",
    "不能判定完成",
    "缺少",
    "沒有足夠",
    "證據不足",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enabled(config: Mapping[str, Any] | None) -> bool:
    if not raphael_effective_enabled(config, require_default_conversation=False):
        return False
    evolution_cfg = cfg_get(config or {}, "raphael", "evolution", default={})
    if isinstance(evolution_cfg, Mapping):
        return evolution_cfg.get("enabled", True) is True
    return True


def _flag(config: Mapping[str, Any] | None, *path: str, default: bool) -> bool:
    return cfg_get(config or {}, *path, default=default) is True


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            elif isinstance(item, str):
                chunks.append(item)
        return "\n".join(chunks)
    return "" if value is None else str(value)


def _redact_value(value: Any) -> Any:
    redacted = redact_trace_payload(value)
    if isinstance(redacted, str):
        redacted = _SECRET_VALUE_RE.sub(REDACTED_VALUE, redacted)
        redacted = _DATA_URI_RE.sub("[redacted-media]", redacted)
        redacted = _PRIVATE_PATH_RE.sub("[redacted-path]", redacted)
        return _LONG_BASE64ISH_RE.sub("[redacted-payload]", redacted)
    if isinstance(redacted, Mapping):
        return {str(k): _redact_value(v) for k, v in redacted.items()}
    if isinstance(redacted, Sequence) and not isinstance(
        redacted, (str, bytes, bytearray)
    ):
        return [_redact_value(item) for item in redacted]
    return redacted


def _redacted_single_line(value: Any, *, limit: int = EVOLUTION_METADATA_TEXT_LIMIT) -> str:
    redacted = _redact_value(value)
    if isinstance(redacted, Mapping):
        text = json.dumps(redacted, sort_keys=True, ensure_ascii=False)
    elif isinstance(redacted, Sequence) and not isinstance(
        redacted, (str, bytes, bytearray)
    ):
        text = json.dumps(list(redacted), sort_keys=True, ensure_ascii=False)
    else:
        text = "" if redacted is None else str(redacted)
    text = " ".join(text.split())
    return text[:limit]


def sanitize_persistent_error(
    error: Any,
    *,
    limit: int = EVOLUTION_METADATA_TEXT_LIMIT,
) -> str:
    """Return a force-redacted bounded error suitable for durable audit files."""
    error_class = error.__class__.__name__ if isinstance(error, BaseException) else "Error"
    try:
        raw = f"{error_class}: {error}" if isinstance(error, BaseException) else str(error)
        forced = redact_sensitive_text(raw, force=True)
    except Exception:
        forced = f"{error_class}: [redaction-failed]"
    return _redacted_single_line(forced, limit=max(0, int(limit)))


def _clamped_confidence(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence):
        return None
    return round(max(0.0, min(1.0, confidence)), 2)


def sanitize_raphael_evolution_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key in _TEXT_EVOLUTION_METADATA_KEYS:
        if not isinstance(metadata, Mapping) or key not in metadata:
            continue
        text = _redacted_single_line(metadata.get(key))
        if text:
            sanitized[key] = text
    if isinstance(metadata, Mapping) and "confidence" in metadata:
        confidence = _clamped_confidence(metadata.get("confidence"))
        if confidence is not None:
            sanitized["confidence"] = confidence
    if isinstance(metadata, Mapping) and metadata.get("error"):
        sanitized["error"] = sanitize_persistent_error(metadata.get("error"))
    if isinstance(metadata, Mapping) and isinstance(
        metadata.get("learning_outcome"),
        Mapping,
    ):
        outcome = _sanitize_learning_outcome(metadata.get("learning_outcome"))
        if outcome:
            sanitized["learning_outcome"] = outcome
    return sanitized


def _sanitize_learning_outcome(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    sanitized: dict[str, Any] = {}
    for key in ("skill_name", "source", "rollback"):
        text = _redacted_single_line(value.get(key))
        if text:
            sanitized[key] = text
    if isinstance(value.get("saved"), bool):
        sanitized["saved"] = value.get("saved")
    return sanitized


def summarize_learning_outcome(record: Mapping[str, Any]) -> str:
    skill_name = _redacted_single_line(record.get("skill_name")) or "unknown-skill"
    source = _redacted_single_line(record.get("source")) or "unspecified source"
    rollback = (
        _redacted_single_line(record.get("rollback"))
        or "remove or archive the saved learning artifact"
    )
    status = "saved" if record.get("saved") is True else "not saved"
    return (
        f"Learning outcome: {status}; skill={skill_name}; "
        f"source={source}; rollback={rollback}"
    )


def sanitize_raphael_evolution_status_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    sanitized: dict[str, Any] = {}
    review_label = _redacted_single_line(metadata.get("review_label"))
    if review_label:
        sanitized["review_label"] = review_label
    actions = metadata.get("actions")
    if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes, bytearray)):
        action_types = sorted(
            {
                _redacted_single_line(action, limit=80)
                for action in actions
                if _redacted_single_line(action, limit=80)
            }
        )
        sanitized["action_count"] = len(actions)
        if action_types:
            sanitized["action_types"] = action_types[:10]
    session_id = str(metadata.get("session_id") or "").strip()
    if session_id:
        sanitized["session_hash"] = hashlib.sha256(
            session_id.encode("utf-8")
        ).hexdigest()[:12]
    error = str(metadata.get("error") or "").strip()
    if error:
        error_class = error.split(":", 1)[0].splitlines()[0].strip()
        if error_class:
            sanitized["error_class"] = _redacted_single_line(error_class, limit=80)
    outcome = _redacted_single_line(metadata.get("outcome"), limit=80)
    if outcome:
        sanitized["outcome"] = outcome
    return sanitized


def sanitize_evolution_text(value: Any) -> str:
    return _redacted_single_line(value, limit=EVOLUTION_METADATA_TEXT_LIMIT)


def build_evolution_signal(
    *,
    source: str,
    affected_capability: str,
    reason_codes: Sequence[str],
    summary: str,
    evidence_refs: Sequence[str],
    confidence: float,
    proposed_change: str,
    promotion_gate: str,
    rollback_condition: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    signal_metadata = {
        "affected_capability": affected_capability,
        "proposed_change": proposed_change,
        "confidence": confidence,
        "promotion_gate": promotion_gate,
        "rollback_condition": rollback_condition,
    }
    if isinstance(metadata, Mapping):
        signal_metadata.update(metadata)
    return {
        "schema_version": EVOLUTION_RECORD_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "status": "review",
        "should_review": True,
        "review_skills": True,
        "review_memory": False,
        "proposal_only": True,
        "mode": "active_evolution",
        "reason_codes": [str(reason) for reason in reason_codes],
        "evidence_summary": (
            f"{affected_capability} recurring evolution signal: "
            f"{','.join(str(reason) for reason in reason_codes)}"
        ),
        "evidence_refs": [str(ref) for ref in evidence_refs],
        "review_label": REVIEW_LABEL,
        "risk_level": RiskLevel.R2.value,
        "user_message_preview": "",
        "source": str(source),
        "metadata": sanitize_raphael_evolution_metadata(signal_metadata),
    }


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _looks_like_user_correction_or_learning_request(text: str) -> bool:
    if _contains_any(text, _USER_CORRECTION_MARKERS):
        return True
    lowered = text.lower()
    durable_targets = ("skill", "技能", "memory", "記憶", "學習", "learning")
    durable_verbs = ("evolve", "進化", "update", "改進", "修正", "保存", "save")
    return _contains_any(lowered, durable_targets) and _contains_any(
        lowered,
        durable_verbs,
    )


def _message_texts(messages: Sequence[Mapping[str, Any]] | None) -> list[str]:
    texts: list[str] = []
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        content = _text(message.get("content"))
        name = _text(message.get("name"))
        role = _text(message.get("role"))
        texts.append("\n".join(part for part in (role, name, content) if part))
    return texts


def _looks_like_failed_proof_gate(
    response_text: str,
    messages: Sequence[Mapping[str, Any]] | None,
) -> bool:
    texts = [response_text]
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        if _text(message.get("role")).lower() != "assistant":
            continue
        texts.append(_text(message.get("content")))
    for text in texts:
        lowered = text.lower()
        if "proof gate" not in lowered:
            continue
        if any(term.lower() in lowered for term in _PROOF_GATE_FAILURE_TERMS):
            return True
    return False


def _visual_failure_marker_layers(raw: str) -> list[str]:
    lowered = raw.lower()
    return [
        marker
        for marker in _VISUAL_FAILURE_MARKERS
        if marker.lower() in lowered
    ]


def _is_tool_failure_evidence(message: Mapping[str, Any]) -> bool:
    role = _text(message.get("role")).lower()
    name = _text(message.get("name")).lower()
    return (
        role == "tool"
        or bool(message.get("tool_call_id"))
        or name in {"visual_agent_generate", "image_generate", "video_generate"}
    )


def _is_story_video_validation_block(raw: str) -> bool:
    return "STORY_VIDEO_GATE: BLOCKED" in raw or "STORY_VIDEO_RENDER_CONTRACT: BLOCKED" in raw


def _has_story_video_validation_block(
    messages: Sequence[Mapping[str, Any]] | None,
) -> bool:
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        content = _text(message.get("content"))
        name = _text(message.get("name"))
        role = _text(message.get("role"))
        raw = "\n".join(part for part in (role, name, content) if part)
        if _is_story_video_validation_block(raw):
            return True
    return False


def _extract_failure_layers(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    include_narrative: bool = False,
) -> tuple[str, ...]:
    layers: list[str] = []
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        if not include_narrative and not _is_tool_failure_evidence(message):
            continue
        content = _text(message.get("content"))
        name = _text(message.get("name"))
        role = _text(message.get("role"))
        raw = "\n".join(part for part in (role, name, content) if part)
        if _is_story_video_validation_block(raw):
            continue
        try:
            parsed = json.loads(raw.split("\n", 2)[-1])
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, Mapping):
            layer = parsed.get("failure_layer") or parsed.get("failure_class")
            if layer:
                layers.append(str(layer))
            if parsed.get("success") is False and not layer:
                layers.append("tool_failure")
        if _contains_any(raw, _VISUAL_FAILURE_MARKERS):
            for marker in _visual_failure_marker_layers(raw):
                if marker not in layers:
                    layers.append(marker)
    return tuple(dict.fromkeys(layers))


def _infer_affected_capability(reason_codes: Sequence[str]) -> str:
    for reason in reason_codes:
        capability = _CAPABILITY_BY_REASON_CODE.get(str(reason))
        if capability:
            return capability
    return "raphael.control_layer"


def _infer_evolution_metadata(
    reason_codes: Sequence[str],
    *,
    proposal_only: bool,
) -> dict[str, Any]:
    if not reason_codes:
        return {}
    if proposal_only and "high_risk_mutation" in reason_codes:
        return {
            "affected_capability": _infer_affected_capability(reason_codes),
            "proposed_change": (
                "Draft an operator-approved change instead of mutating durable "
                "runtime, tool, cron, or delivery policy automatically."
            ),
            "confidence": 0.45,
            "promotion_gate": "Requires explicit human approval plus focused tests.",
            "rollback_condition": (
                "Discard if approval is absent or later evidence shows unsafe "
                "automation pressure."
            ),
        }
    return {
        "affected_capability": _infer_affected_capability(reason_codes),
        "proposed_change": (
            "Review the affected Raphael capability and update the smallest "
            "skill, policy, or control path supported by current evidence."
        ),
        "confidence": 0.66,
        "promotion_gate": (
            "Promote only after focused tests and a runtime, replay, or LLM smoke "
            "prove the next run improves."
        ),
        "rollback_condition": (
            "Rollback if user feedback or proof records show worse routing, "
            "recovery, delivery, or privacy behavior."
        ),
    }


def _infer_learning_outcome_contract(
    reason_codes: Sequence[str],
    failure_layers: Sequence[str],
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    supplied = metadata if isinstance(metadata, Mapping) else {}
    origin = _redacted_single_line(supplied.get("origin"), limit=32)
    occurrence_id = _redacted_single_line(supplied.get("occurrence_id"), limit=96)
    if origin != "foreground" or not occurrence_id:
        return {}
    capability = _infer_affected_capability(reason_codes)
    failure_class = _redacted_single_line(
        supplied.get("failure_class")
        or (failure_layers[0] if failure_layers else "")
        or (
            "proof_gate"
            if "failed_proof" in reason_codes
            else "execution_loop"
            if "execution_loop_failure" in reason_codes
            else "user_correction"
        ),
        limit=80,
    )
    if failure_class in {"provider_health", "browser_automation", "prompt_moderation"}:
        component = "visual.provider_health"
        owner = "visual-provider-runtime"
        replay_command = "hermes raphael readiness --readiness-profile media --check"
    elif failure_class in {"artifact_quality", "quality_failure"}:
        component = "visual.artifact_quality"
        owner = "visual-agent"
        replay_command = "pytest tests/visual/test_agent_mode_handoff.py -q"
    elif failure_class in {"delivery", "duplicate_delivery", "stale_artifact"}:
        component = "visual.delivery"
        owner = "visual-delivery"
        replay_command = "pytest tests/visual/test_agent_mode_handoff.py -q"
    else:
        component = capability
        owner = "raphael-control"
        replay_command = "pytest tests/agent/test_raphael_finalization.py -q"
    signal_kind = (
        "user_correction"
        if "user_correction" in reason_codes
        else "reproduced_failure"
    )
    inferred = {
        "origin": origin,
        "failure_cluster_id": f"{component}:{failure_class}",
        "component": component,
        "owner": owner,
        "occurrence_id": occurrence_id,
        "signal_kind": signal_kind,
        "replay_command": replay_command,
        "baseline_metric": f"{failure_class}_failure_count=1",
        "target_metric": f"{failure_class}_failure_count=0",
        "approval_class": "R2",
        "failure_class": failure_class,
    }
    return {
        **inferred,
        **{
            key: value
            for key, value in sanitize_raphael_evolution_metadata(supplied).items()
            if key in inferred
        },
    }


def _evolution_record_group_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
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
        str(metadata.get("proposed_change") or ""),
        str(metadata.get("promotion_gate") or ""),
        str(metadata.get("rollback_condition") or ""),
    )


def _collapse_evolution_record_patterns(
    records: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], int]]:
    groups: dict[tuple[Any, ...], tuple[Mapping[str, Any], int]] = {}
    order: list[tuple[Any, ...]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        key = _evolution_record_group_key(record)
        if key not in groups:
            groups[key] = (record, 1)
            order.append(key)
            continue
        first_record, count = groups[key]
        groups[key] = (first_record, count + 1)
    return [groups[key] for key in order]


def _selected_evolution_pattern(
    records: Sequence[Mapping[str, Any]],
    *,
    min_count: int,
) -> tuple[Mapping[str, Any], int, Mapping[str, str]] | None:
    reviewable_records = [
        record
        for record in records
        if isinstance(record, Mapping)
        and (
            record.get("should_review") is True
            or str(record.get("mode") or "") == "active_evolution"
        )
    ]
    grouped: dict[tuple[str, str, str], list[tuple[Mapping[str, Any], dict[str, str]]]] = {}
    for record in reviewable_records:
        contract = normalize_learning_outcome_contract(record.get("metadata"))
        if contract is None:
            continue
        key = (
            contract["failure_cluster_id"],
            contract["component"],
            contract.get("failure_class", ""),
        )
        grouped.setdefault(key, []).append((record, contract))
    eligible: list[
        tuple[Mapping[str, Any], int, Mapping[str, str], int]
    ] = []
    for index, entries in enumerate(grouped.values()):
        occurrence_ids = {
            contract["occurrence_id"] for _record, contract in entries
        }
        signal_kinds = {
            contract.get("signal_kind", "") for _record, contract in entries
        }
        correction_plus_repro = {
            "user_correction",
            "reproduced_failure",
        } <= signal_kinds
        if len(occurrence_ids) < min_count and not correction_plus_repro:
            continue
        record, contract = entries[-1]
        eligible.append((record, len(occurrence_ids), contract, index))
    if not eligible:
        return None
    record, count, contract, _index = max(
        eligible,
        key=lambda item: (item[1], item[3]),
    )
    return record, count, contract


def _format_capability_for_summary(capability: str) -> str:
    text = str(capability or "raphael.control_layer").replace(".", " ").replace("_", " ")
    text = " ".join(text.split())
    if text.startswith("raphael "):
        return "Raphael " + text.removeprefix("raphael ")
    return text or "Raphael control layer"


def _evolution_proposal_verification_commands(capability: str) -> list[str]:
    commands = ["pytest tests/agent/test_raphael_evolution.py -q"]
    if str(capability).startswith("raphael."):
        commands.append("hermes raphael readiness --readiness-profile llm --check")
    return commands


def build_evolution_action_proposal(
    records: Sequence[Mapping[str, Any]],
    *,
    min_pattern_count: int = 2,
    created_at: datetime | None = None,
    now: datetime | None = None,
) -> ActionProposal | None:
    selected = _selected_evolution_pattern(records, min_count=max(2, min_pattern_count))
    if selected is None:
        return None
    record, count, outcome_contract = selected
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    capability = _redacted_single_line(
        metadata.get("affected_capability") or "raphael.control_layer",
        limit=96,
    )
    proposed_change = _redacted_single_line(
        metadata.get("proposed_change") or record.get("evidence_summary"),
        limit=160,
    )
    promotion_gate = _redacted_single_line(
        metadata.get("promotion_gate")
        or "focused tests plus runtime, replay, or LLM smoke",
        limit=160,
    )
    rollback_condition = _redacted_single_line(
        metadata.get("rollback_condition")
        or "next evidence or user feedback shows worse behavior",
        limit=160,
    )
    proposal_seed = "|".join(
        (capability, proposed_change, promotion_gate, rollback_condition)
    )
    proposal_hash = hashlib.sha256(proposal_seed.encode("utf-8")).hexdigest()[:16]
    summary = (
        f"Patch {_format_capability_for_summary(capability)} from {count} recurring "
        f"signals: {proposed_change}. Promote after {promotion_gate}; rollback if "
        f"{rollback_condition}."
    )
    replay_command = outcome_contract["replay_command"]
    verification_commands = _evolution_proposal_verification_commands(capability)
    if replay_command not in verification_commands:
        verification_commands.insert(0, replay_command)
    rollout_plan = {
        "status": "pending_approval",
        "risk": RiskLevel.R2.value,
        "manual_steps": [
            f"Review the scoped local proposal for {capability}.",
            "Apply the proposed skill or strategy change only after approval.",
            "Run the promotion gate before enabling the change.",
        ],
        "verification_commands": verification_commands,
        "promotion_gate": promotion_gate,
        "rollback_condition": rollback_condition,
    }
    return ActionProposal(
        proposal_id=f"evolution-{proposal_hash}",
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary=summary,
        evidence_refs=(
            f"evolution:{capability}",
            f"pattern_count:{count}",
            f"cluster:{outcome_contract['failure_cluster_id']}",
        ),
        created_at=created_at or now or datetime.now(timezone.utc),
        metadata={
            "affected_capability": capability,
            "recurring_signal_count": count,
            "proposed_change": proposed_change,
            **dict(outcome_contract),
            "rollout_plan": rollout_plan,
        },
    )


def record_evolution_action_proposal(
    records: Sequence[Mapping[str, Any]],
    *,
    min_pattern_count: int = 2,
) -> ActionProposal | None:
    proposal = build_evolution_action_proposal(
        records,
        min_pattern_count=min_pattern_count,
    )
    if proposal is None:
        return None
    with raphael_state_lock():
        state = read_state()
        if any(item.proposal_id == proposal.proposal_id for item in state.action_proposals):
            return proposal
        write_state(
            RaphaelState(
                status_cards=state.status_cards,
                action_proposals=(proposal, *state.action_proposals),
                updated_at=datetime.now(timezone.utc),
                active_mission=state.active_mission,
                last_decision=state.last_decision,
            )
        )
    return proposal


@dataclass(frozen=True)
class RaphaelEvolutionDecision:
    should_review: bool
    review_skills: bool
    review_memory: bool
    proposal_only: bool
    mode: str
    reason_codes: tuple[str, ...]
    evidence_summary: str
    review_label: str = REVIEW_LABEL
    risk_level: str = "R1"
    user_message_preview: str = ""
    metadata: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_review": self.should_review,
            "review_skills": self.review_skills,
            "review_memory": self.review_memory,
            "proposal_only": self.proposal_only,
            "mode": self.mode,
            "reason_codes": list(self.reason_codes),
            "evidence_summary": self.evidence_summary,
            "review_label": self.review_label,
            "risk_level": self.risk_level,
            "user_message_preview": self.user_message_preview,
            "metadata": sanitize_raphael_evolution_metadata(self.metadata),
        }


def decide_raphael_evolution(
    *,
    user_message: Any,
    final_response: str | None,
    messages: Sequence[Mapping[str, Any]] | None,
    turn_exit_reason: str | None,
    config: Mapping[str, Any] | None,
    metadata: Mapping[str, Any] | None = None,
) -> RaphaelEvolutionDecision:
    user_text = _text(user_message)
    response_text = final_response or ""

    if not _enabled(config):
        return RaphaelEvolutionDecision(
            should_review=False,
            review_skills=False,
            review_memory=False,
            proposal_only=False,
            mode="disabled",
            reason_codes=(),
            evidence_summary="Raphael evolution is disabled.",
            risk_level="R0",
            user_message_preview=_redacted_single_line(user_text, limit=240),
            metadata=metadata,
        )

    reason_codes: list[str] = []
    evidence: list[str] = []

    high_risk = _contains_any(user_text, _HIGH_RISK_MARKERS)
    if high_risk:
        reason_codes.append("high_risk_mutation")
        evidence.append("high-risk mutation request detected")

    if _looks_like_user_correction_or_learning_request(user_text):
        reason_codes.append("user_correction")
        evidence.append("user corrected Raphael behavior or requested durable learning")

    direct_visual_turn = (
        turn_exit_reason is not None
        and str(turn_exit_reason).startswith("direct_visual_agent")
    )
    if _has_story_video_validation_block(messages) and not direct_visual_turn:
        failure_layers = ()
    else:
        failure_layers = _extract_failure_layers(messages)
    if direct_visual_turn:
        failure_layers = tuple(
            dict.fromkeys(
                [
                    *failure_layers,
                    *_extract_failure_layers(
                        [{"role": "assistant", "content": response_text}],
                        include_narrative=True,
                    ),
                ]
            )
        )
    if failure_layers:
        reason_codes.append("visual_or_provider_failure")
        evidence.append("failure layers: " + ", ".join(failure_layers[:6]))

    if _looks_like_failed_proof_gate(response_text, messages):
        reason_codes.append("failed_proof")
        evidence.append("Raphael proof gate blocked an unverified completion claim")

    if turn_exit_reason and "max_iterations" in str(turn_exit_reason):
        reason_codes.append("execution_loop_failure")
        evidence.append(f"turn_exit_reason={turn_exit_reason}")

    reason_codes = list(dict.fromkeys(reason_codes))
    if high_risk:
        return RaphaelEvolutionDecision(
            should_review=False,
            review_skills=False,
            review_memory=False,
            proposal_only=True,
            mode="proposal_only",
            reason_codes=tuple(reason_codes),
            evidence_summary="; ".join(evidence) or "high-risk mutation request",
            risk_level="R2",
            user_message_preview=_redacted_single_line(user_text, limit=240),
            metadata={
                **_infer_evolution_metadata(reason_codes, proposal_only=True),
                **sanitize_raphael_evolution_metadata(metadata),
            },
        )

    if not reason_codes:
        return RaphaelEvolutionDecision(
            should_review=False,
            review_skills=False,
            review_memory=False,
            proposal_only=False,
            mode="observe",
            reason_codes=(),
            evidence_summary="No durable Raphael learning signal detected.",
            risk_level="R0",
            user_message_preview=_redacted_single_line(user_text, limit=240),
            metadata=metadata,
        )

    skill_review_enabled = _flag(
        config,
        "raphael",
        "evolution",
        "skill_review_enabled",
        default=True,
    )
    memory_review_enabled = _flag(
        config,
        "raphael",
        "evolution",
        "memory_review_enabled",
        default=True,
    )
    skill_writes_enabled = _flag(
        config,
        "raphael",
        "skill_writes_enabled",
        default=False,
    )
    memory_writes_enabled = _flag(
        config,
        "raphael",
        "memory_writes_enabled",
        default=False,
    )
    review_skills = skill_review_enabled and skill_writes_enabled
    review_memory = (
        memory_review_enabled
        and memory_writes_enabled
        and "user_correction" in reason_codes
    )
    should_review = review_skills or review_memory

    return RaphaelEvolutionDecision(
        should_review=should_review,
        review_skills=review_skills,
        review_memory=review_memory,
        proposal_only=not should_review,
        mode="active_evolution" if should_review else "proposal_only",
        reason_codes=tuple(reason_codes),
        evidence_summary="; ".join(evidence),
        risk_level="R1" if should_review else "R1.5",
        user_message_preview=_redacted_single_line(user_text, limit=240),
        metadata={
            **_infer_evolution_metadata(reason_codes, proposal_only=not should_review),
            **_infer_learning_outcome_contract(
                reason_codes,
                failure_layers,
                metadata,
            ),
            **sanitize_raphael_evolution_metadata(metadata),
        },
    )


def build_raphael_evolution_review_prompt(
    decision: RaphaelEvolutionDecision,
) -> str:
    reason_codes = ", ".join(decision.reason_codes) or "none"
    return (
        "Raphael Sage King Evolution Review\n\n"
        "You are Raphael's proactive skill-evolution loop, not a passive advisor. "
        "Review the completed conversation above and decide whether Hermes should "
        "evolve an existing class-level skill, add a support file, or save a durable "
        "memory preference. Use memory and skill_manage only when the evidence is "
        "strong and auditable.\n\n"
        f"Evolution reasons: {reason_codes}\n"
        f"Evidence summary: {decision.evidence_summary}\n"
        f"Risk level: {decision.risk_level}\n\n"
        "Rules:\n"
        "- Prefer patching an existing relevant skill over creating a narrow new skill.\n"
        "- Capture workflow corrections, provider failure recovery, proof ladders, "
        "and user-facing communication lessons that should improve the next run.\n"
        "- Keep every durable change auditable, reversible, and scoped; mention the "
        "rollback condition in the skill text or support file when useful.\n"
        "- Do not store raw prompts, private paths, API keys, provider response bodies, "
        "base64, generated media, or user-private artifacts.\n"
        "- Do not mutate cron, public delivery, tool installation, or provider config. "
        "If such a change seems needed, propose it in text instead of calling a tool.\n"
        "- If the evidence is weak or session-specific, say 'Nothing to save.' and stop.\n\n"
        "Act like a Sage King control layer: identify the reusable lesson, update the "
        "right capability, and leave enough evidence for rollback."
    )


def get_raphael_evolution_records_path():
    return get_raphael_state_dir() / "evolution.jsonl"


def append_evolution_record(
    decision: RaphaelEvolutionDecision,
    *,
    status: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    with raphael_state_lock():
        state_dir = get_raphael_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        record_metadata = {
            **sanitize_raphael_evolution_metadata(decision.metadata),
            **sanitize_raphael_evolution_metadata(metadata),
        }
        payload = {
            "schema_version": EVOLUTION_RECORD_SCHEMA_VERSION,
            "created_at": _utc_now(),
            "status": str(status),
            **decision.to_dict(),
            "metadata": record_metadata,
        }
        redacted = _redact_value(payload)
        with get_raphael_evolution_records_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(redacted, sort_keys=True, ensure_ascii=False) + "\n")
        record_evolution_action_proposal(read_evolution_records(limit=50))


def append_evolution_status_record(
    *,
    status: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    with raphael_state_lock():
        state_dir = get_raphael_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        record_metadata = sanitize_raphael_evolution_status_metadata(metadata)
        payload = {
            "schema_version": EVOLUTION_RECORD_SCHEMA_VERSION,
            "created_at": _utc_now(),
            "status": str(status),
            "should_review": False,
            "review_skills": False,
            "review_memory": False,
            "proposal_only": False,
            "mode": "background_review",
            "reason_codes": [],
            "evidence_summary": "Raphael background review outcome.",
            "review_label": REVIEW_LABEL,
            "risk_level": "R0",
            "user_message_preview": "",
            "metadata": record_metadata,
        }
        redacted = _redact_value(payload)
        with get_raphael_evolution_records_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(redacted, sort_keys=True, ensure_ascii=False) + "\n")


def read_evolution_records(limit: int | None = None) -> list[dict[str, Any]]:
    path = get_raphael_evolution_records_path()
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    if limit is None:
        return records
    bounded = max(0, int(limit))
    if bounded == 0:
        return []
    return records[-bounded:]


__all__ = [
    "EVOLUTION_RECORD_SCHEMA_VERSION",
    "EVOLUTION_METADATA_TEXT_LIMIT",
    "append_evolution_status_record",
    "RaphaelEvolutionDecision",
    "append_evolution_record",
    "build_evolution_action_proposal",
    "build_evolution_signal",
    "build_raphael_evolution_review_prompt",
    "decide_raphael_evolution",
    "get_raphael_evolution_records_path",
    "read_evolution_records",
    "record_evolution_action_proposal",
    "sanitize_evolution_text",
    "sanitize_raphael_evolution_metadata",
    "sanitize_persistent_error",
    "sanitize_raphael_evolution_status_metadata",
    "summarize_learning_outcome",
]

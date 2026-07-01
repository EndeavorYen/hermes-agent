from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from agent.raphael.models import ActionProposal, RaphaelEvent, RiskLevel


_PUBLIC_TEXT_REDACTIONS = (
    (
        re.compile(r"data:[^\s,)]+;base64,[^\s,)]+", re.IGNORECASE),
        "[redacted-base64]",
    ),
    (re.compile(r"base64:[^\s,)]+", re.IGNORECASE), "[redacted-base64]"),
    (re.compile(r"candidate:[^\s,)]+", re.IGNORECASE), "[redacted-candidate]"),
    (
        re.compile(r"(?:file://)?/(?:private|Users|tmp|var)(?:/[^\s,)]+)*"),
        "[redacted-path]",
    ),
)

EVOLUTION_SIGNAL_EVENT_KIND = "evolution_signal_recorded"
PROOF_GATE_RECURRING_SIGNAL_THRESHOLD = 2


@dataclass(frozen=True)
class RaphaelEvolutionSignal:
    source: str
    affected_capability: str
    reason_codes: tuple[str, ...]
    summary: str
    evidence_refs: tuple[str, ...]
    confidence: float
    proposed_change: str
    promotion_gate: str
    rollback_condition: str
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", str(self.source))
        object.__setattr__(
            self,
            "affected_capability",
            _normalize_capability(self.affected_capability),
        )
        object.__setattr__(
            self,
            "reason_codes",
            tuple(str(reason) for reason in self.reason_codes if str(reason).strip()),
        )
        object.__setattr__(self, "summary", sanitize_evolution_text(self.summary))
        object.__setattr__(
            self,
            "evidence_refs",
            tuple(
                sanitize_evolution_text(ref)
                for ref in self.evidence_refs
                if str(ref).strip()
            ),
        )
        object.__setattr__(
            self,
            "confidence",
            max(0.0, min(1.0, float(self.confidence))),
        )
        object.__setattr__(
            self,
            "proposed_change",
            sanitize_evolution_text(self.proposed_change),
        )
        object.__setattr__(
            self,
            "promotion_gate",
            sanitize_evolution_text(self.promotion_gate),
        )
        object.__setattr__(
            self,
            "rollback_condition",
            sanitize_evolution_text(self.rollback_condition),
        )
        if self.metadata is not None:
            object.__setattr__(
                self,
                "metadata",
                sanitize_evolution_metadata(self.metadata),
            )


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
) -> RaphaelEvolutionSignal:
    return RaphaelEvolutionSignal(
        source=source,
        affected_capability=affected_capability,
        reason_codes=tuple(reason_codes),
        summary=summary,
        evidence_refs=tuple(evidence_refs),
        confidence=confidence,
        proposed_change=proposed_change,
        promotion_gate=promotion_gate,
        rollback_condition=rollback_condition,
        metadata=metadata,
    )


def build_evolution_action_proposal(
    signals: Sequence[RaphaelEvolutionSignal | Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> ActionProposal | None:
    normalized = tuple(_coerce_signal(signal) for signal in signals)
    normalized = tuple(signal for signal in normalized if signal is not None)
    if not normalized:
        return None

    selected = _select_focus_signals(normalized)
    if not selected:
        return None
    if _requires_recurring_evidence(selected) and len(selected) < 2:
        return None
    focus = selected[0]
    signal_count = len(selected)
    capability = focus.affected_capability
    reason_codes = tuple(
        sorted({reason for signal in selected for reason in signal.reason_codes})
    )
    evidence_refs = _proposal_evidence_refs(capability, selected)
    proposed_change = focus.proposed_change or "improve the affected Raphael strategy"
    promotion_gate = focus.promotion_gate or "focused tests"
    rollback_condition = (
        focus.rollback_condition
        or "user feedback or proof records show worse behavior"
    )
    confidence = max(signal.confidence for signal in selected)
    label = _capability_label(capability)
    recurring = f"{signal_count} recurring signals" if signal_count > 1 else "1 signal"
    summary = sanitize_evolution_text(
        f"Patch {label} after {recurring}: {proposed_change}. "
        f"Promotion gate: {promotion_gate}. Rollback: {rollback_condition}."
    )
    proposal_id = _proposal_id(capability, reason_codes, proposed_change)
    metadata = {
        "affected_capability": capability,
        "reason_codes": list(reason_codes),
        "confidence": round(confidence, 2),
        "recurring_signal_count": signal_count,
        "promotion_gate": promotion_gate,
        "rollback_condition": rollback_condition,
        "proposed_change": proposed_change,
        "approval_required": True,
        "source_signals": [signal.source for signal in selected],
        "rollout_plan": {
            "manual_steps": [
                f"Open a scoped issue or PR for {capability}.",
                "Apply the proposed skill or strategy change only after approval.",
                "Run the promotion gate before enabling the change.",
            ],
            "verification_commands": _verification_commands(capability),
            "rollback_condition": rollback_condition,
        },
    }
    return ActionProposal(
        proposal_id=proposal_id,
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary=summary,
        evidence_refs=evidence_refs,
        created_at=_ensure_utc(now) if now is not None else _utc_now(),
        metadata=sanitize_evolution_metadata(metadata),
    )


def record_evolution_action_proposal(
    signals: Sequence[RaphaelEvolutionSignal | Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> ActionProposal | None:
    proposal = build_evolution_action_proposal(signals, now=now)
    if proposal is None:
        return None

    from agent.raphael.state import read_state, write_state

    state = read_state()
    proposal_family = _proposal_family_id(proposal.proposal_id)
    for existing in state.action_proposals:
        if (
            _proposal_family_id(existing.proposal_id) == proposal_family
            and existing.status == "pending"
        ):
            return existing

    family_size = sum(
        1
        for existing in state.action_proposals
        if _proposal_family_id(existing.proposal_id) == proposal_family
    )
    if family_size:
        proposal = replace(
            proposal,
            proposal_id=f"{proposal.proposal_id}-r{family_size + 1}",
        )

    updated = replace(
        state,
        action_proposals=(*state.action_proposals, proposal),
        updated_at=proposal.created_at,
    )
    write_state(updated)
    return proposal


def record_proof_gate_failure_signal(
    proof_gate_result: Any,
    *,
    turn_id: str,
    user_message: Any,
    now: datetime | None = None,
) -> ActionProposal | None:
    if getattr(proof_gate_result, "status", None) == "passed":
        return None

    observed_at = _ensure_utc(now) if now is not None else _utc_now()
    signal = _proof_gate_signal_from_result(
        proof_gate_result,
        turn_id=str(turn_id or "unknown"),
        user_message=user_message,
    )
    _append_evolution_signal_event(signal, observed_at=observed_at)
    signals = _read_evolution_signal_events(
        source="proof_gate",
        affected_capability="raphael.proof_gate",
    )
    return record_evolution_action_proposal(signals, now=observed_at)


def sanitize_evolution_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_evolution_metadata(item)
            for key, item in value.items()
            if str(key) != "durable_policy_mutated"
        }
    if isinstance(value, str):
        return sanitize_evolution_text(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_evolution_metadata(item) for item in value]
    return value


def sanitize_evolution_text(value: Any) -> str:
    sanitized = str(value)
    for pattern, replacement in _PUBLIC_TEXT_REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _coerce_signal(
    signal: RaphaelEvolutionSignal | Mapping[str, Any],
) -> RaphaelEvolutionSignal | None:
    if isinstance(signal, RaphaelEvolutionSignal):
        return signal
    if not isinstance(signal, Mapping):
        return None
    return build_evolution_signal(
        source=str(signal.get("source") or "unknown"),
        affected_capability=str(signal.get("affected_capability") or ""),
        reason_codes=tuple(signal.get("reason_codes") or ()),
        summary=str(signal.get("summary") or ""),
        evidence_refs=tuple(signal.get("evidence_refs") or ()),
        confidence=float(signal.get("confidence") or 0.0),
        proposed_change=str(signal.get("proposed_change") or ""),
        promotion_gate=str(signal.get("promotion_gate") or ""),
        rollback_condition=str(signal.get("rollback_condition") or ""),
        metadata=signal.get("metadata") if isinstance(signal.get("metadata"), Mapping) else None,
    )


def _select_focus_signals(
    signals: Sequence[RaphaelEvolutionSignal],
) -> tuple[RaphaelEvolutionSignal, ...]:
    grouped: dict[str, list[RaphaelEvolutionSignal]] = {}
    for signal in signals:
        if not signal.affected_capability:
            continue
        grouped.setdefault(signal.affected_capability, []).append(signal)
    if not grouped:
        return ()
    priority = (
        "user_correction",
        "hostile_review",
        "proof_gate",
        "provider_outcome",
    )
    for source in priority:
        for capability, items in grouped.items():
            focused = [item for item in items if item.source == source]
            if focused:
                return tuple(focused)
    capability, items = max(grouped.items(), key=lambda item: len(item[1]))
    return tuple(items)


def _requires_recurring_evidence(signals: Sequence[RaphaelEvolutionSignal]) -> bool:
    return bool(signals) and all(signal.source == "proof_gate" for signal in signals)


def _proof_gate_signal_from_result(
    proof_gate_result: Any,
    *,
    turn_id: str,
    user_message: Any,
) -> RaphaelEvolutionSignal:
    status = sanitize_evolution_text(getattr(proof_gate_result, "status", "unknown"))
    route_kind = sanitize_evolution_text(
        getattr(proof_gate_result, "route_kind", "unknown")
    )
    missing = tuple(getattr(proof_gate_result, "missing_proofs", ()) or ())
    missing_summary = ", ".join(str(proof) for proof in missing) or "none"
    next_action = getattr(proof_gate_result, "next_action", "")
    next_proof_command = getattr(proof_gate_result, "next_proof_command", "")
    return build_evolution_signal(
        source="proof_gate",
        affected_capability="raphael.proof_gate",
        reason_codes=("failed_proof",),
        summary=(
            f"Raphael proof gate {status} for {route_kind}; "
            f"missing proofs: {missing_summary}."
        ),
        evidence_refs=(
            f"turn:{sanitize_evolution_text(turn_id)}",
            f"proof_gate:{status}:{route_kind}",
        ),
        confidence=0.76,
        proposed_change="tighten proof-gate next-action summaries",
        promotion_gate="focused tests plus LLM smoke",
        rollback_condition="user says proof guidance is still vague",
        metadata={
            "route_kind": route_kind,
            "status": status,
            "missing_proofs": list(missing),
            "next_action": next_action,
            "next_proof_command": next_proof_command,
            "user_message": user_message,
        },
    )


def _append_evolution_signal_event(
    signal: RaphaelEvolutionSignal,
    *,
    observed_at: datetime,
) -> None:
    from agent.raphael.state import append_event

    event_hash = hashlib.sha256(
        "|".join(
            (
                signal.source,
                signal.affected_capability,
                ",".join(signal.evidence_refs),
                observed_at.isoformat(),
            )
        ).encode("utf-8")
    ).hexdigest()[:12]
    append_event(
        RaphaelEvent(
            event_id=f"evolution-signal-{event_hash}",
            kind=EVOLUTION_SIGNAL_EVENT_KIND,
            created_at=observed_at,
            details={"signal": _signal_to_dict(signal)},
        )
    )


def _read_evolution_signal_events(
    *,
    source: str,
    affected_capability: str,
    limit: int = 20,
) -> tuple[RaphaelEvolutionSignal, ...]:
    from agent.raphael.state import get_raphael_events_path

    path = get_raphael_events_path()
    if not path.exists():
        return ()

    signals: list[RaphaelEvolutionSignal] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("kind") != EVOLUTION_SIGNAL_EVENT_KIND:
            continue
        details = payload.get("details")
        raw_signal = details.get("signal") if isinstance(details, Mapping) else None
        signal = _coerce_signal(raw_signal) if isinstance(raw_signal, Mapping) else None
        if signal is None:
            continue
        if signal.source != source:
            continue
        if signal.affected_capability != affected_capability:
            continue
        signals.append(signal)
    return tuple(signals[-max(1, limit):])


def _signal_to_dict(signal: RaphaelEvolutionSignal) -> dict[str, Any]:
    return {
        "source": signal.source,
        "affected_capability": signal.affected_capability,
        "reason_codes": list(signal.reason_codes),
        "summary": signal.summary,
        "evidence_refs": list(signal.evidence_refs),
        "confidence": signal.confidence,
        "proposed_change": signal.proposed_change,
        "promotion_gate": signal.promotion_gate,
        "rollback_condition": signal.rollback_condition,
        "metadata": (
            None
            if signal.metadata is None
            else sanitize_evolution_metadata(signal.metadata)
        ),
    }


def _proposal_evidence_refs(
    capability: str,
    signals: Sequence[RaphaelEvolutionSignal],
) -> tuple[str, ...]:
    refs: list[str] = [f"evolution:{capability}"]
    for signal in signals:
        refs.extend(signal.evidence_refs)
    refs.append(f"signal_count:{len(signals)}")
    seen: set[str] = set()
    deduped = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            deduped.append(ref)
    return tuple(deduped)


def _proposal_id(
    capability: str,
    reason_codes: Sequence[str],
    proposed_change: str,
) -> str:
    seed = "|".join((capability, ",".join(reason_codes), proposed_change))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"evolution-{digest}"


def _proposal_family_id(proposal_id: str) -> str:
    return re.sub(r"-r\d+$", "", str(proposal_id))


def _verification_commands(capability: str) -> list[str]:
    if capability == "raphael.proof_gate":
        return ["python -m pytest tests/agent/test_raphael_proof.py -q"]
    if capability.startswith("visual."):
        return ["python -m pytest tests/visual -q"]
    return ["python -m pytest tests/agent -q"]


def _capability_label(capability: str) -> str:
    return {
        "raphael.proof_gate": "Raphael proof gate",
        "raphael.mode_router": "Raphael mode router",
        "raphael.evidence_gate": "Raphael evidence gate",
        "visual.provider_recovery": "visual provider recovery",
    }.get(capability, capability.replace("_", " ").replace(".", " "))


def _normalize_capability(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "RaphaelEvolutionSignal",
    "build_evolution_action_proposal",
    "build_evolution_signal",
    "record_proof_gate_failure_signal",
    "record_evolution_action_proposal",
    "sanitize_evolution_metadata",
    "sanitize_evolution_text",
]

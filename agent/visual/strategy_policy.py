from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.strategy_atoms import StrategyAtom
from agent.visual.strategy_atoms import builtin_strategy_atom_map


@dataclass(frozen=True)
class StrategyPlan:
    intent_signature: str
    mode: str
    confidence: float
    strategy_signature: str
    atom_signatures: list[str]
    activation_status: str = "shadow"
    prompt_mutation_allowed: bool = False
    activation_id: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "intent_signature": self.intent_signature,
            "mode": self.mode,
            "confidence": self.confidence,
            "strategy_signature": self.strategy_signature,
            "atom_signatures": self.atom_signatures,
            "activation_status": self.activation_status,
            "prompt_mutation_allowed": self.prompt_mutation_allowed,
            "activation_id": self.activation_id,
        }


def select_strategy_plan(
    intent_signature: str,
    *,
    provider_stats: dict[str, Any],
    preference_profile: dict[str, Any],
    exploration_rate: float = 0.2,
) -> StrategyPlan:
    atoms = builtin_strategy_atom_map()
    selected = _select_atoms(atoms, preference_profile=preference_profile)
    confidence = _policy_confidence(
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )
    mode = "exploit" if exploration_rate <= 0 or confidence >= 0.7 else "explore"
    atom_signatures = [atom.signature for atom in selected]
    return StrategyPlan(
        intent_signature=intent_signature,
        mode=mode,
        confidence=confidence,
        strategy_signature=_strategy_signature(intent_signature, atom_signatures),
        atom_signatures=atom_signatures,
    )


def find_controlled_strategy_plan(
    ledger: VisualAttemptLedger,
    *,
    intent_signature: str,
) -> StrategyPlan | None:
    activations = ledger.list_strategy_activations(intent_signature=intent_signature)
    rolled_back_ids = {
        str(row["rollback_of"])
        for row in activations
        if row.get("activation_status") == "rolled_back" and row.get("rollback_of")
    }
    for row in reversed(activations):
        activation_id = str(row.get("id") or "")
        if activation_id in rolled_back_ids:
            continue
        if row.get("activation_status") != "controlled":
            continue
        promotion_decision = row.get("promotion_decision")
        if not _safe_controlled_decision(promotion_decision):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        return StrategyPlan(
            intent_signature=str(row.get("intent_signature") or intent_signature),
            mode="controlled",
            confidence=_coerce_float(promotion_decision.get("confidence")),
            strategy_signature=str(row.get("strategy_signature") or ""),
            atom_signatures=_string_list(metadata.get("atom_signatures")),
            activation_status="controlled",
            prompt_mutation_allowed=False,
            activation_id=activation_id,
        )
    return None


def _select_atoms(
    atoms: dict[str, StrategyAtom],
    *,
    preference_profile: dict[str, Any],
) -> list[StrategyAtom]:
    selected = [atoms["safety.professional_editorial@v1"]]
    signals = preference_profile.get("signals") if isinstance(preference_profile, dict) else {}
    legs_weight = 0.0
    if isinstance(signals, dict):
        legs = signals.get("legs_positive")
        if isinstance(legs, dict):
            legs_weight = _coerce_float(legs.get("weight"))
    if legs_weight >= 0.5:
        selected.append(atoms["composition.leg_emphasis_editorial@v1"])
    else:
        selected.append(atoms["composition.full_subject_visible@v1"])
    selected.append(atoms["motion.camera_push_in@v1"])
    return selected


def _policy_confidence(
    *,
    provider_stats: dict[str, Any],
    preference_profile: dict[str, Any],
) -> float:
    provider_confidence = _provider_confidence(provider_stats)
    sample_count = int(_coerce_float(preference_profile.get("sample_count", 0)))
    preference_confidence = min(1.0, sample_count / 5.0)
    confidence = provider_confidence * 0.55 + preference_confidence * 0.35 + 0.10
    return round(max(0.0, min(1.0, confidence)), 4)


def _provider_confidence(provider_stats: dict[str, Any]) -> float:
    best = 0.0
    for row in provider_stats.values():
        if not isinstance(row, dict):
            continue
        attempt_count = int(_coerce_float(row.get("attempt_count")))
        success_rate = _coerce_float(row.get("generation_success_rate"))
        sample_confidence = min(1.0, attempt_count / 10.0)
        best = max(best, success_rate * sample_confidence)
    return best


def _strategy_signature(intent_signature: str, atom_signatures: list[str]) -> str:
    payload = "|".join([intent_signature, *atom_signatures])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"vstrat_{digest}"


def _safe_controlled_decision(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("allowed") is True
        and value.get("decision") == "promote_controlled"
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

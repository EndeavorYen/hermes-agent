from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STORY_ENGINE_FIELDS = (
    "audience_promise",
    "opening_question",
    "dramatic_question",
    "curiosity_gap",
    "knowledge_payoff",
    "ending_echo",
    "humor_strategy",
)
REQUIRED_ARC_ROLES = frozenset({"hook", "turn", "payoff", "close"})
CHILD_AGE_BANDS = frozenset({"early_childhood", "school_age"})


@dataclass(frozen=True)
class StoryEngineReport:
    ok: bool
    violations: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _version(ledger: dict[str, Any]) -> int:
    try:
        return int(ledger.get("quality_contract_version") or 0)
    except (TypeError, ValueError):
        return 0


def story_contract_enabled(ledger: dict[str, Any]) -> bool:
    return _version(ledger) >= 4 or "story_engine" in ledger


def _arc_roles(ledger: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    for scene in ledger.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        role = _text(scene.get("narrative_role")).lower()
        if role:
            roles.add(role)
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            role = _text(shot.get("narrative_role")).lower()
            if role:
                roles.add(role)
    return roles


def validate_story_engine(ledger: dict[str, Any]) -> StoryEngineReport:
    if not story_contract_enabled(ledger):
        return StoryEngineReport(True)

    violations: list[str] = []
    engine = ledger.get("story_engine")
    if not isinstance(engine, dict):
        return StoryEngineReport(False, ("story_engine",), {"arc_roles": []})

    for field_name in STORY_ENGINE_FIELDS:
        if not _text(engine.get(field_name)):
            violations.append(f"story_engine.{field_name}")

    escalation = engine.get("escalation")
    escalation_steps = (
        [_text(item) for item in escalation if _text(item)]
        if isinstance(escalation, list)
        else []
    )
    if len(escalation_steps) < 3 or len(set(escalation_steps)) < 3:
        violations.append("story_engine.escalation")

    audience = ledger.get("audience_profile")
    audience = audience if isinstance(audience, dict) else {}
    age_band = _text(audience.get("age_band"))
    if age_band in CHILD_AGE_BANDS:
        try:
            minimum_age = int(audience.get("minimum_age_years"))
        except (TypeError, ValueError):
            minimum_age = 0
        required_minimum_age = 5 if age_band == "school_age" else 3
        if minimum_age < required_minimum_age:
            violations.append("audience_profile.minimum_age_years")

    roles = _arc_roles(ledger)
    for role in sorted(REQUIRED_ARC_ROLES - roles):
        violations.append(f"story_arc.missing_role:{role}")

    metrics = {
        "arc_roles": sorted(roles),
        "escalation_steps": len(escalation_steps),
        "minimum_age_years": audience.get("minimum_age_years"),
    }
    return StoryEngineReport(not violations, tuple(violations), metrics)


def validate_story_script_bindings(
    ledger: dict[str, Any],
    script_text: str,
) -> tuple[str, ...]:
    if not story_contract_enabled(ledger):
        return ()
    engine = ledger.get("story_engine")
    if not isinstance(engine, dict):
        return ("script.md missing story_engine",)
    compact_script = "".join(str(script_text or "").split())
    violations: list[str] = []
    for field_name in ("opening_question", "knowledge_payoff", "ending_echo"):
        value = "".join(_text(engine.get(field_name)).split())
        if value and value not in compact_script:
            violations.append(f"script.md missing story_engine.{field_name}")
    return tuple(violations)


__all__ = [
    "CHILD_AGE_BANDS",
    "REQUIRED_ARC_ROLES",
    "STORY_ENGINE_FIELDS",
    "StoryEngineReport",
    "story_contract_enabled",
    "validate_story_engine",
    "validate_story_script_bindings",
]

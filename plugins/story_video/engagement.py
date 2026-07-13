from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


AGE_BANDS = frozenset(
    {"early_childhood", "school_age", "teen", "general", "adult", "professional"}
)
KNOWLEDGE_LEVELS = frozenset({"newcomer", "familiar", "advanced"})
ATTENTION_STYLES = frozenset(
    {"concrete_fast", "curious_explorer", "reflective", "analytical"}
)
SAFETY_INTENSITIES = frozenset({"gentle", "moderate", "standard"})
ENGAGEMENT_MODES = frozenset(
    {
        "young_explorer",
        "discovery_documentary",
        "human_drama",
        "transformation",
        "decision_tension",
        "calm_wonder",
    }
)
ENGAGEMENT_ROLES = frozenset({"hook", "build", "reveal", "reaction", "payoff", "breathe"})
COMPOSITION_ENERGIES = frozenset({"calm", "curious", "tense", "kinetic", "awe"})
VISUAL_TRUTH_MODES = frozenset(
    {
        "direct_evidence",
        "reconstruction",
        "inference",
        "process",
        "comparison",
        "mixed_evidence_reconstruction",
    }
)

DEFAULT_AUDIENCE_PROFILE = {
    "age_band": "general",
    "knowledge_level": "newcomer",
    "attention_style": "curious_explorer",
    "safety_intensity": "standard",
}
DEFAULT_ENGAGEMENT_PROFILE = {
    "mode": "discovery_documentary",
    "energy": "balanced",
    "humor": "none",
    "sensationalism_forbidden": True,
}

REQUIRED_SHOT_FIELDS = (
    "engagement_role",
    "attention_hook",
    "story_moment",
    "action_consequence",
    "composition_energy",
    "viewer_emotion",
    "engagement_criteria",
    "visual_truth_mode",
)

_TOPIC_METHODS = {
    "science_explainer": "mechanism, discovery, or scale",
    "science_documentary": "mechanism, discovery, or scale",
    "documentary": "human process, consequence, or discovery",
    "history": "decision, consequence, or turning point",
    "historical_documentary": "decision, consequence, or turning point",
    "cooking": "transformation, texture, or reveal",
    "business": "decision, trade-off, or outcome",
    "product": "decision, trade-off, or outcome",
    "biography": "effort, choice, or turning point",
    "calm_education": "curiosity, pattern, or recognition",
}

_TRUTH_INSTRUCTIONS = {
    "direct_evidence": (
        "Show only directly observable evidence; do not let a reconstruction stand in "
        "for the evidence itself."
    ),
    "reconstruction": (
        "Present a clearly plausible reconstruction grounded in the declared evidence; "
        "do not imply the exact depicted behavior was directly observed."
    ),
    "inference": (
        "Visualize the supported inference while retaining visible uncertainty and "
        "avoiding a claim stronger than the narration."
    ),
    "process": "Make the real process and its observable result the visual proof.",
    "comparison": "Keep both comparison terms readable under one consistent scale logic.",
    "mixed_evidence_reconstruction": (
        "Make the declared evidence bridge explicit: evidence first, then a visibly "
        "distinct reconstruction or inference."
    ),
}


@dataclass(frozen=True)
class EngagementReport:
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


def engagement_contract_enabled(ledger: dict[str, Any]) -> bool:
    return (
        _version(ledger) >= 3
        or "audience_profile" in ledger
        or "engagement_profile" in ledger
    )


def normalize_audience_profile(ledger: dict[str, Any]) -> dict[str, str]:
    profile = ledger.get("audience_profile")
    source = profile if isinstance(profile, dict) else {}
    return {
        key: _text(source.get(key)) or value
        for key, value in DEFAULT_AUDIENCE_PROFILE.items()
    }


def normalize_engagement_profile(ledger: dict[str, Any]) -> dict[str, Any]:
    profile = ledger.get("engagement_profile")
    source = profile if isinstance(profile, dict) else {}
    normalized = dict(DEFAULT_ENGAGEMENT_PROFILE)
    for key in ("mode", "energy", "humor"):
        normalized[key] = _text(source.get(key)) or normalized[key]
    if isinstance(source.get("sensationalism_forbidden"), bool):
        normalized["sensationalism_forbidden"] = source["sensationalism_forbidden"]
    return normalized


def compile_engagement_directives(
    ledger: dict[str, Any],
    shot: dict[str, Any],
) -> tuple[str, ...]:
    audience = normalize_audience_profile(ledger)
    engagement = normalize_engagement_profile(ledger)
    production_type = _text(ledger.get("production_type")).lower()
    topic_method = _TOPIC_METHODS.get(
        production_type,
        "concrete action, consequence, or reveal",
    )
    truth_mode = _text(shot.get("visual_truth_mode")) or "direct_evidence"
    criteria = "; ".join(
        _text(item) for item in shot.get("engagement_criteria") or [] if _text(item)
    )
    parts = [
        (
            "Audience contract: "
            f"age_band={audience['age_band']}, "
            f"knowledge_level={audience['knowledge_level']}, "
            f"attention_style={audience['attention_style']}, "
            f"safety_intensity={audience['safety_intensity']}."
        ),
        (
            "Engagement contract: "
            f"mode={engagement['mode']}, energy={engagement['energy']}, "
            f"humor={engagement['humor']}; use {topic_method}."
        ),
        f"Attention hook: {_text(shot.get('attention_hook'))}.",
        (
            "Story moment: capture one decisive visible instant: "
            f"{_text(shot.get('story_moment'))}."
        ),
        f"Visible consequence: {_text(shot.get('action_consequence'))}.",
        (
            "Composition intent: "
            f"role={_text(shot.get('engagement_role')) or 'build'}, "
            f"energy={_text(shot.get('composition_energy')) or 'curious'}, "
            f"viewer emotion={_text(shot.get('viewer_emotion')) or 'curiosity'}."
        ),
        f"Visual truth mode: {truth_mode}. {_TRUTH_INSTRUCTIONS.get(truth_mode, _TRUTH_INSTRUCTIONS['direct_evidence'])}",
    ]
    bridge = _text(shot.get("evidence_bridge"))
    if bridge:
        parts.append(f"Evidence bridge: {bridge}.")
    calm_reason = _text(shot.get("calm_reason"))
    if calm_reason:
        parts.append(f"Intentional calm reason: {calm_reason}.")
    if criteria:
        parts.append(f"Engagement acceptance: {criteria}.")
    if engagement.get("sensationalism_forbidden") is True:
        parts.append(
            "Do not invent danger, conflict, emotion, behavior, or certainty beyond the shot contract."
        )
    return tuple(parts)


def _shot_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scene in ledger.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        rows.extend(shot for shot in scene.get("shots") or [] if isinstance(shot, dict))
    return rows


def _profile_violation(
    violations: list[str],
    profile: dict[str, Any],
    field_name: str,
    allowed: frozenset[str],
    prefix: str,
) -> None:
    value = _text(profile.get(field_name))
    if value not in allowed:
        violations.append(f"{prefix}.{field_name}:{value or '<missing>'}")


def validate_engagement_ledger(ledger: dict[str, Any]) -> EngagementReport:
    if not engagement_contract_enabled(ledger):
        return EngagementReport(True)

    violations: list[str] = []
    audience = ledger.get("audience_profile")
    engagement = ledger.get("engagement_profile")
    if not isinstance(audience, dict):
        violations.append("audience_profile")
        audience = {}
    if not isinstance(engagement, dict):
        violations.append("engagement_profile")
        engagement = {}

    _profile_violation(violations, audience, "age_band", AGE_BANDS, "audience_profile")
    _profile_violation(
        violations,
        audience,
        "knowledge_level",
        KNOWLEDGE_LEVELS,
        "audience_profile",
    )
    _profile_violation(
        violations,
        audience,
        "attention_style",
        ATTENTION_STYLES,
        "audience_profile",
    )
    _profile_violation(
        violations,
        audience,
        "safety_intensity",
        SAFETY_INTENSITIES,
        "audience_profile",
    )
    _profile_violation(
        violations,
        engagement,
        "mode",
        ENGAGEMENT_MODES,
        "engagement_profile",
    )
    if engagement.get("sensationalism_forbidden") is not True:
        violations.append("engagement_profile.sensationalism_forbidden")

    shots = _shot_rows(ledger)
    for shot in shots:
        shot_id = _text(shot.get("shot_id")) or "shot"
        for field_name in REQUIRED_SHOT_FIELDS:
            value = shot.get(field_name)
            if field_name == "engagement_criteria":
                if not isinstance(value, list) or not any(_text(item) for item in value):
                    violations.append(f"{shot_id}.{field_name}")
            elif not _text(value):
                violations.append(f"{shot_id}.{field_name}")
        role = _text(shot.get("engagement_role"))
        energy = _text(shot.get("composition_energy"))
        truth_mode = _text(shot.get("visual_truth_mode"))
        if role and role not in ENGAGEMENT_ROLES:
            violations.append(f"{shot_id}.engagement_role:{role}")
        if energy and energy not in COMPOSITION_ENERGIES:
            violations.append(f"{shot_id}.composition_energy:{energy}")
        if truth_mode and truth_mode not in VISUAL_TRUTH_MODES:
            violations.append(f"{shot_id}.visual_truth_mode:{truth_mode}")
        if role == "breathe" and not _text(shot.get("calm_reason")):
            violations.append(f"{shot_id}.calm_reason")
        if truth_mode == "mixed_evidence_reconstruction" and not _text(
            shot.get("evidence_bridge")
        ):
            violations.append(f"{shot_id}.evidence_bridge")

    for field_name, reason_field, code in (
        (
            "engagement_role",
            "intentional_engagement_repeat_reason",
            "repeated_engagement_role_without_reason",
        ),
        (
            "composition_energy",
            "intentional_energy_repeat_reason",
            "repeated_composition_energy_without_reason",
        ),
    ):
        run_value = ""
        run_length = 0
        for shot in shots:
            value = _text(shot.get(field_name))
            if value and value == run_value:
                run_length += 1
            else:
                run_value = value
                run_length = 1
            if run_length == 3 and not _text(shot.get(reason_field)):
                violations.append(f"{code}:{value}:3")

    metrics = {
        "shot_count": len(shots),
        "engagement_roles": sorted(
            {_text(shot.get("engagement_role")) for shot in shots if _text(shot.get("engagement_role"))}
        ),
        "composition_energies": sorted(
            {_text(shot.get("composition_energy")) for shot in shots if _text(shot.get("composition_energy"))}
        ),
    }
    return EngagementReport(not violations, tuple(violations), metrics)


__all__ = [
    "AGE_BANDS",
    "ATTENTION_STYLES",
    "COMPOSITION_ENERGIES",
    "ENGAGEMENT_MODES",
    "ENGAGEMENT_ROLES",
    "EngagementReport",
    "KNOWLEDGE_LEVELS",
    "SAFETY_INTENSITIES",
    "VISUAL_TRUTH_MODES",
    "compile_engagement_directives",
    "engagement_contract_enabled",
    "normalize_audience_profile",
    "normalize_engagement_profile",
    "validate_engagement_ledger",
]

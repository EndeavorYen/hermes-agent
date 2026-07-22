from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ACCESSIBLE_EXPLAINER_PROFILE_ID = "story-video-accessible-explainer-v1"
EXPLANATION_PROFILE_SCHEMA = "story_video_accessible_explanation_v1"
ACCESSIBILITY_METRICS_SCHEMA = "story_video_accessibility_metrics_v1"
NEWCOMER_REVIEWER_ID = "newcomer_comprehension_editor"
EXPLANATION_MODES = frozenset({"accessible", "advanced", "professional"})

_PROFESSIONAL_MODE_RE = re.compile(
    r"(?:專業版|专业版|學術版|学术版|專家版|专家版)|"
    r"(?:(?:不要|不需|不用|停用|關閉|关闭|取消).{0,12}"
    r"(?:淺白化|浅白化|淺顯化|浅显化|普及化|accessible[ -]?explainer|科普淺白化))",
    re.IGNORECASE,
)
_ADVANCED_MODE_RE = re.compile(
    r"(?:進階版|进阶版|深入版|艱深一點|艰深一点|進階難度|进阶难度|"
    r"advanced(?:\s+mode)?)",
    re.IGNORECASE,
)
_EXPLANATORY_PRODUCTION_RE = re.compile(
    r"(?:explainer|documentary|science|history|historical|biography|education|"
    r"economics|finance|technology|natural_history)",
    re.IGNORECASE,
)
_SEGMENT_RE = re.compile(r"(?m)^###\s+(S\d+)\s*$")
ACCESSIBILITY_CONCEPT_BRIDGE_FIELDS = (
    "term",
    "segment_id",
    "concrete_anchor",
    "plain_explanation",
    "precision_boundary",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def resolve_explanation_mode(operator_text: str) -> str:
    text = _text(operator_text)
    if _PROFESSIONAL_MODE_RE.search(text):
        return "professional"
    if _ADVANCED_MODE_RE.search(text):
        return "advanced"
    return "accessible"


def build_explanation_profile(operator_text: str) -> dict[str, Any]:
    mode = resolve_explanation_mode(operator_text)
    audience_target = {
        "accessible": "curious_newcomer_5_plus",
        "advanced": "informed_generalist",
        "professional": "domain_specialist",
    }[mode]
    return {
        "schema": EXPLANATION_PROFILE_SCHEMA,
        "profile_id": ACCESSIBLE_EXPLAINER_PROFILE_ID,
        "mode": mode,
        "activation": "default" if mode == "accessible" else "operator_override",
        "scope": "explanatory_beats_only",
        "audience_target": audience_target,
        "explanation_order": [
            "concrete_intuition",
            "causal_chain",
            "formal_term",
            "precision_boundary",
        ],
        "baby_talk_forbidden": True,
        "precision_loss_forbidden": True,
    }


def validate_explanation_profile(profile: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    if _text(profile.get("schema")) != EXPLANATION_PROFILE_SCHEMA:
        violations.append("explanation_profile schema is invalid")
    if _text(profile.get("profile_id")) != ACCESSIBLE_EXPLAINER_PROFILE_ID:
        violations.append("explanation_profile profile_id is invalid")
    mode = _text(profile.get("mode")).lower()
    if mode not in EXPLANATION_MODES:
        violations.append("explanation_profile mode is invalid")
    expected_activation = "default" if mode == "accessible" else "operator_override"
    if _text(profile.get("activation")) != expected_activation:
        violations.append("explanation_profile activation is invalid")
    if _text(profile.get("scope")) != "explanatory_beats_only":
        violations.append("explanation_profile scope is invalid")
    if not _text(profile.get("audience_target")):
        violations.append("explanation_profile audience_target is missing")
    if profile.get("explanation_order") != [
        "concrete_intuition",
        "causal_chain",
        "formal_term",
        "precision_boundary",
    ]:
        violations.append("explanation_profile explanation_order is invalid")
    if profile.get("baby_talk_forbidden") is not True:
        violations.append("explanation_profile baby_talk_forbidden is not true")
    if profile.get("precision_loss_forbidden") is not True:
        violations.append("explanation_profile precision_loss_forbidden is not true")
    return tuple(violations)


def ensure_explanation_profile(
    project_dir: Path,
    operator_text: str,
) -> dict[str, Any]:
    path = project_dir / "explanation_profile.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict) and not validate_explanation_profile(existing):
            return existing

    profile = build_explanation_profile(operator_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return profile


def explanation_is_required(ledger: dict[str, Any]) -> bool:
    if ledger.get("explanation_required") is True:
        return True
    return (
        _EXPLANATORY_PRODUCTION_RE.search(_text(ledger.get("production_type")))
        is not None
    )


def _validate_accessibility_metrics(
    report: dict[str, Any],
    *,
    ledger: dict[str, Any],
    script_text: str,
) -> list[str]:
    violations: list[str] = []
    metrics = report.get("accessibility_metrics")
    if not isinstance(metrics, dict):
        return ["script_review_report accessibility_metrics is missing"]
    if _text(metrics.get("schema")) != ACCESSIBILITY_METRICS_SCHEMA:
        violations.append("accessibility_metrics schema is invalid")
    if _text(metrics.get("status")).upper() != "PASS":
        violations.append("accessibility_metrics status is not PASS")
    jargon = metrics.get("unexplained_jargon")
    if not isinstance(jargon, list):
        violations.append("accessibility_metrics unexplained_jargon is not a list")
    elif jargon:
        violations.append("accessibility_metrics unexplained_jargon is not empty")
    for field_name in ("baby_talk_detected", "precision_loss_detected"):
        if metrics.get(field_name) is not False:
            violations.append(f"accessibility_metrics {field_name} is not false")

    bridges = metrics.get("concept_bridges")
    bridge_rows = bridges if isinstance(bridges, list) else []
    if not isinstance(bridges, list):
        violations.append("accessibility_metrics concept_bridges is not a list")
    if explanation_is_required(ledger) and not bridge_rows:
        violations.append("accessibility_metrics concept_bridges is empty")
    segment_ids = set(_SEGMENT_RE.findall(script_text))
    for index, bridge in enumerate(bridge_rows):
        if not isinstance(bridge, dict):
            violations.append(
                f"accessibility_metrics concept_bridges[{index}] is invalid"
            )
            continue
        for field_name in ACCESSIBILITY_CONCEPT_BRIDGE_FIELDS:
            if not _text(bridge.get(field_name)):
                violations.append(
                    f"accessibility_metrics concept_bridges[{index}].{field_name} is missing"
                )
        segment_id = _text(bridge.get("segment_id"))
        if segment_id and segment_id not in segment_ids:
            violations.append(
                f"accessibility_metrics concept_bridges[{index}].segment_id is unknown"
            )
    return violations


def validate_explanation_bundle(
    *,
    profile: dict[str, Any],
    content_profile: dict[str, Any],
    review_report: dict[str, Any],
    ledger: dict[str, Any],
    script_text: str,
) -> tuple[str, ...]:
    violations = list(validate_explanation_profile(profile))
    mode = _text(profile.get("mode")).lower()
    if _text(content_profile.get("explanation_profile_id")) != _text(
        profile.get("profile_id")
    ):
        violations.append("content_profile explanation_profile_id mismatch")
    if _text(content_profile.get("explanation_mode")).lower() != mode:
        violations.append("content_profile explanation_mode mismatch")

    if mode != "accessible" or not explanation_is_required(ledger):
        return tuple(violations)

    supplemental = content_profile.get("supplemental_writer_profile_ids")
    if not isinstance(supplemental, list) or ACCESSIBLE_EXPLAINER_PROFILE_ID not in {
        _text(item) for item in supplemental
    }:
        violations.append(
            "content_profile supplemental_writer_profile_ids missing accessible explainer"
        )

    reviewers = review_report.get("reviewers")
    reviewer_rows = reviewers if isinstance(reviewers, list) else []
    matches = [
        row
        for row in reviewer_rows
        if isinstance(row, dict)
        and _text(row.get("reviewer_id")) == NEWCOMER_REVIEWER_ID
    ]
    if not matches:
        violations.append(
            "accessible explanation missing newcomer_comprehension_editor"
        )
    elif len(matches) > 1:
        violations.append(
            "accessible explanation duplicate newcomer_comprehension_editor"
        )
    else:
        reviewer = matches[0]
        if _text(reviewer.get("status")).upper() != "PASS":
            violations.append("newcomer_comprehension_editor status is not PASS")
        score = reviewer.get("score")
        if type(score) is not int or score < 85:
            violations.append("newcomer_comprehension_editor score<85")
        if not isinstance(reviewer.get("findings"), list):
            violations.append("newcomer_comprehension_editor findings are not a list")
    violations.extend(
        _validate_accessibility_metrics(
            review_report,
            ledger=ledger,
            script_text=script_text,
        )
    )
    return tuple(violations)


__all__ = [
    "ACCESSIBILITY_METRICS_SCHEMA",
    "ACCESSIBLE_EXPLAINER_PROFILE_ID",
    "EXPLANATION_MODES",
    "EXPLANATION_PROFILE_SCHEMA",
    "NEWCOMER_REVIEWER_ID",
    "build_explanation_profile",
    "ensure_explanation_profile",
    "explanation_is_required",
    "resolve_explanation_mode",
    "validate_explanation_bundle",
    "validate_explanation_profile",
]

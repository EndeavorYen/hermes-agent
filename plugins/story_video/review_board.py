from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .editorial_quality import EDITORIAL_PROFILE_ID, validate_editorial_profile_v2
from .music import validate_music_direction


REVIEW_CONTRACT_VERSION = 6
REVIEW_SCORE_THRESHOLD = 85
REQUIRED_REVIEWER_IDS = (
    "language_editor",
    "fact_checker",
    "clarity_editor",
    "engagement_editor",
    "audience_safety_editor",
    "performance_editor",
)
OPTIONAL_REVIEWER_IDS = ("newcomer_comprehension_editor",)
V6_QUALITY_CHECKS = (
    "language_fluency",
    "factual_integrity",
    "clarity_concision",
    "engagement",
    "audience_fit",
    "read_aloud_performance",
    "dramatic_arc",
    "visual_causality",
    "style_consistency",
)

_ACTIVE_RATINGS = frozenset({"family", "general"})
_RESERVED_RATINGS = frozenset({"mature", "adult_explicit"})
_EXECUTION_MODES = frozenset({"structured_board", "independent_agents"})
_FINDING_SEVERITIES = frozenset({"minor", "moderate", "major", "critical"})
_FINDING_RESOLUTIONS = frozenset({"resolved", "unresolved", "accepted_risk"})
_CHILD_AGE_BANDS = frozenset({"early_childhood", "school_age"})
_FACTUAL_PRODUCTION_TYPES = frozenset(
    {
        "science_explainer",
        "science_documentary",
        "documentary",
        "natural_history_documentary",
        "history",
        "historical_documentary",
        "biography",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FINDING_FIELDS = (
    "finding_id",
    "severity",
    "location",
    "category",
    "evidence",
    "recommendation",
    "resolution_status",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [_text(item) for item in value if _text(item)]


def content_profile_requires_child_curiosity(
    ledger: dict[str, Any], profile: dict[str, Any] | None
) -> bool:
    rating = _text(profile.get("rating")).lower() if isinstance(profile, dict) else ""
    audience = ledger.get("audience_profile")
    age_band = (
        _text(audience.get("age_band")).lower()
        if isinstance(audience, dict)
        else ""
    )
    return rating == "family" or age_band in _CHILD_AGE_BANDS


def validate_content_profile(
    profile: dict[str, Any], ledger: dict[str, Any]
) -> tuple[str, ...]:
    violations: list[str] = []
    if _text(profile.get("schema")) != "story_video_content_profile_v1":
        violations.append("content_profile schema is invalid")

    rating = _text(profile.get("rating")).lower()
    if rating in _RESERVED_RATINGS:
        return tuple(violations + [f"content_profile rating {rating} SETUP_REQUIRED"])
    if rating not in _ACTIVE_RATINGS:
        violations.append(f"content_profile rating is invalid: {rating or '<missing>'}")

    if _text(profile.get("activation_status")).lower() != "active":
        violations.append("content_profile activation_status is not active")
    if _text(profile.get("provider_capability_status")).lower() != "available":
        violations.append("content_profile provider_capability_status is not available")
    for field_name in (
        "policy_profile_id",
        "writer_profile_id",
        "review_profile_id",
    ):
        if not _text(profile.get(field_name)):
            violations.append(f"content_profile {field_name} is missing")

    minimum_age = profile.get("minimum_viewer_age")
    if type(minimum_age) is not int or minimum_age < 0:
        violations.append("content_profile minimum_viewer_age is invalid")
    elif rating == "family" and minimum_age < 3:
        violations.append("content_profile family minimum_viewer_age<3")

    audience = ledger.get("audience_profile")
    age_band = (
        _text(audience.get("age_band")).lower()
        if isinstance(audience, dict)
        else ""
    )
    if rating == "general" and age_band in _CHILD_AGE_BANDS:
        violations.append("content_profile general rating conflicts with child age band")
    return tuple(violations)


def _validate_finding(
    finding: Any,
    *,
    reviewer_id: str,
    index: int,
    seen_finding_ids: set[str],
) -> tuple[list[str], str, bool]:
    violations: list[str] = []
    if not isinstance(finding, dict):
        return (
            [f"script_review_report reviewer {reviewer_id} finding[{index}] is not an object"],
            "",
            False,
        )
    for field_name in _FINDING_FIELDS:
        if not _text(finding.get(field_name)):
            violations.append(
                f"script_review_report reviewer {reviewer_id} finding[{index}] "
                f"{field_name} is missing"
            )
    finding_id = _text(finding.get("finding_id"))
    if finding_id:
        if finding_id in seen_finding_ids:
            violations.append(f"script_review_report duplicate finding_id: {finding_id}")
        seen_finding_ids.add(finding_id)
    severity = _text(finding.get("severity")).lower()
    resolution = _text(finding.get("resolution_status")).lower()
    if severity and severity not in _FINDING_SEVERITIES:
        violations.append(
            f"script_review_report finding {finding_id or index} severity is invalid"
        )
    if resolution and resolution not in _FINDING_RESOLUTIONS:
        violations.append(
            f"script_review_report finding {finding_id or index} resolution_status is invalid"
        )
    unresolved_critical = severity == "critical" and resolution != "resolved"
    return violations, finding_id, unresolved_critical


def validate_script_review_report(
    report: dict[str, Any],
    *,
    ledger: dict[str, Any],
    director_report: dict[str, Any],
    script_bytes: bytes,
) -> tuple[str, ...]:
    violations: list[str] = []
    if _text(report.get("schema")) != "story_video_script_review_v1":
        violations.append("script_review_report schema is invalid")
    if report.get("quality_contract_version") != REVIEW_CONTRACT_VERSION:
        violations.append("script_review_report quality_contract_version is not 6")
    if _upper(report.get("status")) != "PASS":
        violations.append("script_review_report status is not PASS")
    if _text(report.get("execution_mode")).lower() not in _EXECUTION_MODES:
        violations.append("script_review_report execution_mode is invalid")
    rounds = report.get("revision_round_count")
    if type(rounds) is not int or not 1 <= rounds <= 2:
        violations.append("script_review_report revision_round_count must be 1 or 2")

    reviewers = report.get("reviewers")
    reviewer_rows = reviewers if isinstance(reviewers, list) else []
    if not isinstance(reviewers, list):
        violations.append("script_review_report reviewers are not a list")
    reviewer_counts: dict[str, int] = {}
    reviewer_by_id: dict[str, dict[str, Any]] = {}
    seen_finding_ids: set[str] = set()
    finding_resolution_by_id: dict[str, str] = {}
    unresolved_critical_ids: list[str] = []
    for index, reviewer in enumerate(reviewer_rows):
        if not isinstance(reviewer, dict):
            violations.append(f"script_review_report reviewer[{index}] is not an object")
            continue
        reviewer_id = _text(reviewer.get("reviewer_id"))
        if not reviewer_id:
            violations.append(f"script_review_report reviewer[{index}] reviewer_id is missing")
            continue
        reviewer_counts[reviewer_id] = reviewer_counts.get(reviewer_id, 0) + 1
        reviewer_by_id.setdefault(reviewer_id, reviewer)
        if _upper(reviewer.get("status")) != "PASS":
            violations.append(f"script_review_report reviewer {reviewer_id} status is not PASS")
        score = reviewer.get("score")
        if type(score) is not int or not 0 <= score <= 100:
            violations.append(f"script_review_report reviewer {reviewer_id} score is invalid")
        elif score < REVIEW_SCORE_THRESHOLD:
            violations.append(
                f"script_review_report reviewer {reviewer_id} score<{REVIEW_SCORE_THRESHOLD}"
            )
        findings = reviewer.get("findings")
        if not isinstance(findings, list):
            violations.append(f"script_review_report reviewer {reviewer_id} findings are not a list")
            continue
        for finding_index, finding in enumerate(findings):
            finding_violations, finding_id, unresolved_critical = _validate_finding(
                finding,
                reviewer_id=reviewer_id,
                index=finding_index,
                seen_finding_ids=seen_finding_ids,
            )
            violations.extend(finding_violations)
            if finding_id and isinstance(finding, dict):
                finding_resolution_by_id.setdefault(
                    finding_id,
                    _text(finding.get("resolution_status")).lower(),
                )
            if unresolved_critical:
                unresolved_critical_ids.append(finding_id or f"{reviewer_id}[{finding_index}]")

    for reviewer_id, count in sorted(reviewer_counts.items()):
        if count > 1:
            violations.append(f"script_review_report duplicate reviewer: {reviewer_id}")
    for reviewer_id in REQUIRED_REVIEWER_IDS:
        if reviewer_counts.get(reviewer_id, 0) == 0:
            violations.append(f"script_review_report missing reviewer: {reviewer_id}")
    allowed_reviewer_ids = set(REQUIRED_REVIEWER_IDS) | set(OPTIONAL_REVIEWER_IDS)
    for reviewer_id in sorted(set(reviewer_counts) - allowed_reviewer_ids):
        violations.append(f"script_review_report unexpected reviewer: {reviewer_id}")
    for finding_id in unresolved_critical_ids:
        violations.append(f"script_review_report unresolved critical finding: {finding_id}")

    production_type = _text(ledger.get("production_type")).lower()
    fact_checker = reviewer_by_id.get("fact_checker")
    if production_type in _FACTUAL_PRODUCTION_TYPES and isinstance(fact_checker, dict):
        if not _string_list(fact_checker.get("evidence_source_ids")):
            violations.append("script_review_report fact_checker evidence_source_ids are missing")

    adjudication = report.get("adjudication")
    resolved_ids: list[str] = []
    unresolved_ids: list[str] = []
    if not isinstance(adjudication, dict):
        violations.append("script_review_report adjudication is missing")
    else:
        if _upper(adjudication.get("status")) != "PASS":
            violations.append("script_review_report adjudication status is not PASS")
        parsed_resolved_ids = _string_list(adjudication.get("resolved_finding_ids"))
        parsed_unresolved_ids = _string_list(adjudication.get("unresolved_finding_ids"))
        if parsed_resolved_ids is None:
            violations.append("script_review_report resolved_finding_ids are not a list")
        else:
            resolved_ids = parsed_resolved_ids
        if parsed_unresolved_ids is None:
            violations.append("script_review_report unresolved_finding_ids are not a list")
        else:
            unresolved_ids = parsed_unresolved_ids
        for finding_id in resolved_ids + unresolved_ids:
            if finding_id not in seen_finding_ids:
                violations.append(
                    f"script_review_report adjudication references unknown finding: {finding_id}"
                )
        resolved_set = set(resolved_ids)
        unresolved_set = set(unresolved_ids)
        for finding_id, resolution in finding_resolution_by_id.items():
            in_resolved = finding_id in resolved_set
            in_unresolved = finding_id in unresolved_set
            if not in_resolved and not in_unresolved:
                violations.append(
                    f"script_review_report adjudication omits finding: {finding_id}"
                )
            elif in_resolved and in_unresolved:
                violations.append(
                    f"script_review_report adjudication classifies finding twice: {finding_id}"
                )
            elif resolution == "resolved" and not in_resolved:
                violations.append(
                    f"script_review_report adjudication conflicts with finding: {finding_id}"
                )
            elif resolution in {"unresolved", "accepted_risk"} and not in_unresolved:
                violations.append(
                    f"script_review_report adjudication conflicts with finding: {finding_id}"
                )

    actual_sha = hashlib.sha256(script_bytes).hexdigest()
    verification = report.get("final_verification")
    if not isinstance(verification, dict):
        violations.append("script_review_report final_verification is missing")
    else:
        if _upper(verification.get("status")) != "PASS":
            violations.append("script_review_report final_verification status is not PASS")
        reviewed_sha = _text(verification.get("final_script_sha256")).lower()
        if not _SHA256_RE.fullmatch(reviewed_sha):
            violations.append("script_review_report final_script_sha256 is invalid")
        elif reviewed_sha != actual_sha:
            violations.append("script_review_report final_script_sha256 mismatch")

    director_sha = _text(director_report.get("final_script_sha256")).lower()
    if not _SHA256_RE.fullmatch(director_sha):
        violations.append("script_quality_report final_script_sha256 is invalid")
    elif director_sha != actual_sha:
        violations.append("script_quality_report final_script_sha256 mismatch")
    return tuple(violations)


def validate_v6_review_bundle(
    project_dir: Path,
    ledger: dict[str, Any],
    director_report: dict[str, Any],
    content_profile: dict[str, Any],
    review_report: dict[str, Any],
) -> tuple[str, ...]:
    script_path = project_dir / "script.md"
    try:
        script_bytes = script_path.read_bytes()
    except OSError:
        return ("script.md is unreadable for v6 review verification",)
    violations = list(validate_content_profile(content_profile, ledger))
    violations.extend(
        validate_script_review_report(
            review_report,
            ledger=ledger,
            director_report=director_report,
            script_bytes=script_bytes,
        )
    )
    if _text(content_profile.get("review_profile_id")) == EDITORIAL_PROFILE_ID:
        music_direction = ledger.get("music_direction")
        if not isinstance(music_direction, dict):
            violations.append("music_direction is missing")
        else:
            violations.extend(validate_music_direction(music_direction))
        editorial_metrics = review_report.get("editorial_metrics")
        if not isinstance(editorial_metrics, dict):
            violations.append("script_review_report editorial_metrics is missing")
        else:
            violations.extend(
                validate_editorial_profile_v2(
                    script_bytes.decode("utf-8"),
                    editorial_metrics,
                    ledger.get("target_duration_sec", 0),
                )
            )
    return tuple(violations)


__all__ = [
    "REQUIRED_REVIEWER_IDS",
    "OPTIONAL_REVIEWER_IDS",
    "REVIEW_CONTRACT_VERSION",
    "REVIEW_SCORE_THRESHOLD",
    "V6_QUALITY_CHECKS",
    "content_profile_requires_child_curiosity",
    "validate_content_profile",
    "validate_script_review_report",
    "validate_v6_review_bundle",
]

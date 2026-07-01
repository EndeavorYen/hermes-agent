from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

from agent.visual.provider_failures import classify_visual_provider_failure


MIN_OPENAI_IMAGE_QUALITY_SCORE = 0.80
DEFAULT_OPENAI_IMAGE_EVIDENCE_MAX_AGE_SECONDS = 24 * 60 * 60
REQUIRED_OPENAI_IMAGE_EVIDENCE_REF_KEYS = (
    "generation",
    "selection",
    "freshness",
    "dedupe",
    "geometry",
    "quality_review",
)
OPENAI_IMAGE_READINESS_CONTRACT = "raphael.media.openai_image.phase7.current_selected.v1"

_FORBIDDEN_MEDIA_READY_KEYWORDS = {
    "grok_web_imagine": ("grok", "grok web imagine", "imagine"),
    "video": ("video", "影片", "視頻", "短片"),
    "slack_delivery": ("slack", "native upload", "native delivery", "delivery", "交付"),
    "full_media": ("full media", "media", "visual", "完整媒體", "完整視覺"),
}

_PRIVATE_TEXT_REDACTIONS = (
    (
        re.compile(r"data:[^\s,)]+;base64,[^\s,)]+", re.IGNORECASE),
        "[redacted-media-payload]",
    ),
    (re.compile(r"base64:[^\s,)]+", re.IGNORECASE), "[redacted-media-payload]"),
    (re.compile(r"\bbase64\b", re.IGNORECASE), "[redacted-media-payload]"),
    (re.compile(r"\bcandidate:[^\s,)]+", re.IGNORECASE), "[redacted-artifact]"),
    (
        re.compile(r"(?:file://)?/(?:private|Users|tmp|var)(?:/[^\s,)]+)*"),
        "[redacted-path]",
    ),
)


@dataclass(frozen=True)
class RaphaelMediaEvidence:
    status: str
    provider: str
    capability: str
    evidence_refs: tuple[str, ...]
    failure_layer: str | None
    blocking_reason: str | None
    next_action: str
    artifact_id: str | None = None
    selected_artifact_id: str | None = None
    dimensions: Mapping[str, int] | None = None
    quality_score: float | None = None
    verification_contract: str | None = None


@dataclass(frozen=True)
class RaphaelMediaReadinessReport:
    status: str
    slices: Mapping[str, Mapping[str, Any]]
    public_claims: tuple[str, ...]
    blocked_claims: tuple[str, ...]
    openai_image: RaphaelMediaEvidence | None
    created_at: datetime


@dataclass(frozen=True)
class RaphaelMediaClaimBoundaryResult:
    passed: bool
    evidence_refs: tuple[str, ...]
    summary: str


def classify_openai_image_evidence(
    payload: Mapping[str, Any] | None,
    *,
    expected_session_id: str | None = None,
    current_selected_artifact_id: str | None = None,
    max_age_seconds: int = DEFAULT_OPENAI_IMAGE_EVIDENCE_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> RaphaelMediaEvidence:
    if not isinstance(payload, Mapping):
        return _failed_openai_image(
            evidence_refs=("media-readiness:missing",),
            layer="openai_image_evidence",
            reason="openai_image_evidence_missing",
            next_action="Provide OpenAI image evidence from the current selected artifact.",
        )

    optional_evidence_refs = _optional_evidence_refs(payload)
    provider = _safe_text(payload.get("provider") or "unknown")
    capability = _safe_text(payload.get("capability") or "unknown")
    status = str(payload.get("status") or "").strip().lower()

    if provider != "openai":
        return _failed_openai_image(
            evidence_refs=optional_evidence_refs,
            layer="provider_routing",
            reason="openai_image_wrong_provider",
            next_action="Route this slice through the OpenAI image provider before claiming readiness.",
            provider=provider,
            capability=capability,
        )
    if capability != "image":
        return _failed_openai_image(
            evidence_refs=optional_evidence_refs,
            layer="provider_routing",
            reason="openai_image_wrong_capability",
            next_action="Provide image-generation evidence, not video or text evidence.",
            provider=provider,
            capability=capability,
        )

    if status not in {"success", "passed", "ready"}:
        return _classify_openai_failure(payload, evidence_refs=optional_evidence_refs)

    evidence_refs, evidence_refs_error = _required_evidence_refs(payload)
    if evidence_refs_error is not None:
        return _failed_openai_image(
            evidence_refs=optional_evidence_refs,
            layer="openai_image_evidence",
            reason=evidence_refs_error,
            next_action="Record structured generation, selection, freshness, dedupe, geometry, and quality evidence.",
        )

    expected_session = str(expected_session_id or "").strip()
    session_id = _safe_text(payload.get("session_id") or "")
    if not expected_session:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_freshness",
            reason="openai_image_expected_session_missing",
            next_action="Pass the expected OpenAI image session id to prevent replayed evidence.",
        )
    if session_id != expected_session:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_freshness",
            reason="openai_image_session_mismatch",
            next_action="Use evidence from the current OpenAI image run session.",
        )

    generated_at = _parse_datetime(payload.get("generated_at"))
    if generated_at is None:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_freshness",
            reason="openai_image_generated_at_missing",
            next_action="Record generated_at so stale evidence cannot be replayed.",
        )
    created_at = _ensure_utc(now) if now is not None else _utc_now()
    if generated_at > created_at + timedelta(minutes=5):
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_freshness",
            reason="openai_image_evidence_from_future",
            next_action="Recreate evidence with a trustworthy current timestamp.",
        )
    age_seconds = max(0, int(max_age_seconds))
    if (created_at - generated_at).total_seconds() > age_seconds:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_freshness",
            reason="openai_image_evidence_stale",
            next_action="Regenerate or revalidate the selected artifact in the current run.",
        )

    artifact_id = _safe_text(payload.get("artifact_id") or "")
    selected_artifact_id = _safe_text(payload.get("selected_artifact_id") or "")
    current_selected_artifact = _safe_text(current_selected_artifact_id or "")
    dimensions = _safe_dimensions(payload.get("dimensions"))
    quality_score, quality_passed = _quality_result(payload.get("quality"))

    if not artifact_id:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_selection",
            reason="openai_image_artifact_missing",
            next_action="Record the generated image artifact id before claiming readiness.",
        )
    if selected_artifact_id != artifact_id:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_selection",
            reason="openai_image_not_selected_artifact",
            next_action="Use the current selected artifact as the public deliverable.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id or None,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if not current_selected_artifact:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_selection",
            reason="openai_image_current_selected_artifact_missing",
            next_action="Pass the current selected artifact id to prevent stale selected-artifact replay.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if selected_artifact_id != current_selected_artifact:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_selection",
            reason="openai_image_not_current_selected_artifact",
            next_action="Use evidence for the artifact that is currently selected for delivery.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if payload.get("fresh") is not True:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_freshness",
            reason="openai_image_artifact_stale",
            next_action="Generate or select a fresh artifact tied to the current request.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if "duplicated" not in payload:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_deduplication",
            reason="openai_image_duplicate_status_missing",
            next_action="Record duplicate-delivery status explicitly before claiming readiness.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if payload.get("duplicated") is True:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_deduplication",
            reason="openai_image_duplicate_artifact",
            next_action="Reject duplicate or previously delivered artifacts before public delivery.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if payload.get("duplicated") is not False:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_deduplication",
            reason="openai_image_duplicate_status_invalid",
            next_action="Record duplicate-delivery status as a boolean false for the selected artifact.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if "rejected" not in payload:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_quality",
            reason="openai_image_rejection_status_missing",
            next_action="Record rejection status explicitly before claiming readiness.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if payload.get("rejected") is True:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_quality",
            reason="openai_image_artifact_rejected",
            next_action="Repair or regenerate instead of delivering a rejected candidate.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if payload.get("rejected") is not False:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_quality",
            reason="openai_image_rejection_status_invalid",
            next_action="Record rejection status as a boolean false for the selected artifact.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )
    if dimensions is None:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_geometry",
            reason="openai_image_dimensions_missing",
            next_action="Record width and height so packaging can preserve geometry.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            quality_score=quality_score,
        )
    if not quality_passed or quality_score < MIN_OPENAI_IMAGE_QUALITY_SCORE:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="artifact_quality",
            reason="openai_image_quality_below_threshold",
            next_action="Run visual review or regenerate before claiming OpenAI image readiness.",
            artifact_id=artifact_id,
            selected_artifact_id=selected_artifact_id,
            dimensions=dimensions,
            quality_score=quality_score,
        )

    return RaphaelMediaEvidence(
        status="passed",
        provider="openai",
        capability="image",
        evidence_refs=evidence_refs,
        failure_layer=None,
        blocking_reason=None,
        next_action="Record this OpenAI image result as Phase 7 slice evidence.",
        artifact_id=artifact_id,
        selected_artifact_id=selected_artifact_id,
        dimensions=dimensions,
        quality_score=round(quality_score, 4),
        verification_contract=OPENAI_IMAGE_READINESS_CONTRACT,
    )


def build_media_readiness(
    *,
    openai_image: RaphaelMediaEvidence | None,
    now: datetime | None = None,
) -> RaphaelMediaReadinessReport:
    created_at = _ensure_utc(now) if now is not None else _utc_now()
    if openai_image is None:
        openai_image = _failed_openai_image(
            evidence_refs=("media-readiness:missing",),
            layer="openai_image_evidence",
            reason="openai_image_evidence_missing",
            next_action="Provide OpenAI image evidence before claiming media readiness.",
        )

    contract_failure = _openai_image_readiness_contract_failure(openai_image)
    openai_ready = openai_image.status == "passed" and contract_failure is None
    openai_blockers = (
        []
        if openai_ready
        else [
            _safe_text(
                openai_image.blocking_reason
                or contract_failure
                or "openai_image_failed"
            )
        ]
    )
    slices: dict[str, dict[str, Any]] = {
        "openai_image": {
            "ready": openai_ready,
            "blocking_reasons": openai_blockers,
            "evidence_refs": (
                [_safe_text(ref) for ref in openai_image.evidence_refs]
                if openai_ready
                else []
            ),
            "provider": "openai",
            "selected_artifact_id": (
                _safe_text(openai_image.selected_artifact_id)
                if openai_ready and openai_image.selected_artifact_id
                else None
            ),
            "dimensions": dict(openai_image.dimensions or {}) if openai_ready else None,
            "quality_score": openai_image.quality_score if openai_ready else None,
            "failure_layer": _safe_optional_text(openai_image.failure_layer),
            "next_action": _safe_text(openai_image.next_action),
        },
        "grok_web_imagine": {
            "ready": False,
            "blocking_reasons": ["grok_web_imagine_live_evidence_missing"],
            "evidence_refs": [],
        },
        "video": {
            "ready": False,
            "blocking_reasons": ["video_live_evidence_missing"],
            "evidence_refs": [],
        },
        "slack_delivery": {
            "ready": False,
            "blocking_reasons": ["slack_delivery_live_evidence_missing"],
            "evidence_refs": [],
        },
        "full_media": {
            "ready": False,
            "blocking_reasons": ["full_media_live_evidence_missing"],
            "evidence_refs": [],
        },
    }

    public_claims = (
        ("OpenAI image slice is ready.",)
        if openai_ready
        else ("OpenAI image slice is not ready.",)
    )
    blocked_claims = (
        "Grok Web Imagine readiness requires separate live evidence.",
        "Video readiness requires separate live evidence.",
        "Slack native delivery readiness requires separate live evidence.",
        "Full media readiness remains blocked.",
    )
    boundary = validate_media_claim_boundary(public_claims + blocked_claims)
    if not boundary.passed:
        slices["openai_image"]["ready"] = False
        slices["openai_image"]["blocking_reasons"] = _dedupe(
            [
                *slices["openai_image"]["blocking_reasons"],
                "media_public_claim_boundary_failed",
            ]
        )
        openai_ready = False

    return RaphaelMediaReadinessReport(
        status="openai_image_ready" if openai_ready else "blocked",
        slices=slices,
        public_claims=public_claims,
        blocked_claims=blocked_claims,
        openai_image=openai_image,
        created_at=created_at,
    )


def validate_media_claim_boundary(
    claims: tuple[str, ...],
) -> RaphaelMediaClaimBoundaryResult:
    violations: list[str] = []
    for name, keywords in _FORBIDDEN_MEDIA_READY_KEYWORDS.items():
        if _has_forbidden_ready_claim(claims, keywords):
            violations.append(f"forbidden_claim:{name}")
    return RaphaelMediaClaimBoundaryResult(
        passed=not violations,
        evidence_refs=tuple(violations or ("media_claim_boundary:clean",)),
        summary=(
            "OpenAI image claim boundary is clean."
            if not violations
            else "Forbidden Grok/video/delivery/full-media readiness claims detected."
        ),
    )


def write_media_readiness_gate(
    report: RaphaelMediaReadinessReport,
    path: str | Path,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_report_to_dict(report), allow_nan=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def render_media_readiness(report: RaphaelMediaReadinessReport) -> str:
    openai_image = report.slices["openai_image"]
    grok = report.slices["grok_web_imagine"]
    video = report.slices["video"]
    slack = report.slices["slack_delivery"]
    full_media = report.slices["full_media"]
    lines = [
        "Raphael Media Slice Readiness",
        f"Overall: {_safe_text(report.status)}",
        f"OpenAI image slice: {'ready' if openai_image.get('ready') else 'blocked'}",
        f"Grok Web Imagine slice: {'ready' if grok.get('ready') else 'not ready'}",
        f"Video slice: {'ready' if video.get('ready') else 'not ready'}",
        f"Slack delivery slice: {'ready' if slack.get('ready') else 'not ready'}",
        f"Full media: {'ready' if full_media.get('ready') else 'blocked'}",
    ]
    blockers = tuple(str(reason) for reason in openai_image.get("blocking_reasons", ()))
    if blockers:
        lines.append(
            "OpenAI image blockers: "
            f"{', '.join(_safe_text(reason) for reason in blockers)}"
        )
    if openai_image.get("evidence_refs"):
        lines.append(
            "OpenAI image evidence: "
            f"{', '.join(_safe_text(ref) for ref in openai_image.get('evidence_refs', ())) or 'none'}"
        )
    if openai_image.get("selected_artifact_id"):
        lines.append(f"Selected artifact: {_safe_text(openai_image['selected_artifact_id'])}")
    if openai_image.get("dimensions"):
        dimensions = openai_image["dimensions"]
        width = dimensions.get("width") if isinstance(dimensions, Mapping) else "unknown"
        height = dimensions.get("height") if isinstance(dimensions, Mapping) else "unknown"
        lines.append(f"Geometry: {_safe_text(width)}x{_safe_text(height)}")
    lines.append("Public claims:")
    lines.extend(f"- {_safe_text(claim)}" for claim in report.public_claims)
    lines.append("Blocked claims:")
    lines.extend(f"- {_safe_text(claim)}" for claim in report.blocked_claims)
    return "\n".join(lines)


def _classify_openai_failure(
    payload: Mapping[str, Any],
    *,
    evidence_refs: tuple[str, ...],
) -> RaphaelMediaEvidence:
    failure_text = _payload_text(payload)
    if _is_setup_failure(payload, failure_text):
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="setup_required",
            reason="openai_image_setup_required",
            next_action="Configure OpenAI image credentials before running the media gate.",
        )

    provider_failure = classify_visual_provider_failure(dict(payload))
    failure_class = str(provider_failure.get("failure_class") or "unknown")
    if failure_class == "quota_exceeded":
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="quota_required",
            reason="openai_image_quota_required",
            next_action="Restore provider quota or run with a provider account that has image capacity.",
        )
    if failure_class in {"provider_unavailable", "rate_limited", "timeout", "empty_response"}:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="provider_health",
            reason="openai_image_provider_health_failed",
            next_action="Re-run after provider/runtime health is restored.",
        )
    if failure_class == "content_moderation":
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="prompt_moderation",
            reason="openai_image_prompt_moderated",
            next_action="Safely reframe the prompt before retrying.",
        )
    if failure_class in {"unsupported_reference", "unsupported_aspect_ratio"}:
        return _failed_openai_image(
            evidence_refs=evidence_refs,
            layer="provider_capability",
            reason=f"openai_image_{failure_class}",
            next_action="Change provider, reference mode, or geometry before retrying.",
        )
    return _failed_openai_image(
        evidence_refs=evidence_refs,
        layer="provider_health",
        reason="openai_image_provider_failure_unknown",
        next_action="Inspect provider/runtime evidence and classify the failure before retrying.",
    )


def _failed_openai_image(
    *,
    evidence_refs: tuple[str, ...],
    layer: str,
    reason: str,
    next_action: str,
    provider: str = "openai",
    capability: str = "image",
    artifact_id: str | None = None,
    selected_artifact_id: str | None = None,
    dimensions: Mapping[str, int] | None = None,
    quality_score: float | None = None,
) -> RaphaelMediaEvidence:
    return RaphaelMediaEvidence(
        status="failed",
        provider=_safe_text(provider),
        capability=_safe_text(capability),
        evidence_refs=tuple(_safe_text(ref) for ref in evidence_refs if _safe_text(ref)),
        failure_layer=layer,
        blocking_reason=reason,
        next_action=_safe_text(next_action),
        artifact_id=_safe_text(artifact_id) if artifact_id else None,
        selected_artifact_id=_safe_text(selected_artifact_id) if selected_artifact_id else None,
        dimensions=dimensions,
        quality_score=quality_score,
    )


def _openai_image_readiness_contract_failure(
    evidence: RaphaelMediaEvidence,
) -> str | None:
    if evidence.status != "passed":
        return None
    if evidence.verification_contract != OPENAI_IMAGE_READINESS_CONTRACT:
        return "openai_image_contract_unverified"
    if evidence.provider != "openai" or evidence.capability != "image":
        return "openai_image_contract_wrong_provider_or_capability"
    if len(tuple(ref for ref in evidence.evidence_refs if _safe_text(ref))) < len(
        REQUIRED_OPENAI_IMAGE_EVIDENCE_REF_KEYS
    ):
        return "openai_image_evidence_refs_incomplete"
    if not _safe_text(evidence.selected_artifact_id or ""):
        return "openai_image_selected_artifact_missing"
    if _safe_dimensions(evidence.dimensions) is None:
        return "openai_image_dimensions_missing"
    if _float(evidence.quality_score) < MIN_OPENAI_IMAGE_QUALITY_SCORE:
        return "openai_image_quality_below_threshold"
    return None


def _required_evidence_refs(payload: Mapping[str, Any]) -> tuple[tuple[str, ...], str | None]:
    raw_refs = payload.get("evidence_refs")
    if not isinstance(raw_refs, Mapping):
        return (), "openai_image_evidence_refs_missing"

    refs: list[str] = []
    missing: list[str] = []
    for key in REQUIRED_OPENAI_IMAGE_EVIDENCE_REF_KEYS:
        value = _safe_text(raw_refs.get(key) or "")
        if not value or value.endswith(":unknown") or value == "unknown":
            missing.append(key)
            continue
        refs.append(value)
    if missing:
        if len(missing) == len(REQUIRED_OPENAI_IMAGE_EVIDENCE_REF_KEYS):
            return (), "openai_image_evidence_refs_missing"
        return tuple(refs), "openai_image_evidence_refs_incomplete"
    return tuple(refs), None


def _optional_evidence_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    refs, error = _required_evidence_refs(payload)
    if error is None:
        return refs
    legacy = _safe_text(payload.get("evidence_ref") or "")
    return (legacy,) if legacy else ("openai-image:evidence-unavailable",)


def _is_setup_failure(payload: Mapping[str, Any], failure_text: str) -> bool:
    status_code = _status_code(payload)
    return bool(
        status_code in {401, 403}
        or _contains(
            failure_text,
            "auth_required",
            "api_key",
            "api key",
            "missing key",
            "invalid_api_key",
            "invalid api key",
            "unauthorized",
            "forbidden",
            "permission denied",
            "permission_required",
            "account setup",
        )
    )


def _status_code(payload: Mapping[str, Any]) -> int | None:
    try:
        return int(payload.get("status_code"))
    except (TypeError, ValueError):
        return None


def _quality_result(value: Any) -> tuple[float, bool]:
    if not isinstance(value, Mapping):
        return 0.0, False
    score = _float(value.get("score"))
    return score, value.get("passed") is True


def _safe_dimensions(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        width = int(value.get("width"))
        height = int(value.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _report_to_dict(report: RaphaelMediaReadinessReport) -> dict[str, Any]:
    return {
        "schema_version": "raphael.media_readiness.v1",
        "status": _safe_text(report.status),
        "created_at": report.created_at.isoformat(),
        "slices": {
            _safe_text(key): _safe_json_value(value)
            for key, value in report.slices.items()
        },
        "public_claims": [_safe_text(claim) for claim in report.public_claims],
        "blocked_claims": [_safe_text(claim) for claim in report.blocked_claims],
        "openai_image": (
            None
            if report.openai_image is None
            else {
                "status": _safe_text(report.openai_image.status),
                "provider": _safe_text(report.openai_image.provider),
                "capability": _safe_text(report.openai_image.capability),
                "evidence_refs": [_safe_text(ref) for ref in report.openai_image.evidence_refs],
                "failure_layer": _safe_optional_text(report.openai_image.failure_layer),
                "blocking_reason": _safe_optional_text(report.openai_image.blocking_reason),
                "next_action": _safe_text(report.openai_image.next_action),
                "artifact_id": _safe_optional_text(report.openai_image.artifact_id),
                "selected_artifact_id": _safe_optional_text(report.openai_image.selected_artifact_id),
                "dimensions": (
                    None
                    if report.openai_image.dimensions is None
                    else _safe_json_value(dict(report.openai_image.dimensions))
                ),
                "quality_score": _safe_json_value(report.openai_image.quality_score),
                "verification_contract": _safe_optional_text(
                    report.openai_image.verification_contract
                ),
            }
        ),
    }


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {_safe_text(key): _safe_json_value(item) for key, item in value.items()}
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, tuple):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    return value


def _has_forbidden_ready_claim(claims: tuple[str, ...], keywords: tuple[str, ...]) -> bool:
    for sentence in _claim_sentences(claims):
        if not _has_ready_intent(sentence):
            continue
        if not any(keyword in sentence for keyword in keywords):
            continue
        if _negates_ready_claim(sentence):
            continue
        return True
    return False


def _claim_sentences(claims: tuple[str, ...]) -> tuple[str, ...]:
    joined = "\n".join(str(claim) for claim in claims)
    return tuple(
        sentence.strip().lower()
        for sentence in re.split(r"[\n.;!?。！？]+", joined)
        if sentence.strip()
    )


def _has_ready_intent(sentence: str) -> bool:
    return bool(
        "ready" in sentence
        or "readiness" in sentence
        or "certified" in sentence
        or "approved" in sentence
        or "passed" in sentence
        or "已就緒" in sentence
        or "就緒" in sentence
        or "可用" in sentence
        or "可以上線" in sentence
    )


def _negates_ready_claim(sentence: str) -> bool:
    return bool(
        "not ready" in sentence
        or "not certified" in sentence
        or "requires separate" in sentence
        or "require separate" in sentence
        or "remains blocked" in sentence
        or "blocked" in sentence
        or "不能" in sentence
        or "不可" in sentence
        or "不得" in sentence
        or "不證明" in sentence
        or "尚未" in sentence
        or re.search(r"\bnot\b(?:\s+\w+){0,4}\s+\bready\b", sentence)
    )


def _payload_text(payload: Mapping[str, Any]) -> str:
    return " ".join(_flatten_text(value) for value in payload.values()).lower()


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _safe_text(value: Any) -> str:
    text = str(value)
    for pattern, replacement in _PRIVATE_TEXT_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text.strip()


def _safe_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _safe_text(value)


def _contains(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "RaphaelMediaClaimBoundaryResult",
    "RaphaelMediaEvidence",
    "RaphaelMediaReadinessReport",
    "build_media_readiness",
    "classify_openai_image_evidence",
    "render_media_readiness",
    "validate_media_claim_boundary",
    "write_media_readiness_gate",
]

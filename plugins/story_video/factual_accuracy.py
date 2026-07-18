from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse

from .editorial_quality import parse_script_segments


FACTUAL_EVIDENCE_SCHEMA = "story_video_factual_evidence_v1"
FACTUAL_PRODUCTION_TYPES = frozenset(
    {
        "science_explainer",
        "science_documentary",
        "documentary",
        "natural_history_documentary",
        "history",
        "historical_documentary",
        "biography",
        "educational",
        "educational_explainer",
    }
)
FACTUAL_SOURCE_FIELDS = (
    "source_id",
    "title",
    "publisher",
    "url",
    "source_type",
    "accessed_at",
)
FACTUAL_CLAIM_FIELDS = (
    "claim_id",
    "segment_id",
    "quote",
    "importance",
    "confidence",
    "source_ids",
    "verification_status",
    "verification_note",
)
NONFACTUAL_SEGMENT_FIELDS = ("segment_id", "reason")

_SOURCE_TYPES = frozenset(
    {"primary", "official", "peer_reviewed", "authoritative_reference"}
)
_AUTHORITATIVE_SOURCE_TYPES = frozenset({"primary", "official", "peer_reviewed"})
_IMPORTANCE_LEVELS = frozenset({"central", "supporting"})
_CONFIDENCE_LEVELS = frozenset({"established", "supported_inference", "uncertain"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    values = [_text(item) for item in value]
    if any(not item for item in values):
        return None
    return values


def factual_accuracy_required(ledger: dict[str, Any]) -> bool:
    return _text(ledger.get("production_type")).lower() in FACTUAL_PRODUCTION_TYPES


def _valid_https_url(value: Any) -> bool:
    parsed = urlparse(_text(value))
    return parsed.scheme == "https" and bool(parsed.hostname)


def _valid_date(value: Any) -> bool:
    try:
        date.fromisoformat(_text(value))
    except ValueError:
        return False
    return True


def validate_factual_evidence(
    evidence: dict[str, Any],
    *,
    ledger: dict[str, Any],
    script_text: str,
    fact_checker: dict[str, Any] | None,
) -> tuple[str, ...]:
    if not factual_accuracy_required(ledger):
        return ()

    violations: list[str] = []
    if _text(evidence.get("schema")) != FACTUAL_EVIDENCE_SCHEMA:
        violations.append("factual_evidence schema is invalid")
    if _text(evidence.get("status")).upper() != "PASS":
        violations.append("factual_evidence status is not PASS")

    sources_value = evidence.get("sources")
    sources = sources_value if isinstance(sources_value, list) else []
    if not isinstance(sources_value, list) or not sources:
        violations.append("factual_evidence sources are missing")
    source_by_id: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            violations.append(f"factual_evidence source[{index}] is not an object")
            continue
        source_id = _text(source.get("source_id"))
        for field_name in FACTUAL_SOURCE_FIELDS:
            if not _text(source.get(field_name)):
                violations.append(
                    f"factual_evidence source {source_id or index} {field_name} is missing"
                )
        if source_id in source_by_id:
            violations.append(f"factual_evidence duplicate source_id: {source_id}")
        elif source_id:
            source_by_id[source_id] = source
        source_type = _text(source.get("source_type")).lower()
        if source_type and source_type not in _SOURCE_TYPES:
            violations.append(
                f"factual_evidence source {source_id or index} source_type is invalid"
            )
        if _text(source.get("url")) and not _valid_https_url(source.get("url")):
            violations.append(f"factual_evidence source {source_id or index} url is invalid")
        if _text(source.get("accessed_at")) and not _valid_date(source.get("accessed_at")):
            violations.append(
                f"factual_evidence source {source_id or index} accessed_at is invalid"
            )

    script_segments = parse_script_segments(script_text)
    claims_value = evidence.get("claims")
    claims = claims_value if isinstance(claims_value, list) else []
    if not isinstance(claims_value, list) or not claims:
        violations.append("factual_evidence claims are missing")
    seen_claim_ids: set[str] = set()
    claimed_segments: set[str] = set()
    referenced_source_ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            violations.append(f"factual_evidence claim[{index}] is not an object")
            continue
        claim_id = _text(claim.get("claim_id"))
        for field_name in FACTUAL_CLAIM_FIELDS:
            value = claim.get(field_name)
            missing = not value if field_name == "source_ids" else not _text(value)
            if missing:
                violations.append(
                    f"factual_evidence claim {claim_id or index} {field_name} is missing"
                )
        if claim_id in seen_claim_ids:
            violations.append(f"factual_evidence duplicate claim_id: {claim_id}")
        elif claim_id:
            seen_claim_ids.add(claim_id)

        segment_id = _text(claim.get("segment_id"))
        quote = _text(claim.get("quote"))
        if segment_id not in script_segments:
            violations.append(
                f"factual_evidence claim {claim_id or index} segment is unknown: {segment_id}"
            )
        else:
            claimed_segments.add(segment_id)
            if quote and quote not in script_segments[segment_id]:
                violations.append(
                    f"factual_evidence claim {claim_id or index} quote is not exact in {segment_id}"
                )

        importance = _text(claim.get("importance")).lower()
        confidence = _text(claim.get("confidence")).lower()
        if importance and importance not in _IMPORTANCE_LEVELS:
            violations.append(
                f"factual_evidence claim {claim_id or index} importance is invalid"
            )
        if confidence and confidence not in _CONFIDENCE_LEVELS:
            violations.append(
                f"factual_evidence claim {claim_id or index} confidence is invalid"
            )
        if _text(claim.get("verification_status")).lower() != "verified":
            violations.append(
                f"factual_evidence claim {claim_id or index} is not verified"
            )

        source_ids = _string_list(claim.get("source_ids"))
        if source_ids is None:
            source_ids = []
            violations.append(
                f"factual_evidence claim {claim_id or index} source_ids are invalid"
            )
        for source_id in source_ids:
            referenced_source_ids.add(source_id)
            if source_id not in source_by_id:
                violations.append(
                    f"factual_evidence claim {claim_id or index} references unknown source: {source_id}"
                )
        if importance == "central" and source_ids:
            known_sources = [source_by_id[sid] for sid in source_ids if sid in source_by_id]
            has_authoritative = any(
                _text(source.get("source_type")).lower() in _AUTHORITATIVE_SOURCE_TYPES
                for source in known_sources
            )
            domains = {
                urlparse(_text(source.get("url"))).hostname
                for source in known_sources
                if _valid_https_url(source.get("url"))
            }
            if not has_authoritative and len(domains) < 2:
                violations.append(
                    f"factual_evidence central claim {claim_id or index} lacks authoritative or corroborated support"
                )

    nonfactual_value = evidence.get("nonfactual_segments")
    nonfactual_rows = nonfactual_value if isinstance(nonfactual_value, list) else []
    if not isinstance(nonfactual_value, list):
        violations.append("factual_evidence nonfactual_segments are not a list")
    nonfactual_segments: set[str] = set()
    for index, row in enumerate(nonfactual_rows):
        if not isinstance(row, dict):
            violations.append(
                f"factual_evidence nonfactual_segment[{index}] is not an object"
            )
            continue
        segment_id = _text(row.get("segment_id"))
        for field_name in NONFACTUAL_SEGMENT_FIELDS:
            if not _text(row.get(field_name)):
                violations.append(
                    f"factual_evidence nonfactual_segment {segment_id or index} {field_name} is missing"
                )
        if segment_id not in script_segments:
            violations.append(
                f"factual_evidence nonfactual segment is unknown: {segment_id}"
            )
        if segment_id in nonfactual_segments:
            violations.append(f"factual_evidence duplicate nonfactual segment: {segment_id}")
        elif segment_id:
            nonfactual_segments.add(segment_id)

    for segment_id in sorted(claimed_segments & nonfactual_segments):
        violations.append(
            f"factual_evidence segment {segment_id} is both claimed and nonfactual"
        )
    for segment_id in script_segments:
        if segment_id not in claimed_segments and segment_id not in nonfactual_segments:
            violations.append(f"factual_evidence segment {segment_id} is uncovered")

    unused_source_ids = set(source_by_id) - referenced_source_ids
    for source_id in sorted(unused_source_ids):
        violations.append(f"factual_evidence source is unused: {source_id}")

    if not isinstance(fact_checker, dict):
        violations.append("script_review_report fact_checker is missing")
    else:
        verified_claim_ids = _string_list(fact_checker.get("verified_claim_ids"))
        evidence_source_ids = _string_list(fact_checker.get("evidence_source_ids"))
        if verified_claim_ids is None or set(verified_claim_ids) != seen_claim_ids:
            violations.append("script_review_report fact_checker verified_claim_ids mismatch")
        if not evidence_source_ids:
            violations.append(
                "script_review_report fact_checker evidence_source_ids are missing"
            )
        if evidence_source_ids is None or set(evidence_source_ids) != referenced_source_ids:
            violations.append("script_review_report fact_checker evidence_source_ids mismatch")
    return tuple(violations)

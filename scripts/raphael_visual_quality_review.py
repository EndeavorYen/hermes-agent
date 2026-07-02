from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COMMAND_NAME = "scripts/raphael_visual_quality_review.py"
KIND = "raphael_visual_quality_review"
PRODUCER = "hermes-visual-quality-review"
REQUIRED_DIMENSIONS = (
    "composition",
    "prompt_adherence",
    "geometry",
    "subject_quality",
)
ACCEPTED_VERDICTS = {
    "pass",
    "passed",
    "accept",
    "accepted",
    "approved",
    "ok",
}
BLOCKED_REVIEWERS = {
    "",
    "self",
    "self_review",
    "provider",
    "live_harness",
    "grok_web_imagine_live",
    "grok_web_imagine",
    "openai",
    "openai_codex",
    "gpt_image",
    "gpt_image_2_low",
    "gpt_image_2_medium",
    "gpt_image_2_high",
    "image2",
}
DEFAULT_RESIDUAL_RISK = (
    "human or vision-backed reviewer remains responsible for subjective quality."
)
DEFAULT_EVIDENCE = (
    "artifact path reviewed",
    "required visual quality dimensions passed",
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_visual_quality_review_report(
        artifact=args.artifact,
        reviewer=args.reviewer,
        verdict=args.verdict,
        dimensions=args.dimension,
        evidence=args.evidence,
        residual_risk=args.residual_risk,
        review_source_type=args.review_source_type,
        review_model_provider=args.review_model_provider,
        review_model=args.review_model,
        review_evidence_digest=args.review_evidence_digest,
        review_transcript_report=args.review_transcript_report,
        run_id=args.run_id,
        argv=list(argv or sys.argv[1:]),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.get("success") is True else 2


def build_visual_quality_review_report(
    *,
    artifact: str | Path,
    reviewer: str,
    verdict: str,
    dimensions: list[str],
    evidence: list[str],
    residual_risk: str,
    review_source_type: str = "",
    review_model_provider: str = "",
    review_model: str = "",
    review_evidence_digest: str = "",
    review_transcript_report: str | Path | None = None,
    run_id: str | None = None,
    argv: list[str] | None = None,
) -> dict[str, Any]:
    generated_at = _utc_now_text()
    artifact_path = Path(artifact).expanduser().resolve()
    artifact_metadata = _artifact_metadata(artifact_path)
    parsed_dimensions, malformed_dimensions = _parse_dimensions(dimensions)
    missing_dimensions = [
        key for key in REQUIRED_DIMENSIONS if key not in parsed_dimensions
    ]
    failing_dimensions = [
        key
        for key in REQUIRED_DIMENSIONS
        if key in parsed_dimensions and not _dimension_passed(parsed_dimensions[key])
    ]
    failure_classes: list[str] = []
    reviewer_independent = _reviewer_is_independent(reviewer)
    evidence_items = _evidence_items(evidence, True)
    transcript = _load_model_review_transcript(review_transcript_report)
    transcript_payload = transcript["payload"]
    transcript_path = transcript["path"]
    transcript_digest = transcript["digest"]
    transcript_valid = _model_review_transcript_valid(
        transcript_payload,
        artifact_path=artifact_path,
        artifact_metadata=artifact_metadata,
        dimensions=parsed_dimensions,
        verdict=verdict,
    )
    review_digest = str(review_evidence_digest or "").strip() or _review_digest(
        artifact_sha256=artifact_metadata["sha256"],
        dimensions=parsed_dimensions,
        evidence=evidence_items,
        review_model_provider=review_model_provider,
        review_model=review_model,
    )
    normalized_review_source = _review_source_key(review_source_type)
    transcript_provider = (
        str(transcript_payload.get("review_model_provider") or "").strip()
        if isinstance(transcript_payload, dict)
        else ""
    )
    transcript_model = (
        str(transcript_payload.get("review_model") or "").strip()
        if isinstance(transcript_payload, dict)
        else ""
    )
    transcript_response_id = (
        str(transcript_payload.get("response_id") or "").strip()
        if isinstance(transcript_payload, dict)
        else ""
    )
    effective_model_provider = str(review_model_provider or transcript_provider).strip()
    effective_model = str(review_model or transcript_model).strip()
    review_provenance_verified = _review_provenance_verified(
        source_type=normalized_review_source,
        review_model_provider=effective_model_provider,
        review_model=effective_model,
        review_evidence_digest=review_digest,
        reviewer_independent=reviewer_independent,
        transcript_valid=transcript_valid,
        response_id=transcript_response_id,
    )
    if not artifact_path.is_file():
        failure_classes.append("artifact_missing")
    if not reviewer_independent:
        failure_classes.append("reviewer_not_independent")
    if _verdict_key(verdict) not in ACCEPTED_VERDICTS:
        failure_classes.append("verdict_not_accepted")
    if missing_dimensions or failing_dimensions or malformed_dimensions:
        failure_classes.append("missing_or_failing_dimensions")
    if not review_provenance_verified:
        failure_classes.append("review_provenance_missing")

    success = not failure_classes
    return {
        "schema_version": 1,
        "kind": KIND,
        "generated_at": generated_at,
        "command": COMMAND_NAME,
        "arguments": list(argv or []),
        "run_id": run_id or _default_run_id(generated_at),
        "producer": PRODUCER,
        "reviewer": str(reviewer or "").strip(),
        "reviewer_independent": reviewer_independent,
        "artifact_path": str(artifact_path),
        "artifact_exists": artifact_path.is_file(),
        "artifact_sha256": artifact_metadata["sha256"],
        "artifact_size_bytes": artifact_metadata["size_bytes"],
        "artifact_mtime": artifact_metadata["mtime"],
        "artifact_identity_verified": artifact_metadata["identity_verified"],
        "review_source_type": normalized_review_source,
        "review_model_provider": effective_model_provider,
        "review_model": effective_model,
        "review_evidence_digest": review_digest,
        "review_response_id": transcript_response_id,
        "review_transcript_report_path": str(transcript_path) if transcript_path else "",
        "review_transcript_digest": transcript_digest,
        "review_provenance_verified": review_provenance_verified,
        "artifact_quality_verdict": _verdict_key(verdict) if success else "blocked",
        "dimensions": parsed_dimensions,
        "dimensions_verified": success,
        "missing_dimensions": missing_dimensions,
        "failing_dimensions": failing_dimensions,
        "malformed_dimensions": malformed_dimensions,
        "success": success,
        "status": "pass" if success else "blocked",
        "failure_classes": failure_classes,
        "evidence": _evidence_items(evidence, success),
        "residual_risk": str(residual_risk or DEFAULT_RESIDUAL_RISK).strip()
        or DEFAULT_RESIDUAL_RISK,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write an independent Raphael visual quality review source report."
    )
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--dimension", action="append", default=[])
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--review-source-type", default="")
    parser.add_argument("--review-model-provider", default="")
    parser.add_argument("--review-model", default="")
    parser.add_argument("--review-evidence-digest", default="")
    parser.add_argument("--review-transcript-report", default="")
    parser.add_argument("--residual-risk", default=DEFAULT_RESIDUAL_RISK)
    parser.add_argument("--run-id")
    parser.add_argument("--output")
    return parser


def _load_model_review_transcript(
    path_value: str | Path | None,
) -> dict[str, Any]:
    path_text = str(path_value or "").strip()
    if not path_text:
        return {"payload": {}, "path": None, "digest": ""}
    path = Path(path_text).expanduser().resolve()
    try:
        text = path.read_text(encoding="utf-8")
        parsed = json.loads(text)
    except Exception:
        return {"payload": {}, "path": path, "digest": ""}
    return {
        "payload": parsed if isinstance(parsed, dict) else {},
        "path": path,
        "digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _model_review_transcript_valid(
    transcript: dict[str, Any],
    *,
    artifact_path: Path,
    artifact_metadata: dict[str, Any],
    dimensions: dict[str, Any],
    verdict: str,
) -> bool:
    if not isinstance(transcript, dict):
        return False
    if transcript.get("schema_version") != 1:
        return False
    if str(transcript.get("kind") or "").strip() != "raphael_visual_quality_model_review":
        return False
    if str(transcript.get("producer") or "").strip() != "openai-gpt-vision-review":
        return False
    response_id = str(transcript.get("response_id") or "").strip()
    if not response_id.startswith(
        ("resp_", "openai-response:", "codex-openai-vision-review:")
    ):
        return False
    provider = str(transcript.get("review_model_provider") or "").strip().lower()
    if provider.replace("_", "-") not in {"openai", "openai-codex"}:
        return False
    if not str(transcript.get("review_model") or "").strip():
        return False
    if str(transcript.get("artifact_path") or "").strip() != str(artifact_path):
        return False
    if str(transcript.get("artifact_sha256") or "").strip() != artifact_metadata["sha256"]:
        return False
    try:
        transcript_size = int(transcript.get("artifact_size_bytes"))
    except (TypeError, ValueError):
        return False
    if transcript_size != artifact_metadata["size_bytes"]:
        return False
    if _verdict_key(transcript.get("artifact_quality_verdict")) != _verdict_key(verdict):
        return False
    if not _transcript_dimensions_match(transcript.get("dimensions"), dimensions):
        return False
    evidence = transcript.get("evidence")
    return isinstance(evidence, list) and any(str(item or "").strip() for item in evidence)


def _transcript_dimensions_match(left: Any, right: dict[str, Any]) -> bool:
    if not isinstance(left, dict):
        return False
    for key in REQUIRED_DIMENSIONS:
        if not _dimension_passed(left.get(key)) or not _dimension_passed(right.get(key)):
            return False
    return True


def _review_digest(
    *,
    artifact_sha256: str,
    dimensions: dict[str, Any],
    evidence: list[str],
    review_model_provider: str,
    review_model: str,
) -> str:
    payload = json.dumps(
        {
            "artifact_sha256": artifact_sha256,
            "dimensions": dimensions,
            "evidence": evidence,
            "review_model_provider": str(review_model_provider or "").strip(),
            "review_model": str(review_model or "").strip(),
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _review_source_key(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _review_provenance_verified(
    *,
    source_type: str,
    review_model_provider: str,
    review_model: str,
    review_evidence_digest: str,
    reviewer_independent: bool,
    transcript_valid: bool,
    response_id: str,
) -> bool:
    if not review_evidence_digest:
        return False
    if source_type == "vision_model":
        return (
            transcript_valid
            and str(response_id or "").startswith(
                ("resp_", "openai-response:", "codex-openai-vision-review:")
            )
            and str(review_model_provider or "").strip().lower().replace("_", "-")
            in {"openai", "openai-codex"}
            and bool(str(review_model or "").strip())
        )
    if source_type == "human_independent":
        return reviewer_independent
    return False


def _artifact_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "sha256": "",
            "size_bytes": 0,
            "mtime": 0.0,
            "identity_verified": False,
        }
    try:
        data = path.read_bytes()
        stat = path.stat()
    except OSError:
        return {
            "sha256": "",
            "size_bytes": 0,
            "mtime": 0.0,
            "identity_verified": False,
        }
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mtime": float(stat.st_mtime),
        "identity_verified": True,
    }


def _parse_dimensions(items: list[str]) -> tuple[dict[str, Any], list[str]]:
    dimensions: dict[str, Any] = {}
    malformed: list[str] = []
    for item in items:
        key, separator, value = str(item or "").partition("=")
        key = key.strip()
        if not separator or not key:
            malformed.append(str(item or ""))
            continue
        parsed = _coerce_dimension_value(value.strip())
        dimensions[key] = parsed
        if isinstance(parsed, float) and not math.isfinite(parsed):
            dimensions[key] = value.strip()
            malformed.append(key)
    return dimensions, malformed


def _coerce_dimension_value(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return float(value)
    except ValueError:
        return value


def _dimension_passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        score = float(value)
        return math.isfinite(score) and score >= 0.75
    return str(value or "").strip().lower() in ACCEPTED_VERDICTS


def _reviewer_is_independent(value: str) -> bool:
    key = _reviewer_key(value)
    if key in BLOCKED_REVIEWERS:
        return False
    return not any(
        _reviewer_key_contains_phrase(key, phrase)
        for phrase in BLOCKED_REVIEWERS
        if phrase
    )


def _reviewer_key_contains_phrase(key: str, phrase: str) -> bool:
    return (
        key == phrase
        or key.startswith(f"{phrase}_")
        or key.endswith(f"_{phrase}")
        or f"_{phrase}_" in key
    )


def _reviewer_key(value: str) -> str:
    text = str(value or "").strip().lower()
    normalized = "".join(character if character.isalnum() else "_" for character in text)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _verdict_key(value: str) -> str:
    return str(value or "").strip().lower()


def _evidence_items(items: list[str], success: bool) -> list[str]:
    evidence = [str(item).strip() for item in items if str(item).strip()]
    if evidence:
        return evidence
    if success:
        return list(DEFAULT_EVIDENCE)
    return ["review blocked before media release evidence could be trusted"]


def _default_run_id(generated_at: str) -> str:
    suffix = generated_at.replace(":", "").replace("-", "").replace(".", "")
    return f"raphael-visual-quality-review-{suffix}"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

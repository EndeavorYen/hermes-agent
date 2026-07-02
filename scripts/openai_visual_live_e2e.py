from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


DEFAULT_PROMPT = (
    "Create a polished square product photograph of a matte black fountain pen "
    "on clean white paper, soft window light, minimal professional composition."
)
REQUIRED_OPT_INS = (
    ("HERMES_VISUAL_LIVE_E2E", "HERMES_VISUAL_LIVE_E2E=1"),
    ("HERMES_OPENAI_VISUAL_LIVE_E2E", "HERMES_OPENAI_VISUAL_LIVE_E2E=1"),
)
ACCEPTED_QUALITY_VERDICTS = {
    "pass",
    "passed",
    "accept",
    "accepted",
    "approved",
}
BLOCKED_QUALITY_REVIEWERS = {
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
REQUIRED_QUALITY_DIMENSIONS = (
    "composition",
    "prompt_adherence",
    "geometry",
    "subject_quality",
)


def build_openai_visual_live_e2e_report(
    *,
    work_dir: str | Path | None = None,
    prompt: str = DEFAULT_PROMPT,
    aspect_ratio: str = "square",
    generation_fn: Callable[[dict[str, Any]], Any] | None = None,
    env: dict[str, str] | None = None,
    quality_review_report: str | Path | None = None,
) -> dict[str, Any]:
    generated_at = _utc_now_text()
    run_id = _default_run_id(generated_at)
    env_map = env if env is not None else os.environ
    missing_opt_in = _missing_opt_ins(env_map)
    if missing_opt_in:
        return _with_release_provenance({
            "run_id": run_id,
            "generated_at": generated_at,
            "success": False,
            "status": "disabled",
            "provider_mode": "openai-gpt-image-live",
            "requires_operator_setup": True,
            "missing_opt_in": missing_opt_in,
            "request": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "operation": "generate",
            },
            "self_review": {
                "safe_by_default": True,
                "provider_called": False,
                "next_action": "Set opt-in flags before spending OpenAI visual quota.",
            },
        })

    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)

    args = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "provider": "openai-codex",
        "_disable_visual_tracking": True,
    }
    raw_result = (
        generation_fn(args)
        if generation_fn is not None
        else _generate_with_openai_provider(args)
    )
    payload = _coerce_json_object(raw_result)
    if payload is None:
        return _with_release_provenance(_failure_report(
            run_id=run_id,
            generated_at=generated_at,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            status="invalid_provider_response",
            error="OpenAI visual provider did not return a JSON object",
            error_type="invalid_provider_response",
            provider_called=True,
        ))

    if payload.get("success") is not True:
        failure_class = str(
            payload.get("error_type") or payload.get("status") or "failed"
        ).strip()
        error = str(payload.get("error") or "").strip()
        requires_setup = any(
            marker in f"{failure_class} {error}".lower()
            for marker in ("auth", "credential", "quota", "subscription")
        )
        return _with_release_provenance({
            **_failure_report(
                run_id=run_id,
                generated_at=generated_at,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                status="setup_required" if requires_setup else "failed",
                error=error,
                error_type=failure_class,
                provider_called=True,
            ),
            "requires_operator_setup": requires_setup,
            "provider": {
                "name": str(payload.get("provider") or "openai-codex"),
                "model": str(payload.get("model") or ""),
            },
            "provider_result": _safe_provider_result(payload),
        })

    artifact_path = str(payload.get("image") or payload.get("artifact_path") or "").strip()
    artifact_exists = bool(artifact_path and Path(artifact_path).is_file())
    result_surface_id = _openai_result_surface_id(payload)
    result_surface_verified = bool(result_surface_id)
    success = artifact_exists and result_surface_verified
    status = "completed" if success else (
        "result_surface_unverified" if artifact_exists else "artifact_missing"
    )
    report: dict[str, Any] = {
        "run_id": run_id,
        "generated_at": generated_at,
        "success": success,
        "status": status,
        "provider_mode": "openai-gpt-image-live",
        "requires_operator_setup": False,
        "provider": {
            "name": str(payload.get("provider") or "openai-codex"),
            "model": str(payload.get("model") or ""),
        },
        "artifact": {
            "path": artifact_path,
            "exists": artifact_exists,
            "source": "openai_response",
            "durability": "provider_response_artifact",
            "history_verified": result_surface_verified,
        },
        "result_surface_id": result_surface_id,
        "request": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "operation": "generate",
        },
        "provider_result": _safe_provider_result(payload),
        "self_review": {
            "provider_called": True,
            "artifact_verified": artifact_exists,
            "durable_history_verified": result_surface_verified,
            "artifact_quality_verdict": "unreviewed",
            "next_action": "Attach independent quality review before media release gate."
            if success
            else (
                "Fix OpenAI visual provider result id before media release gate."
                if artifact_exists
                else "Fix OpenAI visual artifact output before media release gate."
            ),
        },
    }
    if quality_review_report is not None:
        return attach_quality_review_report(report, quality_review_report)
    return _with_release_provenance(report)


def attach_quality_review_report(
    report: dict[str, Any],
    quality_review_report: str | Path,
) -> dict[str, Any]:
    path = Path(quality_review_report).expanduser().resolve()
    try:
        quality = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _with_release_provenance({
            **report,
            "success": False,
            "status": "quality_review_attachment_error",
            "quality_review": {
                "source_report_path": str(path),
                "attachment_error": exc.__class__.__name__,
            },
        })
    if not isinstance(quality, dict):
        return _with_release_provenance({
            **report,
            "success": False,
            "status": "quality_review_attachment_error",
            "quality_review": {
                "source_report_path": str(path),
                "attachment_error": "not_json_object",
            },
        })
    report = dict(report)
    report["quality_review"] = {
        "schema_version": quality.get("schema_version"),
        "kind": str(quality.get("kind") or "").strip(),
        "producer": str(quality.get("producer") or "").strip(),
        "command": str(quality.get("command") or "").strip(),
        "source_report_path": str(path),
        "run_id": str(quality.get("run_id") or "").strip(),
        "reviewer": str(
            quality.get("reviewer")
            or quality.get("reviewer_role")
            or quality.get("producer")
            or ""
        ).strip(),
        "artifact_path": str(quality.get("artifact_path") or "").strip(),
        "artifact_sha256": str(quality.get("artifact_sha256") or "").strip(),
        "artifact_size_bytes": _optional_int(quality.get("artifact_size_bytes")),
        "artifact_mtime": _optional_float(quality.get("artifact_mtime")),
        "artifact_identity_verified": quality.get("artifact_identity_verified") is True,
        "review_source_type": str(quality.get("review_source_type") or "").strip(),
        "review_model_provider": str(
            quality.get("review_model_provider") or ""
        ).strip(),
        "review_model": str(quality.get("review_model") or "").strip(),
        "review_evidence_digest": str(
            quality.get("review_evidence_digest") or ""
        ).strip(),
        "review_response_id": str(quality.get("review_response_id") or "").strip(),
        "review_transcript_report_path": str(
            quality.get("review_transcript_report_path") or ""
        ).strip(),
        "review_transcript_digest": str(
            quality.get("review_transcript_digest") or ""
        ).strip(),
        "review_provenance_verified": (
            quality.get("review_provenance_verified") is True
        ),
        "artifact_quality_verdict": str(
            quality.get("artifact_quality_verdict")
            or quality.get("quality_verdict")
            or quality.get("verdict")
            or ""
        ).strip(),
        "dimensions": quality.get("dimensions") if isinstance(quality.get("dimensions"), dict) else {},
        "dimensions_verified": _quality_dimensions_verified(quality.get("dimensions")),
    }
    attachment_failure = _quality_review_attachment_failure(report)
    if attachment_failure:
        status, error = attachment_failure
        self_review = (
            dict(report.get("self_review"))
            if isinstance(report.get("self_review"), dict)
            else {}
        )
        self_review.update(
            {
                "artifact_quality_verdict": report["quality_review"].get(
                    "artifact_quality_verdict",
                    "",
                ),
                "next_action": (
                    "Attach a passing independent quality review for the selected "
                    "OpenAI visual artifact before media release gate."
                ),
            }
        )
        report.update(
            {
                "success": False,
                "status": status,
                "failure_class": status,
                "error": error,
                "self_review": self_review,
            }
        )
    else:
        self_review = (
            dict(report.get("self_review"))
            if isinstance(report.get("self_review"), dict)
            else {}
        )
        self_review.update(
            {
                "artifact_quality_verdict": report["quality_review"].get(
                    "artifact_quality_verdict",
                    "",
                ),
                "next_action": (
                    "Submit the reviewed OpenAI visual live E2E report to the "
                    "media release gate."
                ),
            }
        )
        report["self_review"] = self_review
    return _with_release_provenance(report)


def _quality_review_attachment_failure(report: dict[str, Any]) -> tuple[str, str] | None:
    if report.get("success") is not True:
        return None
    review = report.get("quality_review")
    if not isinstance(review, dict):
        return None
    artifact = report.get("artifact") if isinstance(report.get("artifact"), dict) else {}
    artifact_path = str(
        artifact.get("path")
        or report.get("artifact_path")
        or report.get("selected_artifact_id")
        or ""
    ).strip()
    review_artifact_path = str(review.get("artifact_path") or "").strip()
    if artifact_path and review_artifact_path and artifact_path != review_artifact_path:
        return (
            "quality_review_artifact_mismatch",
            "Quality review artifact does not match the selected OpenAI visual artifact.",
        )
    verdict = str(review.get("artifact_quality_verdict") or "").strip().lower()
    if verdict not in ACCEPTED_QUALITY_VERDICTS:
        return (
            "quality_review_failed",
            "Quality review verdict did not approve the selected OpenAI visual artifact.",
        )
    if not _quality_review_attachment_verified(review, artifact_path=artifact_path):
        return (
            "quality_review_unverified",
            (
                "Quality review did not include independent OpenAI/GPT vision "
                "provenance for the selected OpenAI visual artifact."
            ),
        )
    return None


def _quality_review_attachment_verified(
    review: dict[str, Any],
    *,
    artifact_path: str,
) -> bool:
    if review.get("schema_version") != 1:
        return False
    if str(review.get("kind") or "").strip() != "raphael_visual_quality_review":
        return False
    if str(review.get("producer") or "").strip() != "hermes-visual-quality-review":
        return False
    if not str(review.get("command") or "").strip():
        return False
    if not str(review.get("run_id") or "").strip():
        return False
    if not _reviewer_is_independent(str(review.get("reviewer") or "")):
        return False
    if not _quality_artifact_identity_verified(review, artifact_path=artifact_path):
        return False
    if str(review.get("review_source_type") or "").strip() != "vision_model":
        return False
    provider = str(review.get("review_model_provider") or "").strip().lower()
    if provider.replace("_", "-") not in {"openai", "openai-codex"}:
        return False
    if not str(review.get("review_model") or "").strip():
        return False
    if not str(review.get("review_evidence_digest") or "").strip():
        return False
    if review.get("review_provenance_verified") is not True:
        return False
    if not str(review.get("review_response_id") or "").strip().startswith(
        ("resp_", "openai-response:", "codex-openai-vision-review:")
    ):
        return False
    if not _quality_transcript_digest_verified(review):
        return False
    return review.get("dimensions_verified") is True


def _quality_artifact_identity_verified(
    review: dict[str, Any],
    *,
    artifact_path: str,
) -> bool:
    if review.get("artifact_identity_verified") is not True:
        return False
    expected_sha256 = str(review.get("artifact_sha256") or "").strip()
    expected_size = _optional_int(review.get("artifact_size_bytes"))
    expected_mtime = _optional_float(review.get("artifact_mtime"))
    if not expected_sha256 or expected_size is None or expected_mtime is None:
        return False
    path = Path(artifact_path) if artifact_path else None
    if path is None or not path.is_file():
        return False
    try:
        data = path.read_bytes()
        stat = path.stat()
    except OSError:
        return False
    return (
        hashlib.sha256(data).hexdigest() == expected_sha256
        and len(data) == expected_size
        and abs(float(stat.st_mtime) - expected_mtime) < 0.001
    )


def _quality_transcript_digest_verified(review: dict[str, Any]) -> bool:
    transcript_path = str(review.get("review_transcript_report_path") or "").strip()
    transcript_digest = str(review.get("review_transcript_digest") or "").strip()
    if not transcript_path or not transcript_digest:
        return False
    path = Path(transcript_path).expanduser().resolve()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return hashlib.sha256(text.encode("utf-8")).hexdigest() == transcript_digest


def _quality_dimensions_verified(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(_quality_dimension_passed(value.get(key)) for key in REQUIRED_QUALITY_DIMENSIONS)


def _quality_dimension_passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        score = float(value)
        return math.isfinite(score) and score >= 0.75
    return str(value or "").strip().lower() in ACCEPTED_QUALITY_VERDICTS


def _reviewer_is_independent(value: str) -> bool:
    key = _reviewer_key(value)
    if key in BLOCKED_QUALITY_REVIEWERS:
        return False
    return not any(
        _reviewer_key_contains_phrase(key, phrase)
        for phrase in BLOCKED_QUALITY_REVIEWERS
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


def _with_release_provenance(report: dict[str, Any]) -> dict[str, Any]:
    stamped = dict(report)
    stamped.update(
        {
            "schema_version": 1,
            "kind": "raphael_visual_live_e2e",
            "producer": "openai-visual-live-e2e",
            "command": "scripts/openai_visual_live_e2e.py",
        }
    )
    script_path = Path(__file__).resolve()
    try:
        script_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
    except OSError:
        script_sha256 = ""
    stamped.update(
        {
            "script_path": str(script_path),
            "script_sha256": script_sha256,
            "script_identity_verified": bool(script_sha256),
        }
    )
    stamped.pop("report_digest", None)
    stamped["report_digest"] = _release_report_digest(stamped)
    return stamped


def _release_report_digest(report: dict[str, Any]) -> str:
    try:
        payload = json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _generate_with_openai_provider(args: dict[str, Any]) -> str:
    from tools.image_generation_tool import _handle_image_generate

    return _handle_image_generate(args)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.input_report:
        report = _read_input_report(args.input_report)
        report = attach_quality_review_report(report, args.quality_review_report)
    else:
        report = build_openai_visual_live_e2e_report(
            work_dir=args.work_dir,
            prompt=args.prompt,
            aspect_ratio=args.aspect_ratio,
            quality_review_report=args.quality_review_report,
        )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.get("success") is True else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an OpenAI/Codex image-only visual live E2E smoke for Raphael media readiness."
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--aspect-ratio", default="square")
    parser.add_argument("--work-dir")
    parser.add_argument("--input-report")
    parser.add_argument("--quality-review-report")
    parser.add_argument("--output")
    return parser


def _read_input_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    try:
        parsed = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "run_id": _default_run_id(_utc_now_text()),
            "generated_at": _utc_now_text(),
            "success": False,
            "status": "input_report_error",
            "provider_mode": "openai-gpt-image-live",
            "source_report_path": str(report_path),
            "error": exc.__class__.__name__,
        }
    if isinstance(parsed, dict):
        return parsed
    return {
        "run_id": _default_run_id(_utc_now_text()),
        "generated_at": _utc_now_text(),
        "success": False,
        "status": "input_report_error",
        "provider_mode": "openai-gpt-image-live",
        "source_report_path": str(report_path),
        "error": "not_json_object",
    }


def _coerce_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _failure_report(
    *,
    run_id: str,
    generated_at: str,
    prompt: str,
    aspect_ratio: str,
    status: str,
    error: str,
    error_type: str,
    provider_called: bool,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "success": False,
        "status": status,
        "provider_mode": "openai-gpt-image-live",
        "requires_operator_setup": False,
        "failure_class": error_type,
        "error": error,
        "request": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "operation": "generate",
        },
        "self_review": {
            "provider_called": provider_called,
            "next_action": "Fix OpenAI visual live E2E failure before media release gate.",
        },
    }


def _safe_provider_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key
        in {
            "success",
            "image",
            "artifact_path",
            "provider",
            "model",
            "aspect_ratio",
            "modality",
            "error",
            "error_type",
            "size",
            "quality",
            "response_id",
            "result_id",
            "generation_id",
            "id",
        }
    }


def _openai_result_surface_id(payload: dict[str, Any]) -> str:
    result_id = _provider_result_id(payload)
    return f"openai-response:{result_id}" if result_id else ""


def _provider_result_id(payload: dict[str, Any]) -> str:
    for key in ("response_id", "result_id", "generation_id", "id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _missing_opt_ins(env: dict[str, str]) -> list[str]:
    return [message for key, message in REQUIRED_OPT_INS if env.get(key) != "1"]


def _default_run_id(generated_at: str) -> str:
    compact = generated_at.replace(":", "").replace("-", "").replace(".", "")
    return "openai-visual-live-" + compact


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


DEFAULT_PROMPT = (
    "Create a polished vertical editorial image of a tasteful fantasy character, "
    "clean anatomy, refined lighting, high-quality finished illustration."
)
PREFLIGHT_PROBE_PROMPT = "Hermes Raphael preflight browser readiness probe. Do not submit."
REQUIRED_OPT_INS = (
    ("HERMES_VISUAL_LIVE_E2E", "HERMES_VISUAL_LIVE_E2E=1"),
    ("HERMES_GROK_WEB_IMAGINE", "HERMES_GROK_WEB_IMAGINE=1"),
)


def build_grok_web_imagine_preflight_report(
    *,
    work_dir: str | Path | None = None,
    provider_factory: Callable[[], Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    generated_at = _utc_now_text()
    run_id = "grok-web-preflight-" + generated_at.replace(":", "").replace("-", "").replace(".", "")
    env_map = env if env is not None else os.environ
    missing_opt_in = _missing_opt_ins(env_map)
    if missing_opt_in:
        return {
            "run_id": run_id,
            "generated_at": generated_at,
            "success": False,
            "status": "disabled",
            "provider_mode": "grok-web-imagine-live",
            "requires_operator_setup": True,
            "missing_opt_in": missing_opt_in,
            "quota_used": False,
            "checks": {
                "opt_in": False,
                "provider_constructed": False,
                "generation_called": False,
            },
            "self_review": {
                "provider_called": False,
                "next_action": "Set opt-in flags before running Grok Web Imagine live E2E.",
            },
        }

    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)

    try:
        provider = provider_factory() if provider_factory is not None else _default_provider()
    except Exception as exc:  # noqa: BLE001 - preflight should report setup failures.
        return {
            "run_id": run_id,
            "generated_at": generated_at,
            "success": False,
            "status": "provider_unavailable",
            "provider_mode": "grok-web-imagine-live",
            "requires_operator_setup": True,
            "quota_used": False,
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "checks": {
                "opt_in": True,
                "provider_constructed": False,
                "generation_called": False,
            },
            "self_review": {
                "provider_called": False,
                "next_action": "Fix Grok Web Imagine provider setup before spending visual quota.",
            },
        }

    browser_preflight = _run_provider_preflight(provider, probe_prompt=PREFLIGHT_PROBE_PROMPT)
    if browser_preflight is None:
        return {
            "run_id": run_id,
            "generated_at": generated_at,
            "success": False,
            "status": "provider_preflight_unavailable",
            "provider_mode": "grok-web-imagine-live",
            "requires_operator_setup": True,
            "provider": {
                "name": str(getattr(provider, "name", "") or "grok-web-imagine"),
                "model": str(getattr(provider, "model", "") or "grok-web-imagine"),
            },
            "quota_used": False,
            "error": "Grok Web Imagine provider does not expose a browser preflight check.",
            "error_type": "provider_preflight_unavailable",
            "checks": {
                "opt_in": True,
                "provider_constructed": True,
                "provider_preflight": False,
                "generation_called": False,
            },
            "self_review": {
                "provider_called": False,
                "preflight_called": False,
                "next_action": "Use a Grok Web Imagine provider build with browser preflight before live E2E.",
            },
        }
    if browser_preflight is not None and not browser_preflight["safe_to_submit"]:
        return {
            "run_id": run_id,
            "generated_at": generated_at,
            "success": False,
            "status": "browser_preflight_blocked",
            "provider_mode": "grok-web-imagine-live",
            "requires_operator_setup": True,
            "provider": {
                "name": str(getattr(provider, "name", "") or "grok-web-imagine"),
                "model": str(getattr(provider, "model", "") or "grok-web-imagine"),
            },
            "quota_used": False,
            "error": browser_preflight["message"],
            "error_type": browser_preflight["status"],
            "browser_preflight": browser_preflight,
            "checks": {
                "opt_in": True,
                "provider_constructed": True,
                "provider_preflight": True,
                "generation_called": False,
            },
            "self_review": {
                "provider_called": False,
                "preflight_called": True,
                "next_action": (
                    "Fix Grok Web Imagine browser preflight before live E2E: "
                    f"{browser_preflight['message']}"
                ),
            },
        }

    checks = {
        "opt_in": True,
        "provider_constructed": True,
        "generation_called": False,
    }
    if browser_preflight is not None:
        checks["provider_preflight"] = True

    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "success": True,
        "status": "preflight_ready",
        "provider_mode": "grok-web-imagine-live",
        "requires_operator_setup": False,
        "provider": {
            "name": str(getattr(provider, "name", "") or "grok-web-imagine"),
            "model": str(getattr(provider, "model", "") or "grok-web-imagine"),
        },
        "quota_used": False,
        **({"browser_preflight": browser_preflight} if browser_preflight is not None else {}),
        "checks": checks,
        "self_review": {
            "provider_called": False,
            "preflight_called": browser_preflight is not None,
            "next_action": (
                "Run live E2E only after visual quota is approved; preflight did not submit a prompt."
            ),
        },
    }


def build_grok_web_imagine_live_e2e_report(
    *,
    work_dir: str | Path | None = None,
    prompt: str = DEFAULT_PROMPT,
    aspect_ratio: str = "portrait",
    image_url: str | None = None,
    reference_image_urls: list[str] | None = None,
    operation: str = "generate",
    timeout_seconds: int = 240,
    provider_factory: Callable[[], Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env_map = env if env is not None else os.environ
    missing_opt_in = _missing_opt_ins(env_map)
    if missing_opt_in:
        return {
            "success": False,
            "status": "disabled",
            "provider_mode": "grok-web-imagine-live",
            "requires_operator_setup": True,
            "missing_opt_in": missing_opt_in,
            "self_review": {
                "safe_by_default": True,
                "provider_called": False,
                "next_action": "Set opt-in flags and ensure debug Chrome is logged into Grok Imagine.",
            },
        }

    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)

    refs = list(reference_image_urls or [])
    try:
        provider = provider_factory() if provider_factory is not None else _default_provider()
    except Exception as exc:  # noqa: BLE001 - setup must be reported, not raised.
        return _setup_required_report(
            status="setup_required",
            error=f"Grok Web Imagine provider setup failed: {exc}",
            error_type=exc.__class__.__name__,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            image_url=image_url,
            reference_image_urls=refs,
            operation=operation,
        )

    browser_preflight = _run_provider_preflight(
        provider,
        probe_prompt=PREFLIGHT_PROBE_PROMPT,
    )
    if browser_preflight is None:
        return _setup_required_report(
            status="setup_required",
            error="Grok Web Imagine provider does not expose browser preflight.",
            error_type="provider_preflight_unavailable",
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            image_url=image_url,
            reference_image_urls=refs,
            operation=operation,
        )
    if browser_preflight.get("safe_to_submit") is not True:
        return {
            "success": False,
            "status": "browser_preflight_blocked",
            "provider_mode": "grok-web-imagine-live",
            "requires_operator_setup": True,
            "error": str(browser_preflight.get("message") or "Browser preflight blocked submission."),
            "error_type": str(browser_preflight.get("status") or "browser_preflight_blocked"),
            "browser_preflight": browser_preflight,
            "request": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "image_url": image_url,
                "reference_image_urls": refs,
                "operation": operation,
            },
            "self_review": {
                "provider_called": False,
                "preflight_called": True,
                "next_action": "Fix browser preflight before submitting a live generation.",
            },
        }

    try:
        result = provider.generate(
            prompt,
            aspect_ratio=aspect_ratio,
            image_url=image_url,
            reference_image_urls=refs or None,
            operation=operation,
            timeout_seconds=int(timeout_seconds),
        )
    except Exception as exc:  # noqa: BLE001 - live harness should report, not traceback.
        return _failure_report(
            status="provider_exception",
            error=str(exc),
            error_type=exc.__class__.__name__,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            image_url=image_url,
            reference_image_urls=refs,
            operation=operation,
        )

    artifact_path = str(result.get("image") or result.get("artifact_path") or "").strip()
    artifact_exists = bool(artifact_path and Path(artifact_path).exists())
    provider_success = bool(result.get("success"))
    artifact_source = str(result.get("artifact_source") or result.get("source") or "")
    artifact_durability = str(result.get("artifact_durability") or _default_artifact_durability(artifact_source))
    durable_history_verified = _truthy_value(
        result.get("history_verified")
    ) or _has_result_surface_evidence(result)
    result_surface_id = _result_surface_id(result)
    success = provider_success and artifact_exists and durable_history_verified
    status = "completed" if success else ("ephemeral_artifact" if provider_success and artifact_exists else "failed")
    generated_at = _utc_now_text()
    run_id = "grok-web-live-" + generated_at.replace(":", "").replace("-", "").replace(".", "")
    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "success": success,
        "status": status,
        "provider_mode": "grok-web-imagine-live",
        "requires_operator_setup": False,
        "provider": {
            "name": str(result.get("provider") or "grok-web-imagine"),
            "model": str(result.get("model") or "grok-web-imagine"),
            "quota_source": str(result.get("quota_source") or ""),
        },
        "artifact": {
            "path": artifact_path,
            "exists": artifact_exists,
            "source": artifact_source,
            "durability": artifact_durability,
            "history_verified": durable_history_verified,
            "page_url": str(result.get("page_url") or ""),
        },
        "result_surface_id": result_surface_id,
        "history_entry_id": str(result.get("history_entry_id") or ""),
        "browser_preflight": browser_preflight,
        "request": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_url": image_url,
            "reference_image_urls": refs,
            "operation": operation,
            "timeout_seconds": int(timeout_seconds),
        },
        "provider_result": _safe_provider_result(result),
        "self_review": {
            "provider_called": True,
            "artifact_verified": artifact_exists,
            "durable_history_verified": durable_history_verified,
            "artifact_quality_verdict": "unreviewed",
            "consumer_web_quota_track": (result.get("quota_source") == "consumer_web"),
            "next_action": _next_action_for_status(status),
        },
    }


def _default_provider() -> Any:
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    return GrokWebImagineProvider()


def _missing_opt_ins(env: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for env_name, label in REQUIRED_OPT_INS:
        if not _truthy(env.get(env_name)):
            missing.append(label)
    return missing


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _truthy_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _truthy(str(value) if value is not None else None)


def _run_provider_preflight(provider: Any, *, probe_prompt: str) -> dict[str, Any] | None:
    preflight = getattr(provider, "preflight", None)
    if not callable(preflight):
        return None
    try:
        result = preflight(probe_prompt=probe_prompt)
    except TypeError:
        try:
            result = preflight()
        except Exception as exc:  # noqa: BLE001 - preflight should classify setup failures.
            return {
                "status": "provider_preflight_failed",
                "ready": False,
                "safe_to_submit": False,
                "message": f"Provider preflight failed before generation: {exc}",
                "url": "",
                "title": "",
                "quota_used": False,
            }
    except Exception as exc:  # noqa: BLE001 - preflight should classify setup failures.
        return {
            "status": "provider_preflight_failed",
            "ready": False,
            "safe_to_submit": False,
            "message": f"Provider preflight failed before generation: {exc}",
            "url": "",
            "title": "",
            "quota_used": False,
        }
    return _normalise_provider_preflight(result)


def _normalise_provider_preflight(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "status": "invalid_preflight_result",
            "ready": False,
            "safe_to_submit": False,
            "message": "Provider preflight did not return an object.",
            "url": "",
            "title": "",
            "quota_used": False,
        }
    has_safe_to_submit = "safe_to_submit" in result
    safe_to_submit = (
        _truthy_value(result.get("safe_to_submit"))
        if has_safe_to_submit
        else _truthy_value(result.get("ready"))
    )
    ready = _truthy_value(result.get("ready")) or safe_to_submit
    return {
        "status": str(result.get("status") or ("ready" if ready else "unknown")),
        "ready": ready,
        "safe_to_submit": safe_to_submit,
        "message": str(result.get("message") or ""),
        "url": str(result.get("url") or ""),
        "title": str(result.get("title") or ""),
        "quota_used": _truthy_value(result.get("quota_used")),
        **(
            {"prompt_probe": _normalise_prompt_probe(result.get("prompt_probe"))}
            if isinstance(result.get("prompt_probe"), dict)
            else {}
        ),
    }


def _normalise_prompt_probe(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "attempted": False,
            "prompt_text_present": False,
            "submit_enabled": False,
            "reason": "prompt_probe_missing",
            "tag": "",
            "filled_text_preview": "",
        }
    return {
        "attempted": value.get("attempted") is True,
        "prompt_text_present": value.get("prompt_text_present") is True,
        "submit_enabled": value.get("submit_enabled") is True,
        "reason": str(value.get("reason") or ""),
        "tag": str(value.get("tag") or ""),
        "filled_text_preview": str(value.get("filled_text_preview") or "")[:120],
    }


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_artifact_durability(source: str) -> str:
    if source in {"browser_data_url", "browser_blob", "browser_fetch", "browser_screenshot", "browser_url"}:
        return "ephemeral_browser_page"
    return "unknown"


def _result_surface_id(result: dict[str, Any]) -> str:
    return str(
        result.get("result_surface_id")
        or result.get("history_entry_id")
        or result.get("page_url")
        or ""
    ).strip()


def _has_result_surface_evidence(result: dict[str, Any]) -> bool:
    if _is_strong_grok_result_reference(result.get("result_surface_id")):
        return True
    if _is_strong_grok_result_reference(result.get("history_entry_id")):
        return True
    page_url = str(result.get("page_url") or "").strip()
    return _looks_like_grok_result_page_url(page_url)


def _is_strong_grok_result_reference(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith(("http://", "https://")):
        return _looks_like_grok_result_page_url(text)
    if text in {"current", "latest", "selected", "active", "gallery", "result"}:
        return False
    return len(text) >= 8


def _looks_like_grok_result_page_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("https://grok.com/") and (
        "/imagine/post/" in text or "/imagine/history/" in text
    )


def _next_action_for_status(status: str) -> str:
    if status == "completed":
        return (
            "Run artifact quality review before media release; durability alone "
            "does not certify composition, identity, or visual quality."
        )
    if status == "ephemeral_artifact":
        return (
            "Do not claim live Grok Imagine success yet; verify a history/post URL or fix the browser route "
            "before treating this artifact as durable."
        )
    return "Inspect provider_result and browser setup."


def _safe_provider_result(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "success",
        "error",
        "error_type",
        "provider",
        "model",
        "image",
        "aspect_ratio",
        "quota_source",
        "artifact_source",
        "artifact_durability",
        "history_verified",
        "page_url",
        "history_entry_id",
        "result_surface_id",
        "page_title",
        "reference_image_count",
        "operation",
    }
    return {key: value for key, value in result.items() if key in allowed}


def attach_quality_review_report(
    report: dict[str, Any],
    quality_review_report_path: str | Path | None,
) -> dict[str, Any]:
    path_text = str(quality_review_report_path or "").strip()
    if not path_text:
        return report
    path = Path(path_text).expanduser().resolve()
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - CLI should return a report, not traceback.
        report["quality_review"] = {
            "source_report_path": str(path),
            "attachment_error": exc.__class__.__name__,
        }
        return report
    if not isinstance(review, dict):
        report["quality_review"] = {
            "source_report_path": str(path),
            "attachment_error": "report_not_object",
        }
        return report
    report["quality_review"] = {
        "source_report_path": str(path),
        "schema_version": review.get("schema_version"),
        "kind": str(review.get("kind") or ""),
        "generated_at": str(review.get("generated_at") or ""),
        "run_id": str(review.get("run_id") or ""),
        "producer": str(review.get("producer") or ""),
        "reviewer": str(
            review.get("reviewer")
            or review.get("reviewer_role")
            or review.get("producer")
            or ""
        ),
        "artifact_path": str(
            review.get("artifact_path")
            or review.get("selected_artifact_id")
            or review.get("artifact_id")
            or ""
        ),
        "artifact_quality_verdict": str(
            review.get("artifact_quality_verdict")
            or review.get("quality_verdict")
            or review.get("visual_quality_verdict")
            or review.get("verdict")
            or ""
        ),
        "dimensions": review.get("dimensions") or review.get("checks") or review.get("scores"),
    }
    return report


def _failure_report(
    *,
    status: str,
    error: str,
    error_type: str,
    prompt: str,
    aspect_ratio: str,
    image_url: str | None,
    reference_image_urls: list[str],
    operation: str = "generate",
) -> dict[str, Any]:
    return {
        "success": False,
        "status": status,
        "provider_mode": "grok-web-imagine-live",
        "requires_operator_setup": False,
        "error": error,
        "error_type": error_type,
        "request": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_url": image_url,
            "reference_image_urls": reference_image_urls,
            "operation": operation,
        },
        "self_review": {
            "provider_called": True,
            "artifact_verified": False,
            "next_action": "Inspect browser setup and provider error before retrying.",
        },
    }


def _setup_required_report(
    *,
    status: str,
    error: str,
    error_type: str,
    prompt: str,
    aspect_ratio: str,
    image_url: str | None,
    reference_image_urls: list[str],
    operation: str,
) -> dict[str, Any]:
    return {
        "success": False,
        "status": status,
        "provider_mode": "grok-web-imagine-live",
        "requires_operator_setup": True,
        "error": error,
        "error_type": error_type,
        "request": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_url": image_url,
            "reference_image_urls": reference_image_urls,
            "operation": operation,
        },
        "self_review": {
            "provider_called": False,
            "preflight_called": False,
            "next_action": "Complete Grok Web Imagine provider and browser setup before retrying.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in live E2E harness for Grok Web Imagine.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--aspect-ratio", default="portrait")
    parser.add_argument("--image-url")
    parser.add_argument("--reference-image", action="append", default=[])
    parser.add_argument(
        "--operation",
        default="generate",
        choices=["generate", "edit_current", "continue_current", "regenerate_current"],
    )
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--work-dir")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--input-report")
    parser.add_argument("--quality-review-report")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    if args.preflight_only:
        report = build_grok_web_imagine_preflight_report(
            work_dir=args.work_dir,
        )
    elif args.input_report:
        report = _load_existing_report(args.input_report)
    else:
        report = build_grok_web_imagine_live_e2e_report(
            work_dir=args.work_dir,
            prompt=args.prompt,
            aspect_ratio=args.aspect_ratio,
            image_url=args.image_url,
            reference_image_urls=args.reference_image,
            operation=args.operation,
            timeout_seconds=args.timeout_seconds,
        )
    report = attach_quality_review_report(report, args.quality_review_report)
    if _quality_review_attachment_failed(report):
        report["success"] = False
        report["status"] = "quality_review_attachment_error"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.get("success") else 2


def _quality_review_attachment_failed(report: dict[str, Any]) -> bool:
    review = report.get("quality_review")
    return isinstance(review, dict) and bool(review.get("attachment_error"))


def _load_existing_report(path_text: str | Path) -> dict[str, Any]:
    path = Path(path_text).expanduser().resolve()
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - CLI should emit a report, not traceback.
        return {
            "success": False,
            "status": "input_report_error",
            "provider_mode": "grok-web-imagine-live",
            "input_report_path": str(path),
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
    if not isinstance(report, dict):
        return {
            "success": False,
            "status": "input_report_not_object",
            "provider_mode": "grok-web-imagine-live",
            "input_report_path": str(path),
        }
    return report


if __name__ == "__main__":
    raise SystemExit(main())

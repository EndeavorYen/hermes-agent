from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


DEFAULT_PROMPT = (
    "Create a polished vertical editorial image of a tasteful fantasy character, "
    "clean anatomy, refined lighting, high-quality finished illustration."
)
REQUIRED_OPT_INS = (
    ("HERMES_VISUAL_LIVE_E2E", "HERMES_VISUAL_LIVE_E2E=1"),
    ("HERMES_GROK_WEB_IMAGINE", "HERMES_GROK_WEB_IMAGINE=1"),
)


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

    provider = provider_factory() if provider_factory is not None else _default_provider()
    refs = list(reference_image_urls or [])
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
        )

    artifact_path = str(result.get("image") or result.get("artifact_path") or "").strip()
    artifact_exists = bool(artifact_path and Path(artifact_path).exists())
    success = bool(result.get("success")) and artifact_exists
    return {
        "success": success,
        "status": "completed" if success else "failed",
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
            "source": str(result.get("artifact_source") or result.get("source") or ""),
        },
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
            "consumer_web_quota_track": (result.get("quota_source") == "consumer_web"),
            "next_action": "Use this selected artifact as Grok Web polish output." if success else "Inspect provider_result and browser setup.",
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
        "reference_image_count",
        "operation",
    }
    return {key: value for key, value in result.items() if key in allowed}


def _failure_report(
    *,
    status: str,
    error: str,
    error_type: str,
    prompt: str,
    aspect_ratio: str,
    image_url: str | None,
    reference_image_urls: list[str],
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
        },
        "self_review": {
            "provider_called": True,
            "artifact_verified": False,
            "next_action": "Inspect browser setup and provider error before retrying.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in live E2E harness for Grok Web Imagine.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--aspect-ratio", default="portrait")
    parser.add_argument("--image-url")
    parser.add_argument("--reference-image", action="append", default=[])
    parser.add_argument("--operation", default="generate", choices=["generate", "edit_current"])
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--work-dir")
    args = parser.parse_args(argv)

    report = build_grok_web_imagine_live_e2e_report(
        work_dir=args.work_dir,
        prompt=args.prompt,
        aspect_ratio=args.aspect_ratio,
        image_url=args.image_url,
        reference_image_urls=args.reference_image,
        operation=args.operation,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())

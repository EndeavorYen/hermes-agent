"""Mission-level image generation with bounded retries and basic QC.

This tool restores the local runtime contract used by Visual Arsenal and the
Hermes image mission config. It intentionally delegates single-shot generation
to the current ``image_generate`` implementation and keeps the mission layer
focused on bounded attempts, prompt mediation, candidate selection, and
auditable result metadata.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from agent.image_gen_provider import DEFAULT_ASPECT_RATIO, VALID_ASPECT_RATIOS
from tools.image2_adaptive_mediator import (
    MediatedImagePrompt,
    mediate_image2_prompt as _mediate_image2_prompt,
    read_image2_adaptive_mediator_config as _read_image2_adaptive_mediator_config,
    record_image2_mediator_attempt as _record_image2_mediator_attempt,
)
from tools.image_generation_tool import (
    _handle_image_generate,
    _legacy_reference_image_urls,
    check_image_generation_requirements,
)
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

QC_PASS_THRESHOLD = 70
_DEFAULT_BUDGET = "task"
_VALID_BUDGETS = ("task", "conservative", "aggressive")
_MAX_ATTEMPT_CAP = 4
_COMPLEXITY_MARKERS = (
    "reference",
    "identity",
    "face",
    "hands",
    "fingers",
    "portrait",
    "character",
    "logo",
    "text",
    "product",
    "outfit",
    "exact",
    "photoreal",
    "realistic",
    "anatomy",
    "full body",
)


@dataclass(frozen=True)
class DeterministicQcReport:
    score: int
    passed: bool
    fatal: bool
    issues: List[str]
    summary: str
    width: Optional[int] = None
    height: Optional[int] = None
    image_format: Optional[str] = None
    file_size: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "score": self.score,
            "passed": self.passed,
            "fatal": self.fatal,
            "issues": list(self.issues),
            "summary": self.summary,
            "width": self.width,
            "height": self.height,
            "image_format": self.image_format,
            "file_size": self.file_size,
        }
        return {key: value for key, value in payload.items() if value is not None}


def resolve_attempt_budget(
    prompt: str,
    *,
    budget: str = _DEFAULT_BUDGET,
    reference_images: Optional[List[str]] = None,
) -> int:
    budget = budget if budget in _VALID_BUDGETS else _DEFAULT_BUDGET
    if budget == "conservative":
        return 2
    if budget == "aggressive":
        return 4
    lowered = str(prompt or "").lower()
    if reference_images or any(marker in lowered for marker in _COMPLEXITY_MARKERS):
        return 4
    return 3


def _coerce_attempt_cap(value: Any) -> Optional[int]:
    try:
        cap = int(value)
    except (TypeError, ValueError):
        return None
    if cap <= 0:
        return None
    return max(1, min(_MAX_ATTEMPT_CAP, cap))


def _read_configured_mission_attempt_cap() -> Optional[int]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
    except Exception as exc:
        logger.debug("Could not read image_gen.mission config: %s", exc)
        return None
    section = cfg.get("image_gen") if isinstance(cfg, dict) else None
    mission = section.get("mission") if isinstance(section, dict) else None
    if not isinstance(mission, dict):
        return None
    return _coerce_attempt_cap(mission.get("max_attempts"))


def build_attempt_prompt(
    prompt: str,
    attempt_index: int,
    *,
    previous_failure: str = "",
    reference_images: Optional[List[str]] = None,
) -> str:
    subject = str(prompt or "").strip() or "the requested subject"
    refs = reference_images or []
    if attempt_index <= 1 and not previous_failure:
        direction = "Faithfully preserve the user's visual intent."
    elif attempt_index == 2:
        direction = (
            "Use a clearer, more literal visual description while preserving "
            "the requested subject, composition, style, and reference constraints."
        )
    elif attempt_index == 3:
        direction = "Prioritize clean composition, readable silhouette, natural proportions, and controlled lighting."
    else:
        direction = "Refine toward the closest acceptable result with crisp detail and coherent anatomy."

    parts = [
        "Create a polished Image2 result from this structured brief.",
        f"Subject: {subject}.",
        (
            "Reference handling: Preserve identity, palette, outfit, composition, and product details from reference images."
            if refs
            else "Reference handling: No reference images were provided; follow the written prompt."
        ),
        "Quality guard: sharp, high-resolution, anatomically coherent, no heavy artifacts, no warped hands, no malformed limbs, no unreadable intended text.",
        f"Attempt direction: {direction}",
    ]
    if previous_failure:
        parts.append(f"Previous generation issue: {previous_failure[:300]}")
        parts.append("Correction scope: fix only the listed issue while preserving the user intent anchors.")
    return "\n\n".join(parts)


def evaluate_deterministic_qc(
    image_path: str,
    *,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> DeterministicQcReport:
    if _is_remote_url(str(image_path or "")):
        return DeterministicQcReport(
            score=80,
            passed=True,
            fatal=False,
            issues=["remote_image_not_locally_inspected"],
            summary="Remote image result accepted; local pixel inspection was skipped.",
        )

    path = Path(str(image_path or "")).expanduser()
    if not image_path or not path.exists():
        return DeterministicQcReport(
            score=0,
            passed=False,
            fatal=True,
            issues=["missing_image"],
            summary="Generated image file is missing.",
        )
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = None
    if not file_size:
        return DeterministicQcReport(
            score=0,
            passed=False,
            fatal=True,
            issues=["empty_image_file"],
            summary="Generated image file is empty.",
            file_size=file_size,
        )

    try:
        from PIL import Image, ImageStat

        with Image.open(path) as opened:
            image_format = opened.format
            width, height = opened.size
            image = opened.convert("RGB")
            stat = ImageStat.Stat(image.resize((64, 64)))
            extrema = image.getextrema()
    except Exception as exc:
        return DeterministicQcReport(
            score=0,
            passed=False,
            fatal=True,
            issues=["unreadable_image"],
            summary=f"Generated image could not be decoded: {exc}",
            file_size=file_size,
        )

    issues: List[str] = []
    fatal = False
    if width < 64 or height < 64:
        issues.append("low_resolution")
        fatal = True
    channel_ranges = [high - low for low, high in extrema]
    max_stddev = max(stat.stddev or [0.0])
    if max(channel_ranges, default=0) <= 4 and max_stddev <= 2.0:
        issues.append("blank_or_nearly_uniform")
        fatal = True
    expected = _expected_aspect_ratio(aspect_ratio)
    if expected:
        actual = width / height if height else 0
        if actual and abs(actual - expected) / expected > 0.35:
            issues.append("aspect_ratio_mismatch")

    score = 100
    if "aspect_ratio_mismatch" in issues:
        score -= 10
    if "low_resolution" in issues:
        score -= 70
    if "blank_or_nearly_uniform" in issues:
        score -= 90
    return DeterministicQcReport(
        score=max(0, score),
        passed=not fatal,
        fatal=fatal,
        issues=issues,
        summary="Deterministic image checks passed." if not issues else ", ".join(issues),
        width=width,
        height=height,
        image_format=image_format,
        file_size=file_size,
    )


async def run_image_generation_mission(
    *,
    prompt: str,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    budget: str = _DEFAULT_BUDGET,
    reference_images: Optional[List[str]] = None,
    max_attempts: Optional[int] = None,
    generate_once: Optional[Callable[..., Any]] = None,
    deterministic_check: Optional[Callable[..., DeterministicQcReport]] = None,
) -> Dict[str, Any]:
    prompt = str(prompt or "").strip()
    if not prompt:
        return {
            "success": False,
            "image": None,
            "error": "Prompt is required and must be a non-empty string",
            "error_type": "invalid_argument",
        }

    refs = _normalize_reference_images(reference_images)
    original_prompt = prompt
    mediated: Optional[MediatedImagePrompt] = None
    mediator_config = _read_image2_adaptive_mediator_config()
    if mediator_config.get("enabled"):
        try:
            mediated = _mediate_image2_prompt(prompt, config=mediator_config)
            if mediated.final_prompt.strip():
                prompt = mediated.final_prompt.strip()
        except Exception as exc:
            logger.info("Image2 adaptive mediator unavailable for mission: %s", exc)

    base_attempts = resolve_attempt_budget(prompt, budget=budget, reference_images=refs)
    configured_cap = _coerce_attempt_cap(max_attempts)
    attempt_limit = min(base_attempts, configured_cap) if configured_cap else base_attempts
    generator = generate_once or _default_generate_once
    deterministic = deterministic_check or evaluate_deterministic_qc

    attempts: List[Dict[str, Any]] = []
    best_attempt: Optional[Dict[str, Any]] = None
    previous_failure = ""

    for attempt_index in range(1, attempt_limit + 1):
        attempt_prompt = build_attempt_prompt(
            prompt,
            attempt_index,
            previous_failure=previous_failure,
            reference_images=refs,
        )
        raw_result = generator(
            prompt=attempt_prompt,
            aspect_ratio=aspect_ratio,
            reference_images=refs,
            attempt_index=attempt_index,
        )
        result = _coerce_generation_result(await _maybe_await(raw_result))
        attempt_record: Dict[str, Any] = {
            "attempt_index": attempt_index,
            "prompt": attempt_prompt,
            "accepted": False,
            "result": result,
        }
        image = str(result.get("image") or "").strip()
        if not result.get("success") or not image:
            previous_failure = _generation_retry_feedback(result)
            attempt_record["error"] = previous_failure
            attempts.append(attempt_record)
            continue

        qc = deterministic(image, aspect_ratio=aspect_ratio)
        attempt_record["image"] = image
        attempt_record["deterministic_qc"] = qc.to_dict()
        attempt_record["qc"] = qc.to_dict()
        attempts.append(attempt_record)
        if best_attempt is None or qc.score > int(best_attempt.get("qc", {}).get("score", -1)):
            best_attempt = attempt_record
        if qc.passed and qc.score >= QC_PASS_THRESHOLD:
            attempt_record["accepted"] = True
            payload = _mission_success(
                result,
                attempts,
                prompt=prompt,
                original_prompt=original_prompt,
                mediated=mediated,
                mediator_config=mediator_config,
            )
            return payload
        previous_failure = qc.summary

    payload = _mission_failure(
        "qc_failed" if best_attempt is not None else "generation_failed",
        "Image mission did not produce an accepted candidate within the attempt budget.",
        attempts,
        best_attempt,
        prompt=prompt,
        original_prompt=original_prompt,
        mediated=mediated,
    )
    _record_mediator_outcome(
        mediated,
        payload,
        mediator_config,
        status="failed",
        failure_class=[payload["error_type"]],
    )
    return payload


async def _handle_image_generate_mission(args: Dict[str, Any], **_kw: Any) -> str:
    prompt = args.get("prompt", "")
    if not prompt:
        return tool_error("prompt is required for image generation", success=False)
    requested_cap = _coerce_attempt_cap(args.get("max_attempts"))
    configured_cap = _read_configured_mission_attempt_cap()
    caps = [cap for cap in (requested_cap, configured_cap) if cap is not None]
    result = await run_image_generation_mission(
        prompt=prompt,
        aspect_ratio=args.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
        budget=args.get("budget", _DEFAULT_BUDGET),
        reference_images=args.get("reference_images") or _legacy_reference_image_urls(args),
        max_attempts=min(caps) if caps else None,
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


def check_image_mission_requirements() -> bool:
    return check_image_generation_requirements()


def _mission_success(
    result: Dict[str, Any],
    attempts: List[Dict[str, Any]],
    *,
    prompt: str,
    original_prompt: str,
    mediated: Optional[MediatedImagePrompt],
    mediator_config: Dict[str, Any],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(result)
    payload.update(
        {
            "success": True,
            "image": result.get("image"),
            "prompt": prompt,
            "original_prompt": original_prompt,
            "attempt_count": len(attempts),
            "attempts": [_public_attempt(attempt) for attempt in attempts],
            "best_candidate": _public_attempt(attempts[-1]),
            "mission": {
                "qc_mode": "deterministic",
                "attempt_budget": len(attempts),
            },
        }
    )
    _record_mediator_outcome(mediated, payload, mediator_config, status="success", failure_class=[])
    if mediated is not None:
        payload["adaptive_mediator"] = mediated.to_public_dict()
    return payload


def _mission_failure(
    error_type: str,
    error: str,
    attempts: List[Dict[str, Any]],
    best_attempt: Optional[Dict[str, Any]],
    *,
    prompt: str,
    original_prompt: str,
    mediated: Optional[MediatedImagePrompt],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "success": False,
        "image": None,
        "error": error,
        "error_type": error_type,
        "prompt": prompt,
        "original_prompt": original_prompt,
        "attempt_count": len(attempts),
        "attempts": [_public_attempt(attempt) for attempt in attempts],
    }
    if best_attempt is not None:
        payload["best_candidate"] = _public_attempt(best_attempt)
    if mediated is not None:
        payload["adaptive_mediator"] = mediated.to_public_dict()
    return payload


def _record_mediator_outcome(
    mediated: Optional[MediatedImagePrompt],
    payload: Dict[str, Any],
    mediator_config: Dict[str, Any],
    *,
    status: str,
    failure_class: List[str],
) -> None:
    if mediated is None:
        return
    try:
        _record_image2_mediator_attempt(
            mediated,
            image2_status=status,
            feedback_source="visual_inspection" if status == "success" else "image2_error",
            failure_class=failure_class,
            config=mediator_config,
            notes=str(payload.get("error") or "")[:300],
        )
    except Exception as exc:
        logger.info("Could not record Image2 mediator attempt: %s", exc)


def _default_generate_once(**kwargs: Any) -> str:
    args = {
        "prompt": kwargs.get("prompt", ""),
        "aspect_ratio": kwargs.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
        "skip_prompt_preprocessor": True,
    }
    refs = kwargs.get("reference_images")
    if refs:
        args["reference_images"] = refs
    return _handle_image_generate(args)


def _normalize_reference_images(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_generation_result(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {
                "success": False,
                "image": None,
                "error": value,
                "error_type": "invalid_generation_result",
            }
    return {
        "success": False,
        "image": None,
        "error": f"Unsupported generation result type: {type(value).__name__}",
        "error_type": "invalid_generation_result",
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _public_attempt(attempt: Dict[str, Any]) -> Dict[str, Any]:
    result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
    public = {
        "attempt_index": attempt.get("attempt_index"),
        "accepted": bool(attempt.get("accepted")),
        "image": attempt.get("image") or result.get("image"),
        "error_type": result.get("error_type"),
        "error": result.get("error") or attempt.get("error"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "deterministic_qc": attempt.get("deterministic_qc"),
        "qc": attempt.get("qc"),
    }
    return {key: value for key, value in public.items() if value is not None}


def _generation_retry_feedback(result: Dict[str, Any]) -> str:
    error_type = str(result.get("error_type") or "generation_failed").strip() or "generation_failed"
    if error_type == "policy_refusal":
        return "policy_refusal: rewrite in adult, non-explicit, non-nude fashion/editorial language while preserving intent."
    if error_type == "empty_response":
        return "empty_response: request a complete final image while preserving intent."
    if result.get("error"):
        return f"{error_type}: {result.get('error')}"
    return error_type


def _expected_aspect_ratio(aspect_ratio: str) -> Optional[float]:
    if aspect_ratio == "square":
        return 1.0
    if aspect_ratio == "landscape":
        return 16 / 9
    if aspect_ratio == "portrait":
        return 9 / 16
    return None


def _is_remote_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


IMAGE_GENERATE_MISSION_SCHEMA = {
    "name": "image_generate_mission",
    "description": (
        "Generate an image as a bounded mission. It wraps the configured "
        "image_generate backend, applies Image2 adaptive mediation when enabled, "
        "tries a capped number of prompt variants, runs deterministic image QC, "
        "and returns the accepted or best candidate with attempt evidence. Use "
        "this for image-only requests that need retry/QC. For image plus video "
        "or assembled packages, use visual_agent_generate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The target image. Include must-have visual details.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": list(VALID_ASPECT_RATIOS),
                "description": "The desired image aspect ratio.",
                "default": DEFAULT_ASPECT_RATIO,
            },
            "reference_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional source/reference image URLs, data URLs, or local paths.",
            },
            "budget": {
                "type": "string",
                "enum": list(_VALID_BUDGETS),
                "description": "Attempt budget. 'task' auto-scales by prompt complexity.",
                "default": _DEFAULT_BUDGET,
            },
            "max_attempts": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_ATTEMPT_CAP,
                "description": "Optional hard cap for generation attempts. Runtime config image_gen.mission.max_attempts can also cap this value.",
            },
        },
        "required": ["prompt"],
    },
}


registry.register(
    name="image_generate_mission",
    toolset="image_gen",
    schema=IMAGE_GENERATE_MISSION_SCHEMA,
    handler=_handle_image_generate_mission,
    check_fn=check_image_mission_requirements,
    requires_env=[],
    is_async=True,
    emoji="🎯",
)

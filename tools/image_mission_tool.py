"""Mission-level image generation with visual QC.

This tool wraps the existing single-shot ``image_generate`` path. It adds a
bounded attempt budget, prompt variants, vision-based quality control, and
best-candidate selection so low-quality or malformed images are not accepted
just because generation technically succeeded.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from agent.image_gen_provider import DEFAULT_ASPECT_RATIO, VALID_ASPECT_RATIOS
from tools.image_generation_tool import (
    _handle_image_generate,
    _normalize_image_generate_refs,
    check_image_generation_requirements,
)
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

QC_PASS_THRESHOLD = 70
QC_NEAR_MISS_THRESHOLD = 65
_DEFAULT_BUDGET = "task"
_VALID_BUDGETS = ("task", "conservative", "aggressive")
_FATAL_VISION_ISSUES = {
    "blur",
    "deformed_anatomy",
    "heavy_artifacts",
    "qc_unavailable",
    "semantic_mismatch",
    "unreadable_text",
    "reference_drift",
}

_COMPLEXITY_MARKERS = (
    "reference", "identity", "face", "hands", "fingers", "portrait",
    "character", "logo", "text", "product", "outfit", "exact",
    "photoreal", "realistic", "anatomy", "full body",
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


@dataclass(frozen=True)
class VisualQcReport:
    score: int
    passed: bool
    fatal: bool
    issues: List[str]
    summary: str
    raw: str
    quality_score: Optional[int] = None
    adherence_score: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "fatal": self.fatal,
            "issues": list(self.issues),
            "summary": self.summary,
            "quality_score": self.quality_score,
            "adherence_score": self.adherence_score,
            "raw": self.raw,
        }


def resolve_attempt_budget(
    prompt: str,
    *,
    budget: str = _DEFAULT_BUDGET,
    reference_images: Optional[List[str]] = None,
) -> int:
    """Return the max generation attempts for the selected budget mode."""
    budget = budget if budget in _VALID_BUDGETS else _DEFAULT_BUDGET
    if budget == "conservative":
        return 3
    if budget == "aggressive":
        return 8

    text = (prompt or "").lower()
    refs = reference_images or []
    complexity = sum(1 for marker in _COMPLEXITY_MARKERS if marker in text)
    if refs or complexity >= 4 or len(text) > 220:
        return 8
    if complexity >= 2 or len(text) > 120:
        return 6
    return 3


def build_attempt_prompt(prompt: str, attempt_index: int, *, previous_failure: str = "") -> str:
    """Create a Codex image2-friendly prompt variant for this attempt."""
    base = (prompt or "").strip()
    quality_guard = (
        "Render a sharp, anatomically coherent, high-resolution image. "
        "Avoid blurry output, distorted faces, warped hands, extra fingers, "
        "missing fingers, malformed limbs, melted details, low-resolution "
        "texture, and heavy artifacts."
    )
    if attempt_index <= 1:
        variant = "Faithfully preserve the user's visual intent."
    elif attempt_index == 2:
        variant = (
            "Use a more literal and image2-safe visual description. Preserve "
            "the concrete subject, composition, style, and reference-image "
            "constraints while avoiding unsupported wording."
        )
    elif attempt_index == 3:
        variant = (
            "Prioritize clean composition, readable silhouette, natural "
            "proportions, and controlled lighting."
        )
    else:
        variant = (
            "Refine toward the closest acceptable result. Emphasize precise "
            "subject structure, crisp detail, coherent anatomy, and polished "
            "final-image quality."
        )

    parts = [base, variant, quality_guard]
    if previous_failure:
        parts.append(f"Correct the previous issue: {previous_failure[:300]}")
    return "\n\n".join(part for part in parts if part)


def evaluate_deterministic_qc(
    image_path: str,
    *,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> DeterministicQcReport:
    """Run objective file and pixel sanity checks before vision-agent QC."""
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
    score = max(0, score)

    return DeterministicQcReport(
        score=score,
        passed=not fatal,
        fatal=fatal,
        issues=issues,
        summary="Deterministic image checks passed." if not issues else ", ".join(issues),
        width=width,
        height=height,
        image_format=image_format,
        file_size=file_size,
    )


def evaluate_visual_qc(analysis: str, prompt: str = "") -> VisualQcReport:
    """Score a vision-analysis response and flag fatal visual defects."""
    raw = analysis if isinstance(analysis, str) else str(analysis)
    parsed = _extract_json_object(raw)
    if parsed:
        if "analysis" in parsed and (
            parsed.get("success") is False
            or "quality_score" not in parsed
            or "adherence_score" not in parsed
        ):
            return evaluate_visual_qc(str(parsed.get("analysis") or ""), prompt=prompt)
        quality_score = _coerce_score(parsed.get("quality_score"))
        adherence_score = _coerce_score(parsed.get("adherence_score"))
        issues = _normalize_issues(parsed.get("fatal_issues")) + _normalize_issues(parsed.get("issues"))
        issues = _dedupe_preserve_order([_normalize_issue_name(issue) for issue in issues])
        fatal = bool(_normalize_issues(parsed.get("fatal_issues"))) or any(
            issue in _FATAL_VISION_ISSUES
            for issue in issues
        )
        if quality_score is not None and adherence_score is not None:
            score = round((quality_score * 0.6) + (adherence_score * 0.4))
        elif quality_score is not None:
            score = quality_score
        elif adherence_score is not None:
            score = adherence_score
        else:
            score = _score_from_text(raw, issues)
        if fatal:
            score = min(score, 69)
        return VisualQcReport(
            score=score,
            passed=(score >= QC_PASS_THRESHOLD and not fatal),
            fatal=fatal,
            issues=issues,
            summary=str(parsed.get("summary") or raw[:500]),
            raw=raw,
            quality_score=quality_score,
            adherence_score=adherence_score,
        )

    issues = _issues_from_text(raw)
    fatal = any(
        issue in _FATAL_VISION_ISSUES
        for issue in issues
    )
    score = _score_from_text(raw, issues)
    if fatal:
        score = min(score, 69)
    return VisualQcReport(
        score=score,
        passed=(score >= QC_PASS_THRESHOLD and not fatal),
        fatal=fatal,
        issues=issues,
        summary=raw[:500],
        raw=raw,
    )


async def run_image_generation_mission(
    *,
    prompt: str,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    budget: str = _DEFAULT_BUDGET,
    reference_images: Optional[List[str]] = None,
    generate_once: Optional[Callable[..., Any]] = None,
    inspect_image: Optional[Callable[[str, str], Any]] = None,
    deterministic_check: Optional[Callable[..., DeterministicQcReport]] = None,
) -> Dict[str, Any]:
    """Generate multiple candidates, QC them, and return the best accepted image."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {
            "success": False,
            "image": None,
            "error": "Prompt is required and must be a non-empty string",
            "error_type": "invalid_argument",
        }

    refs = _normalize_image_generate_refs(reference_images) or []
    base_attempts = resolve_attempt_budget(prompt, budget=budget, reference_images=refs)
    max_attempts = base_attempts
    attempt_cap = _strategy_attempt_cap(budget, base_attempts)
    strategy: Dict[str, Any] = {
        "qc_mode": "hybrid",
        "base_attempts": base_attempts,
        "attempt_cap": attempt_cap,
        "extensions": [],
    }
    generator = generate_once or _default_generate_once
    inspector = inspect_image or _default_inspect_image
    deterministic = deterministic_check or evaluate_deterministic_qc

    attempts: List[Dict[str, Any]] = []
    best_attempt: Optional[Dict[str, Any]] = None
    previous_failure = ""

    attempt_index = 1
    while attempt_index <= max_attempts:
        attempt_prompt = build_attempt_prompt(
            prompt,
            attempt_index,
            previous_failure=previous_failure,
        )
        raw_result = generator(
            prompt=attempt_prompt,
            aspect_ratio=aspect_ratio,
            reference_images=refs,
            attempt_index=attempt_index,
        )
        result = _coerce_generation_result(raw_result)
        attempt_record: Dict[str, Any] = {
            "attempt_index": attempt_index,
            "prompt": attempt_prompt,
            "accepted": False,
            "result": result,
        }

        if not result.get("success"):
            error = str(result.get("error") or result.get("error_type") or "generation failed")
            retryable = bool(result.get("retryable")) or result.get("error_type") in {
                "empty_response", "api_error", "provider_exception",
            }
            attempt_record["retryable"] = retryable
            attempts.append(attempt_record)
            previous_failure = error
            if not retryable:
                return _mission_failure(
                    "generation_failed",
                    error,
                    attempts,
                    best_attempt,
                )
            attempt_index += 1
            continue

        image = result.get("image")
        if not isinstance(image, str) or not image.strip():
            attempt_record["retryable"] = True
            attempts.append(attempt_record)
            previous_failure = "generation succeeded without a deliverable image"
            attempt_index += 1
            continue

        deterministic_qc = deterministic(image, aspect_ratio=aspect_ratio)
        attempt_record["deterministic_qc"] = deterministic_qc.to_dict()
        if deterministic_qc.fatal:
            attempt_record["qc"] = deterministic_qc.to_dict()
            attempts.append(attempt_record)
            previous_failure = ", ".join(deterministic_qc.issues) or deterministic_qc.summary
            attempt_index += 1
            continue

        analysis = await _maybe_await(inspector(image, attempt_prompt))
        vision_qc = evaluate_visual_qc(str(analysis or ""), prompt=attempt_prompt)
        attempt_record["vision_qc"] = vision_qc.to_dict()
        attempt_record["qc"] = vision_qc.to_dict()
        attempt_record["image"] = image
        attempt_record["accepted"] = deterministic_qc.passed and vision_qc.passed
        attempts.append(attempt_record)

        if best_attempt is None or vision_qc.score > best_attempt["qc"]["score"]:
            best_attempt = attempt_record

        if attempt_record["accepted"]:
            return {
                "success": True,
                "image": image,
                "error": None,
                "error_type": None,
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "budget": budget,
                "max_attempts": max_attempts,
                "attempt_count": len(attempts),
                "strategy": strategy,
                "best": _public_attempt(attempt_record),
                "attempts": [_public_attempt(attempt) for attempt in attempts],
            }

        previous_failure = _retry_feedback(deterministic_qc, vision_qc)
        if (
            attempt_index >= max_attempts
            and _should_extend_for_near_miss(best_attempt)
            and max_attempts < attempt_cap
        ):
            max_attempts += 1
            strategy["extensions"].append("qc-near-miss")
        attempt_index += 1

    return _mission_failure(
        "qc_failed",
        "No generated candidate passed visual QC.",
        attempts,
        best_attempt,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        budget=budget,
        max_attempts=max_attempts,
        strategy=strategy,
    )


def _default_generate_once(**kwargs: Any) -> str:
    args = {
        "prompt": kwargs.get("prompt", ""),
        "aspect_ratio": kwargs.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
    }
    refs = kwargs.get("reference_images")
    if refs:
        args["reference_images"] = refs
    return _handle_image_generate(args)


async def _default_inspect_image(image_path: str, attempt_prompt: str) -> str:
    from tools.vision_tools import vision_analyze_tool

    qc_prompt = (
        "Evaluate this generated image for delivery quality. Return compact JSON "
        "with keys: quality_score 0-100, adherence_score 0-100, fatal_issues "
        "array, issues array, summary string. Treat semantic mismatch against "
        "the prompt, visible blur, deformed faces, warped hands, extra or "
        "missing fingers, malformed limbs, heavy artifacts, unreadable intended "
        "text, or reference-image drift as serious issues. Prompt:\n"
        f"{attempt_prompt}"
    )
    raw = await vision_analyze_tool(image_path, qc_prompt)
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict) and isinstance(payload.get("analysis"), str):
            return payload["analysis"]
    except Exception:
        pass
    return raw


async def _handle_image_generate_mission(args: Dict[str, Any], **kw: Any) -> str:
    prompt = args.get("prompt", "")
    if not prompt:
        return tool_error("prompt is required for image generation", success=False)
    result = await run_image_generation_mission(
        prompt=prompt,
        aspect_ratio=args.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
        budget=args.get("budget", _DEFAULT_BUDGET),
        reference_images=args.get("reference_images"),
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


def check_image_mission_requirements() -> bool:
    if not check_image_generation_requirements():
        return False
    try:
        from tools.vision_tools import check_vision_requirements
        return bool(check_vision_requirements())
    except Exception:
        logger.debug("image_generate_mission unavailable: vision requirement check failed")
        return False


def _mission_failure(
    error_type: str,
    error: str,
    attempts: List[Dict[str, Any]],
    best_attempt: Optional[Dict[str, Any]],
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "success": False,
        "image": None,
        "error": error,
        "error_type": error_type,
        "attempt_count": len(attempts),
        "attempts": [_public_attempt(attempt) for attempt in attempts],
    }
    if best_attempt is not None:
        payload["best_candidate"] = _public_attempt(best_attempt)
    payload.update(extra)
    return payload


def _expected_aspect_ratio(aspect_ratio: str) -> Optional[float]:
    if aspect_ratio == "square":
        return 1.0
    if aspect_ratio == "landscape":
        return 16 / 9
    if aspect_ratio == "portrait":
        return 9 / 16
    return None


def _strategy_attempt_cap(budget: str, base_attempts: int) -> int:
    budget = budget if budget in _VALID_BUDGETS else _DEFAULT_BUDGET
    if budget == "aggressive":
        return 8
    if budget == "conservative":
        return base_attempts
    return 8


def _should_extend_for_near_miss(best_attempt: Optional[Dict[str, Any]]) -> bool:
    if not best_attempt:
        return False
    qc = best_attempt.get("qc")
    if not isinstance(qc, dict):
        return False
    if bool(qc.get("fatal")):
        return False
    try:
        score = int(qc.get("score", 0))
    except (TypeError, ValueError):
        return False
    return QC_NEAR_MISS_THRESHOLD <= score < QC_PASS_THRESHOLD


def _retry_feedback(
    deterministic_qc: DeterministicQcReport,
    vision_qc: VisualQcReport,
) -> str:
    issues = list(deterministic_qc.issues) + list(vision_qc.issues)
    if issues:
        return ", ".join(_dedupe_preserve_order(issues))
    return vision_qc.summary or deterministic_qc.summary


def _public_attempt(attempt: Dict[str, Any]) -> Dict[str, Any]:
    result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
    public = {
        "attempt_index": attempt.get("attempt_index"),
        "accepted": bool(attempt.get("accepted")),
        "image": attempt.get("image") or result.get("image"),
        "error_type": result.get("error_type"),
        "error": result.get("error"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "deterministic_qc": attempt.get("deterministic_qc"),
        "vision_qc": attempt.get("vision_qc"),
        "qc": attempt.get("qc"),
    }
    return {key: value for key, value in public.items() if value is not None}


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


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    candidates = [raw]
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_score(value: Any) -> Optional[int]:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _normalize_issues(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _normalize_issue_name(value: str) -> str:
    lower = value.strip().lower()
    text = lower.replace("-", "_").replace(" ", "_")
    if _has_semantic_mismatch(lower):
        return "semantic_mismatch"
    if _has_unreadable_text_issue(lower):
        return "unreadable_text"
    if _has_reference_drift_issue(lower):
        return "reference_drift"
    if _has_blur_issue(lower):
        return "blur"
    if _has_deformed_anatomy_issue(lower):
        return "deformed_anatomy"
    if "artifact" in text or "melt" in text:
        return "heavy_artifacts"
    if "low" in text and "quality" in text:
        return "low_quality"
    return text or "unspecified"


def _issues_from_text(text: str) -> List[str]:
    lower = (text or "").lower()
    issues: List[str] = []
    if _has_semantic_mismatch(lower):
        issues.append("semantic_mismatch")
    if _has_unreadable_text_issue(lower):
        issues.append("unreadable_text")
    if _has_reference_drift_issue(lower):
        issues.append("reference_drift")
    if _has_blur_issue(lower):
        issues.append("blur")
    if _has_deformed_anatomy_issue(lower):
        issues.append("deformed_anatomy")
    if any(pattern in lower for pattern in (
        "heavy artifact", "obvious artifact", "melted detail", "glitch",
        "warped detail",
    )):
        issues.append("heavy_artifacts")
    if any(pattern in lower for pattern in (
        "could not be analyzed", "could not analyze", "vision api rejected",
        "problem with the request", "error analyzing image",
        "does not support vision",
    )):
        issues.append("qc_unavailable")
    if "low quality" in lower or "low-resolution" in lower or "low resolution" in lower:
        issues.append("low_quality")
    return _dedupe_preserve_order(issues)


def _has_semantic_mismatch(lower: str) -> bool:
    return any(pattern in lower for pattern in (
        "semantic mismatch", "does not match the prompt", "doesn't match the prompt",
        "wrong subject", "incorrect subject", "different subject",
        "not the requested", "not what was requested",
    ))


def _has_unreadable_text_issue(lower: str) -> bool:
    return "text" in lower and any(pattern in lower for pattern in (
        "unreadable", "illegible", "gibberish", "garbled", "misspelled",
        "misspelling", "not readable", "cannot be read", "can't be read",
        "unintelligible",
    ))


def _has_reference_drift_issue(lower: str) -> bool:
    return any(pattern in lower for pattern in (
        "reference drift", "reference image drift", "identity drift",
        "reference mismatch", "does not match the reference",
        "doesn't match the reference", "deviates from the reference",
        "reference identity changed", "identity changed",
    ))


def _has_blur_issue(lower: str) -> bool:
    if any(negated in lower for negated in (
        "not blurry", "not blurred", "no blur", "no visible blur",
        "sharp and not", "crisp and not",
    )):
        return False
    return any(pattern in lower for pattern in (
        "blur", "blurry", "blurred", "visibly blurry", "out of focus",
        "soft focus", "not sharp",
    ))


def _has_deformed_anatomy_issue(lower: str) -> bool:
    if re.search(r"\b(handbag|handle|handrail|handwritten)\b", lower):
        lower = re.sub(r"\b(handbag|handle|handrail|handwritten)\b", "", lower)
    return any(pattern in lower for pattern in (
        "deformed", "distorted anatomy", "warped finger", "warped hand",
        "extra finger", "missing finger", "malformed limb", "bad hand",
        "mangled", "unnatural hand", "extra limb", "extra fingers",
        "missing fingers", "malformed limbs", "warped hands",
    ))


def _score_from_text(raw: str, issues: List[str]) -> int:
    lower = (raw or "").lower()
    score = 88
    if "sharp" in lower or "crisp" in lower:
        score += 5
    if "coherent anatomy" in lower or "natural hands" in lower:
        score += 5
    penalties = {
        "blur": 35,
        "deformed_anatomy": 45,
        "heavy_artifacts": 30,
        "low_quality": 25,
        "qc_unavailable": 88,
        "semantic_mismatch": 45,
        "unreadable_text": 40,
        "reference_drift": 40,
    }
    for issue in issues:
        score -= penalties.get(issue, 12)
    return max(0, min(100, score))


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


IMAGE_GENERATE_MISSION_SCHEMA = {
    "name": "image_generate_mission",
    "description": (
        "Generate a high-quality image as a bounded mission with hybrid QC: "
        "plan task-level attempts, rewrite Codex image2-friendly prompt "
        "variants, run deterministic file/pixel sanity checks, run vision QC "
        "for semantic mismatch, unreadable text, reference drift, blur, "
        "deformed anatomy, and heavy artifacts, then retry with QC feedback "
        "until the task budget is exhausted or a deliverable candidate passes. "
        "Use this instead of plain image_generate when the user cares about "
        "final image quality, reference fidelity, avoiding malformed anatomy, "
        "readable text, or wants Hermes to try multiple approaches."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The user's target image. Include must-have visual details.",
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

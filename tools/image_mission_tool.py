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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from agent.image_gen_provider import DEFAULT_ASPECT_RATIO, VALID_ASPECT_RATIOS
from tools.environments.base import touch_activity_if_due
from tools.image_generation_tool import (
    _call_image_prompt_preprocessor,
    _handle_image_generate,
    _read_image_prompt_preprocessor_config,
    _normalize_image_generate_refs,
    check_image_generation_requirements,
)
from tools.image2_adaptive_mediator import (
    MediatedImagePrompt,
    mediate_image2_prompt as _mediate_image2_prompt,
    read_image2_adaptive_mediator_config as _read_image2_adaptive_mediator_config,
    record_image2_mediator_attempt as _record_image2_mediator_attempt,
)
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

QC_PASS_THRESHOLD = 70
QC_NEAR_MISS_THRESHOLD = 65
QC_MIN_ADHERENCE_SCORE = 70
_DEFAULT_BUDGET = "task"
_VALID_BUDGETS = ("task", "conservative", "aggressive")
_MAX_ATTEMPT_CAP = 4
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
        return 2
    if budget == "aggressive":
        return 4
    lowered = (prompt or "").lower()
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
    """Read optional ``image_gen.mission.max_attempts`` from config.yaml."""
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


def _rewrite_sensitive_image2_language(prompt: str) -> str:
    text = (prompt or "").strip()
    replacements = (
        ("性感美女", "adult fashion model with elegant, confident styling"),
        ("性感", "elegant fashion-editorial"),
        ("美女", "adult fashion model"),
        ("辣妹", "adult fashion model"),
        ("hot girl", "adult fashion model"),
        ("sexy girl", "adult fashion model with elegant editorial styling"),
        ("sexy woman", "adult fashion model with elegant editorial styling"),
    )
    for source, replacement in replacements:
        text = text.replace(source, replacement)
    return text.strip()


def compose_image2_prompt(
    prompt: str,
    *,
    attempt_index: int = 1,
    previous_failure: str = "",
    reference_images: Optional[List[str]] = None,
    recovery: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a structured Image2 prompt from a user request."""
    subject = _rewrite_sensitive_image2_language(prompt)
    if not subject:
        subject = "the requested subject"
    refs = reference_images or []
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

    parts = [
        "Create a polished Image2 result from this structured brief.",
        f"Subject: {subject}.",
        (
            "User intent anchors: "
            f"{subject}. Preserve the requested subject, setting, style, product details, "
            "composition, exclusions, and reference constraints as closely as policy allows. "
            "Do not replace the requested subject, setting, or style with a generic safer alternative."
        ),
        "Setting: Choose a coherent environment that supports the subject and keeps the scene readable.",
        "Composition: Use intentional camera framing, clean silhouette, natural perspective, and balanced negative space.",
        "Lighting: Use controlled editorial lighting with clear facial or product detail and no muddy shadows.",
        "Material and detail: Preserve believable textures, fabric, skin, product surfaces, and fine edges.",
        "Style: Photorealistic, commercial/editorial, tasteful, refined, and visually polished.",
        (
            "Reference handling: Preserve identity, palette, outfit, composition, and product details from "
            "reference images."
            if refs
            else "Reference handling: No reference images were provided; follow the written prompt."
        ),
        "Safety rewrite: Use adult, non-explicit, non-nude, fashion/editorial framing for people.",
        f"Attempt direction: {variant}",
        f"Constraints: {quality_guard}",
    ]
    if previous_failure:
        parts.append(f"Previous generation issue: {previous_failure[:300]}")
        parts.append(
            "Correction scope: Fix only the listed issue(s); keep every User intent anchor intact unless it is explicitly unsafe."
        )
    if recovery:
        action = str(recovery.get("action") or "retry_same_intent").strip()
        parts.append(f"Recovery action: {action}.")
        issues = [
            str(issue)
            for issue in recovery.get("issues", [])
            if str(issue).strip()
        ]
        if issues:
            parts.append(f"Recovery issues: {', '.join(issues)}.")
        correction = str(recovery.get("prompt_correction") or "").strip()
        if correction:
            parts.append(f"Prompt correction: {correction}")
        if action == "simplify_prompt":
            parts.append(
                "Simplify the prompt structure and remove only unsupported or overly dense wording; keep the requested subject, setting, style, and constraints."
            )
        parts.append(
            "Do not switch to a generic safer subject, generic style, unrelated provider fallback, or unrelated stock-image direction."
        )
    return "\n\n".join(part for part in parts if part)


def build_attempt_prompt(
    prompt: str,
    attempt_index: int,
    *,
    previous_failure: str = "",
    reference_images: Optional[List[str]] = None,
    recovery: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a Codex image2-friendly prompt variant for this attempt."""
    return compose_image2_prompt(
        prompt,
        attempt_index=attempt_index,
        previous_failure=previous_failure,
        reference_images=reference_images,
        recovery=recovery,
    )


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
        if adherence_score is not None and adherence_score < QC_MIN_ADHERENCE_SCORE:
            issues = _dedupe_preserve_order(issues + ["semantic_mismatch"])
            fatal = True
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


def _new_mission_activity_state() -> Dict[str, float]:
    now = time.monotonic()
    return {
        "last_touch": now - 999.0,
        "start": now,
        "interval": 10.0,
    }


def _touch_mission_activity(state: Dict[str, float], label: str) -> None:
    try:
        touch_activity_if_due(state, label)
    except Exception:
        pass


async def run_image_generation_mission(
    *,
    prompt: str,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    budget: str = _DEFAULT_BUDGET,
    reference_images: Optional[List[str]] = None,
    max_attempts: Optional[int] = None,
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
    original_prompt = prompt
    mediated: Optional[MediatedImagePrompt] = None
    mediator_config = _read_image2_adaptive_mediator_config()
    if mediator_config.get("enabled"):
        preprocessor_config = _read_image_prompt_preprocessor_config()

        def draft_with_config(user_prompt: str) -> Optional[str]:
            if not preprocessor_config.get("enabled"):
                return None
            return _call_image_prompt_preprocessor(user_prompt, preprocessor_config)

        try:
            mediated = _mediate_image2_prompt(
                prompt,
                config=mediator_config,
                preprocessor_config=preprocessor_config,
                draft_fn=draft_with_config,
            )
            if mediated.final_prompt.strip():
                prompt = mediated.final_prompt.strip()
                logger.info(
                    "Image2 adaptive mediator applied to mission strategy=%s (%d -> %d chars)",
                    mediated.strategy,
                    len(original_prompt or ""),
                    len(prompt),
                )
        except Exception as exc:
            logger.info("Image2 adaptive mediator unavailable for mission: %s", exc)

    base_attempts = resolve_attempt_budget(prompt, budget=budget, reference_images=refs)
    configured_attempt_cap = _coerce_attempt_cap(max_attempts)
    max_attempts = min(base_attempts, configured_attempt_cap) if configured_attempt_cap else base_attempts
    attempt_cap = _strategy_attempt_cap(budget, base_attempts)
    if configured_attempt_cap:
        attempt_cap = min(attempt_cap, configured_attempt_cap)
    strategy: Dict[str, Any] = {
        "qc_mode": "hybrid",
        "recovery_controller": "image2_state_machine",
        "fallback_policy": "preserve_intent_no_generic_fallback",
        "base_attempts": base_attempts,
        "attempt_cap": attempt_cap,
        "extensions": [],
    }
    if configured_attempt_cap:
        strategy["configured_attempt_cap"] = configured_attempt_cap
    generator = generate_once or _default_generate_once
    inspector = inspect_image or _default_inspect_image
    deterministic = deterministic_check or evaluate_deterministic_qc

    attempts: List[Dict[str, Any]] = []
    best_attempt: Optional[Dict[str, Any]] = None
    previous_failure = ""
    previous_recovery: Optional[Dict[str, Any]] = None
    learning_corrections: List[str] = []
    activity_state = _new_mission_activity_state()

    attempt_index = 1
    while attempt_index <= max_attempts:
        _touch_mission_activity(
            activity_state,
            f"image mission attempt {attempt_index}/{max_attempts}: generating",
        )
        attempt_prompt = build_attempt_prompt(
            prompt,
            attempt_index,
            previous_failure=previous_failure,
            reference_images=refs,
            recovery=previous_recovery,
        )
        raw_result = generator(
            prompt=attempt_prompt,
            aspect_ratio=aspect_ratio,
            reference_images=refs,
            attempt_index=attempt_index,
        )
        _touch_mission_activity(
            activity_state,
            f"image mission attempt {attempt_index}/{max_attempts}: generation complete",
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
            rewrite_prompt = bool(result.get("rewrite_prompt")) or result.get("error_type") == "policy_refusal"
            retryable = rewrite_prompt or bool(result.get("retryable")) or result.get("error_type") in {
                "empty_response", "api_error", "provider_exception",
            }
            recovery = _generation_recovery(result)
            attempt_record["recovery"] = recovery
            _append_learning_correction(learning_corrections, recovery)
            attempt_record["retryable"] = retryable
            if rewrite_prompt:
                attempt_record["rewrite_prompt"] = True
            attempts.append(attempt_record)
            previous_failure = _generation_retry_feedback(result)
            previous_recovery = recovery
            if not retryable:
                return _mission_failure(
                    "generation_failed",
                    error,
                    attempts,
                    best_attempt,
                    learning_corrections=learning_corrections,
                )
            attempt_index += 1
            continue

        image = result.get("image")
        if not isinstance(image, str) or not image.strip():
            attempt_record["retryable"] = True
            recovery = _generation_recovery({
                "error_type": "missing_image",
                "error": "generation succeeded without a deliverable image",
            })
            attempt_record["recovery"] = recovery
            _append_learning_correction(learning_corrections, recovery)
            attempts.append(attempt_record)
            previous_failure = "generation succeeded without a deliverable image"
            previous_recovery = recovery
            attempt_index += 1
            continue

        _touch_mission_activity(
            activity_state,
            f"image mission attempt {attempt_index}/{max_attempts}: deterministic QC",
        )
        deterministic_qc = deterministic(image, aspect_ratio=aspect_ratio)
        attempt_record["deterministic_qc"] = deterministic_qc.to_dict()
        if deterministic_qc.fatal:
            attempt_record["qc"] = deterministic_qc.to_dict()
            recovery = _qc_recovery(deterministic_qc, None)
            attempt_record["recovery"] = recovery
            _append_learning_correction(learning_corrections, recovery)
            attempts.append(attempt_record)
            previous_failure = ", ".join(deterministic_qc.issues) or deterministic_qc.summary
            previous_recovery = recovery
            attempt_index += 1
            continue

        _touch_mission_activity(
            activity_state,
            f"image mission attempt {attempt_index}/{max_attempts}: vision QC",
        )
        analysis = await _maybe_await(inspector(image, attempt_prompt))
        _touch_mission_activity(
            activity_state,
            f"image mission attempt {attempt_index}/{max_attempts}: QC complete",
        )
        vision_qc = evaluate_visual_qc(str(analysis or ""), prompt=attempt_prompt)
        attempt_record["vision_qc"] = vision_qc.to_dict()
        attempt_record["qc"] = vision_qc.to_dict()
        attempt_record["image"] = image
        attempt_record["accepted"] = deterministic_qc.passed and vision_qc.passed
        if not attempt_record["accepted"]:
            recovery = _qc_recovery(deterministic_qc, vision_qc)
            attempt_record["recovery"] = recovery
            _append_learning_correction(learning_corrections, recovery)
        attempts.append(attempt_record)

        if best_attempt is None or vision_qc.score > best_attempt["qc"]["score"]:
            best_attempt = attempt_record

        if attempt_record["accepted"]:
            return _finalize_mediated_mission_result({
                "success": True,
                "image": image,
                "error": None,
                "error_type": None,
                "prompt": original_prompt,
                "mediated_prompt": prompt if mediated is not None else None,
                "aspect_ratio": aspect_ratio,
                "budget": budget,
                "max_attempts": max_attempts,
                "attempt_count": len(attempts),
                "strategy": strategy,
                "best": _public_attempt(attempt_record),
                "attempts": [_public_attempt(attempt) for attempt in attempts],
                "learning_corrections": learning_corrections,
            }, mediated, mediator_config)

        previous_failure = _retry_feedback(deterministic_qc, vision_qc)
        previous_recovery = attempt_record.get("recovery")
        if (
            attempt_index >= max_attempts
            and _should_extend_for_near_miss(best_attempt)
            and max_attempts < attempt_cap
        ):
            max_attempts += 1
            strategy["extensions"].append("qc-near-miss")
        attempt_index += 1

    return _finalize_mediated_mission_result(_mission_failure(
        "qc_failed",
        "No generated candidate passed visual QC.",
        attempts,
        best_attempt,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        budget=budget,
        max_attempts=max_attempts,
        strategy=strategy,
        learning_corrections=learning_corrections,
    ), mediated, mediator_config)


def _finalize_mediated_mission_result(
    payload: Dict[str, Any],
    mediated: Optional[MediatedImagePrompt],
    mediator_config: Dict[str, Any],
) -> Dict[str, Any]:
    if mediated is None:
        return payload
    success = bool(payload.get("success"))
    error_type = str(payload.get("error_type") or "").strip()
    status = "success" if success else "failed"
    failure_class: List[str] = []
    if not success:
        failure_class = [error_type or "failed"]
        if error_type == "policy_refusal":
            status = "blocked"
            failure_class = ["blocked"]
    payload["adaptive_mediator"] = mediated.to_public_dict()
    _record_image2_mediator_attempt(
        mediated,
        image2_status=status,
        feedback_source="visual_inspection" if success else "image2_error",
        failure_class=failure_class,
        config=mediator_config,
        notes=str(payload.get("error") or "")[:300],
    )
    return payload


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
    requested_cap = _coerce_attempt_cap(args.get("max_attempts"))
    configured_cap = _read_configured_mission_attempt_cap()
    caps = [cap for cap in (requested_cap, configured_cap) if cap is not None]
    result = await run_image_generation_mission(
        prompt=prompt,
        aspect_ratio=args.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
        budget=args.get("budget", _DEFAULT_BUDGET),
        reference_images=args.get("reference_images"),
        max_attempts=min(caps) if caps else None,
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
        return 4
    return base_attempts


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


def _generation_retry_feedback(result: Dict[str, Any]) -> str:
    error_type = str(result.get("error_type") or "generation_failed").strip() or "generation_failed"
    if error_type == "policy_refusal":
        return (
            "policy_refusal: rewrite in adult, non-explicit, non-nude fashion/editorial language "
            "while preserving User intent anchors."
        )
    if error_type == "empty_response":
        return "empty_response: request a complete final PNG and preserve User intent anchors."
    if error_type in {"timeout", "transient_network", "stream_parse_error", "api_error", "provider_exception"}:
        return f"{error_type}: retry generation without changing User intent anchors."
    return error_type


def _generation_recovery(result: Dict[str, Any]) -> Dict[str, Any]:
    error_type = str(result.get("error_type") or "generation_failed").strip() or "generation_failed"
    if error_type == "empty_response":
        return {
            "state": "empty_response",
            "action": "simplify_prompt",
            "fallback_allowed": False,
            "preserve_intent": True,
        }
    if error_type == "policy_refusal":
        return {
            "state": "generation_failed",
            "action": "rewrite_prompt",
            "fallback_allowed": False,
            "preserve_intent": True,
            "issues": ["policy_refusal"],
            "prompt_correction": (
                "Rewrite only unsafe phrasing into adult, non-explicit, fashion/editorial language while preserving the requested subject, style, and composition."
            ),
        }
    if error_type in {"timeout", "transient_network", "stream_parse_error", "api_error", "provider_exception"}:
        return {
            "state": "generation_failed",
            "action": "retry_same_intent",
            "fallback_allowed": False,
            "preserve_intent": True,
            "issues": [error_type],
            "prompt_correction": "Retry with the same visual intent and a cleaner, less dense prompt structure.",
        }
    return {
        "state": "generation_failed",
        "action": "retry_same_intent",
        "fallback_allowed": False,
        "preserve_intent": True,
        "issues": [error_type],
    }


def _qc_recovery(
    deterministic_qc: DeterministicQcReport,
    vision_qc: Optional[VisualQcReport],
) -> Dict[str, Any]:
    issues = list(deterministic_qc.issues)
    if vision_qc is not None:
        issues.extend(vision_qc.issues)
    issues = _dedupe_preserve_order(issues)
    return {
        "state": "qc_failed",
        "action": "repair_prompt",
        "fallback_allowed": False,
        "preserve_intent": True,
        "issues": issues,
        "prompt_correction": _prompt_correction_for_issues(issues),
    }


def _prompt_correction_for_issues(issues: List[str]) -> str:
    issue_set = set(issues)
    corrections: List[str] = []
    if "semantic_mismatch" in issue_set:
        corrections.append(
            "Restore the requested subject, setting, style, composition, and must-have details before improving aesthetics."
        )
    if "reference_drift" in issue_set:
        corrections.append(
            "Re-anchor identity, outfit, palette, and source-image visual DNA; do not invent a new character or product."
        )
    if "unreadable_text" in issue_set:
        corrections.append(
            "Simplify typography and make intended text large, clean, and readable; omit decorative pseudo-text."
        )
    if "blur" in issue_set:
        corrections.append(
            "Increase sharp focus, crisp edges, and camera-real detail while preserving the original framing."
        )
    if "deformed_anatomy" in issue_set:
        corrections.append(
            "Prioritize natural hands, coherent limbs, realistic proportions, and clean anatomy."
        )
    if "blank_or_nearly_uniform" in issue_set or "empty_image_file" in issue_set or "missing_image" in issue_set:
        corrections.append(
            "Request a complete final PNG with visible subject detail and the same user intent anchors."
        )
    if "heavy_artifacts" in issue_set or "low_quality" in issue_set:
        corrections.append(
            "Reduce visual complexity, clean up artifacts, and keep the same subject instead of changing direction."
        )
    if not corrections:
        corrections.append(
            "Repair the listed QC issues while preserving the user's original subject and style."
        )
    return " ".join(corrections)


def _append_learning_correction(corrections: List[str], recovery: Dict[str, Any]) -> None:
    correction = str(recovery.get("prompt_correction") or "").strip()
    if correction and correction not in corrections:
        corrections.append(correction)


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
        "recovery": attempt.get("recovery"),
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
        "deformed anatomy, and heavy artifacts, then run an Image2 recovery state machine "
        "for empty_response / qc_failed without switching to a generic fallback, "
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
            "max_attempts": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_ATTEMPT_CAP,
                "description": (
                    "Optional hard cap for generation attempts. Runtime config "
                    "image_gen.mission.max_attempts can also cap this value."
                ),
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

from __future__ import annotations

from typing import Any

from agent.visual.aspect_policy import select_video_aspect_ratio


DEFAULT_SUPPORTED_ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"]
_MOTION_HINT = (
    "natural real-time motion, normal playback speed, clear continuous motion, "
    "visible subject, camera, or environmental movement, purposeful camera movement, "
    "avoid slow cinematic-only push-in, not slow motion"
)
_MOTION_REQUIRED_PHRASES = (
    "natural real-time motion",
    "normal playback speed",
    "clear continuous motion",
    "visible subject, camera, or environmental movement",
    "avoid slow cinematic-only push-in",
    "not slow motion",
)
_EXPLICIT_SLOW_MOTION_TOKENS = (
    "slow motion",
    "slow-motion",
    "slo-mo",
    "slomo",
    "慢動作",
    "慢镜头",
    "慢鏡頭",
)


def build_hardened_video_request(
    *,
    prompt: str,
    requested_aspect_ratio: str | None,
    source_media: dict[str, Any],
    supported_aspect_ratios: list[str] | None = None,
) -> dict[str, Any]:
    supported = supported_aspect_ratios or DEFAULT_SUPPORTED_ASPECT_RATIOS
    source_width = _int_or_none(source_media.get("width"))
    source_height = _int_or_none(source_media.get("height"))
    aspect_ratio = select_video_aspect_ratio(
        source_width=source_width,
        source_height=source_height,
        requested_aspect_ratio=requested_aspect_ratio,
        supported=supported,
        default="16:9",
    )
    return {
        "prompt": _with_motion_hint(prompt),
        "aspect_ratio": aspect_ratio,
        "metadata": {
            "motion_mode": _motion_mode(prompt),
            "source_aspect_ratio": aspect_ratio if source_width and source_height else None,
            "no_stretch": True,
        },
    }


def classify_video_feedback_repair(parsed_feedback: dict[str, Any]) -> dict[str, Any]:
    issues = parsed_feedback.get("issues") if isinstance(parsed_feedback.get("issues"), list) else []
    issue_set = {str(issue) for issue in issues}
    if issue_set & {"static_video", "slow_motion", "motion_bad", "too_slow"}:
        return {
            "decision": "retry_video",
            "reason": "static_or_slow_motion_feedback",
            "motion_mode": "natural_motion",
        }
    return {"decision": "observe", "reason": "no_video_motion_issue"}


def _with_motion_hint(prompt: str) -> str:
    clean = str(prompt or "").strip()
    lower = clean.lower()
    if _explicit_slow_motion_requested(clean):
        return clean
    if all(phrase in lower for phrase in _MOTION_REQUIRED_PHRASES):
        return clean
    if not clean:
        return _MOTION_HINT
    if "natural real-time motion" in lower and "not slow motion" in lower:
        missing = [phrase for phrase in _MOTION_REQUIRED_PHRASES if phrase not in lower]
        return f"{clean}. {', '.join(missing)}."
    return f"{clean}. {_MOTION_HINT}."


def _motion_mode(prompt: str) -> str:
    if _explicit_slow_motion_requested(prompt):
        return "slow_motion_requested"
    return "natural_motion"


def _explicit_slow_motion_requested(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    return any(token in lowered for token in _EXPLICIT_SLOW_MOTION_TOKENS)


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

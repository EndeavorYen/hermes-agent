from __future__ import annotations

from typing import Any

from agent.visual.aspect_policy import nearest_aspect_ratio


def plan_visual_recovery(
    request: dict[str, Any],
    failure: dict[str, Any],
    *,
    retry_budget_remaining: int,
) -> dict[str, Any]:
    failure_class = str(failure.get("failure_class") or "unknown")
    arguments = dict(request.get("arguments") or {})
    if retry_budget_remaining <= 0:
        return _decision("fail", "retry_budget_exhausted", arguments, failure_class, retry_budget_remaining)
    if failure.get("retryable") is False:
        return _decision("fail", "provider_failure_not_retryable", arguments, failure_class, retry_budget_remaining)

    if failure_class == "content_moderation":
        if failure.get("safe_reframe_allowed") is not True:
            return _decision(
                "ask_user",
                "content_moderation_needs_user_choice",
                arguments,
                failure_class,
                retry_budget_remaining,
            )
        arguments["prompt"] = _safe_reframe_prompt(arguments.get("prompt") or request.get("prompt"))
        return _decision(
            "retry",
            "content_moderation_safe_reframe",
            arguments,
            failure_class,
            retry_budget_remaining,
        )

    if failure_class == "timeout":
        arguments["duration"] = max(1, min(_int(arguments.get("duration"), default=6), 12) // 2)
        if "candidate_budget" in arguments:
            arguments["candidate_budget"] = 1
        return _decision("retry", "timeout_reduce_work", arguments, failure_class, retry_budget_remaining)

    if failure_class == "unsupported_aspect_ratio":
        aspect_ratio = _nearest_supported_aspect(request)
        if aspect_ratio is None:
            return _decision("ask_user", "unsupported_aspect_ratio_needs_user_choice", arguments, failure_class, retry_budget_remaining)
        arguments["aspect_ratio"] = aspect_ratio
        return _decision(
            "retry",
            "unsupported_aspect_ratio_nearest_supported",
            arguments,
            failure_class,
            retry_budget_remaining,
        )

    if failure_class == "empty_response":
        arguments["prompt"] = _simplify_prompt(arguments.get("prompt") or request.get("prompt"))
        return _decision("retry", "empty_response_simplify_prompt", arguments, failure_class, retry_budget_remaining)

    if failure_class == "unsupported_reference":
        arguments = {
            key: value
            for key, value in arguments.items()
            if key not in {"reference_image_urls", "image_url"}
        }
        arguments["prompt"] = _text_only_reference_fallback_prompt(arguments.get("prompt") or request.get("prompt"))
        decision = _decision(
            "retry",
            "unsupported_reference_text_only_fallback",
            arguments,
            failure_class,
            retry_budget_remaining,
        )
        decision["removed_arguments"] = ["reference_image_urls", "image_url"]
        return decision

    if failure_class in {"rate_limited", "provider_unavailable"}:
        return _decision("retry", f"{failure_class}_retry_later", arguments, failure_class, retry_budget_remaining)

    return _decision("fail", "unknown_failure_no_recovery", arguments, failure_class, retry_budget_remaining)


def _decision(
    decision: str,
    reason: str,
    modified_arguments: dict[str, Any],
    failure_class: str,
    retry_budget_remaining: int,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "modified_arguments": modified_arguments,
        "user_visible_summary": _summary(decision, failure_class),
        "audit": {
            "failure_class": failure_class,
            "retry_budget_remaining": retry_budget_remaining,
        },
    }


def _safe_reframe_prompt(value: Any) -> str:
    prompt = str(value or "").strip()
    if not prompt:
        return "Create a professional, policy-compliant visual variant of the user's request."
    return (
        "Create a professional, policy-compliant editorial visual variant while preserving "
        f"the non-sensitive user intent: {prompt}"
    )


def _simplify_prompt(value: Any) -> str:
    prompt = str(value or "").strip()
    if not prompt:
        return "Create the requested visual with a simple clean composition."
    return f"Create a clean, simple version of this visual request: {prompt}"


def _text_only_reference_fallback_prompt(value: Any) -> str:
    prompt = str(value or "").strip()
    if not prompt:
        return "Create a text-only visual approximation without reference-image conditioning."
    return f"Create a text-only visual approximation without reference-image conditioning: {prompt}"


def _nearest_supported_aspect(request: dict[str, Any]) -> str | None:
    source_media = request.get("source_media") if isinstance(request.get("source_media"), dict) else {}
    supported = request.get("supported_aspect_ratios")
    if not isinstance(supported, list):
        supported = ["16:9", "9:16", "1:1"]
    width = _int(source_media.get("width"), default=0)
    height = _int(source_media.get("height"), default=0)
    return nearest_aspect_ratio(width, height, [str(item) for item in supported])


def _summary(decision: str, failure_class: str) -> str:
    if decision == "retry":
        return f"Provider failed with {failure_class}; retrying a bounded feasible variant."
    if decision == "ask_user":
        return f"Provider failed with {failure_class}; user choice is required before retry."
    return f"Provider failed with {failure_class}; no safe automatic recovery is available."


def _int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

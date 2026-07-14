from __future__ import annotations

import re
from typing import Any

from agent.visual.production_kernel.contract import compile_visual_intent_contract
from agent.visual.production_kernel.contract import visual_contract_hash
from agent.visual.production_kernel.providers import choose_visual_provider


_EXPLICIT_PROVIDER_SOURCES = {
    "direct_override",
    "explicit_override",
    "prompt_override",
    "user",
}


def attach_visual_production_kernel(
    original_prompt: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Attach provider-neutral contract and bounded policy to Visual Agent args."""
    result = dict(arguments)
    if _uses_planner_default_budget(result):
        result["candidate_budget"] = 1
    if isinstance(result.get("storyboard"), dict):
        storyboard = dict(result["storyboard"])
        if str(storyboard.get("candidate_budget_source") or "planner_default") == "planner_default":
            storyboard["candidate_budget_per_shot"] = 1
        result["storyboard"] = storyboard

    provider = str(result.get("image_provider") or "xai").strip()
    provider_source = str(result.get("image_provider_source") or "visual_agent_default").strip()
    explicit_provider = provider if provider_source in _EXPLICIT_PROVIDER_SOURCES else None
    authorized = _authorized_providers(result, provider)
    profiles = result.get("provider_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    unavailable = result.get("unavailable_image_providers")
    if not isinstance(unavailable, (list, tuple)):
        unavailable = ()
    provider_decision = choose_visual_provider(
        explicit_provider=explicit_provider,
        default_provider=provider,
        authorized_providers=authorized,
        profiles=profiles,
        unavailable_providers=unavailable,
    )
    if provider_decision.provider:
        result["image_provider"] = provider_decision.provider
    if provider_decision.reason == "measured_quality_profile":
        result["image_provider_source"] = "visual_kernel_quality_profile"

    contract = compile_visual_intent_contract(
        original_prompt,
        {
            "primary_subject": _primary_subject(original_prompt),
            "observable_action": result.get("observable_action"),
            "decisive_moment": result.get("decisive_moment"),
            "focal_point": result.get("focal_point"),
            "composition": result.get("composition"),
            "style": result.get("style"),
            "audience_effect": result.get("audience_effect"),
            "reference_roles": _reference_roles(result.get("reference_binding")),
            "required_details": result.get("required_details"),
            "forbidden_details": result.get("forbidden_details"),
            "acceptance_criteria": result.get("acceptance_criteria"),
            "aspect_ratio": result.get("aspect_ratio"),
            "truth_mode": result.get("truth_mode"),
        },
    )
    result.update(
        {
            "visual_production_kernel": True,
            "max_generated_repairs": _bounded_repair_budget(
                result.get("max_generated_repairs")
            ),
            "visual_intent_contract": contract.to_canonical_dict(),
            "visual_contract_hash": visual_contract_hash(contract),
            "provider_decision": provider_decision.to_record(),
        }
    )
    return result


def _uses_planner_default_budget(arguments: dict[str, Any]) -> bool:
    return (
        "candidate_budget" in arguments
        and str(arguments.get("candidate_budget_source") or "planner_default") == "planner_default"
    )


def _authorized_providers(arguments: dict[str, Any], current: str) -> tuple[str, ...]:
    configured = arguments.get("authorized_image_providers")
    values = list(configured) if isinstance(configured, (list, tuple)) else []
    values.extend((current, "xai", "openai-codex", "grok-web-imagine"))
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _reference_roles(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    roles: list[dict[str, str]] = []
    for item in value.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = str(item.get("index") or "").strip()
        source = f"ref:{index}" if index else ""
        role = str(item.get("role_hint") or "").strip()
        if source and role:
            roles.append({"source": source, "role": role})
    return roles


def _bounded_repair_budget(value: Any) -> int:
    if value is None:
        return 1
    try:
        return max(0, min(1, int(value)))
    except (TypeError, ValueError):
        return 1


def _primary_subject(prompt: str) -> str:
    text = str(prompt or "").strip()
    for pattern in (
        r"主體(?:是|為)\s*([^，。；;\n]+)",
        r"(?:subject|featuring)\s*(?:is|:)?\s*([^.;\n]+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return text

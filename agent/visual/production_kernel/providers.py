from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Mapping


MIN_PROFILE_SAMPLES = 5
PROFILE_OVERRIDE_MARGIN = 0.05


@dataclass(frozen=True)
class ProviderDecision:
    provider: str | None
    reason: str
    available: bool
    evidence: dict[str, object]

    def to_record(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "reason": self.reason,
            "available": self.available,
            "evidence": dict(self.evidence),
        }


def choose_visual_provider(
    *,
    explicit_provider: str | None,
    default_provider: str,
    authorized_providers: tuple[str, ...] | list[str],
    profiles: Mapping[str, Mapping[str, Any]],
    unavailable_providers: tuple[str, ...] | list[str] = (),
) -> ProviderDecision:
    authorized = tuple(dict.fromkeys(_provider(value) for value in authorized_providers if _provider(value)))
    unavailable = {_provider(value) for value in unavailable_providers if _provider(value)}
    explicit = _provider(explicit_provider)
    default = _provider(default_provider)
    if explicit:
        is_authorized = explicit in authorized
        is_available = is_authorized and explicit not in unavailable
        return ProviderDecision(
            provider=explicit,
            reason="explicit_override" if is_available else "explicit_override_unavailable",
            available=is_available,
            evidence={
                "authorized": is_authorized,
                "unavailable": explicit in unavailable,
                "providers_evaluated": 1,
            },
        )

    available = [provider for provider in authorized if provider not in unavailable]
    if not available:
        return ProviderDecision(
            provider=None,
            reason="no_authorized_provider_available",
            available=False,
            evidence={"providers_evaluated": 0},
        )
    if default not in available:
        return ProviderDecision(
            provider=available[0],
            reason="provider_unavailable_fallback",
            available=True,
            evidence={
                "configured_default": default,
                "providers_evaluated": len(available),
            },
        )

    measured = [
        (provider, _profile_score(profiles.get(provider, {})))
        for provider in available
        if _sample_count(profiles.get(provider, {})) >= MIN_PROFILE_SAMPLES
    ]
    scores = {provider: score for provider, score in measured}
    best_provider = max(measured, key=lambda item: (item[1], item[0]))[0] if measured else default
    default_score = scores.get(default)
    best_score = scores.get(best_provider)
    if (
        best_provider != default
        and default_score is not None
        and best_score is not None
        and best_score >= default_score + PROFILE_OVERRIDE_MARGIN
    ):
        return ProviderDecision(
            provider=best_provider,
            reason="measured_quality_profile",
            available=True,
            evidence={
                "providers_evaluated": len(measured),
                "selected_score": round(best_score, 4),
                "default_score": round(default_score, 4),
                "minimum_samples": MIN_PROFILE_SAMPLES,
            },
        )
    return ProviderDecision(
        provider=default,
        reason="configured_default",
        available=True,
        evidence={
            "providers_evaluated": len(measured),
            "minimum_samples": MIN_PROFILE_SAMPLES,
        },
    )


def _profile_score(profile: Mapping[str, Any]) -> float:
    first_pass_rate = _rate(profile.get("first_pass_rate"))
    failure_rate = _rate(profile.get("failure_rate"))
    return first_pass_rate - failure_rate * 0.5


def _sample_count(profile: Mapping[str, Any]) -> int:
    try:
        return max(0, int(profile.get("sample_count") or 0))
    except (TypeError, ValueError):
        return 0


def _rate(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _provider(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "openai": "openai-codex",
        "openai-image2": "openai-codex",
        "image2": "openai-codex",
        "grok": "xai",
        "x.ai": "xai",
    }
    return aliases.get(text, text)

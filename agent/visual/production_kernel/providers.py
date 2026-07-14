from __future__ import annotations

import json
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


def build_provider_quality_profiles(
    ledger: Any,
    *,
    category: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build category-scoped provider profiles from first-candidate artifact QC."""
    try:
        requests = ledger._list("visual_requests")
        attempts = ledger._list("visual_attempts")
        judgments = ledger._list("visual_judgments")
    except Exception:
        return {}
    request_categories = {
        _row_id(request, "id", "request_id"): _request_category(request)
        for request in requests
        if isinstance(request, dict)
    }
    latest_judgment: dict[str, dict[str, Any]] = {}
    for judgment in judgments:
        if not isinstance(judgment, dict):
            continue
        if str(judgment.get("judge_name") or "").strip() != "visual_quality_judge":
            continue
        attempt_id = _row_id(judgment, "attempt_id")
        if attempt_id:
            latest_judgment[attempt_id] = judgment

    grouped: dict[str, dict[str, int]] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict) or _candidate_index(attempt) != 0:
            continue
        if category is not None:
            request_id = _row_id(attempt, "request_id")
            if request_categories.get(request_id) != category:
                continue
        provider = _provider(attempt.get("provider"))
        if not provider:
            continue
        counts = grouped.setdefault(
            provider,
            {"sample_count": 0, "first_pass_count": 0, "failure_count": 0},
        )
        counts["sample_count"] += 1
        if _attempt_failed(attempt):
            counts["failure_count"] += 1
            continue
        judgment = latest_judgment.get(_row_id(attempt, "id", "attempt_id"))
        if judgment is not None and _judgment_passed(judgment):
            counts["first_pass_count"] += 1

    return {
        provider: {
            "sample_count": counts["sample_count"],
            "first_pass_rate": _fraction(
                counts["first_pass_count"],
                counts["sample_count"],
            ),
            "failure_rate": _fraction(
                counts["failure_count"],
                counts["sample_count"],
            ),
        }
        for provider, counts in sorted(grouped.items())
    }


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


def _candidate_index(attempt: Mapping[str, Any]) -> int:
    try:
        return int(attempt.get("candidate_index") or 0)
    except (TypeError, ValueError):
        return 0


def _attempt_failed(attempt: Mapping[str, Any]) -> bool:
    status = str(attempt.get("status") or "").strip().lower()
    return status in {"failed", "error", "blocked"} or bool(
        attempt.get("error_type") or attempt.get("provider_error_type")
    )


def _judgment_passed(judgment: Mapping[str, Any]) -> bool:
    details = _mapping(judgment.get("details") or judgment.get("score_json"))
    quality_issues = details.get("quality_issues")
    if isinstance(quality_issues, (list, tuple, set)) and quality_issues:
        return False
    verdict = str(judgment.get("verdict") or "").strip().lower()
    if verdict in {"pass", "passed", "accept", "post", "selected"}:
        return True
    try:
        return float(judgment.get("score") or 0.0) >= 0.7
    except (TypeError, ValueError):
        return False


def _request_category(request: Mapping[str, Any]) -> str:
    intent = _mapping(
        request.get("normalized_intent") or request.get("normalized_intent_json")
    )
    return str(intent.get("category") or "").strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        if isinstance(decoded, Mapping):
            return decoded
    return {}


def _row_id(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _fraction(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator > 0 else 0.0

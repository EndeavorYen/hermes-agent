"""Best-effort visual generation tracking hooks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from agent.visual.artifact_store import ArtifactStore
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.error_taxonomy import normalize_visual_error_type
from agent.visual.source_context import get_visual_source_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualTrackingConfig:
    enabled: bool = True
    shadow_mode: bool = True
    ledger_path: Optional[Path] = None


def default_visual_ledger_path() -> Path:
    from hermes_constants import get_hermes_home

    config = read_visual_tracking_config()
    if config.ledger_path is not None:
        return config.ledger_path
    return get_hermes_home() / "visual" / "attempt_ledger.sqlite3"


def visual_tracking_enabled() -> bool:
    return read_visual_tracking_config().enabled


def read_visual_tracking_config() -> VisualTrackingConfig:
    from hermes_constants import get_config_path, get_hermes_home

    try:
        import yaml  # type: ignore

        config_path = get_config_path()
        with open(config_path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    section = raw.get("visual_tracking") or {}
    if not isinstance(section, dict):
        section = {}

    ledger_value = section.get("ledger_path")
    ledger_path: Optional[Path] = None
    if ledger_value is not None and str(ledger_value).strip():
        candidate = Path(str(ledger_value).strip()).expanduser()
        if not candidate.is_absolute():
            candidate = get_hermes_home() / candidate
        ledger_path = candidate

    return VisualTrackingConfig(
        enabled=_coerce_bool(section.get("enabled"), default=True),
        shadow_mode=_coerce_bool(section.get("shadow_mode"), default=True),
        ledger_path=ledger_path,
    )


def record_visual_generation_attempt(
    payload: Dict[str, Any],
    *,
    user_prompt: str,
    prompt_original: str,
    prompt_mediated: str,
    modality: str,
    operation: str,
    artifact_key: str,
    kind: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    request_id: Optional[str] = None,
    candidate_index: int = 0,
    strategy_id: Optional[str] = None,
    strategy_version: Optional[str] = None,
    prompt_negative: Optional[str] = None,
    parameters_requested: Optional[Dict[str, Any]] = None,
    parameters_effective: Optional[Dict[str, Any]] = None,
    input_artifacts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record one generated visual attempt and add visual IDs to *payload*.

    This function is intentionally best-effort for shadow mode. Generation
    results must not fail just because local evidence recording failed.
    """
    if not isinstance(payload, dict):
        return payload
    if not visual_tracking_enabled():
        return payload

    try:
        return _record_visual_generation_attempt(
            payload,
            user_prompt=user_prompt,
            prompt_original=prompt_original,
            prompt_mediated=prompt_mediated,
            modality=modality,
            operation=operation,
            artifact_key=artifact_key,
            kind=kind,
            provider=provider,
            model=model,
            request_id=request_id,
            candidate_index=candidate_index,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            prompt_negative=prompt_negative,
            parameters_requested=parameters_requested,
            parameters_effective=parameters_effective,
            input_artifacts=input_artifacts,
        )
    except Exception as exc:  # noqa: BLE001 - shadow-mode guard
        logger.debug("Visual generation tracking skipped: %s", exc, exc_info=True)
        return payload


def _record_visual_generation_attempt(
    payload: Dict[str, Any],
    *,
    user_prompt: str,
    prompt_original: str,
    prompt_mediated: str,
    modality: str,
    operation: str,
    artifact_key: str,
    kind: str,
    provider: Optional[str],
    model: Optional[str],
    request_id: Optional[str],
    candidate_index: int,
    strategy_id: Optional[str],
    strategy_version: Optional[str],
    prompt_negative: Optional[str],
    parameters_requested: Optional[Dict[str, Any]],
    parameters_effective: Optional[Dict[str, Any]],
    input_artifacts: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()

    success = bool(payload.get("success"))
    resolved_provider = (
        str(payload.get("provider") or provider or "").strip() or "unknown"
    )
    resolved_model = str(payload.get("model") or model or "").strip() or "unknown"
    visual_error_type = normalize_visual_error_type(
        payload.get("error_type"),
        success=success,
    )

    if request_id:
        ledger.update_request_status(
            request_id,
            "completed" if success else "failed",
        )
    else:
        source_context = get_visual_source_context()
        request_id = ledger.record_request(
            user_prompt=user_prompt,
            normalized_intent={
                "modality": modality,
                "operation": operation,
                "artifact_kind": kind,
            },
            modality=modality,
            operation=operation,
            conversation_id=(
                source_context.conversation_id if source_context else None
            ),
            user_id=source_context.user_id if source_context else None,
            platform=source_context.platform if source_context else None,
            channel_id=source_context.channel_id if source_context else None,
            thread_id=source_context.thread_id if source_context else None,
            message_id=source_context.message_id if source_context else None,
            status="completed" if success else "failed",
        )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=candidate_index,
        provider=resolved_provider,
        model=resolved_model,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        prompt_original=prompt_original,
        prompt_mediated=prompt_mediated,
        prompt_negative=prompt_negative,
        parameters_requested=parameters_requested,
        parameters_effective=parameters_effective,
        input_artifacts=input_artifacts,
        provider_request_id=_string_or_none(payload.get("request_id")),
        provider_error_type=None if success else visual_error_type,
        provider_error_message=(
            None if success else _string_or_none(payload.get("error"))
        ),
    )

    payload["visual_request_id"] = request_id
    payload["visual_attempt_id"] = attempt_id
    if not success:
        payload["visual_error_type"] = visual_error_type
        return payload

    artifact_value = payload.get(artifact_key)
    if not artifact_value:
        return payload

    store = ArtifactStore()
    artifact = store.import_local_file(
        str(artifact_value),
        request_id=request_id,
        attempt_id=attempt_id,
        kind=kind,
    )
    if not artifact.is_stable and str(artifact_value).lower().startswith(
        ("http://", "https://")
    ):
        artifact = store.describe_reference(
            str(artifact_value),
            request_id=request_id,
            attempt_id=attempt_id,
            kind=kind,
            artifact_id=artifact.artifact_id,
        )
    ledger.record_artifact(**artifact.to_ledger_kwargs())
    payload["visual_artifact_id"] = artifact.artifact_id
    return payload


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default

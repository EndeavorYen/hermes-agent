"""Best-effort visual generation tracking hooks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from agent.visual.artifact_store import ArtifactStore
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.error_taxonomy import normalize_visual_error_type

logger = logging.getLogger(__name__)


def default_visual_ledger_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "visual" / "attempt_ledger.sqlite3"


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
        request_id = ledger.record_request(
            user_prompt=user_prompt,
            normalized_intent={
                "modality": modality,
                "operation": operation,
                "artifact_kind": kind,
            },
            modality=modality,
            operation=operation,
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

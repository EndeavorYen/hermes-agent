from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.judges.deterministic import judge_artifact
from agent.visual.judges.quality import judge_visual_quality
from agent.visual.judges.vision import build_vision_judge_observation


VisionAnalyzer = Callable[[dict[str, Any]], Any]


def audit_independent_vision_judgments(
    db_path: str | Path,
    *,
    analyzer: VisionAnalyzer | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _report(db_path, [], created_count=0, error_count=0)
    ledger = VisualAttemptLedger(db_path)
    candidates = _candidate_feedback_artifacts(ledger)
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]
    created_count = 0
    error_count = 0
    if not dry_run:
        if analyzer is None:
            raise ValueError("analyzer is required unless dry_run is true")
        for artifact in candidates:
            try:
                observation = parse_vision_judge_analysis(analyzer(artifact))
                quality = _quality_from_observation(artifact, observation)
                ledger.record_judgment(
                    request_id=artifact.get("request_id") or "",
                    attempt_id=artifact.get("attempt_id") or "",
                    artifact_id=artifact.get("artifact_id") or artifact.get("id") or "",
                    judge_name="visual_quality_judge",
                    score=quality["confidence"],
                    verdict="pass" if quality["confidence"] >= 0.5 else "review",
                    details=quality,
                    metadata={
                        "source": "independent_vision_judge",
                        "judge_sources": quality.get("judge_sources", {}),
                        "uncertainty_reasons": quality.get("uncertainty_reasons", []),
                    },
                )
                created_count += 1
            except Exception:
                error_count += 1
    return _report(db_path, candidates, created_count=created_count, error_count=error_count)


def parse_vision_judge_analysis(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if value.get("success") is False:
            raise ValueError("vision analyzer returned success=false")
        analysis = value.get("analysis", value)
        if isinstance(analysis, dict):
            return build_vision_judge_observation(analysis)
        value = analysis
    text = str(value or "")
    payload = _extract_json_object(text)
    if not payload:
        raise ValueError("vision analyzer returned no parseable JSON object")
    return build_vision_judge_observation(payload)


def _quality_from_observation(artifact: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    expected_kind = str(artifact.get("kind") or "image")
    deterministic = judge_artifact(
        artifact,
        expected_kind=expected_kind,
        requested_parameters={},
    )
    candidate = {
        **artifact,
        "scores": deterministic["scores"],
        "hard_gate": deterministic["hard_gate"],
    }
    return judge_visual_quality(
        candidate,
        request_context={"has_reference_image": False, "category": "fashion"},
        recent_artifact_hashes=set(),
        vision_observation=observation,
    )


def _candidate_feedback_artifacts(ledger: VisualAttemptLedger) -> list[dict[str, Any]]:
    feedback_ids = _feedback_artifact_ids(ledger)
    independently_judged = _latest_independent_vision_artifact_ids(ledger)
    candidates: list[dict[str, Any]] = []
    for artifact_id in sorted(feedback_ids - independently_judged):
        try:
            artifact = ledger.get_artifact(artifact_id)
        except KeyError:
            continue
        if artifact.get("kind") != "image":
            continue
        if not (artifact.get("local_path") or artifact.get("source_url") or artifact.get("uri")):
            continue
        candidates.append(artifact)
    return candidates


def _feedback_artifact_ids(ledger: VisualAttemptLedger) -> set[str]:
    artifact_ids: set[str] = set()
    for row in ledger._list("visual_feedback"):
        artifact_id = str(row.get("artifact_id") or "")
        polarity = _float(row.get("polarity"))
        if artifact_id and polarity != 0:
            artifact_ids.add(artifact_id)
    return artifact_ids


def _latest_independent_vision_artifact_ids(ledger: VisualAttemptLedger) -> set[str]:
    latest_by_artifact: dict[str, dict[str, Any]] = {}
    for row in ledger._list("visual_judgments"):
        if row.get("judge_name") != "visual_quality_judge":
            continue
        artifact_id = str(row.get("artifact_id") or "")
        if artifact_id:
            latest_by_artifact[artifact_id] = row
    judged: set[str] = set()
    for artifact_id, row in latest_by_artifact.items():
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if metadata.get("source") == "independent_vision_judge":
            judged.add(artifact_id)
    return judged


def _extract_json_object(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        text = text[start : end + 1] if start >= 0 and end > start else "{}"
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _report(
    db_path: Path,
    artifacts: list[dict[str, Any]],
    *,
    created_count: int,
    error_count: int,
) -> dict[str, Any]:
    artifact_ids = [
        str(row.get("artifact_id") or row.get("id") or "")
        for row in artifacts
        if row.get("artifact_id") or row.get("id")
    ]
    return {
        "success": error_count == 0,
        "db_path": str(db_path),
        "candidate_count": len(artifact_ids),
        "created_count": created_count,
        "error_count": error_count,
        "artifact_ids": artifact_ids,
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

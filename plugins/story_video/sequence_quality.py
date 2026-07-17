from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .shot_contract import shot_contract_hash


SEQUENCE_QUALITY_SCHEMA = "story_video_sequence_quality_v1"
SEQUENCE_QUALITY_THRESHOLD = 80.0
_OPENAI_PROVIDERS = frozenset({"openai", "openai-codex"})
_BOUND_FIELDS = (
    "schema",
    "status",
    "source_binding",
    "metrics",
    "repair_shot_ids",
    "violations",
    "entries",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ordered_shots(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        shot
        for scene in ledger.get("scenes") or []
        if isinstance(scene, dict)
        for shot in scene.get("shots") or []
        if isinstance(shot, dict) and _text(shot.get("shot_id"))
    ]


def _selected_by_shot(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {}
    for row in manifest.get("outputs") or []:
        if not isinstance(row, dict) or row.get("selected") is not True:
            continue
        shot_id = _text(row.get("shot_id"))
        if shot_id:
            selected.setdefault(shot_id, []).append(row)
    return selected


def _score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dimension_score(dimensions: Any, names: tuple[str, ...]) -> float:
    if not isinstance(dimensions, dict):
        return 0.0
    return min((_score(dimensions.get(name)) for name in names), default=0.0)


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def build_sequence_quality_report(
    project_dir: str | Path,
    ledger: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    root = Path(project_dir).resolve()
    selected = _selected_by_shot(manifest)
    violations: list[str] = []
    repair_shot_ids: list[str] = []
    entries: list[dict[str, Any]] = []
    artifact_shots: dict[str, list[str]] = {}

    for shot in _ordered_shots(ledger):
        shot_id = _text(shot.get("shot_id"))
        shot_violations: list[str] = []
        rows = selected.get(shot_id, [])
        if len(rows) != 1:
            shot_violations.append(f"{shot_id} lacks exactly one selected current artifact")
            row: dict[str, Any] = {}
        else:
            row = rows[0]

        relative_path = _text(row.get("local_path"))
        path = Path(relative_path)
        if not path.is_absolute():
            path = root / path
        try:
            resolved_path = path.resolve()
            in_project = resolved_path.is_relative_to(root)
        except (OSError, ValueError):
            resolved_path = path
            in_project = False

        artifact_sha = ""
        if not relative_path or not in_project or not resolved_path.is_file():
            shot_violations.append(f"{shot_id} selected artifact is missing or outside project")
        else:
            try:
                artifact_sha = _file_sha256(resolved_path)
            except OSError:
                shot_violations.append(f"{shot_id} selected artifact is unreadable")
            if artifact_sha:
                artifact_shots.setdefault(artifact_sha, []).append(shot_id)

        stored_artifact_sha = _text(row.get("artifact_sha256")).lower()
        if artifact_sha and stored_artifact_sha != artifact_sha:
            shot_violations.append(f"{shot_id} artifact hash does not match current file")

        current_contract_hash = shot_contract_hash(shot)
        stored_contract_hash = _text(row.get("shot_contract_hash")).lower()
        if stored_contract_hash != current_contract_hash:
            shot_violations.append(f"{shot_id} assessment uses superseded shot contract")

        if _text(row.get("status")).lower() != "selected_current":
            shot_violations.append(f"{shot_id} selected artifact status is not current")
        if _text(row.get("provider")).lower() not in _OPENAI_PROVIDERS:
            shot_violations.append(f"{shot_id} source provider is not OpenAI")
        if _text(row.get("judge_provider")).lower() not in _OPENAI_PROVIDERS:
            shot_violations.append(f"{shot_id} judge provider is not OpenAI")

        inherited = (
            _text(row.get("quality_score_origin")).lower()
            not in {"", "current_artifact"}
            or (
                _text(row.get("vision_evidence_applies_to_shot_id"))
                not in {"", shot_id}
            )
        )
        if inherited:
            shot_violations.append(
                f"{shot_id} assessment is inherited from another artifact or shot"
            )
        if row.get("final_qc_review_required") is True:
            shot_violations.append(f"{shot_id} requires final visual QC")
        if row.get("auto_terminal_fallback"):
            shot_violations.append(f"{shot_id} uses an automatic terminal fallback")

        vision = row.get("vision_evidence")
        if (
            not isinstance(vision, dict)
            or _text(vision.get("status")).upper() != "PASS"
            or not _text(vision.get("response_id"))
        ):
            shot_violations.append(f"{shot_id} lacks current OpenAI vision evidence")
        if _score(row.get("quality_score")) < SEQUENCE_QUALITY_THRESHOLD:
            shot_violations.append(f"{shot_id} overall quality score<80")
        if row.get("hard_blockers"):
            shot_violations.append(f"{shot_id} has unresolved visual blockers")

        dimensions = row.get("quality_dimensions")
        dimension_groups = {
            "semantic": ("text_alignment", "evidence_specificity"),
            "story": ("narrative_engagement", "story_moment_clarity"),
            "cinematic": ("cinematic_impact", "professional_quality"),
            "style": ("style_consistency",),
        }
        evidence_scores = {
            group: _dimension_score(dimensions, names)
            for group, names in dimension_groups.items()
        }
        for group, score in evidence_scores.items():
            if score < SEQUENCE_QUALITY_THRESHOLD:
                shot_violations.append(f"{shot_id} {group} evidence score<80")

        if shot_violations:
            repair_shot_ids.append(shot_id)
            violations.extend(shot_violations)
        entries.append(
            {
                "shot_id": shot_id,
                "local_path": relative_path,
                "artifact_sha256": artifact_sha,
                "shot_contract_hash": current_contract_hash,
                "quality_score": _score(row.get("quality_score")),
                "evidence_scores": evidence_scores,
                "status": "REPAIR_REQUIRED" if shot_violations else "PASS",
                "violations": shot_violations,
            }
        )

    for artifact_sha, shot_ids in sorted(artifact_shots.items()):
        if len(shot_ids) < 2:
            continue
        duplicate_violation = f"duplicate artifact sha256 used by: {','.join(shot_ids)}"
        violations.append(duplicate_violation)
        for shot_id in shot_ids:
            _append_once(repair_shot_ids, shot_id)
            for entry in entries:
                if entry["shot_id"] == shot_id:
                    entry["status"] = "REPAIR_REQUIRED"
                    _append_once(entry["violations"], duplicate_violation)

    return {
        "schema": SEQUENCE_QUALITY_SCHEMA,
        "status": "PASS" if not violations else "REPAIR_REQUIRED",
        "source_binding": {
            "ledger_sha256": _canonical_sha256(ledger),
            "candidate_manifest_sha256": _canonical_sha256(manifest),
        },
        "metrics": {
            "shot_count": len(entries),
            "selected_artifact_count": sum(1 for entry in entries if entry["local_path"]),
            "unique_artifact_count": len(artifact_shots),
            "repair_shot_count": len(repair_shot_ids),
        },
        "repair_shot_ids": repair_shot_ids,
        "violations": violations,
        "entries": entries,
    }


def write_sequence_quality_report(
    project_dir: str | Path,
    ledger: dict[str, Any],
    manifest: dict[str, Any],
) -> Path:
    root = Path(project_dir)
    path = root / "manifests" / "sequence_quality_report.json"
    payload = build_sequence_quality_report(root, ledger, manifest)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def validate_sequence_quality_report(
    project_dir: str | Path,
    ledger: dict[str, Any],
    manifest: dict[str, Any],
    report: dict[str, Any],
) -> tuple[str, ...]:
    expected = build_sequence_quality_report(project_dir, ledger, manifest)
    reported_bound = {field: report.get(field) for field in _BOUND_FIELDS}
    expected_bound = {field: expected.get(field) for field in _BOUND_FIELDS}
    if reported_bound != expected_bound:
        return tuple(
            ["sequence_quality_report is stale or does not match current artifacts"]
            + list(expected["violations"])
        )
    return tuple(expected["violations"])


__all__ = [
    "SEQUENCE_QUALITY_SCHEMA",
    "SEQUENCE_QUALITY_THRESHOLD",
    "build_sequence_quality_report",
    "validate_sequence_quality_report",
    "write_sequence_quality_report",
]

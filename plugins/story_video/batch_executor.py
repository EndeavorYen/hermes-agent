from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.visual.generation_waves import GenerationWaveItem
from agent.visual.generation_waves import GenerationWaveScheduler

from .batch_policy import BatchBudget, BatchPolicy
from .editorial_quality import EDITORIAL_PROFILE_ID
from .sequence_quality import build_sequence_quality_report, write_sequence_quality_report


_MANIFEST_LOCK = threading.RLock()
_SEQUENCE_QUALITY_GATE_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _write_candidate_manifest_atomic(
    path: Path, payload: dict[str, Any]
) -> dict[str, Any]:
    outputs = [row for row in payload.get("outputs") or [] if isinstance(row, dict)]
    history = [
        row for row in payload.get("attempt_history") or [] if isinstance(row, dict)
    ]
    selected_shot_ids = {
        _text(row.get("shot_id")) for row in outputs if row.get("selected") is True
    } - {""}
    updated = {
        **payload,
        "selected_shot_count": len(selected_shot_ids),
        "generated_candidate_count": len(history) if history else len(outputs),
    }
    _write_json_atomic(path, updated)
    return updated


def _ordered_shots(context: Any) -> list[dict[str, Any]]:
    ledger = _load_json(Path(context.project_dir) / "scene_ledger.json")
    return [
        shot
        for scene in ledger.get("scenes") or []
        if isinstance(scene, dict)
        for shot in scene.get("shots") or []
        if isinstance(shot, dict) and str(shot.get("shot_id") or "").strip()
    ]


def _write_sequence_report(context: Any, candidate_manifest: dict[str, Any]) -> None:
    project_dir = Path(context.project_dir)
    ledger = _load_json(project_dir / "scene_ledger.json")
    write_sequence_quality_report(project_dir, ledger, candidate_manifest)


def _sequence_quality_enabled(context: Any) -> bool:
    profile = _load_json(Path(context.project_dir) / "content_profile.json")
    return _text(profile.get("review_profile_id")) == EDITORIAL_PROFILE_ID


def _replanned_shot_ids(candidate_manifest: dict[str, Any]) -> set[str]:
    return {
        _text(row.get("shot_id"))
        for row in candidate_manifest.get("contract_replans") or []
        if isinstance(row, dict) and _text(row.get("shot_id"))
    }


def _legacy_strategy_pivot_migration_shot_ids(
    candidate_manifest: dict[str, Any],
) -> set[str]:
    return {
        _text(row.get("shot_id"))
        for row in candidate_manifest.get("contract_replans") or []
        if isinstance(row, dict)
        and _text(row.get("shot_id"))
        and row.get("legacy_strategy_pivot_migration") is True
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sequence_blocker_codes(violations: list[str]) -> list[str]:
    joined = " ".join(violations).lower()
    codes: list[str] = []
    mappings = (
        ("duplicate", "continuity_redundancy"),
        ("style", "style_drift"),
        ("cinematic", "flat_composition"),
        ("story", "missing_story_moment"),
        ("semantic", "audience_mismatch"),
    )
    for marker, code in mappings:
        if marker in joined and code not in codes:
            codes.append(code)
    return codes or ["other"]


def _prepare_sequence_rescue_manifest(
    path: Path,
    manifest: dict[str, Any],
    report: dict[str, Any],
    shot_ids: list[str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    requested = set(shot_ids)
    violations_by_shot = {
        _text(entry.get("shot_id")): [
            _text(value) for value in entry.get("violations") or [] if _text(value)
        ]
        for entry in report.get("entries") or []
        if isinstance(entry, dict)
    }
    originals: dict[str, dict[str, Any]] = {}
    outputs: list[dict[str, Any]] = []
    history = [row for row in manifest.get("attempt_history") or [] if isinstance(row, dict)]
    history_keys = {
        (_text(row.get("shot_id")), _text(row.get("candidate_id"))) for row in history
    }
    for row in manifest.get("outputs") or []:
        if not isinstance(row, dict):
            continue
        shot_id = _text(row.get("shot_id"))
        if shot_id not in requested or row.get("selected") is not True:
            outputs.append(row)
            continue
        originals[shot_id] = dict(row)
        key = (shot_id, _text(row.get("candidate_id")))
        if key not in history_keys:
            history.append(dict(row))
            history_keys.add(key)
        shot_violations = violations_by_shot.get(shot_id) or [
            "sequence-level visual quality did not pass"
        ]
        outputs.append(
            {
                **row,
                "selected": False,
                "status": "repair_required",
                "sequence_rescue_pending": True,
                "hard_blockers": shot_violations,
                "blocker_codes": _sequence_blocker_codes(shot_violations),
            }
        )
    updated = _write_candidate_manifest_atomic(
        path,
        {**manifest, "outputs": outputs, "attempt_history": history},
    )
    return updated, originals


def _restore_sequence_originals(
    path: Path,
    manifest: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    failed_shot_ids: set[str],
) -> dict[str, Any]:
    if not failed_shot_ids:
        return manifest
    retained = [
        row
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and _text(row.get("shot_id")) not in failed_shot_ids
    ]
    restored = []
    for shot_id in sorted(failed_shot_ids):
        original = originals.get(shot_id)
        if original is not None:
            restored.append(
                {
                    **original,
                    "selected": True,
                    "status": "selected_current",
                    "sequence_rescue_pending": False,
                }
            )
    updated = _write_candidate_manifest_atomic(
        path,
        {**manifest, "outputs": [*retained, *restored]},
    )
    return updated


@dataclass(frozen=True)
class BatchRunSummary:
    work_status: str
    wave: str
    attempted_shots: tuple[str, ...] = ()
    selected_shots: tuple[str, ...] = ()
    failed_shots: tuple[str, ...] = ()
    generated_candidates: int = 0
    provider_failure_classes: tuple[str, ...] = ()
    error_type: str = ""


class StoryVideoBatchExecutor:
    def __init__(
        self,
        *,
        prompt_compiler: Callable[..., dict[str, Any]],
        image_generator: Callable[..., dict[str, Any]],
        candidate_judge: Callable[..., dict[str, Any]],
        max_workers: int = 3,
    ) -> None:
        self.prompt_compiler = prompt_compiler
        self.image_generator = image_generator
        self.candidate_judge = candidate_judge
        self.max_workers = max(1, min(int(max_workers or 1), 3))

    def run_chunk(
        self,
        context: Any,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> BatchRunSummary:
        cancelled = cancel_check or (lambda: False)
        if cancelled():
            return BatchRunSummary(work_status="stopped", wave="none")

        shots = _ordered_shots(context)
        shot_ids = [str(shot["shot_id"]) for shot in shots]
        critical_ids = self._critical_shot_ids(context, shots)
        batch_path = Path(context.project_dir) / "manifests" / "batch_run_manifest.json"
        candidate_path = (
            Path(context.project_dir) / "manifests" / "shot_candidate_manifest.json"
        )
        with _MANIFEST_LOCK:
            batch_manifest = _load_json(batch_path)
            candidate_manifest = _load_json(candidate_path)
            critical_ids.update(_replanned_shot_ids(candidate_manifest))
            budget = self._load_budget(
                batch_manifest,
                len(shot_ids),
                candidate_manifest=candidate_manifest,
            )
            budget.grant_contract_replan_slots(
                [
                    (
                        _text(row.get("shot_id")),
                        _text(row.get("new_shot_contract_hash")),
                    )
                    for row in candidate_manifest.get("contract_replans") or []
                    if isinstance(row, dict)
                ]
            )
            if critical_ids.intersection(
                _legacy_strategy_pivot_migration_shot_ids(candidate_manifest)
            ):
                budget.grant_legacy_strategy_pivot_slot()

        sequence_rescue_wave = False
        sequence_originals: dict[str, dict[str, Any]] = {}
        selected = {
            str(row.get("shot_id") or "")
            for row in candidate_manifest.get("outputs") or []
            if isinstance(row, dict) and row.get("selected") is True
        }
        if len(selected.intersection(shot_ids)) == len(shot_ids):
            _write_sequence_report(context, candidate_manifest)
            sequence_report = build_sequence_quality_report(
                context.project_dir,
                _load_json(Path(context.project_dir) / "scene_ledger.json"),
                candidate_manifest,
            )
            if not _sequence_quality_enabled(context) or sequence_report["status"] == "PASS":
                return BatchRunSummary(
                    work_status="complete",
                    wave="none",
                    selected_shots=tuple(
                        shot_id for shot_id in shot_ids if shot_id in selected
                    ),
                )
            attempted_rescues = {
                _text(value)
                for value in batch_manifest.get("sequence_rescue_attempted_shot_ids") or []
                if _text(value)
            }
            try:
                sequence_gate_version = int(
                    batch_manifest.get("sequence_quality_gate_version") or 0
                )
            except (TypeError, ValueError):
                sequence_gate_version = 0
            if sequence_gate_version < _SEQUENCE_QUALITY_GATE_VERSION:
                migrated_attempts = [
                    shot_id for shot_id in shot_ids if shot_id in attempted_rescues
                ]
                attempted_rescues.clear()
                batch_manifest.update(
                    {
                        "sequence_quality_gate_version": _SEQUENCE_QUALITY_GATE_VERSION,
                        "sequence_quality_gate_migrated_attempted_shot_ids": (
                            migrated_attempts
                        ),
                        "sequence_rescue_attempted_shot_ids": [],
                    }
                )
            requested = [
                shot_id
                for shot_id in sequence_report.get("repair_shot_ids") or []
                if shot_id not in attempted_rescues
            ][: self.max_workers]
            if not requested:
                return BatchRunSummary(
                    work_status="terminal_required",
                    wave="sequence_rescue",
                    selected_shots=tuple(
                        shot_id for shot_id in shot_ids if shot_id in selected
                    ),
                    failed_shots=tuple(sequence_report.get("repair_shot_ids") or ()),
                    error_type="sequence_quality_rescue_exhausted",
                )
            sequence_rescue_wave = True
            wave = "sequence_rescue"
            with _MANIFEST_LOCK:
                candidate_manifest, sequence_originals = _prepare_sequence_rescue_manifest(
                    candidate_path,
                    candidate_manifest,
                    sequence_report,
                    requested,
                )
        else:
            fresh = [
                shot_id
                for shot_id in shot_ids
                if shot_id not in selected and budget.generated_for(shot_id) == 0
            ]
            pending_anchor = next(
                (
                    shot_id
                    for shot_id in shot_ids
                    if shot_id in critical_ids and shot_id not in selected
                ),
                "",
            )
            if pending_anchor and budget.can_generate(pending_anchor, critical=True):
                wave = "anchor"
                requested = [pending_anchor]
            elif pending_anchor:
                wave = "terminal"
                requested = []
            elif fresh:
                wave = "initial"
                requested = fresh[: self.max_workers]
            else:
                wave = "repair"
                remaining_budget = budget.remaining_candidates
                requested = [
                    shot_id
                    for shot_id in shot_ids
                    if shot_id not in selected
                    and budget.can_generate(
                        shot_id,
                        critical=shot_id in critical_ids,
                    )
                ][: min(self.max_workers, remaining_budget)]

        if not requested:
            return BatchRunSummary(
                work_status="terminal_required",
                wave="terminal",
                selected_shots=tuple(shot_id for shot_id in shot_ids if shot_id in selected),
                failed_shots=tuple(shot_id for shot_id in shot_ids if shot_id not in selected),
            )

        compiled: list[dict[str, Any]] = []
        compile_failures: list[str] = []
        for shot_id in requested:
            if cancelled():
                break
            prompt_info = self.prompt_compiler(context, shot_id=shot_id)
            if not prompt_info.get("success"):
                compile_failures.append(shot_id)
                continue
            compiled.append(prompt_info)

        if not compiled:
            if sequence_rescue_wave:
                with _MANIFEST_LOCK:
                    restored = _restore_sequence_originals(
                        candidate_path,
                        _load_json(candidate_path),
                        sequence_originals,
                        set(requested),
                    )
                    _write_sequence_report(context, restored)
                    if not cancelled():
                        attempted_rescues = {
                            _text(value)
                            for value in batch_manifest.get(
                                "sequence_rescue_attempted_shot_ids"
                            )
                            or []
                            if _text(value)
                        }
                        attempted_rescues.update(compile_failures)
                        batch_manifest["sequence_rescue_attempted_shot_ids"] = [
                            shot_id for shot_id in shot_ids if shot_id in attempted_rescues
                        ]
                        self._save_budget(
                            batch_path,
                            batch_manifest,
                            context=context,
                            budget=budget,
                            event={
                                "stage": "compile_failed",
                                "wave": wave,
                                "shot_ids": compile_failures,
                                "work_status": "terminal_required",
                                "timestamp": _utc_now(),
                            },
                        )
            return BatchRunSummary(
                work_status="stopped" if cancelled() else "terminal_required",
                wave=wave,
                failed_shots=tuple(compile_failures),
            )
        if cancelled():
            if sequence_rescue_wave:
                with _MANIFEST_LOCK:
                    restored = _restore_sequence_originals(
                        candidate_path,
                        _load_json(candidate_path),
                        sequence_originals,
                        set(requested),
                    )
                    _write_sequence_report(context, restored)
            return BatchRunSummary(work_status="stopped", wave=wave)

        with _MANIFEST_LOCK:
            if not sequence_rescue_wave:
                for item in compiled:
                    shot_id = str(item["shot_id"])
                    budget.record_generation(
                        shot_id,
                        str(item.get("shot_contract_hash") or ""),
                        critical=shot_id in critical_ids,
                    )
            batch_manifest = self._save_budget(
                batch_path,
                batch_manifest,
                context=context,
                budget=budget,
                event={
                    "stage": "dispatch",
                    "wave": wave,
                    "shot_ids": [str(item["shot_id"]) for item in compiled],
                    "timestamp": _utc_now(),
                },
            )

        dispatch_items = compiled

        def generate(item: dict[str, Any]) -> dict[str, Any]:
            return self.image_generator(
                self._generation_args(item),
                task_id=f"story-video-{context.run_id}-{item['shot_id']}",
            )

        generation_wave_run = GenerationWaveScheduler(
            provider="openai-codex",
            requested_parallelism=self.max_workers,
        ).run(
            [
                GenerationWaveItem(
                    key=str(item["shot_id"]),
                    group_key=str(item["shot_id"]),
                    payload=item,
                )
                for item in dispatch_items
            ],
            generate,
        )
        generation_results = {
            result.key: (
                result.value
                if isinstance(result.value, dict)
                else {
                    "success": False,
                    "error_type": result.failure_class or "provider_exception",
                    "error": result.error or "image generation was not dispatched",
                }
            )
            for result in generation_wave_run.results
        }
        provider_failure_classes = tuple(
            sorted(
                {
                    result.failure_class
                    for result in generation_wave_run.results
                    if result.failure_class
                }
            )
        )
        generated_shot_ids = {
            shot_id
            for shot_id, result in generation_results.items()
            if result.get("success") and str(result.get("image") or "").strip()
        }
        for item in compiled:
            shot_id = str(item["shot_id"])
            if not sequence_rescue_wave and shot_id not in generated_shot_ids:
                budget.release_generation(
                    shot_id,
                    str(item.get("shot_contract_hash") or ""),
                )

        selected_now: list[str] = []
        failed_now: list[str] = list(compile_failures)
        for item in compiled:
            shot_id = str(item["shot_id"])
            result = generation_results.get(shot_id) or {}
            image_path = str(result.get("image") or "").strip()
            if not result.get("success") or not image_path:
                failed_now.append(shot_id)
                continue
            candidate = {
                "candidate_id": str(item.get("candidate_id_hint") or shot_id),
                "path": image_path,
                "provider": "openai-codex",
                "model": str(result.get("model") or ""),
                "response_id": str(result.get("response_id") or ""),
                "generation_prompt": str(item.get("prompt") or ""),
                "shot_contract_hash": str(item.get("shot_contract_hash") or ""),
                "repair_strategy": str(item.get("repair_strategy") or "initial"),
                "strategy_reset": bool(item.get("strategy_reset")),
            }
            judged = self.candidate_judge(
                context,
                shot_id=shot_id,
                candidate=candidate,
                repair_round=min(3, max(1, budget.generated_for(shot_id))),
            )
            if judged.get("success"):
                selected_now.append(shot_id)
            else:
                failed_now.append(shot_id)

        candidate_manifest = _load_json(candidate_path)
        if sequence_rescue_wave:
            failed_rescues = set(requested) - set(selected_now)
            with _MANIFEST_LOCK:
                candidate_manifest = _restore_sequence_originals(
                    candidate_path,
                    candidate_manifest,
                    sequence_originals,
                    failed_rescues,
                )
        selected = {
            str(row.get("shot_id") or "")
            for row in candidate_manifest.get("outputs") or []
            if isinstance(row, dict) and row.get("selected") is True
        }
        pending = [shot_id for shot_id in shot_ids if shot_id not in selected]
        can_continue = any(
            budget.can_generate(shot_id, critical=shot_id in critical_ids)
            for shot_id in pending
        )
        setup_error_type = (
            "provider_quota_or_subscription_required"
            if "quota_exceeded" in provider_failure_classes
            else "provider_authentication_required"
            if "authentication_required" in provider_failure_classes
            else ""
        )
        if sequence_rescue_wave:
            attempted_rescues = {
                _text(value)
                for value in batch_manifest.get("sequence_rescue_attempted_shot_ids") or []
                if _text(value)
            }
            attempted_rescues.update(generated_shot_ids)
            batch_manifest["sequence_rescue_attempted_shot_ids"] = [
                shot_id for shot_id in shot_ids if shot_id in attempted_rescues
            ]
            sequence_report = build_sequence_quality_report(
                context.project_dir,
                _load_json(Path(context.project_dir) / "scene_ledger.json"),
                candidate_manifest,
            )
            _write_sequence_report(context, candidate_manifest)
            remaining_repairs = list(sequence_report.get("repair_shot_ids") or [])
            can_rescue_more = any(
                shot_id not in attempted_rescues for shot_id in remaining_repairs
            )
            work_status = (
                "setup_required"
                if setup_error_type
                else "complete"
                if not remaining_repairs
                else "in_progress"
                if can_rescue_more or not generated_shot_ids
                else "terminal_required"
            )
            pending = remaining_repairs
        else:
            work_status = (
                "setup_required"
                if setup_error_type
                else "complete"
                if not pending
                else "in_progress"
                if can_continue
                else "terminal_required"
            )
            if work_status == "complete":
                _write_sequence_report(context, candidate_manifest)
        with _MANIFEST_LOCK:
            self._save_budget(
                batch_path,
                batch_manifest,
                context=context,
                budget=budget,
                event={
                    "stage": "complete",
                    "wave": wave,
                    "shot_ids": [str(item["shot_id"]) for item in compiled],
                    "selected_shot_ids": selected_now,
                    "failed_shot_ids": failed_now,
                    "work_status": work_status,
                    "provider_failure_classes": list(provider_failure_classes),
                    "error_type": setup_error_type or None,
                    "generation_waves": generation_wave_run.to_record(),
                    "timestamp": _utc_now(),
                },
            )
        return BatchRunSummary(
            work_status=work_status,
            wave=wave,
            attempted_shots=tuple(str(item["shot_id"]) for item in compiled),
            selected_shots=tuple(selected_now),
            failed_shots=tuple(dict.fromkeys(failed_now)),
            generated_candidates=len(generated_shot_ids),
            provider_failure_classes=provider_failure_classes,
            error_type=setup_error_type,
        )

    @staticmethod
    def _critical_shot_ids(context: Any, shots: list[dict[str, Any]]) -> set[str]:
        ledger = _load_json(Path(context.project_dir) / "scene_ledger.json")
        style_bible = ledger.get("style_bible")
        anchor = (
            str(style_bible.get("anchor_shot_id") or "").strip()
            if isinstance(style_bible, dict)
            else ""
        )
        return {anchor} if anchor else set()

    @staticmethod
    def _load_budget(
        manifest: dict[str, Any],
        shot_count: int,
        *,
        candidate_manifest: dict[str, Any],
    ) -> BatchBudget:
        payload = manifest.get("budget") if isinstance(manifest, dict) else None
        if isinstance(payload, dict):
            try:
                return BatchBudget.from_dict(payload)
            except (TypeError, ValueError):
                pass
        return BatchBudget.from_candidate_manifest(
            BatchPolicy.for_run(shot_count),
            candidate_manifest,
        )

    @staticmethod
    def _save_budget(
        path: Path,
        manifest: dict[str, Any],
        *,
        context: Any,
        budget: BatchBudget,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            **manifest,
            "schema": "story_video_batch_run_v1",
            "run_id": str(context.run_id),
            "project_id": str(getattr(context, "project_id", "")),
            "provider": "openai-codex",
            "budget": budget.to_dict(),
            "events": [*(manifest.get("events") or []), event],
            "updated_at": _utc_now(),
        }
        _write_json_atomic(path, payload)
        return payload

    @staticmethod
    def _generation_args(item: dict[str, Any]) -> dict[str, Any]:
        args: dict[str, Any] = {
            "prompt": str(item.get("prompt") or ""),
            "aspect_ratio": "16:9",
            "provider": "openai-codex",
        }
        source = str(item.get("source_image_url") or "").strip()
        if source:
            args["image_url"] = source
        references = [
            str(value)
            for value in item.get("reference_image_urls") or []
            if str(value).strip()
        ]
        if references:
            args["reference_image_urls"] = references
        return args


__all__ = ["BatchRunSummary", "StoryVideoBatchExecutor"]

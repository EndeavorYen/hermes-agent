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
from .sequence_quality import write_sequence_quality_report


_MANIFEST_LOCK = threading.RLock()


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
            budget = self._load_budget(
                batch_manifest,
                len(shot_ids),
                candidate_manifest=candidate_manifest,
            )

        selected = {
            str(row.get("shot_id") or "")
            for row in candidate_manifest.get("outputs") or []
            if isinstance(row, dict) and row.get("selected") is True
        }
        if len(selected.intersection(shot_ids)) == len(shot_ids):
            _write_sequence_report(context, candidate_manifest)
            return BatchRunSummary(
                work_status="complete",
                wave="none",
                selected_shots=tuple(shot_id for shot_id in shot_ids if shot_id in selected),
            )

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
            remaining_budget = max(
                0,
                budget.policy.max_total_candidates - budget.total_generated,
            )
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
            return BatchRunSummary(
                work_status="stopped" if cancelled() else "terminal_required",
                wave=wave,
                failed_shots=tuple(compile_failures),
            )
        if cancelled():
            return BatchRunSummary(work_status="stopped", wave=wave)

        with _MANIFEST_LOCK:
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
            if shot_id not in generated_shot_ids:
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
                repair_round=budget.generated_for(shot_id),
            )
            if judged.get("success"):
                selected_now.append(shot_id)
            else:
                failed_now.append(shot_id)

        candidate_manifest = _load_json(candidate_path)
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

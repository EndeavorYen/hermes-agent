#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.story_video.batch_executor import StoryVideoBatchExecutor


class BenchmarkGenerator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0
        self.provider_wait_sec = 0.0
        self._lock = threading.Lock()

    def __call__(self, args: dict[str, Any], *, task_id: str = "") -> dict[str, Any]:
        started = time.monotonic()
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(dict(args))
            call_index = len(self.calls)
        time.sleep(0.02)
        image = self.root / f"candidate-{call_index:02d}.png"
        image.write_bytes(task_id.encode("utf-8"))
        elapsed = time.monotonic() - started
        with self._lock:
            self.active -= 1
            self.provider_wait_sec += elapsed
        return {
            "success": True,
            "image": str(image),
            "provider": "openai-codex",
            "model": "benchmark-fixture",
            "response_id": f"benchmark-{call_index:02d}",
        }


class BenchmarkJudge:
    def __init__(
        self,
        *,
        initial_failures: set[str],
        repair_successes: set[str],
    ) -> None:
        self.initial_failures = initial_failures
        self.repair_successes = repair_successes
        self.calls = 0

    def __call__(
        self,
        context: Any,
        *,
        shot_id: str,
        candidate: dict[str, Any],
        repair_round: int,
    ) -> dict[str, Any]:
        self.calls += 1
        first_pass = repair_round == 1
        selected = (
            shot_id not in self.initial_failures
            if first_pass
            else shot_id in self.repair_successes
        )
        row = {
            **candidate,
            "shot_id": shot_id,
            "selected": selected,
            "status": "selected_current" if selected else "repair_required",
            "quality_score": 88.0 if selected else 72.0,
            "hard_blockers": [] if selected else ["fixture evidence is unclear"],
            "repair_round": repair_round,
            "vision_evidence": {
                "status": "PASS",
                "response_id": f"qc-{self.calls:02d}",
            },
        }
        path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            manifest = {"outputs": [], "attempt_history": []}
        manifest["outputs"] = [
            existing
            for existing in manifest.get("outputs") or []
            if existing.get("shot_id") != shot_id
        ] + [row]
        manifest.setdefault("attempt_history", []).append(row)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return {
            "success": selected,
            "status": "selected" if selected else "repair_required",
        }


def _compiler(_context: Any, *, shot_id: str) -> dict[str, Any]:
    return {
        "success": True,
        "shot_id": shot_id,
        "prompt": f"benchmark prompt for {shot_id}",
        "candidate_id_hint": f"{shot_id}_CANDIDATE",
        "shot_contract_hash": f"hash-{shot_id}",
        "repair_strategy": "initial",
        "reference_image_urls": [],
    }


def run_benchmark(fixture: dict[str, Any], root: Path) -> dict[str, Any]:
    shot_count = int(fixture["shot_count"])
    project_dir = root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    shots = [{"shot_id": f"S{index:02d}_SH00"} for index in range(shot_count)]
    (project_dir / "scene_ledger.json").write_text(
        json.dumps({"scenes": [{"scene_id": "S00", "shots": shots}]}),
        encoding="utf-8",
    )
    context = SimpleNamespace(
        project_dir=project_dir,
        run_id="benchmark-run",
        project_id="benchmark-project",
        phase="batch",
        auto_mode=True,
    )
    generator = BenchmarkGenerator(root)
    judge = BenchmarkJudge(
        initial_failures=set(fixture.get("initial_failures") or []),
        repair_successes=set(fixture.get("repair_successes") or []),
    )
    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=generator,
        candidate_judge=judge,
        max_workers=3,
    )

    started = time.monotonic()
    summaries = []
    for _ in range(20):
        summary = executor.run_chunk(context)
        summaries.append(summary)
        if summary.work_status in {"complete", "terminal_required"}:
            break
    wall_time_sec = time.monotonic() - started

    candidate_manifest = json.loads(
        (project_dir / "manifests" / "shot_candidate_manifest.json").read_text()
    )
    batch_manifest = json.loads(
        (project_dir / "manifests" / "batch_run_manifest.json").read_text()
    )
    selected_rows = [
        row for row in candidate_manifest["outputs"] if row.get("selected") is True
    ]
    selected_ids = {str(row["shot_id"]) for row in selected_rows}
    unresolved = [shot["shot_id"] for shot in shots if shot["shot_id"] not in selected_ids]
    generated_by_shot = batch_manifest["budget"]["generated_by_shot"]
    expected = fixture["expected"]
    checks = {
        "candidate_cap": len(generator.calls) <= int(expected["max_image_generations"]),
        "per_shot_cap": max(generated_by_shot.values(), default=0)
        <= int(expected["max_candidates_per_shot"]),
        "orchestration_cap": len(summaries)
        <= int(expected["max_orchestration_calls"]),
        "parallelism": generator.max_active == int(expected["expected_parallelism"]),
        "selected_count": len(selected_rows) == int(expected["expected_selected_count"]),
        "continuity_hold_count": len(unresolved)
        == int(expected["expected_continuity_hold_count"]),
        "provider_lock": all(
            call.get("provider") == "openai-codex" for call in generator.calls
        ),
        "no_hard_blocked_selection": all(
            not row.get("hard_blockers") for row in selected_rows
        ),
    }
    return {
        "schema": "story_video_batch_performance_v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "wall_time_sec": round(wall_time_sec, 4),
        "provider_wait_sec": round(generator.provider_wait_sec, 4),
        "orchestration_api_calls": len(summaries),
        "vision_qc_calls": judge.calls,
        "image_generations": len(generator.calls),
        "repair_generations": sum(max(0, count - 1) for count in generated_by_shot.values()),
        "session_rotations": len(summaries) // 9,
        "selected_count": len(selected_rows),
        "continuity_hold_count": len(unresolved),
        "continuity_hold_shot_ids": unresolved,
        "hard_blocker_count": sum(bool(row.get("hard_blockers")) for row in selected_rows),
        "max_parallelism": generator.max_active,
        "max_candidates_for_one_shot": max(generated_by_shot.values(), default=0),
        "chunks": [
            {
                "wave": summary.wave,
                "work_status": summary.work_status,
                "attempted_shots": list(summary.attempted_shots),
            }
            for summary in summaries
        ],
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="story-video-benchmark-") as tmp:
        report = run_benchmark(fixture, Path(tmp))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

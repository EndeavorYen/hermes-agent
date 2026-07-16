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
from tools.image_generation_tool import generate_image


class LiveGenerator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, args: dict[str, Any], *, task_id: str = "") -> dict[str, Any]:
        started = time.monotonic()
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append({**args, "task_id": task_id, "started": started})
            index = len(self.calls) - 1
        result = generate_image(args, task_id=task_id)
        completed = time.monotonic()
        with self._lock:
            self.active -= 1
            self.calls[index]["completed"] = completed
            self.results.append(dict(result))
        return result


def _compiler(_context: Any, *, shot_id: str) -> dict[str, Any]:
    subjects = {
        "S00_SH00": "a curious child-safe feathered dinosaur discovering a glowing beetle",
        "S01_SH00": "a tiny early dinosaur crossing a rain-soaked Triassic forest clearing",
        "S02_SH00": "a cinematic close-up of a fossil footprint revealed beneath soft sand",
    }
    return {
        "success": True,
        "shot_id": shot_id,
        "prompt": (
            f"{subjects[shot_id]}, cinematic educational science documentary, "
            "photorealistic, strong focal point, dramatic natural light, 16:9, no text"
        ),
        "candidate_id_hint": f"{shot_id}_LIVE_C01",
        "shot_contract_hash": f"live-{shot_id}",
        "repair_strategy": "initial",
        "reference_image_urls": [],
    }


def _judge(
    context: Any,
    *,
    shot_id: str,
    candidate: dict[str, Any],
    repair_round: int,
) -> dict[str, Any]:
    path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        manifest = {"outputs": [], "attempt_history": []}
    row = {
        **candidate,
        "shot_id": shot_id,
        "selected": True,
        "status": "selected_current",
        "quality_score": None,
        "quality_score_origin": "live_scheduler_smoke_not_visual_qc",
        "hard_blockers": [],
        "repair_round": repair_round,
    }
    manifest["outputs"] = [
        existing
        for existing in manifest.get("outputs") or []
        if existing.get("shot_id") != shot_id
    ] + [row]
    manifest.setdefault("attempt_history", []).append(row)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return {"success": True, "status": "selected"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/private/tmp/story-video-native-batch-live-smoke.json"),
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="story-video-live-smoke-") as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir()
        shots = [{"shot_id": f"S{index:02d}_SH00"} for index in range(3)]
        (project_dir / "scene_ledger.json").write_text(
            json.dumps({"scenes": [{"scene_id": "S00", "shots": shots}]}),
            encoding="utf-8",
        )
        context = SimpleNamespace(
            project_dir=project_dir,
            run_id="native-batch-live-smoke",
            project_id="native-batch-live-smoke",
            phase="batch",
            auto_mode=True,
        )
        generator = LiveGenerator()
        started = time.monotonic()
        summary = StoryVideoBatchExecutor(
            prompt_compiler=_compiler,
            image_generator=generator,
            candidate_judge=_judge,
            max_workers=3,
        ).run_chunk(context)
        elapsed = time.monotonic() - started

        providers = [str(row.get("provider") or "") for row in generator.results]
        images = [str(row.get("image") or "") for row in generator.results]
        checks = {
            "complete": summary.work_status == "complete",
            "three_images": len(images) == 3 and all(Path(path).is_file() for path in images),
            "openai_only": providers == ["openai-codex"] * 3,
            "parallel_overlap": generator.max_active == 3,
            "explicit_provider": all(
                call.get("provider") == "openai-codex" for call in generator.calls
            ),
        }
        report = {
            "schema": "story_video_native_batch_live_smoke_v1",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "scope": "scheduler_provider_integration_only",
            "visual_qc_performed": False,
            "elapsed_sec": round(elapsed, 3),
            "max_parallelism": generator.max_active,
            "providers": providers,
            "models": [str(row.get("model") or "") for row in generator.results],
            "images": images,
            "checks": checks,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

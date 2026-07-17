from __future__ import annotations

import json
import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from plugins.story_video.batch_executor import StoryVideoBatchExecutor
from plugins.story_video.shot_contract import shot_contract_hash


def _context(tmp_path: Path, shot_count: int = 6) -> SimpleNamespace:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shots = [
        {
            "shot_id": f"S{index:02d}_SH00",
            "subject": f"subject {index}",
            "action": f"action {index}",
        }
        for index in range(shot_count)
    ]
    (project_dir / "scene_ledger.json").write_text(
        json.dumps({"scenes": [{"scene_id": "S00", "shots": shots}]}),
        encoding="utf-8",
    )
    return SimpleNamespace(
        project_dir=project_dir,
        run_id="run-batch",
        project_id="project-batch",
        phase="batch",
        auto_mode=True,
    )


class FakeGenerator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[dict] = []
        self.intervals: list[tuple[float, float]] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, args: dict, *, task_id: str = "") -> dict:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            started = time.monotonic()
            self.calls.append(dict(args))
        time.sleep(0.04)
        path = self.root / f"{task_id}-{len(self.calls)}.png"
        path.write_bytes(task_id.encode())
        with self.lock:
            completed = time.monotonic()
            self.intervals.append((started, completed))
            self.active -= 1
        return {
            "success": True,
            "image": str(path),
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
            "response_id": f"resp-{task_id}",
        }


class FakeJudge:
    def __init__(self, failed_first_pass: set[str]) -> None:
        self.failed_first_pass = failed_first_pass
        self.calls: list[str] = []

    def __call__(
        self,
        context,
        *,
        shot_id: str,
        candidate: dict,
        repair_round: int,
    ) -> dict:
        self.calls.append(shot_id)
        path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            manifest = {"outputs": [], "attempt_history": []}
        prior = [
            row
            for row in manifest.get("attempt_history") or []
            if row.get("shot_id") == shot_id
        ]
        selected = shot_id not in self.failed_first_pass or bool(prior)
        row = {
            **candidate,
            "shot_id": shot_id,
            "selected": selected,
            "status": "selected_current" if selected else "repair_required",
            "quality_score": 88.0 if selected else 70.0,
            "hard_blockers": [] if selected else ["focal evidence is unclear"],
            "repair_round": repair_round,
            "vision_evidence": {"status": "PASS", "response_id": f"qc-{shot_id}"},
        }
        outputs = [
            existing
            for existing in manifest.get("outputs") or []
            if existing.get("shot_id") != shot_id
        ]
        manifest["outputs"] = [*outputs, row]
        manifest.setdefault("attempt_history", []).append(row)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return {
            "success": selected,
            "status": "selected" if selected else "repair_required",
            "best_score": row["quality_score"],
        }


def _compiler(_context, *, shot_id: str) -> dict:
    return {
        "success": True,
        "shot_id": shot_id,
        "prompt": f"precise prompt for {shot_id}",
        "candidate_id_hint": f"{shot_id}_CANDIDATE",
        "shot_contract_hash": f"hash-{shot_id}",
        "repair_strategy": "targeted_repair",
        "reference_image_urls": [],
    }


def test_executor_runs_fresh_shots_before_one_bounded_repair_wave(tmp_path) -> None:
    context = _context(tmp_path)
    generator = FakeGenerator(tmp_path)
    judge = FakeJudge({"S01_SH00", "S04_SH00"})
    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=generator,
        candidate_judge=judge,
        max_workers=3,
    )

    first = executor.run_chunk(context)
    second = executor.run_chunk(context)
    repaired = executor.run_chunk(context)
    complete = executor.run_chunk(context)

    assert first.wave == "initial"
    assert first.attempted_shots == ("S00_SH00", "S01_SH00", "S02_SH00")
    assert second.wave == "initial"
    assert second.attempted_shots == ("S03_SH00", "S04_SH00", "S05_SH00")
    assert repaired.wave == "repair"
    assert repaired.attempted_shots == ("S01_SH00", "S04_SH00")
    assert repaired.work_status == "complete"
    assert complete.work_status == "complete"
    assert len(generator.calls) == 8
    assert generator.max_active == 3
    assert all(call["provider"] == "openai-codex" for call in generator.calls)

    batch_manifest = json.loads(
        (context.project_dir / "manifests" / "batch_run_manifest.json").read_text()
    )
    assert batch_manifest["budget"]["generated_by_shot"]["S01_SH00"] == 2
    assert batch_manifest["budget"]["generated_by_shot"]["S04_SH00"] == 2
    assert sum(batch_manifest["budget"]["generated_by_shot"].values()) == 8
    sequence_report = json.loads(
        (context.project_dir / "manifests" / "sequence_quality_report.json").read_text()
    )
    assert sequence_report["schema"] == "story_video_sequence_quality_v1"
    assert sequence_report["metrics"]["shot_count"] == 6


def test_executor_runs_one_parallel_sequence_rescue_then_stops(tmp_path) -> None:
    context = _context(tmp_path, shot_count=2)
    (context.project_dir / "content_profile.json").write_text(
        json.dumps({"review_profile_id": "family-review-board-v2"}), encoding="utf-8"
    )
    ledger = json.loads(
        (context.project_dir / "scene_ledger.json").read_text(encoding="utf-8")
    )
    shots = ledger["scenes"][0]["shots"]
    duplicate = context.project_dir / "images" / "duplicate.png"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_bytes(b"duplicate-sequence-frame")
    duplicate_sha = hashlib.sha256(duplicate.read_bytes()).hexdigest()
    outputs = [
        {
            "shot_id": shot["shot_id"],
            "candidate_id": f"{shot['shot_id']}_INITIAL",
            "selected": True,
            "status": "selected_current",
            "local_path": str(duplicate.relative_to(context.project_dir)),
            "artifact_sha256": duplicate_sha,
            "shot_contract_hash": shot_contract_hash(shot),
            "provider": "openai-codex",
            "judge_provider": "openai-codex",
            "quality_score": 90,
            "quality_dimensions": {
                "text_alignment": 90,
                "evidence_specificity": 90,
                "narrative_engagement": 90,
                "story_moment_clarity": 90,
                "cinematic_impact": 90,
                "professional_quality": 90,
                "style_consistency": 90,
            },
            "hard_blockers": [],
            "vision_evidence": {"status": "PASS", "response_id": "initial-qc"},
        }
        for shot in shots
    ]
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"outputs": outputs, "attempt_history": outputs}), encoding="utf-8"
    )

    def compiler(_context, *, shot_id: str) -> dict:
        shot = next(item for item in shots if item["shot_id"] == shot_id)
        return {
            "success": True,
            "shot_id": shot_id,
            "prompt": f"sequence rescue for {shot_id}",
            "candidate_id_hint": f"{shot_id}_SEQUENCE_RESCUE",
            "shot_contract_hash": shot_contract_hash(shot),
            "repair_strategy": "story_reframe",
            "reference_image_urls": [],
        }

    def judge(_context, *, shot_id: str, candidate: dict, repair_round: int) -> dict:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        destination = _context.project_dir / "images" / f"{shot_id}-rescue.png"
        destination.write_bytes(Path(candidate["path"]).read_bytes())
        shot = next(item for item in shots if item["shot_id"] == shot_id)
        row = {
            **candidate,
            "shot_id": shot_id,
            "selected": True,
            "status": "selected_current",
            "local_path": str(destination.relative_to(_context.project_dir)),
            "artifact_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "shot_contract_hash": shot_contract_hash(shot),
            "judge_provider": "openai-codex",
            "quality_score": 92,
            "quality_dimensions": {
                "text_alignment": 92,
                "evidence_specificity": 92,
                "narrative_engagement": 92,
                "story_moment_clarity": 92,
                "cinematic_impact": 92,
                "professional_quality": 92,
                "style_consistency": 92,
            },
            "hard_blockers": [],
            "vision_evidence": {"status": "PASS", "response_id": f"rescue-{shot_id}"},
            "repair_round": repair_round,
        }
        manifest["outputs"] = [
            output for output in manifest["outputs"] if output["shot_id"] != shot_id
        ] + [row]
        manifest.setdefault("attempt_history", []).append(row)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return {"success": True, "status": "selected", "best_score": 92}

    generator = FakeGenerator(tmp_path)
    executor = StoryVideoBatchExecutor(
        prompt_compiler=compiler,
        image_generator=generator,
        candidate_judge=judge,
        max_workers=3,
    )

    rescued = executor.run_chunk(context)
    complete = executor.run_chunk(context)

    assert rescued.wave == "sequence_rescue"
    assert rescued.attempted_shots == ("S00_SH00", "S01_SH00")
    assert rescued.work_status == "complete"
    assert complete.work_status == "complete"
    assert len(generator.calls) == 2
    batch_manifest = json.loads(
        (context.project_dir / "manifests" / "batch_run_manifest.json").read_text()
    )
    assert batch_manifest["sequence_rescue_attempted_shot_ids"] == [
        "S00_SH00",
        "S01_SH00",
    ]
    sequence_report = json.loads(
        (context.project_dir / "manifests" / "sequence_quality_report.json").read_text()
    )
    assert sequence_report["status"] == "PASS"


def test_executor_honors_stop_before_dispatch(tmp_path) -> None:
    context = _context(tmp_path, shot_count=3)
    generator = FakeGenerator(tmp_path)
    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=generator,
        candidate_judge=FakeJudge(set()),
        max_workers=3,
    )

    summary = executor.run_chunk(context, cancel_check=lambda: True)

    assert summary.work_status == "stopped"
    assert summary.attempted_shots == ()
    assert generator.calls == []


def test_executor_does_not_spend_budget_when_stopped_after_compile(tmp_path) -> None:
    context = _context(tmp_path, shot_count=3)
    generator = FakeGenerator(tmp_path)
    checks = 0

    def cancel_after_compile() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 5

    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=generator,
        candidate_judge=FakeJudge(set()),
        max_workers=3,
    )

    summary = executor.run_chunk(context, cancel_check=cancel_after_compile)

    assert summary.work_status == "stopped"
    assert summary.attempted_shots == ()
    assert generator.calls == []
    batch_path = context.project_dir / "manifests" / "batch_run_manifest.json"
    assert not batch_path.exists()


def test_executor_generates_style_anchor_alone_before_parallel_fresh_shots(
    tmp_path,
) -> None:
    context = _context(tmp_path, shot_count=4)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["style_bible"] = {"anchor_shot_id": "S02_SH00"}
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    generator = FakeGenerator(tmp_path)
    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=generator,
        candidate_judge=FakeJudge(set()),
        max_workers=3,
    )

    anchor = executor.run_chunk(context)
    remaining = executor.run_chunk(context)

    assert anchor.wave == "anchor"
    assert anchor.attempted_shots == ("S02_SH00",)
    assert remaining.wave == "initial"
    assert remaining.attempted_shots == (
        "S00_SH00",
        "S01_SH00",
        "S03_SH00",
    )
    assert generator.max_active == 3


def test_executor_repairs_failed_style_anchor_before_other_fresh_shots(
    tmp_path,
) -> None:
    context = _context(tmp_path, shot_count=4)
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["style_bible"] = {"anchor_shot_id": "S02_SH00"}
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    generator = FakeGenerator(tmp_path)
    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=generator,
        candidate_judge=FakeJudge({"S02_SH00"}),
        max_workers=3,
    )

    first_anchor = executor.run_chunk(context)
    repaired_anchor = executor.run_chunk(context)
    remaining = executor.run_chunk(context)

    assert first_anchor.attempted_shots == ("S02_SH00",)
    assert repaired_anchor.wave == "anchor"
    assert repaired_anchor.attempted_shots == ("S02_SH00",)
    assert remaining.attempted_shots == (
        "S00_SH00",
        "S01_SH00",
        "S03_SH00",
    )


def test_executor_recovers_legacy_candidate_usage_before_resuming(tmp_path) -> None:
    context = _context(tmp_path, shot_count=3)
    manifest_path = (
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": "S00_SH00",
                        "candidate_id": "S00_SH00_C02",
                        "selected": False,
                        "repair_round": 2,
                        "shot_contract_hash": "hash-new",
                    }
                ],
                "attempt_history": [
                    {
                        "shot_id": "S00_SH00",
                        "candidate_id": "S00_SH00_C01",
                        "repair_round": 1,
                        "shot_contract_hash": "hash-old",
                    },
                    {
                        "shot_id": "S00_SH00",
                        "candidate_id": "S00_SH00_C02",
                        "repair_round": 2,
                        "shot_contract_hash": "hash-new",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    generator = FakeGenerator(tmp_path)
    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=generator,
        candidate_judge=FakeJudge(set()),
        max_workers=3,
    )

    summary = executor.run_chunk(context)

    assert summary.wave == "initial"
    assert summary.attempted_shots == ("S01_SH00", "S02_SH00")
    batch_manifest = json.loads(
        (context.project_dir / "manifests" / "batch_run_manifest.json").read_text()
    )
    assert batch_manifest["budget"]["generated_by_shot"]["S00_SH00"] == 2


def test_executor_passes_source_image_and_style_references_to_openai(tmp_path) -> None:
    context = _context(tmp_path, shot_count=1)
    generator = FakeGenerator(tmp_path)

    def compiler(_context, *, shot_id: str) -> dict:
        return {
            **_compiler(_context, shot_id=shot_id),
            "source_image_url": "/tmp/repair-source.png",
            "reference_image_urls": ["/tmp/style-anchor.png"],
        }

    executor = StoryVideoBatchExecutor(
        prompt_compiler=compiler,
        image_generator=generator,
        candidate_judge=FakeJudge(set()),
        max_workers=3,
    )

    summary = executor.run_chunk(context)

    assert summary.work_status == "complete"
    assert generator.calls == [
        {
            "prompt": "precise prompt for S00_SH00",
            "aspect_ratio": "16:9",
            "provider": "openai-codex",
            "image_url": "/tmp/repair-source.png",
            "reference_image_urls": ["/tmp/style-anchor.png"],
        }
    ]


def test_executor_surfaces_quota_as_setup_required_without_semantic_repair(
    tmp_path,
) -> None:
    context = _context(tmp_path, shot_count=3)

    def quota_generator(args: dict, *, task_id: str = "") -> dict:
        return {
            "success": False,
            "provider": "openai-codex",
            "error_type": "quota_exceeded",
            "error": "provider quota exceeded",
        }

    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=quota_generator,
        candidate_judge=FakeJudge(set()),
        max_workers=3,
    )

    summary = executor.run_chunk(context)

    assert summary.work_status == "setup_required"
    assert summary.provider_failure_classes == ("quota_exceeded",)
    assert summary.error_type == "provider_quota_or_subscription_required"
    assert summary.generated_candidates == 0
    batch_manifest = json.loads(
        (context.project_dir / "manifests" / "batch_run_manifest.json").read_text()
    )
    assert batch_manifest["budget"]["generated_by_shot"] == {}


def test_executor_retries_transient_provider_failure_as_fresh_without_repair_spend(
    tmp_path,
) -> None:
    context = _context(tmp_path, shot_count=3)
    generator = FakeGenerator(tmp_path)
    failed_once = False

    def transient_generator(args: dict, *, task_id: str = "") -> dict:
        nonlocal failed_once
        if task_id.endswith("S01_SH00") and not failed_once:
            failed_once = True
            return {
                "success": False,
                "provider": "openai-codex",
                "error_type": "provider_unavailable",
                "error": "HTTP 503 Service Unavailable",
            }
        return generator(args, task_id=task_id)

    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compiler,
        image_generator=transient_generator,
        candidate_judge=FakeJudge(set()),
        max_workers=3,
    )

    first = executor.run_chunk(context)
    retried = executor.run_chunk(context)

    assert first.generated_candidates == 2
    assert retried.wave == "initial"
    assert retried.attempted_shots == ("S01_SH00",)
    batch_manifest = json.loads(
        (context.project_dir / "manifests" / "batch_run_manifest.json").read_text()
    )
    assert batch_manifest["budget"]["generated_by_shot"] == {
        "S00_SH00": 1,
        "S01_SH00": 1,
        "S02_SH00": 1,
    }

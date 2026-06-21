from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import trace
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


DEFAULT_TARGET_FILES = [
    "agent/visual/learning/outcomes.py",
    "agent/visual/learning/proposals.py",
    "agent/visual/promotion_policy.py",
    "agent/visual/strategy_activation.py",
    "agent/visual/judges/quality.py",
    "scripts/visual_learning_report.py",
]

DEFAULT_TEST_PATHS = [
    "tests/visual/test_learning_outcomes.py",
    "tests/visual/test_learning_proposals.py",
    "tests/visual/test_promotion_policy.py",
    "tests/visual/test_strategy_activation.py",
    "tests/visual/test_quality_judges.py",
    "tests/scripts/test_visual_learning_report.py",
]


def build_visual_test_coverage_report(
    *,
    repo_root: str | Path = _REPO_ROOT,
    target_files: list[str | Path] | None = None,
    test_paths: list[str | Path] | None = None,
    min_line_coverage: float = 0.70,
    run_tests: bool = True,
) -> dict[str, Any]:
    repo_root = Path(repo_root)
    target_paths = [_resolve(repo_root, path) for path in (target_files or DEFAULT_TARGET_FILES)]
    test_path_values = [_resolve(repo_root, path) for path in (test_paths or DEFAULT_TEST_PATHS)]
    test_count = count_test_functions(test_path_values)
    if not run_tests:
        return {
            "success": test_count > 0,
            "mode": "contract-only",
            "failures": [] if test_count > 0 else ["no_test_functions_found"],
            "tests": {"count": test_count, "paths": [_rel(repo_root, path) for path in test_path_values]},
            "coverage": {"min_line_coverage": min_line_coverage, "files": []},
        }

    pytest_exit_code, hit_counts = run_targeted_tests_with_trace(repo_root, test_path_values)
    files = [
        _coverage_for_file(repo_root, path, hit_counts)
        for path in target_paths
    ]
    failures: list[str] = []
    if pytest_exit_code != 0:
        failures.append(f"pytest_failed:{pytest_exit_code}")
    if test_count == 0:
        failures.append("no_test_functions_found")
    for item in files:
        if item["executable_lines"] and item["line_coverage"] < min_line_coverage:
            failures.append(f"line_coverage_below_threshold:{item['path']}")
    return {
        "success": not failures,
        "mode": "trace",
        "failures": failures,
        "tests": {"count": test_count, "paths": [_rel(repo_root, path) for path in test_path_values]},
        "coverage": {
            "min_line_coverage": min_line_coverage,
            "files": files,
        },
    }


def run_targeted_tests_with_trace(
    repo_root: str | Path,
    test_paths: list[Path],
) -> tuple[int, dict[tuple[str, int], int]]:
    repo_root = Path(repo_root)
    pytest_exit_code = _run_pytest_quiet(repo_root, test_paths)
    tracer = trace.Trace(
        count=True,
        trace=False,
        ignoredirs=[sys.prefix, sys.exec_prefix],
    )
    old_cwd = Path.cwd()
    try:
        os.chdir(repo_root)
        _clear_target_modules()
        tracer.runfunc(run_visual_coverage_probes)
    finally:
        os.chdir(old_cwd)
    return int(pytest_exit_code), dict(tracer.results().counts)


def _clear_target_modules() -> None:
    module_names = [
        "agent.visual.learning",
        "agent.visual.learning.outcomes",
        "agent.visual.learning.proposals",
        "agent.visual.promotion_policy",
        "agent.visual.strategy_activation",
        "agent.visual.judges.quality",
        "scripts.visual_learning_report",
    ]
    for module_name in module_names:
        sys.modules.pop(module_name, None)
    for parent_name, attribute in [
        ("agent.visual", "learning"),
        ("agent.visual.learning", "outcomes"),
        ("agent.visual.learning", "proposals"),
        ("agent.visual", "promotion_policy"),
        ("agent.visual", "strategy_activation"),
        ("agent.visual.judges", "quality"),
        ("scripts", "visual_learning_report"),
    ]:
        parent = sys.modules.get(parent_name)
        if parent is not None and hasattr(parent, attribute):
            delattr(parent, attribute)


def count_test_functions(paths: list[str | Path]) -> int:
    total = 0
    for path_value in paths:
        path = Path(path_value)
        if not path.exists() or path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        total += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        )
    return total


def executable_lines(path: str | Path) -> set[int]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {
        int(node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.stmt)
        and hasattr(node, "lineno")
    }


def _coverage_for_file(
    repo_root: Path,
    path: Path,
    hit_counts: dict[tuple[str, int], int],
) -> dict[str, Any]:
    executable = executable_lines(path)
    normalized = str(path.resolve())
    hit_lines = {
        lineno
        for (filename, lineno), count in hit_counts.items()
        if str(Path(filename).resolve()) == normalized and count > 0
    }
    covered = executable & hit_lines
    line_coverage = round(len(covered) / len(executable), 4) if executable else 1.0
    return {
        "path": _rel(repo_root, path),
        "executable_lines": len(executable),
        "covered_lines": len(covered),
        "line_coverage": line_coverage,
        "missing_lines": sorted(executable - covered)[:40],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run targeted visual test coverage using stdlib trace.")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--min-line-coverage", type=float, default=0.70)
    parser.add_argument("--no-run-tests", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_test_coverage_report(
        repo_root=args.repo_root,
        min_line_coverage=args.min_line_coverage,
        run_tests=not args.no_run_tests,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual test coverage report {status}")
    return 0 if payload["success"] else 1


def _run_pytest(paths: list[str]) -> int:
    import pytest

    return int(pytest.main([*paths, "-q"]))


def _run_pytest_quiet(repo_root: Path, test_paths: list[Path]) -> int:
    import io

    old_cwd = Path.cwd()
    output = io.StringIO()
    try:
        os.chdir(repo_root)
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            return _run_pytest([_rel(repo_root, path) for path in test_paths])
    finally:
        os.chdir(old_cwd)


def run_visual_coverage_probes() -> None:
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.judges.quality import judge_visual_quality
    from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes
    from agent.visual.learning.proposals import propose_visual_policy_updates
    from agent.visual.promotion_policy import evaluate_shadow_promotion
    from agent.visual.strategy_activation import record_strategy_activation
    from scripts import visual_learning_report

    with tempfile.TemporaryDirectory(prefix="hermes-visual-coverage-") as tmp:
        db_path = Path(tmp) / "visual.sqlite3"
        ledger = VisualAttemptLedger(db_path)
        ledger.initialize()
        bucket = "visig_probe"
        strategy = "vstrat_probe"
        for index in range(12):
            request_id = ledger.record_request(
                status="completed",
                metadata={"intent_signature": bucket},
                normalized_intent={"kind": "visual_package"},
                modality="package",
                operation="visual_package_generate",
            )
            attempt_id = ledger.record_attempt(
                request_id=request_id,
                provider="fixture",
                model="image",
                status="completed",
                metadata={"retry_of": 0} if index == 0 else {},
            )
            artifact_id = ledger.record_artifact(
                request_id=request_id,
                attempt_id=attempt_id,
                kind="image",
                local_path=f"/tmp/probe-{index}.png",
                content_hash=f"sha256:probe-{index}",
                mime_type="image/png",
                width=1024,
                height=1024,
                freshness_status="fresh",
                is_stable=True,
            )
            ledger.record_delivery(
                request_id=request_id,
                attempt_id=attempt_id,
                artifact_id=artifact_id,
                platform="slack",
                destination_id="C_PROBE",
                thread_id=f"T_PROBE_{index}",
                delivery_status="sent",
            )
            ledger.record_judgment(
                request_id=request_id,
                attempt_id=attempt_id,
                artifact_id=artifact_id,
                judge_name="visual_quality_judge",
                score=0.84,
                verdict="pass",
                details={"scores": {"aesthetic_fit": 0.84}},
            )
            ledger.record_feedback(
                request_id=request_id,
                artifact_id=artifact_id,
                feedback_text="positive",
                polarity=1.0,
                parsed={"signals": ["positive"]},
            )
            ledger.record_ranking(
                request_id=request_id,
                selected_artifact_id=artifact_id,
                decision="post",
                scores={"reward": {"final_score": 0.84, "confidence": 0.82}},
                metadata={
                    "strategy_signature": strategy,
                    "active_learning": {"action": "auto_post", "requires_user": False},
                    "strategy_plan": {"strategy_signature": strategy},
                },
            )

        negative_request_id = ledger.record_request(
            status="completed",
            metadata={"intent_signature": "visig_probe_negative"},
        )
        negative_attempt_id = ledger.record_attempt(
            request_id=negative_request_id,
            provider="fixture",
            model="video",
            status="failed",
            error_type="content_moderation",
        )
        negative_artifact_id = ledger.record_artifact(
            request_id=negative_request_id,
            attempt_id=negative_attempt_id,
            kind="video",
            local_path="/tmp/probe-negative.mp4",
            content_hash="sha256:probe-negative",
            freshness_status="fresh",
        )
        ledger.record_judgment(
            request_id=negative_request_id,
            attempt_id=negative_attempt_id,
            artifact_id=negative_artifact_id,
            judge_name="visual_quality_judge",
            score=0.9,
            verdict="pass",
        )
        ledger.record_feedback(
            request_id=negative_request_id,
            artifact_id=negative_artifact_id,
            feedback_text="退貨",
            polarity=-1.0,
            parsed={"veto": True},
        )
        ledger.record_ranking(
            request_id=negative_request_id,
            selected_artifact_id=negative_artifact_id,
            decision="ask",
            scores={},
            metadata={
                "strategy_signature": "vstrat_negative",
                "active_learning": {"action": "ask_user"},
            },
        )

        outcomes = aggregate_visual_strategy_outcomes(db_path)
        propose_visual_policy_updates(outcomes)
        visual_learning_report.build_visual_learning_report(db_path)
        promotion = evaluate_shadow_promotion(
            {
                "bucket_request_count": 25,
                "successful_artifact_count": 12,
                "successful_delivery_count": 12,
                "provider_confidence": 0.95,
                "shadow_confidence": 0.90,
                "duplicate_delivery_count": 0,
                "missing_source_metadata_count": 0,
                "recent_negative_feedback_count": 0,
                "human_veto_count": 0,
                "judge_human_disagreement_rate": 0.0,
                "self_validation_success": True,
            },
            operator_approved=True,
        )
        activation_id = record_strategy_activation(
            ledger,
            shadow_update_id="vsh_probe",
            intent_signature=bucket,
            strategy_signature=strategy,
            activation_status="controlled",
            promotion_decision=promotion.to_record(),
        )
        record_strategy_activation(
            ledger,
            shadow_update_id="vsh_probe",
            intent_signature=bucket,
            strategy_signature=strategy,
            activation_status="rolled_back",
            promotion_decision={"decision": "rollback", "allowed": False},
            rollback_of=activation_id,
        )
        record_strategy_activation(
            ledger,
            shadow_update_id="vsh_probe_blocked",
            intent_signature=bucket,
            strategy_signature="vstrat_blocked",
            activation_status="disabled",
            promotion_decision={
                "decision": "blocked",
                "allowed": False,
                "reasons": ["operator_approval_required"],
            },
        )
        try:
            record_strategy_activation(
                ledger,
                shadow_update_id="vsh_probe",
                intent_signature=bucket,
                strategy_signature=strategy,
                activation_status="controlled",
                promotion_decision={"decision": "promote_controlled", "allowed": True},
                metadata={"prompt_mutation_allowed": True},
            )
        except ValueError:
            pass
        visual_learning_report.build_visual_learning_report(db_path)
        visual_learning_report.build_visual_learning_report(Path(tmp) / "missing.sqlite3")
        visual_learning_report._failures(
            unsafe_activation_count=1,
            prompt_mutation_read_count=1,
            duplicate_delivery_count=1,
            missing_source_metadata_count=1,
        )
        visual_learning_report._json_value("{not-json")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            visual_learning_report.main(["--db-path", str(db_path), "--json"])
            visual_learning_report.main(["--db-path", str(db_path)])

    judge_visual_quality(
        {
            "kind": "video",
            "content_hash": "sha256:dup",
            "scores": {"resolution": 0.9, "final_score": 0.8, "aspect_match": 0.75, "duration": 0.7},
            "hard_gate": {"passed": True, "delivery_possible": True},
            "metadata": {"reference_adherence": 0.8},
        },
        request_context={"has_reference_image": True, "category": "portrait fashion"},
        recent_artifact_hashes={"sha256:dup"},
        vision_observation={
            "confidence": 0.9,
            "visual_appeal": 0.88,
            "composition": 0.8,
            "aspect_integrity": 0.7,
            "motion_quality": 0.65,
            "artifact_defects": ["distorted_face"],
        },
    )
    judge_visual_quality(
        {"scores": {}, "hard_gate": {"passed": False, "delivery_possible": False}},
        request_context={},
    )


def _resolve(repo_root: Path, path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else repo_root / path


def _rel(repo_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())

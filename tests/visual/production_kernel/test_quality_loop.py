from agent.visual.production_kernel.quality_loop import BoundedQualityLoop
from agent.visual.production_kernel.quality_loop import QualitySnapshot


def _snapshot(
    artifact_id: str,
    *,
    score: float,
    blockers: tuple[str, ...],
    deliverable: bool = False,
    artifact_valid: bool = True,
) -> QualitySnapshot:
    return QualitySnapshot(
        artifact_id=artifact_id,
        score=score,
        blocker_codes=blockers,
        deliverable=deliverable,
        artifact_valid=artifact_valid,
    )


def test_bounded_loop_keeps_champion_when_challenger_is_worse():
    loop = BoundedQualityLoop(
        _snapshot("initial", score=0.55, blockers=("composition_weak",)),
        max_rounds=2,
    )

    result = loop.observe(
        _snapshot("worse", score=0.40, blockers=("composition_weak",)),
        repair_fingerprint="composition_reset:composition_weak",
    )

    assert result.accepted is False
    assert result.champion.artifact_id == "initial"
    assert result.stop_reason == "no_progress"
    assert loop.to_record()["rounds_attempted"] == 1


def test_bounded_loop_allows_improving_round_then_stops_on_deliverable_champion():
    loop = BoundedQualityLoop(
        _snapshot(
            "initial",
            score=0.45,
            blockers=("composition_weak", "action_or_moment_missing"),
        ),
        max_rounds=2,
    )

    first = loop.observe(
        _snapshot("better", score=0.58, blockers=("action_or_moment_missing",)),
        repair_fingerprint="composition_reset:composition_weak,action_or_moment_missing",
    )
    second = loop.observe(
        _snapshot("final", score=0.88, blockers=(), deliverable=True),
        repair_fingerprint="story_moment_reframe:action_or_moment_missing",
    )

    assert first.accepted is True
    assert first.stop_reason is None
    assert second.accepted is True
    assert second.champion.artifact_id == "final"
    assert second.stop_reason == "quality_gate_passed"
    assert loop.to_record()["rounds_attempted"] == 2
    assert loop.to_record()["history"][0]["prior_champion_artifact_id"] == "initial"
    assert loop.to_record()["history"][0]["champion_artifact_id"] == "better"


def test_bounded_loop_stops_before_repeating_the_same_repair_strategy():
    loop = BoundedQualityLoop(
        _snapshot("initial", score=0.45, blockers=("composition_weak",)),
        max_rounds=2,
    )
    loop.observe(
        _snapshot("better", score=0.55, blockers=("composition_weak",)),
        repair_fingerprint="composition_reset:composition_weak",
    )

    decision = loop.can_attempt("composition_reset:composition_weak")

    assert decision.allowed is False
    assert decision.stop_reason == "repeated_strategy"


def test_bounded_loop_rejects_invalid_challenger_even_with_higher_score():
    loop = BoundedQualityLoop(
        _snapshot("initial", score=0.45, blockers=("composition_weak",)),
        max_rounds=2,
    )

    result = loop.observe(
        _snapshot(
            "invalid",
            score=0.99,
            blockers=(),
            deliverable=True,
            artifact_valid=False,
        ),
        repair_fingerprint="composition_reset:composition_weak",
    )

    assert result.accepted is False
    assert result.champion.artifact_id == "initial"
    assert result.stop_reason == "no_progress"


def test_bounded_loop_rejects_deliverable_challenger_with_major_quality_regression():
    loop = BoundedQualityLoop(
        _snapshot("initial", score=0.72, blockers=("action_or_moment_missing",)),
        max_rounds=2,
    )

    result = loop.observe(
        _snapshot("technically-clean", score=0.40, blockers=(), deliverable=True),
        repair_fingerprint="story_moment_reframe:action_or_moment_missing",
    )

    assert result.accepted is False
    assert result.champion.artifact_id == "initial"
    assert result.stop_reason == "no_progress"


def test_bounded_loop_rejects_challenger_that_introduces_a_new_blocker():
    loop = BoundedQualityLoop(
        _snapshot("initial", score=0.55, blockers=("composition_weak",)),
        max_rounds=2,
    )

    result = loop.observe(
        _snapshot("different-defect", score=0.80, blockers=("truth_or_evidence_risk",)),
        repair_fingerprint="composition_reset:composition_weak",
    )

    assert result.accepted is False
    assert result.champion.artifact_id == "initial"
    assert loop.to_record()["history"][0]["introduced_blocker_codes"] == [
        "truth_or_evidence_risk"
    ]


def test_bounded_loop_allows_one_distinct_retry_after_near_equal_challenger_adds_blocker():
    loop = BoundedQualityLoop(
        _snapshot("champion", score=0.6876, blockers=("artifact_defect",)),
        max_rounds=2,
    )

    first = loop.observe(
        _snapshot(
            "challenger",
            score=0.6787,
            blockers=("artifact_defect", "composition_weak"),
        ),
        repair_fingerprint="targeted_repair:artifact_defect",
    )
    second_decision = loop.can_attempt("constraint_rebuild:artifact_defect")

    assert first.accepted is False
    assert first.champion.artifact_id == "champion"
    assert first.stop_reason is None
    assert second_decision.allowed is True

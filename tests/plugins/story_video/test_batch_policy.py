from __future__ import annotations

import pytest

from plugins.story_video.batch_policy import (
    BatchBudget,
    BatchBudgetExceeded,
    BatchPolicy,
)


def test_eighteen_shot_run_caps_repairs_at_four() -> None:
    policy = BatchPolicy.for_run(18)

    assert policy.initial_candidate_cap == 18
    assert policy.repair_candidate_cap == 4
    assert policy.max_total_candidates == 22
    assert policy.max_candidates_per_shot == 2


def test_replan_does_not_reset_end_to_end_shot_budget() -> None:
    budget = BatchBudget(BatchPolicy.for_run(18))

    budget.record_generation("S06_SH00", "contract-a")
    budget.record_generation("S06_SH00", "contract-b")

    assert budget.can_generate("S06_SH00", critical=False) is False
    with pytest.raises(BatchBudgetExceeded, match="S06_SH00"):
        budget.record_generation("S06_SH00", "contract-c")


def test_critical_shot_gets_third_attempt_without_expanding_run_cap() -> None:
    budget = BatchBudget(BatchPolicy.for_run(2))

    budget.record_generation("S00_SH00", "contract-a", critical=True)
    budget.record_generation("S00_SH00", "contract-b", critical=True)

    assert budget.can_generate("S00_SH00", critical=True) is True
    assert budget.can_generate("S00_SH00", critical=False) is False


def test_budget_round_trip_preserves_counts_across_contract_hashes() -> None:
    original = BatchBudget(BatchPolicy.for_run(6))
    original.record_generation("S01_SH00", "contract-a")
    original.record_generation("S01_SH00", "contract-b")
    original.record_generation("S02_SH00", "contract-a")

    restored = BatchBudget.from_dict(original.to_dict())

    assert restored.total_generated == 3
    assert restored.generated_for("S01_SH00") == 2
    assert restored.contract_hashes_for("S01_SH00") == ("contract-a", "contract-b")
    assert restored.can_generate("S01_SH00") is False


def test_run_wide_cap_stops_otherwise_eligible_shot() -> None:
    policy = BatchPolicy(
        initial_candidate_cap=1,
        repair_candidate_cap=1,
        max_candidates_per_shot=2,
        critical_max_candidates_per_shot=3,
    )
    budget = BatchBudget(policy)
    budget.record_generation("S00_SH00", "contract-a")
    budget.record_generation("S01_SH00", "contract-a")

    assert budget.total_generated == policy.max_total_candidates
    assert budget.can_generate("S02_SH00") is False


def test_batch_budget_releases_failed_provider_reservation() -> None:
    budget = BatchBudget(BatchPolicy.for_run(3))
    budget.record_generation("S00_SH00", "contract-a")

    budget.release_generation("S00_SH00", "contract-a")

    assert budget.generated_for("S00_SH00") == 0
    assert budget.contract_hashes_for("S00_SH00") == ()
    assert budget.can_generate("S00_SH00") is True

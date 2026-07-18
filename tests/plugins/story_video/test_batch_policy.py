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
    assert policy.max_total_candidates == 23
    assert policy.max_candidates_per_shot == 2
    assert policy.semantic_pivot_candidate_cap == 1


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


def test_critical_shot_reserves_bounded_semantic_pivot_candidate() -> None:
    budget = BatchBudget(BatchPolicy.for_run(10))

    budget.record_generation("S03", "contract-a", critical=True)
    budget.record_generation("S03", "contract-a", critical=True)
    budget.record_generation("S03", "contract-a", critical=True)

    assert budget.can_generate("S03", critical=True) is True
    budget.record_generation("S03", "contract-b", critical=True)
    assert budget.can_generate("S03", critical=True) is True
    budget.record_generation("S03", "contract-c", critical=True)
    assert budget.can_generate("S03", critical=True) is False
    assert budget.total_generated == 5
    assert budget.policy.max_total_candidates == 14


def test_old_serialized_budget_migrates_critical_replan_slot() -> None:
    restored = BatchBudget.from_dict(
        {
            "policy": {
                "initial_candidate_cap": 10,
                "repair_candidate_cap": 3,
                "max_candidates_per_shot": 2,
                "critical_max_candidates_per_shot": 3,
            },
            "generated_by_shot": {"S03": 3},
            "contract_hashes_by_shot": {"S03": ["contract-a"] * 3},
        }
    )

    assert restored.can_generate("S03", critical=True) is True
    assert restored.policy.critical_max_candidates_per_shot == 5
    assert restored.policy.semantic_pivot_candidate_cap == 1
    assert restored.policy.max_total_candidates == 14


def test_legacy_strategy_pivot_migration_grants_exactly_one_candidate() -> None:
    budget = BatchBudget(BatchPolicy.for_run(10))
    for contract_hash in (
        "contract-a",
        "contract-a",
        "contract-a",
        "contract-b",
        "contract-c",
    ):
        budget.record_generation("S03", contract_hash, critical=True)

    assert budget.can_generate("S03", critical=True) is False
    budget.grant_legacy_strategy_pivot_slot()
    assert budget.policy.legacy_strategy_pivot_candidate_cap == 1
    assert budget.can_generate("S03", critical=True) is True
    budget.record_generation("S03", "contract-d", critical=True)
    assert budget.can_generate("S03", critical=True) is False
    assert budget.total_generated == 6
    assert budget.policy.max_total_candidates == 15


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


def test_replanned_contract_gets_one_persisted_candidate_entitlement() -> None:
    policy = BatchPolicy(
        initial_candidate_cap=1,
        repair_candidate_cap=0,
        max_candidates_per_shot=2,
        critical_max_candidates_per_shot=5,
        semantic_pivot_candidate_cap=0,
    )
    budget = BatchBudget(policy)
    budget.record_generation("S04", "contract-old", critical=True)

    assert budget.can_generate("S04", critical=True) is False
    budget.grant_contract_replan_slots([("S04", "contract-new")])
    assert budget.policy.contract_replan_candidate_cap == 1
    assert budget.can_generate("S04", critical=True) is True
    budget.record_generation("S04", "contract-new", critical=True)
    assert budget.can_generate("S04", critical=True) is False

    restored = BatchBudget.from_dict(budget.to_dict())
    restored.grant_contract_replan_slots([("S04", "contract-new")])
    assert restored.policy.contract_replan_candidate_cap == 1
    assert restored.contract_replan_hashes_granted == ("S04:contract-new",)

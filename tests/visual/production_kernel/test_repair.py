import pytest

from agent.visual.production_kernel.repair import plan_visual_repair


def test_reference_drift_maps_to_identity_recovery():
    plan = plan_visual_repair(
        ("reference_identity_drift",),
        prior_generated_repairs=(),
    )

    assert plan.strategy == "identity_recovery"
    assert plan.should_generate is True
    assert "reference_identity_drift" in plan.directive


def test_composition_failure_maps_to_material_layout_change():
    plan = plan_visual_repair(
        ("composition_weak",),
        prior_generated_repairs=(),
    )

    assert plan.strategy == "composition_reset"
    assert "materially different composition" in plan.directive


def test_persistent_composition_and_action_blockers_advance_to_action_repair():
    plan = plan_visual_repair(
        ("action_or_moment_missing", "composition_weak"),
        prior_generated_repairs=("composition_reset",),
        max_generated_repairs=2,
    )

    assert plan.strategy == "story_moment_reframe"
    assert plan.should_generate is True
    assert "decisive visible action" in plan.directive


@pytest.mark.parametrize(
    ("blocker", "prior_strategy"),
    (
        ("reference_identity_drift", "identity_recovery"),
        ("reference_overcopy", "reference_resynthesis"),
        ("composition_weak", "composition_reset"),
        ("action_or_moment_missing", "story_moment_reframe"),
        ("style_mismatch", "style_correction"),
        ("truth_or_evidence_risk", "truth_reframe"),
    ),
)
def test_persistent_specific_blocker_does_not_repeat_prior_strategy(
    blocker: str,
    prior_strategy: str,
):
    plan = plan_visual_repair(
        (blocker,),
        prior_generated_repairs=(prior_strategy,),
        max_generated_repairs=2,
    )

    assert plan.should_generate is True
    assert plan.strategy == "targeted_repair"


def test_default_repair_budget_stops_after_one_generated_repair():
    plan = plan_visual_repair(
        ("composition_weak",),
        prior_generated_repairs=("composition_reset",),
    )

    assert plan.strategy == "review_required"
    assert plan.should_generate is False
    assert plan.reason == "generated_repair_budget_exhausted"


def test_second_artifact_repair_uses_constraint_rebuild_within_budget():
    plan = plan_visual_repair(
        ("artifact_defect",),
        prior_generated_repairs=("targeted_repair",),
        max_generated_repairs=2,
    )

    assert plan.strategy == "constraint_rebuild"
    assert plan.should_generate is True
    assert plan.should_switch_provider is False
    assert "each explicit user requirement" in plan.directive


@pytest.mark.parametrize("blocker", ("subject_mismatch", "other"))
def test_persistent_targeted_blocker_uses_constraint_rebuild(blocker: str):
    plan = plan_visual_repair(
        (blocker,),
        prior_generated_repairs=("targeted_repair",),
        max_generated_repairs=2,
    )

    assert plan.strategy == "constraint_rebuild"
    assert plan.should_generate is True


def test_provider_failure_requests_switch_instead_of_prompt_tuning():
    plan = plan_visual_repair(
        ("provider_failure",),
        prior_generated_repairs=(),
    )

    assert plan.strategy == "provider_switch"
    assert plan.should_generate is True
    assert plan.should_switch_provider is True


def test_persistent_provider_failure_stops_instead_of_repeating_switch():
    plan = plan_visual_repair(
        ("provider_failure",),
        prior_generated_repairs=("provider_switch",),
        max_generated_repairs=2,
    )

    assert plan.strategy == "review_required"
    assert plan.should_generate is False
    assert plan.reason == "persistent_provider_failure"


def test_stale_contract_requires_recompile_without_generation():
    plan = plan_visual_repair(
        ("stale_contract",),
        prior_generated_repairs=(),
    )

    assert plan.strategy == "recompile_contract"
    assert plan.should_generate is False


def test_reference_overcopy_requests_new_role_locked_synthesis():
    plan = plan_visual_repair(
        ("reference_overcopy",),
        prior_generated_repairs=(),
    )

    assert plan.strategy == "reference_resynthesis"
    assert plan.should_generate is True
    assert "identity reference" in plan.directive
    assert "pose reference" in plan.directive

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


def test_provider_failure_requests_switch_instead_of_prompt_tuning():
    plan = plan_visual_repair(
        ("provider_failure",),
        prior_generated_repairs=(),
    )

    assert plan.strategy == "provider_switch"
    assert plan.should_generate is True
    assert plan.should_switch_provider is True


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

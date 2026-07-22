from agent.visual.production_kernel.integration import attach_visual_production_kernel


def test_production_kernel_never_authorizes_grok_web_provider():
    result = attach_visual_production_kernel(
        "Create a cinematic product image",
        {
            "candidate_budget": 1,
            "candidate_budget_source": "planner_default",
            "image_provider": "grok-web-imagine",
            "authorized_image_providers": ["grok-web-imagine", "xai"],
            "provider_profiles": {
                "grok-web-imagine": {"sample_count": 100, "first_pass_rate": 1.0},
                "xai": {"sample_count": 20, "first_pass_rate": 0.5},
            },
        },
    )

    assert result["image_provider"] == "xai"
    assert "grok-web-imagine" not in result["authorized_image_providers"]


def test_explicit_zero_repair_budget_is_preserved():
    result = attach_visual_production_kernel(
        "Create a clean product image",
        {
            "candidate_budget": 1,
            "candidate_budget_source": "user",
            "image_provider": "xai",
            "max_generated_repairs": 0,
        },
    )

    assert result["max_generated_repairs"] == 0


def test_default_repair_budget_allows_two_bounded_quality_rounds():
    result = attach_visual_production_kernel(
        "Create a dramatic educational image",
        {
            "candidate_budget": 1,
            "candidate_budget_source": "planner_default",
            "image_provider": "xai",
        },
    )

    assert result["candidate_budget"] == 1
    assert result["max_generated_repairs"] == 2


def test_explicit_override_source_cannot_be_replaced_by_quality_profile():
    result = attach_visual_production_kernel(
        "Create a clean product image",
        {
            "candidate_budget": 1,
            "candidate_budget_source": "user",
            "image_provider": "xai",
            "image_provider_source": "explicit_override",
            "provider_profiles": {
                "xai": {"sample_count": 20, "first_pass_rate": 0.2},
                "openai-codex": {"sample_count": 20, "first_pass_rate": 1.0},
            },
        },
    )

    assert result["image_provider"] == "xai"
    assert result["provider_decision"]["reason"] == "explicit_override"


def test_reference_roles_use_stable_indices_instead_of_local_paths():
    base = {
        "candidate_budget": 1,
        "candidate_budget_source": "user",
        "image_provider": "xai",
    }
    first = attach_visual_production_kernel(
        "Create a portrait from the identity reference",
        {
            **base,
            "reference_binding": {
                "reference_order": [
                    {
                        "index": 1,
                        "role_hint": "character_identity",
                        "attachment": "/private/tmp/first.png",
                    }
                ]
            },
        },
    )
    second = attach_visual_production_kernel(
        "Create a portrait from the identity reference",
        {
            **base,
            "reference_binding": {
                "reference_order": [
                    {
                        "index": 1,
                        "role_hint": "character_identity",
                        "attachment": "/Users/example/second.png",
                    }
                ]
            },
        },
    )

    assert first["visual_intent_contract"]["reference_roles"] == [
        ["ref:1", "character_identity"]
    ]
    assert first["visual_contract_hash"] == second["visual_contract_hash"]
    assert "/private/tmp" not in str(first["visual_intent_contract"])


def test_production_kernel_extracts_explicit_chinese_action_constraint():
    result = attach_visual_production_kernel(
        "基於這個動作，試試兩隻手都舉起來的動作，更性感一些，也是 4 張讓我挑選",
        {
            "candidate_budget": 4,
            "candidate_budget_source": "user",
            "image_provider": "xai",
        },
    )

    assert result["visual_intent_contract"]["observable_action"] == "兩隻手都舉起來"


def test_production_kernel_extracts_bare_chinese_limb_action_constraint():
    result = attach_visual_production_kernel("兩隻手都舉起來", {})

    assert result["visual_intent_contract"]["observable_action"] == "兩隻手都舉起來"

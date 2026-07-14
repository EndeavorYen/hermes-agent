from agent.visual.production_kernel.integration import attach_visual_production_kernel


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

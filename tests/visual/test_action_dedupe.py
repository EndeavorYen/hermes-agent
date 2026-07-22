from agent.visual.action_dedupe import dedupe_actions


def test_dedupe_actions_preserves_distinct_quality_dimensions_and_focuses():
    face_repair = {
        "type": "repair_low_preference_dimension",
        "source": "live_quality_burn",
        "dimension": "face_naturalness",
    }
    material_repair = {
        "type": "repair_low_preference_dimension",
        "source": "live_quality_burn",
        "dimension": "fashion_material_quality",
    }
    legwear_focus = {
        "type": "apply_quality_focus_operator",
        "source": "live_quality_trends",
        "dimension": "fashion_material_quality",
        "focus": "legwear_material",
        "strategy_operator": "refine_legwear_material",
    }
    composition_focus = {
        "type": "apply_quality_focus_operator",
        "source": "live_quality_trends",
        "dimension": "pose_composition",
        "focus": "long_leg_composition",
        "strategy_operator": "refine_long_leg_composition",
    }

    assert dedupe_actions(
        [
            face_repair,
            material_repair,
            legwear_focus,
            composition_focus,
            dict(face_repair),
            dict(legwear_focus),
        ]
    ) == [
        face_repair,
        material_repair,
        legwear_focus,
        composition_focus,
    ]


def test_dedupe_actions_preserves_distinct_provider_failure_contexts():
    moderation_retry = {
        "type": "safe_reframe_provider_retry",
        "source": "live_quality_burn",
        "provider_failure_classes": {"content_moderation": 2},
        "provider_error_codes": {"api_error": 2},
    }
    timeout_retry = {
        "type": "safe_reframe_provider_retry",
        "source": "live_quality_burn",
        "provider_failure_classes": {"timeout": 1},
        "provider_error_codes": {"timeout": 1},
    }

    assert dedupe_actions([moderation_retry, timeout_retry, dict(moderation_retry)]) == [
        moderation_retry,
        timeout_retry,
    ]

from __future__ import annotations

from agent.visual.arsenal_prompt import build_arsenal_prompt_variants


def test_arsenal_prompt_variants_turn_preference_repairs_into_distinct_anime_candidates():
    variants = build_arsenal_prompt_variants(
        base_prompt="動漫圖，性感一些，固定角色身份，產出最佳圖片。",
        strategy_plan={
            "atom_signatures": [
                "composition.full_subject_visible@v1",
                "composition.leg_emphasis_editorial@v1",
                "safety.professional_editorial@v1",
            ]
        },
        feedback_policy={
            "repair_dimensions": [
                {
                    "dimension": "subject_beauty",
                    "quality_issue": "subject_not_attractive",
                    "repair_hint": "improve_subject_beauty",
                },
                {
                    "dimension": "fashion_material_quality",
                    "quality_issue": "stockings_bad",
                    "repair_hint": "improve_fashion_material_quality",
                },
            ]
        },
        request_category="anime",
        candidate_budget=3,
    )

    assert len(variants) == 3
    prompts = [variant["prompt"] for variant in variants]
    assert len(set(prompts)) == 3
    assert prompts[0] == "動漫圖，性感一些，固定角色身份，產出最佳圖片。"
    assert all("動漫圖，性感一些" in prompt for prompt in prompts)
    assert any("expressive anime face" in prompt for prompt in prompts)
    assert any("wardrobe and legwear" in prompt for prompt in prompts)
    assert any("long leg line" in prompt for prompt in prompts)
    assert all("natural realism" not in prompt for prompt in prompts)
    assert all("professional editorial photography" not in prompt for prompt in prompts)
    assert variants[0]["source"] == "visual_arsenal"
    assert variants[0]["prompt_delta"] == ""
    assert variants[1]["variant_id"] == "arsenal_repair_combined"
    assert variants[1]["applied_dimensions"] == ["subject_beauty", "fashion_material_quality"]


def test_arsenal_prompt_variants_keep_candidate_budget_diverse():
    variants = build_arsenal_prompt_variants(
        base_prompt="請產出一張產品圖：霧黑鋼筆。",
        strategy_plan={
            "atom_signatures": [
                "safety.professional_editorial@v1",
                "composition.full_subject_visible@v1",
                "motion.natural_continuous_action@v1",
                "product.clean_window_light@v1",
            ]
        },
        feedback_policy={},
        request_category="product",
        candidate_budget=4,
    )

    prompts = [variant["prompt"] for variant in variants]
    assert len(variants) == 4
    assert len(set(prompts)) == 4
    assert all("real-time motion" not in prompt for prompt in prompts)
    assert all("professional editorial photography" not in prompt for prompt in prompts)


def test_arsenal_prompt_variants_are_bounded_when_no_feedback_exists():
    variants = build_arsenal_prompt_variants(
        base_prompt="請產出一張產品圖：霧黑鋼筆。",
        strategy_plan={"atom_signatures": ["product.clean_window_light@v1"]},
        feedback_policy={},
        request_category="product",
        candidate_budget=2,
    )

    assert len(variants) == 2
    assert variants[0]["prompt"] != variants[1]["prompt"]
    assert variants[0]["prompt"] == "請產出一張產品圖：霧黑鋼筆。"
    assert "clean product photography" in variants[1]["prompt"]
    assert all("real-time motion" not in variant["prompt"] for variant in variants)
    assert all("professional editorial photography" not in variant["prompt"] for variant in variants)
    assert variants[0]["applied_dimensions"] == []


def test_arsenal_prompt_variants_reuse_approved_prompt_as_bounded_candidate():
    variants = build_arsenal_prompt_variants(
        base_prompt="動漫圖，固定角色，產出最佳圖片。",
        strategy_plan={"atom_signatures": []},
        feedback_policy={},
        request_category="anime_character",
        candidate_budget=2,
        approved_prompt_entries=[
            {
                "prompt_mediated": (
                    "Anime illustration, youthful cheerful face, tight glossy qipao, "
                    "visible abdominal lines, dynamic best pose, soft cinematic lighting."
                ),
                "confidence": 0.9,
            }
        ],
    )

    assert len(variants) == 2
    assert variants[1]["variant_id"] == "arsenal_approved_prompt_1"
    assert variants[1]["source"] == "visual_arsenal"
    assert variants[1]["approved_prompt_entry"] is True
    assert "user-approved prior prompt pattern" in variants[1]["prompt"]
    assert "tight glossy qipao" in variants[1]["prompt"]
    assert "Adapt the pattern" in variants[1]["prompt"]

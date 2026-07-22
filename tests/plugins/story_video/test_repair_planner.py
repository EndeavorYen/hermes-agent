from plugins.story_video.repair_planner import (
    apply_repair_strategy,
    classify_blockers,
    plan_repair,
)


def test_legacy_chinese_anatomy_and_science_blockers_are_typed() -> None:
    codes = classify_blockers([
        "科學與解剖辨識不足：無法可信辨識為纖細的阿希利龍顎部化石。",
        "牙齒幾何疑似失真，齒冠彼此黏連或不規則分叉。",
    ])

    assert codes == {"anatomy_geometry", "scientific_identity"}


def test_failed_legacy_layout_reset_pivots_to_evidence_reframe() -> None:
    plan = plan_repair([{
        "status": "quality_budget_exhausted",
        "strategy_reset": True,
        "hard_blockers": [
            "科學與解剖辨識不足：無法可信辨識為阿希利龍顎部化石。",
            "牙齒幾何疑似失真。",
        ],
    }])

    assert plan.strategy == "evidence_reframe"
    assert plan.candidate_suffix == "EVIDENCE_C01"
    assert "fragmentary evidence" in plan.directive
    assert plan.exhausted is False


def test_failed_evidence_reframe_advances_to_contextual_replan() -> None:
    plan = plan_repair([
        {
            "status": "quality_budget_exhausted",
            "strategy_reset": True,
            "hard_blockers": ["字幕安全區衝突"],
        },
        {
            "status": "quality_budget_exhausted",
            "repair_strategy": "evidence_reframe",
            "blocker_codes": ["anatomy_geometry"],
            "hard_blockers": ["malformed tooth geometry"],
        },
    ])

    assert plan.strategy == "contextual_replan"
    assert plan.candidate_suffix == "CONTEXT_C01"
    assert plan.exhausted is False


def test_all_semantic_strategies_must_fail_before_exhaustion() -> None:
    plan = plan_repair([
        {"status": "quality_budget_exhausted", "repair_strategy": strategy,
         "blocker_codes": ["scientific_identity"], "hard_blockers": ["wrong"]}
        for strategy in (
            "evidence_reframe", "contextual_replan", "documentary_context"
        )
    ])

    assert plan.exhausted is True
    assert plan.strategy == "human_review_required"


def test_subtitle_collision_repair_reserves_a_concrete_empty_region() -> None:
    plan = plan_repair([
        {
            "status": "quality_budget_exhausted",
            "repair_strategy": "layout_reset",
            "blocker_codes": ["subtitle_collision"],
        },
        {
            "status": "quality_budget_exhausted",
            "repair_strategy": "contextual_replan",
            "blocker_codes": ["subtitle_collision"],
        },
    ])

    assert plan.strategy == "documentary_context"
    effective = apply_repair_strategy(
        {
            "action": "examining a specimen",
            "subtitle_safe_area": "right_third",
            "acceptance_criteria": ["credible research context"],
        },
        plan.strategy,
        blocker_codes=plan.blocker_codes,
    )
    assert "left 60 percent" in effective["action"]
    assert "right 35 percent" in effective["acceptance_criteria"][-1]
    assert "people, hands, tools, and specimens" in effective["acceptance_criteria"][-1]


def test_evidence_reframe_replaces_risky_macro_contract() -> None:
    effective = apply_repair_strategy({
        "subject": "阿希利龍顎部化石",
        "action": "在均勻側光下展示",
        "evidence_detail": "牙齒與下顎保存區",
        "shot_scale": "macro",
        "focal_point": "牙列",
        "acceptance_criteria": ["只展示保存部分"],
    }, "evidence_reframe")

    assert effective["shot_scale"] == "close_up"
    assert effective["subject"] == (
        "fragmentary research specimen showing 牙齒與下顎保存區"
    )
    assert "阿希利龍" not in effective["subject"]
    assert "no invented complete specimen" in effective["acceptance_criteria"]


def test_static_catalog_routes_directly_to_story_reframe() -> None:
    plan = plan_repair(
        [
            {
                "status": "repair_required",
                "repair_round": 1,
                "blocker_codes": ["static_catalog"],
                "hard_blockers": ["The image reads as a static catalog record."],
            }
        ]
    )

    assert plan.strategy == "story_reframe"
    assert plan.candidate_suffix == "STORY_C01"

    effective = apply_repair_strategy(
        {
            "subject": "a component on a workbench",
            "action": "resting on the workbench",
            "story_moment": "a technician seats the component into its final position",
            "action_consequence": "the alignment marks visibly meet",
            "attention_hook": "whether the two marks will align",
            "acceptance_criteria": ["component remains identifiable"],
        },
        plan.strategy,
        blocker_codes=plan.blocker_codes,
    )
    assert "technician seats" in effective["action"]
    assert "alignment marks visibly meet" in effective["action"]
    assert any(
        "decisive instant" in criterion
        for criterion in effective["acceptance_criteria"]
    )


def test_story_reframe_preserves_camera_reveal_as_renderer_motion() -> None:
    shot = {
        "subject": "an aftermath valley",
        "action": "低空緩慢推進",
        "story_moment": "低空緩慢推進後揭示整座河谷",
        "action_consequence": "灰層與水道依序可辨識",
        "shot_scale": "establishing",
        "focal_point": "layered valley",
        "acceptance_criteria": ["aftermath is readable"],
    }

    effective = apply_repair_strategy(
        shot,
        "story_reframe",
        blocker_codes=["missing_story_moment"],
    )

    assert effective["action"] == shot["action"]
    assert any(
        "source frame supports the declared renderer motion" in criterion
        for criterion in effective["acceptance_criteria"]
    )
    assert not any(
        "decisive instant" in criterion
        for criterion in effective["acceptance_criteria"]
    )


def test_audience_mismatch_routes_to_audience_reframe() -> None:
    plan = plan_repair(
        [
            {
                "status": "repair_required",
                "repair_round": 1,
                "blocker_codes": ["audience_mismatch"],
                "hard_blockers": ["The focal hierarchy is too abstract for the audience."],
            }
        ]
    )

    assert plan.strategy == "audience_reframe"
    assert "audience" in plan.directive.lower()


def test_style_drift_gets_one_style_locked_reframe_before_other_repairs() -> None:
    first = plan_repair(
        [
            {
                "status": "repair_required",
                "repair_round": 1,
                "blocker_codes": ["style_drift"],
                "hard_blockers": ["Lighting and palette do not match the style reference."],
            }
        ]
    )

    assert first.strategy == "style_reframe"
    assert first.candidate_suffix == "STYLE_C01"
    assert "locked style bible" in first.directive

    effective = apply_repair_strategy(
        {
            "subject": "one small dinosaur",
            "action": "steps over a fresh track",
            "evidence_detail": "upright hind limbs",
            "acceptance_criteria": ["anatomy remains credible"],
        },
        first.strategy,
        blocker_codes=first.blocker_codes,
    )
    assert effective["subject"] == "one small dinosaur"
    assert effective["action"] == "steps over a fresh track"
    assert any(
        "matches the locked style bible" in criterion
        for criterion in effective["acceptance_criteria"]
    )

    second = plan_repair(
        [
            {
                "status": "quality_budget_exhausted",
                "repair_strategy": "style_reframe",
                "blocker_codes": ["style_drift"],
            }
        ]
    )
    assert second.strategy == "story_reframe"


def test_sensationalized_or_mixed_truth_routes_to_truth_reframe() -> None:
    plan = plan_repair(
        [
            {
                "status": "repair_required",
                "repair_round": 1,
                "blocker_codes": ["sensationalized_claim"],
                "hard_blockers": ["The image depicts danger not supported by the narration."],
            }
        ]
    )

    assert plan.strategy == "truth_reframe"

    effective = apply_repair_strategy(
        {
            "subject": "historical evidence and a reconstructed event",
            "action": "showing both as one seamless event",
            "evidence_detail": "the surviving document",
            "visual_truth_mode": "mixed_evidence_reconstruction",
            "acceptance_criteria": ["document is readable as the evidence object"],
        },
        plan.strategy,
        blocker_codes=("mixed_evidence_reconstruction",),
    )
    assert effective["visual_truth_mode"] == "direct_evidence"
    assert "surviving document" in effective["focal_point"]

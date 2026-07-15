from __future__ import annotations

from plugins.story_video.quality import (
    candidate_budget_for_shot,
    compile_shot_prompt,
    rank_candidate_assessments,
    validate_quality_ledger,
)


def _shot(index: int, *, scale: str = "medium", risk: str = "normal") -> dict:
    shot_id = f"S00_SH{index:02d}"
    return {
        "shot_id": shot_id,
        "narration_text": f"第 {index} 個可視化旁白片段",
        "narrative_role": "evidence" if scale in {"close_up", "macro", "insert"} else "mechanism",
        "viewer_takeaway": "直立腿讓移動更有效率",
        "subject": "小型早期恐龍的後肢",
        "action": "腳掌落在乾裂泥地並帶起細小塵土",
        "evidence_detail": "腿位於身體正下方，關節與足跡清楚可辨",
        "shot_scale": scale,
        "camera_angle": "低視角側面",
        "focal_point": "畫面中央偏左的後肢與腳掌",
        "subtitle_safe_area": "bottom 20 percent clear",
        "acceptance_criteria": [
            "upright limb posture is immediately readable",
            "foot contact and track detail are sharp",
        ],
        "risk_class": risk,
    }


def _ledger(shots: list[dict], *, duration: float = 60.0) -> dict:
    return {
        "schema": "story_video_scene_ledger_v2",
        "production_type": "science_explainer",
        "target_duration_sec": duration,
        "visual_style": "photoreal professional science documentary",
        "scenes": [
            {
                "scene_id": "S00",
                "narrative_role": "mechanism",
                "viewer_takeaway": "直立腿提高移動效率",
                "shots": shots,
            }
        ],
    }


def _assessment(candidate_id: str, score: float, **overrides) -> dict:
    dimensions = {
        "text_alignment": score,
        "focal_clarity": score,
        "evidence_specificity": score,
        "professional_quality": score,
        "scientific_credibility": score,
        "continuity_and_diversity": score,
        "narrative_engagement": score,
        "story_moment_clarity": score,
        "cinematic_impact": score,
    }
    payload = {
        "candidate_id": candidate_id,
        "provider": "openai-codex",
        "judge_provider": "openai-codex",
        "hard_blockers": [],
        "dimensions": dimensions,
        "evidence": ["candidate image inspected by OpenAI vision"],
    }
    payload.update(overrides)
    return payload


def test_quality_ledger_requires_nested_shots_and_visual_evidence() -> None:
    report = validate_quality_ledger(
        {
            "production_type": "science_explainer",
            "target_duration_sec": 300,
            "scenes": [
                {
                    "scene_id": "S00",
                    "viewer_takeaway": "直立腿提高移動效率",
                }
            ],
        }
    )

    assert report.ok is False
    assert "S00.shots" in report.violations


def test_quality_ledger_rejects_shot_without_observable_evidence() -> None:
    shot = _shot(0)
    shot["evidence_detail"] = ""

    report = validate_quality_ledger(_ledger([shot], duration=8))

    assert report.ok is False
    assert "S00_SH00.evidence_detail" in report.violations


def test_five_minute_quality_profile_requires_25_to_40_semantic_shots() -> None:
    report = validate_quality_ledger(_ledger([_shot(i) for i in range(20)], duration=300))

    assert report.ok is False
    assert "shot_density_below_quality_first_minimum:20<25" in report.violations


def test_quality_ledger_rejects_narration_fragments_as_visual_shots() -> None:
    shots = [_shot(i, scale="close_up" if i % 4 == 0 else "medium") for i in range(6)]
    shots[1]["narration_text"] = "海洋與陸地上的生命大量消失，"

    report = validate_quality_ledger(_ledger(shots))

    assert "S00_SH01.narration_fragment" in report.violations


def test_quality_ledger_allows_explicit_fast_cut_fragment() -> None:
    shots = [_shot(i, scale="close_up" if i % 4 == 0 else "medium") for i in range(6)]
    shots[1]["narration_text"] = "海洋與陸地上的生命大量消失，"
    shots[1]["intentional_fast_cut_reason"] = "opening evidence montage"

    report = validate_quality_ledger(_ledger(shots))

    assert "S00_SH01.narration_fragment" not in report.violations


def test_science_profile_requires_close_up_evidence_mix() -> None:
    report = validate_quality_ledger(_ledger([_shot(i) for i in range(10)]))

    assert report.ok is False
    assert "science_close_evidence_ratio_below_target:0.000<0.250" in report.violations

    scales = [
        "close_up",
        "medium",
        "medium",
        "close_up",
        "medium",
        "medium",
        "close_up",
        "medium",
    ]
    passing = [_shot(i, scale=scale) for i, scale in enumerate(scales)]
    assert validate_quality_ledger(_ledger(passing)).ok is True


def test_quality_ledger_rejects_three_consecutive_same_scales() -> None:
    shots = [
        _shot(0, scale="wide"),
        _shot(1, scale="wide"),
        _shot(2, scale="wide"),
        _shot(3, scale="close_up"),
        _shot(4, scale="close_up"),
        _shot(5, scale="macro"),
        _shot(6, scale="medium"),
        _shot(7, scale="medium"),
    ]

    report = validate_quality_ledger(_ledger(shots))

    assert "repeated_shot_scale_without_reason:wide:3" in report.violations


def test_initial_candidate_budget_is_one_for_every_risk_class() -> None:
    assert candidate_budget_for_shot(_shot(0, risk="high")) == 1
    assert candidate_budget_for_shot(_shot(0, risk="normal")) == 1
    assert candidate_budget_for_shot(_shot(0, risk="low")) == 1


def test_prompt_compiler_puts_takeaway_subject_action_and_evidence_first() -> None:
    shot = _shot(0, scale="close_up", risk="high")

    prompt = compile_shot_prompt(
        ledger=_ledger([shot], duration=8),
        scene={"scene_id": "S00", "setting": "乾燥的晚三疊世林地"},
        shot=shot,
    )

    takeaway = prompt.index("直立腿讓移動更有效率")
    subject = prompt.index("小型早期恐龍的後肢")
    action = prompt.index("腳掌落在乾裂泥地")
    evidence = prompt.index("腿位於身體正下方")
    style = prompt.index("photoreal professional science documentary")
    assert takeaway < subject < action < evidence < style
    assert "close-up" in prompt.lower()
    assert "primary subject occupies" in prompt.lower()
    assert "generated text" in prompt.lower()


def test_prompt_compiler_puts_audience_story_moment_and_truth_before_style() -> None:
    shot = _shot(0, scale="close_up", risk="high")
    shot.update(
        {
            "engagement_role": "reveal",
            "attention_hook": "先看見足跡，再找出留下足跡的身體機制",
            "story_moment": "腳掌剛離地，清楚足跡留在泥面",
            "action_consequence": "泥面保留可比較的足跡輪廓",
            "composition_energy": "curious",
            "viewer_emotion": "discovery",
            "engagement_criteria": ["foot and resulting track read as one causal instant"],
            "visual_truth_mode": "reconstruction",
        }
    )
    ledger = _ledger([shot], duration=8)
    ledger.update(
        {
            "quality_contract_version": 3,
            "audience_profile": {
                "age_band": "school_age",
                "knowledge_level": "newcomer",
                "attention_style": "curious_explorer",
                "safety_intensity": "gentle",
            },
            "engagement_profile": {
                "mode": "discovery_documentary",
                "energy": "balanced",
                "humor": "light",
                "sensationalism_forbidden": True,
            },
        }
    )

    prompt = compile_shot_prompt(
        ledger=ledger,
        scene={"scene_id": "S00", "setting": "乾燥的晚三疊世林地"},
        shot=shot,
    )

    assert prompt.index("Audience contract") < prompt.index("Visual style")
    assert "Story moment: capture one decisive visible instant" in prompt
    assert "Visual truth mode: reconstruction" in prompt


def test_prompt_compiler_demands_cinematic_tension_without_reserving_subtitle_space() -> None:
    shot = _shot(0, scale="close_up", risk="high")
    shot.update(
        {
            "engagement_role": "reveal",
            "attention_hook": "先看見結果，再理解成因",
            "story_moment": "關鍵證據在動作發生的一瞬間清楚出現",
            "action_consequence": "前景動作直接改變中景結果",
            "composition_energy": "tense",
            "viewer_emotion": "awe",
            "engagement_criteria": [
                "the decisive instant dominates the frame",
                "下三分之一保留字幕安全區",
            ],
            "acceptance_criteria": [
                "the decisive instant dominates the frame",
                "keep the lower third clear for subtitles",
            ],
            "visual_truth_mode": "reconstruction",
        }
    )
    ledger = _ledger([shot], duration=8)
    ledger.update(
        {
            "quality_contract_version": 3,
            "engagement_profile": {
                "mode": "discovery_documentary",
                "energy": "high",
                "humor": "none",
                "sensationalism_forbidden": True,
            },
        }
    )

    prompt = compile_shot_prompt(
        ledger=ledger,
        scene={"scene_id": "S00", "setting": "scientifically credible setting"},
        shot=shot,
    ).lower()

    assert "cinematic factual reconstruction" in prompt
    assert "foreground, midground, and background" in prompt
    assert "motivated dramatic light" in prompt
    assert "edge-to-edge composition" in prompt
    assert "generic stock documentary" in prompt
    assert "subtitle band" not in prompt
    assert "bottom 20 percent clear" not in prompt
    assert "下三分之一" not in prompt
    assert "lower third" not in prompt


def test_quality_ledger_enforces_engagement_contract_for_v3() -> None:
    shot = _shot(0)
    ledger = _ledger([shot], duration=8)
    ledger.update(
        {
            "quality_contract_version": 3,
            "audience_profile": {
                "age_band": "general",
                "knowledge_level": "newcomer",
                "attention_style": "curious_explorer",
                "safety_intensity": "standard",
            },
            "engagement_profile": {
                "mode": "discovery_documentary",
                "energy": "balanced",
                "humor": "none",
                "sensationalism_forbidden": True,
            },
        }
    )

    report = validate_quality_ledger(ledger)

    assert report.ok is False
    assert "S00_SH00.story_moment" in report.violations


def test_prompt_compiler_uses_comparison_recipe_without_global_conflict() -> None:
    shot = _shot(0)
    shot.update(
        {
            "shot_type": "comparison",
            "subject": "恐龍、翼龍與海生爬行動物的骨架標本",
            "action": "三類標本以清楚間距並列供比較",
            "evidence_detail": "各類標本輪廓互不重疊，保留本地標示空間",
        }
    )

    prompt = compile_shot_prompt(
        ledger=_ledger([shot], duration=8),
        scene={"scene_id": "S00", "setting": "中性博物館展示背景"},
        shot=shot,
    ).lower()

    assert "structured comparison composition" in prompt
    assert "no split-screen" not in prompt
    assert "no generated text" in prompt


def test_ranking_blocks_when_every_candidate_scores_below_80() -> None:
    decision = rank_candidate_assessments(
        [_assessment("C01", 79), _assessment("C02", 72)],
        threshold=80,
    )

    assert decision.selected_candidate_id is None
    assert decision.status == "blocked"
    assert decision.best_score == 79


def test_ranking_rejects_hard_blocker_and_selects_highest_passing_candidate() -> None:
    decision = rank_candidate_assessments(
        [
            _assessment("C01", 95, hard_blockers=["malformed anatomy"]),
            _assessment("C02", 84),
            _assessment("C03", 88),
        ],
        threshold=80,
    )

    assert decision.status == "selected"
    assert decision.selected_candidate_id == "C03"
    assert decision.best_score == 88
    assert decision.ranked_candidate_ids == ("C03", "C02")


def test_ranking_fails_closed_on_non_openai_generation_or_judge() -> None:
    wrong_source = _assessment("C01", 90, provider="xai")
    wrong_judge = _assessment("C02", 90, judge_provider="google")

    decision = rank_candidate_assessments([wrong_source, wrong_judge], threshold=80)

    assert decision.status == "blocked"
    assert decision.selected_candidate_id is None
    assert decision.ranked_candidate_ids == ()

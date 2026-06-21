import json


def test_quality_judge_returns_privacy_safe_dimensions():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_demo",
            "kind": "image",
            "artifact_path": "/tmp/current.png",
            "content_hash": "hash-a",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"aspect_match": 1.0, "resolution": 0.9, "final_score": 0.95},
        },
        request_context={"has_reference_image": False, "raw_prompt": "private prompt"},
        recent_artifact_hashes={"hash-b"},
    )

    assert result["version"].startswith("visual_quality_judge.")
    assert set(result["scores"]) == {
        "reference_adherence",
        "aesthetic_fit",
        "composition",
        "novelty",
        "motion_quality",
        "aspect_integrity",
        "delivery_readiness",
    }
    assert result["scores"]["novelty"] == 1.0
    assert result["confidence"] > 0.6
    assert "private prompt" not in json.dumps(result, ensure_ascii=False)


def test_quality_judge_penalizes_duplicate_content_hash():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_demo",
            "kind": "image",
            "content_hash": "hash-a",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"aspect_match": 1.0, "resolution": 0.9, "final_score": 0.95},
        },
        recent_artifact_hashes={"hash-a"},
    )

    assert result["scores"]["novelty"] == 0.0
    assert "duplicate_content_hash" in result["uncertainty_reasons"]


def test_quality_judge_lowers_reference_adherence_when_reference_evidence_missing():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_demo",
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"aspect_match": 0.9, "resolution": 0.7, "final_score": 0.8},
        },
        request_context={"has_reference_image": True},
    )

    assert result["scores"]["reference_adherence"] == 0.35
    assert "reference_evidence_missing" in result["uncertainty_reasons"]


def test_quality_judge_scores_video_motion_from_duration_score():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_demo",
            "kind": "video",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"aspect_match": 0.95, "duration": 0.8, "resolution": 0.8, "final_score": 0.85},
        },
    )

    assert result["scores"]["motion_quality"] == 0.8


def test_quality_judge_uses_vision_observation_without_leaking_prompt():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_1",
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.6, "aspect_match": 0.7, "final_score": 0.6},
        },
        request_context={"has_reference_image": True, "category": "fashion", "raw_prompt": "private"},
        vision_observation={
            "reference_adherence": 0.9,
            "visual_appeal": 0.8,
            "composition": 0.85,
            "aspect_integrity": 0.95,
            "confidence": 0.75,
            "evidence": {"summary": "same subject, clean pose"},
            "raw_prompt": "must not appear",
        },
    )

    assert result["scores"]["reference_adherence"] == 0.9
    assert result["scores"]["aesthetic_fit"] >= 0.75
    assert result["scores"]["composition"] == 0.85
    assert result["scores"]["aspect_integrity"] == 0.95
    assert result["judge_sources"]["reference_adherence"] == "vision"
    assert result["judge_sources"]["composition"] == "vision"
    assert "must not appear" not in json.dumps(result, ensure_ascii=False)
    assert "private" not in json.dumps(result, ensure_ascii=False)


def test_quality_judge_penalizes_vision_defects_for_portrait_categories():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_1",
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        },
        request_context={"category": "portrait"},
        vision_observation={
            "visual_appeal": 0.95,
            "composition": 0.95,
            "confidence": 0.8,
            "artifact_defects": ["blurred_face"],
        },
    )

    assert result["scores"]["aesthetic_fit"] < 0.95
    assert "vision_defect_blurred_face" in result["uncertainty_reasons"]


def test_quality_judge_surfaces_video_artifact_defects_from_observation():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_video",
            "kind": "video",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.8, "aspect_match": 0.8, "duration": 0.8, "final_score": 0.8},
        },
        vision_observation={
            "aspect_integrity": 0.25,
            "motion_quality": 0.3,
            "confidence": 0.8,
            "artifact_defects": ["weak_aspect_integrity", "weak_motion_or_duration_evidence"],
        },
    )

    assert result["scores"]["aspect_integrity"] == 0.25
    assert result["scores"]["motion_quality"] == 0.3
    assert "vision_defect_weak_aspect_integrity" in result["uncertainty_reasons"]
    assert "vision_defect_weak_motion_or_duration_evidence" in result["uncertainty_reasons"]

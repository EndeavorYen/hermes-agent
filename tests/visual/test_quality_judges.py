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


def test_quality_judge_maps_video_defects_to_delivery_blocking_issue_tags():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_video",
            "kind": "video",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.8, "aspect_match": 0.8, "duration": 0.8, "final_score": 0.8},
        },
        request_context={"category": "product"},
        vision_observation={
            "aspect_integrity": 0.2,
            "motion_quality": 0.25,
            "confidence": 0.8,
            "artifact_defects": ["weak_aspect_integrity", "weak_motion_or_duration_evidence"],
        },
    )

    assert result["quality_issues"] == ["aspect_integrity_bad", "motion_bad"]


def test_quality_judge_keeps_missing_video_metadata_non_blocking():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_video",
            "kind": "video",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.5, "aspect_match": 0.5, "duration": 0.5, "final_score": 0.5},
        },
        request_context={"category": "product"},
        vision_observation={
            "aspect_integrity": 0.5,
            "motion_quality": 0.25,
            "confidence": 0.45,
            "artifact_defects": [
                "weak_aspect_integrity",
                "missing_video_dimensions",
                "missing_video_duration",
                "weak_motion_evidence",
            ],
        },
    )

    assert result["quality_issues"] == ["video_metadata_missing"]


def test_quality_judge_maps_artifact_defects_to_preference_issue_tags():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_1",
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        },
        request_context={"category": "fashion"},
        vision_observation={
            "visual_appeal": 0.9,
            "composition": 0.8,
            "confidence": 0.8,
            "artifact_defects": ["face_quality_low", "stockings_quality_low"],
        },
    )

    assert result["quality_issues"] == ["subject_not_attractive", "stockings_bad"]
    assert "face_quality_low" not in result["quality_issues"]


def test_quality_judge_maps_candidate_grid_defect_to_source_frame_issue():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_grid_source",
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        },
        request_context={"category": "product"},
        vision_observation={
            "visual_appeal": 0.9,
            "composition": 0.9,
            "confidence": 0.8,
            "artifact_defects": ["candidate_grid_layout"],
        },
    )

    assert result["quality_issues"] == ["source_frame_grid"]


def test_quality_judge_filters_portrait_reference_defects_for_product_context():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_product",
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        },
        request_context={"has_reference_image": False, "category": "product"},
        vision_observation={
            "reference_adherence": 0.2,
            "subject_quality": 0.2,
            "visual_appeal": 0.85,
            "composition": 0.85,
            "confidence": 0.8,
            "artifact_defects": [
                "reference_identity_drift",
                "face_quality_low",
                "glamour_impact_low",
                "pose_composition_weak",
                "stockings_quality_low",
            ],
        },
    )

    assert result["quality_issues"] == []
    assert "vision_defect_reference_identity_drift" not in result["uncertainty_reasons"]
    assert "vision_defect_face_quality_low" not in result["uncertainty_reasons"]
    assert result["scores"]["aesthetic_fit"] >= 0.8


def test_quality_judge_exports_portrait_preference_dimensions_and_issue_tags():
    from agent.visual.judges.quality import judge_visual_quality

    result = judge_visual_quality(
        {
            "artifact_id": "var_fashion",
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        },
        request_context={"category": "fashion portrait"},
        vision_observation={
            "subject_quality": 0.35,
            "face_quality": 0.28,
            "glamour_impact": 0.42,
            "fashion_material_quality": 0.31,
            "pose_composition": 0.76,
            "composition": 0.8,
            "visual_appeal": 0.7,
            "confidence": 0.82,
        },
    )

    assert result["preference_dimensions"] == {
        "subject_beauty": 0.35,
        "face_naturalness": 0.28,
        "glamour_impact": 0.42,
        "fashion_material_quality": 0.31,
        "pose_composition": 0.76,
    }
    assert result["quality_issues"] == [
        "subject_not_attractive",
        "face_unnatural",
        "not_glamorous",
        "stockings_bad",
    ]
    assert "preference_dimension_face_naturalness_low" in result["uncertainty_reasons"]
    assert "preference_dimension_fashion_material_quality_low" in result["uncertainty_reasons"]

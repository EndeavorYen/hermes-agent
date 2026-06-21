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

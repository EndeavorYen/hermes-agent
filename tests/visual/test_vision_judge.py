from __future__ import annotations

import json


def test_vision_judge_normalizes_face_and_reference_defects_privacy_safe():
    from agent.visual.judges.vision import build_vision_judge_observation

    observation = build_vision_judge_observation(
        {
            "reference_adherence": 0.25,
            "face_quality": 0.3,
            "visual_appeal": 0.8,
            "composition": 0.7,
            "pose_novelty": 0.6,
            "raw_prompt": "private prompt",
            "local_path": "/Users/simon/private.png",
        }
    )

    assert observation["reference_adherence"] == 0.25
    assert observation["subject_quality"] == 0.3
    assert "reference_identity_drift" in observation["artifact_defects"]
    assert "face_quality_low" in observation["artifact_defects"]
    payload = json.dumps(observation, ensure_ascii=False)
    assert "private prompt" not in payload
    assert "/Users/simon" not in payload


def test_vision_judge_good_observation_has_high_confidence():
    from agent.visual.judges.vision import build_vision_judge_observation

    observation = build_vision_judge_observation(
        {
            "reference_adherence": 0.9,
            "face_quality": 0.88,
            "visual_appeal": 0.86,
            "composition": 0.9,
            "pose_novelty": 0.7,
        }
    )

    assert observation["confidence"] >= 0.8
    assert observation["artifact_defects"] == []


def test_vision_judge_maps_stocking_quality_defect():
    from agent.visual.judges.vision import build_vision_judge_observation

    observation = build_vision_judge_observation(
        {
            "reference_adherence": 0.8,
            "face_quality": 0.8,
            "visual_appeal": 0.8,
            "composition": 0.75,
            "pose_novelty": 0.7,
            "stocking_quality": 0.2,
        }
    )

    assert "stockings_quality_low" in observation["artifact_defects"]
    assert "stocking_quality" not in observation


def test_vision_judge_preserves_preference_dimension_metrics():
    from agent.visual.judges.vision import build_vision_judge_observation

    observation = build_vision_judge_observation(
        {
            "reference_adherence": 0.8,
            "subject_quality": 0.45,
            "face_quality": 0.3,
            "visual_appeal": 0.5,
            "glamour_impact": 0.4,
            "composition": 0.7,
            "pose_composition": 0.35,
            "fashion_material_quality": 0.25,
        }
    )

    assert observation["subject_quality"] == 0.45
    assert observation["face_quality"] == 0.3
    assert observation["glamour_impact"] == 0.4
    assert observation["pose_composition"] == 0.35
    assert observation["fashion_material_quality"] == 0.25
    assert "face_quality_low" in observation["artifact_defects"]
    assert "glamour_impact_low" in observation["artifact_defects"]
    assert "pose_composition_weak" in observation["artifact_defects"]
    assert "composition_weak" not in observation["artifact_defects"]
    assert "stockings_quality_low" in observation["artifact_defects"]


def test_vision_judge_keeps_pose_and_scene_composition_defects_separate():
    from agent.visual.judges.vision import build_vision_judge_observation

    observation = build_vision_judge_observation(
        {
            "composition": 0.8,
            "pose_composition": 0.2,
        }
    )

    assert "pose_composition_weak" in observation["artifact_defects"]
    assert "composition_weak" not in observation["artifact_defects"]


def test_vision_judge_preserves_video_quality_dimensions():
    from agent.visual.judges.vision import build_vision_judge_observation

    observation = build_vision_judge_observation(
        {
            "visual_appeal": 0.8,
            "composition": 0.75,
            "aspect_integrity": 0.2,
            "motion_quality": 0.25,
            "artifact_defects": ["duration_mismatch"],
        }
    )

    assert observation["aspect_integrity"] == 0.2
    assert observation["motion_quality"] == 0.25
    assert "weak_aspect_integrity" in observation["artifact_defects"]
    assert "weak_motion_or_duration_evidence" in observation["artifact_defects"]
    assert "duration_mismatch" in observation["artifact_defects"]

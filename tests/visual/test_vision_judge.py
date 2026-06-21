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


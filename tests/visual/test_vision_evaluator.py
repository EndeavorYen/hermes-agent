from agent.visual.vision_evaluator import build_candidate_vision_observation


def test_candidate_vision_observation_overrides_weak_fallback_video_defects():
    observation = build_candidate_vision_observation(
        {
            "kind": "video",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        },
        fallback_observation={
            "aspect_integrity": 0.3,
            "motion_quality": 0.25,
            "confidence": 0.2,
            "artifact_defects": [
                "weak_aspect_integrity",
                "weak_motion_or_duration_evidence",
            ],
        },
    )

    assert observation["aspect_integrity"] == 0.95
    assert observation["motion_quality"] == 0.9
    assert observation["artifact_defects"] == []

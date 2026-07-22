from __future__ import annotations


def test_artifact_observation_scores_fresh_high_resolution_image():
    from agent.visual.artifact_observation import build_artifact_observation

    observation = build_artifact_observation(
        {
            "kind": "image",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"aspect_match": 1.0, "resolution": 0.95, "final_score": 0.9},
        }
    )

    assert observation["confidence"] >= 0.7
    assert observation["composition"] >= 0.9
    assert observation["aspect_integrity"] == 1.0
    assert observation["visual_appeal"] >= 0.9
    assert observation["artifact_defects"] == []


def test_artifact_observation_flags_weak_video_metadata():
    from agent.visual.artifact_observation import build_artifact_observation

    observation = build_artifact_observation(
        {
            "kind": "video",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"aspect_match": 0.4, "duration": 0.25, "resolution": 0.0, "final_score": 0.45},
        }
    )

    assert observation["motion_quality"] == 0.25
    assert observation["aspect_integrity"] == 0.4
    assert "weak_motion_or_duration_evidence" in observation["artifact_defects"]
    assert "weak_aspect_integrity" in observation["artifact_defects"]


def test_artifact_observation_is_privacy_safe():
    from agent.visual.artifact_observation import build_artifact_observation

    observation = build_artifact_observation(
        {
            "kind": "image",
            "artifact_path": "/private/mock-hermes-home/private/image.png",
            "prompt": "private prompt",
            "scores": {"aspect_match": 1.0, "resolution": 0.9, "final_score": 0.9},
        }
    )

    assert "private prompt" not in str(observation)
    assert "/private/mock-hermes-home" not in str(observation)

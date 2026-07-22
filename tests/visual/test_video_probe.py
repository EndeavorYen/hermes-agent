from __future__ import annotations


def test_video_probe_flags_aspect_and_motion_defects():
    from agent.visual.video_probe import build_video_probe_observation

    observation = build_video_probe_observation(
        {
            "kind": "video",
            "width": 1920,
            "height": 1080,
            "duration_seconds": 8,
            "requested_parameters": {"aspect_ratio": "9:16", "duration_seconds": 8},
            "motion_score": 0.2,
        }
    )

    assert observation["aspect_integrity"] < 0.5
    assert observation["motion_quality"] == 0.2
    assert "aspect_mismatch" in observation["artifact_defects"]
    assert "weak_motion_evidence" in observation["artifact_defects"]


def test_video_probe_fails_soft_when_metadata_missing():
    from agent.visual.video_probe import build_video_probe_observation

    observation = build_video_probe_observation({"kind": "video"})

    assert observation["confidence"] < 0.5
    assert "missing_video_dimensions" in observation["artifact_defects"]
    assert "missing_video_duration" in observation["artifact_defects"]

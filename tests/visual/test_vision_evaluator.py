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


def test_candidate_vision_observation_merges_preference_dimensions_from_inline_judge():
    observation = build_candidate_vision_observation(
        {
            "kind": "image",
            "artifact_path": "/tmp/current.png",
        },
        fallback_observation={
            "composition": 0.5,
            "visual_appeal": 0.5,
            "confidence": 0.2,
            "artifact_defects": [],
        },
        inline_enabled=True,
        analyzer=lambda _candidate: {
            "analysis": {
                "subject_quality": 0.35,
                "face_quality": 0.25,
                "glamour_impact": 0.4,
                "fashion_material_quality": 0.3,
                "pose_composition": 0.8,
                "visual_appeal": 0.6,
                "composition": 0.75,
            }
        },
    )

    assert observation["subject_quality"] == 0.35
    assert observation["face_quality"] == 0.25
    assert observation["glamour_impact"] == 0.4
    assert observation["fashion_material_quality"] == 0.3
    assert observation["pose_composition"] == 0.8
    assert observation["evidence"]["source"] == "inline_vision_judge"


def test_candidate_vision_observation_records_inline_provider_failure():
    observation = build_candidate_vision_observation(
        {
            "kind": "image",
            "artifact_path": "/tmp/current.png",
        },
        fallback_observation={
            "composition": 0.5,
            "visual_appeal": 0.5,
            "confidence": 0.2,
            "artifact_defects": [],
        },
        inline_enabled=True,
        analyzer=lambda _candidate: {
            "success": False,
            "error": (
                "Error code: 403 - {'code':'personal-team-blocked:spending-limit',"
                "'error':'You have run out of credits or need a Grok subscription.'}"
            ),
            "analysis": "Insufficient credits or payment required.",
        },
    )

    assert observation["composition"] == 0.5
    assert observation["evidence"]["source"] == "inline_vision_unavailable"
    assert observation["vision_failure"]["failure_class"] == "quota_exceeded"
    assert observation["vision_failure"]["provider_message_code"] == "personal-team-blocked:spending-limit"

from __future__ import annotations


def test_video_hardening_prefers_source_aspect_and_natural_motion():
    from agent.visual.video_hardening import build_hardened_video_request

    request = build_hardened_video_request(
        prompt="A matte black fountain pen on white paper",
        requested_aspect_ratio="16:9",
        source_media={"width": 720, "height": 1280},
        supported_aspect_ratios=["16:9", "9:16", "1:1"],
    )

    assert request["aspect_ratio"] == "9:16"
    assert "natural real-time motion" in request["prompt"]
    assert "normal playback speed" in request["prompt"]
    assert "clear continuous motion" in request["prompt"]
    assert "not slow motion" in request["prompt"]
    assert request["metadata"]["source_aspect_ratio"] == "9:16"


def test_video_hardening_does_not_duplicate_motion_hint():
    from agent.visual.video_hardening import build_hardened_video_request

    request = build_hardened_video_request(
        prompt="Natural real-time motion of a product on a table, not slow motion",
        requested_aspect_ratio="1:1",
        source_media={},
        supported_aspect_ratios=["16:9", "9:16", "1:1"],
    )

    assert request["prompt"].lower().count("natural real-time motion") == 1
    assert request["aspect_ratio"] == "1:1"


def test_video_hardening_recommends_retry_for_static_video_feedback():
    from agent.visual.video_hardening import classify_video_feedback_repair

    repair = classify_video_feedback_repair({"issues": ["static_video", "composition_bad"]})

    assert repair["decision"] == "retry_video"
    assert repair["reason"] == "static_or_slow_motion_feedback"
    assert repair["motion_mode"] == "natural_motion"


def test_video_hardening_recommends_retry_for_slow_motion_feedback():
    from agent.visual.video_hardening import classify_video_feedback_repair

    repair = classify_video_feedback_repair({"issues": ["slow_motion"]})

    assert repair["decision"] == "retry_video"
    assert repair["reason"] == "static_or_slow_motion_feedback"
    assert repair["motion_mode"] == "natural_motion"

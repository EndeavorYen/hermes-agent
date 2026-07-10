from __future__ import annotations


def test_story_video_implicit_image_provider_is_openai_codex():
    from tools.story_video_provider_guard import resolve_story_video_image_provider

    prompt = "Scene S03 keyframe for a 5-minute documentary with narration and subtitles"
    provider, error = resolve_story_video_image_provider(
        {"prompt": prompt},
        prompt=prompt,
        provider_override=None,
    )

    assert provider == "openai-codex"
    assert error is None


def test_story_video_explicit_xai_image_provider_is_blocked_without_prompt_echo():
    from tools.story_video_provider_guard import resolve_story_video_image_provider

    prompt = "故事影片 keyframe，秘密提示詞 privacy-marker-1793，科普影片 5mins"
    provider, error = resolve_story_video_image_provider(
        {"prompt": prompt, "_provider": "xai"},
        prompt=prompt,
        provider_override="xai",
    )

    assert provider == "xai"
    assert error is not None
    assert error["error_type"] == "story_video_provider_blocked"
    assert "privacy-marker-1793" not in str(error)


def test_story_video_generic_video_payload_does_not_echo_prompt():
    from tools.story_video_provider_guard import story_video_video_block_payload

    prompt = "故事影片：秘密提示詞 privacy-marker-2481，科普影片，大概 5mins"
    error = story_video_video_block_payload(
        {"prompt": prompt},
        prompt=prompt,
        provider="xai",
        model="grok-imagine-video",
    )

    assert error is not None
    assert error["error_type"] == "story_video_provider_blocked"
    assert "privacy-marker-2481" not in str(error)


def test_story_video_false_flag_does_not_trigger_detection():
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "animate this ordinary still for 6s",
        {"story_video": False},
    ) is False


def test_story_video_attachment_path_does_not_trigger_detection():
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "animate this ordinary still for 6s",
        {"image_url": "/story_video/still.png", "duration": 6},
    ) is False


def test_story_video_visual_metadata_path_does_not_trigger_detection():
    from tools.story_video_provider_guard import story_video_request_detected

    prompt = (
        "animate this ordinary still for 6s\n\n"
        "[Visual Arsenal source images]\n"
        "/story_video/still.png"
    )

    assert story_video_request_detected(prompt, {}) is False


def test_story_video_explicit_truthy_workflow_flag_triggers_detection():
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "render the next source still",
        {"story_video_workflow": True},
    ) is True


def test_story_video_provider_aliases_are_exact_not_substring_matches():
    from tools.story_video_provider_guard import normalize_visual_provider

    assert normalize_visual_provider("x.ai") == "xai"
    assert normalize_visual_provider("grok imagine") == "xai"
    assert normalize_visual_provider("image_2") == "openai-codex"
    assert normalize_visual_provider("openai codex") == "openai-codex"
    assert normalize_visual_provider("openai") == "openai"
    assert normalize_visual_provider("custom-openai") == "custom-openai"

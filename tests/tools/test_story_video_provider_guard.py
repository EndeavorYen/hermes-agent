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

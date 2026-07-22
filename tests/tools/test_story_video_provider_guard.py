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


def test_story_video_engine_openai_adapter_is_an_allowed_openai_route():
    from tools.story_video_provider_guard import resolve_story_video_image_provider

    prompt = "Scene S03 keyframe for a 5-minute documentary with narration and subtitles"
    provider, error = resolve_story_video_image_provider(
        {"prompt": prompt, "provider": "visual-engine-openai"},
        prompt=prompt,
        provider_override="visual-engine-openai",
    )

    assert provider == "visual-engine-openai"
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


def test_short_product_intro_stays_on_generic_visual_route():
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "幫我做一支 6 秒產品介紹影片，從產品照開始。",
        {},
    ) is False


def test_short_product_intro_with_whole_video_wording_stays_visual():
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "Visual Agent：幫我做一部 6 秒產品介紹影片，從產品照開始。",
        {},
    ) is False


def test_explicit_visual_agent_route_supports_multimodal_messages():
    from tools.story_video_provider_guard import explicit_visual_agent_request_detected

    assert explicit_visual_agent_request_detected(
        [
            {"type": "text", "text": "Visual Agent：依照附件做一張圖"},
            {"type": "image_url", "image_url": {"url": "/tmp/reference.png"}},
        ]
    ) is True
    assert explicit_visual_agent_request_detected(
        "請用 Visual Agent 幫我做一張產品照"
    ) is True


def test_explicit_visual_agent_route_strips_active_slack_reply_wrapper():
    from tools.story_video_provider_guard import explicit_visual_agent_request_detected

    assert explicit_visual_agent_request_detected(
        '[Replying to: "故事影片：恐龍起源｜5分｜真實照片"]\n\n'
        "Visual Agent：幫我做一張產品照和 6 秒短片"
    ) is True


def test_minute_scale_explainer_routes_to_story_video():
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "幫我做一部恐龍起源的科普影片，大概 5 分鐘。",
        {},
    ) is True


def test_arbitrary_english_minute_scale_documentary_routes_to_story_video():
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "Make a 3-minute documentary about the origin of dinosaurs.",
        {},
    ) is True


def test_single_long_form_structure_signal_routes_video_to_story_video():
    from tools.story_video_provider_guard import story_video_request_detected

    for prompt in (
        "Create a video with narration about dinosaurs.",
        "Create a video with subtitles about dinosaurs.",
        "Create a multi-scene video about dinosaurs.",
    ):
        assert story_video_request_detected(prompt, {}) is True


def test_multi_role_video_routes_to_story_video() -> None:
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "請把以下故事做成短片，旁白用 simon_clean_v2，安安用 Vivian，多角色配音。",
        {},
    ) is True


def test_audio_only_multi_role_dubbing_does_not_force_video_route() -> None:
    from tools.story_video_provider_guard import story_video_request_detected

    assert story_video_request_detected(
        "請把這段文字做成多角色配音，旁白用 simon_clean_v2，安安用 Vivian。",
        {},
    ) is False


def test_long_multirole_story_script_routes_to_story_video() -> None:
    from tools.story_video_provider_guard import story_video_request_detected

    prompt = (
        "故事劇本 (NSFW)\n"
        + "這是一段很長的故事。" * 300
        + "\n多角色配音：旁白用 Vivian，嘉梅用 Serena。"
    )

    assert story_video_request_detected(prompt, {}) is True


def test_story_text_with_role_voice_arrangement_routes_to_story_video() -> None:
    from tools.story_video_provider_guard import story_video_request_detected

    prompt = (
        "故事腳本：三位旅人在山中相遇。\n"
        "角色聲線安排：旁白＝溫暖女聲；旅人甲＝沉穩男聲。"
    )

    assert story_video_request_detected(prompt, {}) is True


def test_negated_structure_terms_keep_seconds_scale_clips_on_visual_route():
    from tools.story_video_provider_guard import story_video_request_detected

    for prompt in (
        "Create a 6-second video about a pen without subtitles.",
        "Create a 6-second video with no narration about a pen.",
        "Create a 6-second video without narration or subtitles.",
        "製作一支 6 秒產品影片，不要字幕。",
        "製作一支 6 秒產品影片，不要旁白或字幕。",
    ):
        assert story_video_request_detected(prompt, {}) is False


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

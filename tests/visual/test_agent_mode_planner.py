def test_agent_mode_planner_routes_image_plus_video_request_without_advanced_knobs():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "請產出一張圖片和一段影片：霧黑鋼筆放在白紙上，柔和窗光。",
        attachments=["/tmp/ref.png"],
    )

    assert plan["tool_name"] == "visual_package_generate"
    assert plan["should_use_visual_package"] is True
    assert plan["confidence"] >= 0.75
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["video_budget"] == 1
    assert plan["arguments"]["attachments"] == ["/tmp/ref.png"]
    assert "autonomy_level" not in plan["arguments"]


def test_agent_mode_planner_treats_reference_variation_as_image_plus_video():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "請用這張 reference 產出一張圖片和一段 6 秒影片",
        attachments=["/tmp/ref.png"],
    )

    assert plan["reason"] == "image_plus_video_request"
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["attachments"] == ["/tmp/ref.png"]
    assert plan["arguments"]["duration"] == 6


def test_agent_mode_planner_binds_ref_indices_to_upload_order_and_prompt_roles():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
        attachments=["/tmp/character.png", "/tmp/pose.png"],
    )

    assert plan["reason"] == "image_request"
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is False
    assert plan["arguments"]["attachments"] == ["/tmp/character.png", "/tmp/pose.png"]
    binding = plan["arguments"]["reference_binding"]
    assert binding == {
        "mode": "ordered_references",
        "reference_order_source": "user_visible_upload_order",
        "role_policy": "derive_from_user_prompt",
        "reference_order": [
            {"index": 1, "role_hint": "character_identity", "attachment": "/tmp/character.png"},
            {"index": 2, "role_hint": "pose_composition", "attachment": "/tmp/pose.png"},
        ],
    }
    prompt = plan["arguments"]["prompt"]
    assert "Reference binding" in prompt
    assert "first uploaded image in the user's visible attachment order" in prompt
    assert "Do not assume fixed roles" in prompt
    assert "reference 1 only for character identity" not in prompt
    assert "/tmp/character.png" not in prompt
    assert "/tmp/pose.png" not in prompt


def test_agent_mode_planner_supports_multiple_reference_roles_without_fixed_defaults():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "ref1 和 ref2 都是人物，ref3 是服裝，請融合成一張圖片",
        attachments=["/tmp/person-a.png", "/tmp/person-b.png", "/tmp/clothes.png"],
    )

    binding = plan["arguments"]["reference_binding"]
    assert binding["mode"] == "ordered_references"
    assert binding["role_policy"] == "derive_from_user_prompt"
    assert "character_reference_index" not in binding
    assert "pose_reference_index" not in binding
    assert binding["reference_order"] == [
        {"index": 1, "role_hint": "character_identity", "attachment": "/tmp/person-a.png"},
        {"index": 2, "role_hint": "character_identity", "attachment": "/tmp/person-b.png"},
        {"index": 3, "role_hint": "wardrobe", "attachment": "/tmp/clothes.png"},
    ]
    prompt = plan["arguments"]["prompt"]
    assert "Do not assume fixed roles" in prompt
    assert "clothing, wardrobe" in prompt


def test_agent_mode_planner_routes_image_only_request():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("幫我做一張乾淨產品攝影圖")

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is False
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["candidate_budget_source"] == "planner_default"


def test_agent_mode_planner_defaults_reference_visual_brief_to_prompt_only():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "固定這位角色，替換不同的服裝與構圖，高品質，8K，光影，性感一些",
        attachments=["/tmp/ref-1.png", "/tmp/ref-2.png"],
    )

    assert plan["should_use_visual_package"] is False
    assert plan["reason"] == "not_visual_agent_request"
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is False
    assert "candidate_budget" not in plan["arguments"]


def test_agent_mode_planner_treats_positive_image_quality_comment_as_feedback_only():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("這次的產圖品質很棒!")

    assert plan["should_use_visual_package"] is False
    assert plan["reason"] == "visual_feedback_only"
    assert plan["feedback"]["polarity"] > 0
    assert "general_positive" in plan["feedback"]["signals"]


def test_agent_mode_planner_treats_latest_output_approval_as_feedback_only():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("最新的產出我覺得可以")

    assert plan["should_use_visual_package"] is False
    assert plan["reason"] == "visual_feedback_only"


def test_agent_mode_planner_ignores_public_raphael_text_task_with_negated_media():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "同一個 hostile UX 測試，現在模擬真實文字任務：我要公開 Raphael，"
        "但又怕 overclaim；我要使用者 wow，但不能產圖、不能用工具、不能假綠燈。"
        "請只用六行回答：目標、成功條件、證據門檻、阻塞、修正策略、可公開說法。"
        "不要宣稱已完成。"
    )

    assert plan["should_use_visual_package"] is False
    assert plan["reason"] == "text_only_visual_analysis"


def test_agent_mode_planner_routes_friendly_draw_character_request():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("幫我畫一位銀髮高冷美少女角色，乾淨背景")

    assert plan["should_use_visual_package"] is True
    assert plan["confidence"] >= 0.75
    assert plan["reason"] == "image_request"
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is False
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["candidate_budget_source"] == "planner_default"
    assert "autonomy_level" not in plan["arguments"]


def test_agent_mode_planner_routes_video_only_request():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("用這張圖產生 6 秒短片", attachments=["/tmp/ref.png"])

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["candidate_budget_source"] == "planner_default"
    assert plan["arguments"]["duration"] == 6
    assert plan["reason"] == "attachment_to_video_image_first_request"


def test_agent_mode_planner_parses_compact_s_suffix_video_duration():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "用 xai，根據我提供的 ref , 產出 15s 性感影片，具乳，水蛇腰，翹臀，蜜大腿",
        attachments=["/tmp/ref.png"],
    )

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["duration"] == 15
    assert plan["reason"] == "attachment_to_video_image_first_request"


def test_agent_mode_planner_routes_move_this_image_as_attachment_video():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("讓這張圖動起來，做成 6 秒自然鏡頭", attachments=["/tmp/ref.png"])

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["candidate_budget_source"] == "planner_default"
    assert plan["arguments"]["duration"] == 6
    assert plan["reason"] == "attachment_to_video_image_first_request"


def test_agent_mode_planner_routes_english_animate_request_as_image_first_video():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("Animate this image into a 5 second natural product shot", attachments=["/tmp/ref.png"])

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["candidate_budget_source"] == "planner_default"
    assert plan["arguments"]["duration"] == 5
    assert plan["reason"] == "attachment_to_video_image_first_request"


def test_agent_mode_planner_routes_text_only_video_through_image_first_candidates():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆")

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["video_budget"] == 1
    assert plan["arguments"]["duration"] == 6
    assert plan["reason"] == "text_to_video_image_first_request"


def test_agent_mode_planner_routes_multishot_video_to_storyboard_contract():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請做一支 3 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上，柔和窗光。")

    assert plan["should_use_visual_package"] is True
    assert plan["reason"] == "storyboard_video_request"
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["candidate_budget_source"] == "planner_default"
    storyboard = plan["arguments"]["storyboard"]
    assert storyboard["enabled"] is True
    assert storyboard["shot_count"] == 3
    assert storyboard["candidate_budget_per_shot"] == 2
    assert storyboard["source_image_policy"] == "one_ranked_image_per_shot"
    assert storyboard["composition_target"] == "single_coherent_video"
    assert len(storyboard["shots"]) == 3
    assert {shot["source_image_policy"] for shot in storyboard["shots"]} == {"single_ranked_image"}


def test_agent_mode_planner_infers_portrait_aspect_for_full_body_fashion_request():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請產出一張全身時尚寫真和一段 6 秒影片，強調腿部構圖")

    assert plan["arguments"]["aspect_ratio"] == "9:16"


def test_agent_mode_planner_does_not_turn_final_image_video_composition_quality_into_guide():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請產出一張性感時尚寫真圖片和一段短影片，重視美女臉、絲襪質感、腿部構圖。")

    assert plan["reason"] == "image_plus_video_request"
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is True
    assert "composition_guide_only" not in plan["arguments"]
    assert plan["arguments"]["image_provider_source"] == "visual_agent_default"


def test_agent_mode_planner_infers_landscape_aspect_for_desk_product_photography():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請用 visual agent mode 產出產品攝影：霧黑鋼筆放在白紙上，柔和窗光，一張圖片和一段影片")

    assert plan["arguments"]["aspect_ratio"] == "16:9"


def test_agent_mode_planner_respects_explicit_square_aspect():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("幫我做一張 1:1 方形產品圖")

    assert plan["arguments"]["aspect_ratio"] == "1:1"


def test_agent_mode_planner_returns_provider_neutral_recovery_policy():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("make a product photo and short video")

    assert plan["recovery_policy"] == {
        "retry_budget": 1,
        "safe_reframe_allowed": True,
        "ask_user_on_low_confidence": True,
    }


def test_agent_mode_planner_records_three_layer_provider_contract():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請產出一張圖片和一段影片")

    assert plan["provider_contract"] == {
        "base_llm_provider": "openai-codex",
        "base_llm_model": "",
        "visual_agent_llm_provider": "xai-oauth",
        "visual_agent_llm_model": "",
        "visual_media_provider_default": "xai",
        "visual_media_model_default": "grok-imagine-image-quality",
        "visual_media_provider_override": None,
    }
    assert plan["arguments"]["image_provider"] == "xai"
    assert plan["arguments"]["image_provider_source"] == "visual_agent_default"


def test_agent_mode_planner_provider_contract_uses_character_design_default_provider():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("先產人物設定圖，安全版角色設定和服裝設計")

    assert plan["should_use_visual_package"] is True
    assert plan["reason"] == "character_design_ref_request"
    assert plan["arguments"]["character_design_ref_only"] is True
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is False
    assert plan["arguments"]["image_provider"] == "openai-codex"
    assert plan["arguments"]["image_provider_source"] == "character_design_default"
    assert plan["provider_contract"]["visual_media_provider_override"] == "openai-codex"
    assert plan["provider_contract"]["visual_agent_llm_provider"] is None
    assert plan["provider_contract"]["visual_agent_llm_model"] is None


def test_agent_mode_planner_provider_contract_uses_composition_guide_default_provider():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("先產構圖，低角度全身動態姿勢，給我 4 張挑最有張力的")

    assert plan["should_use_visual_package"] is True
    assert plan["reason"] == "composition_guide_request"
    assert plan["arguments"]["composition_guide_only"] is True
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is False
    assert plan["arguments"]["candidate_budget"] == 4
    assert plan["arguments"]["candidate_budget_source"] == "user"
    assert plan["arguments"]["image_provider"] == "openai-codex"
    assert plan["arguments"]["image_provider_source"] == "composition_guide_default"
    assert plan["provider_contract"]["visual_media_provider_override"] == "openai-codex"
    assert plan["provider_contract"]["visual_agent_llm_provider"] is None
    assert plan["provider_contract"]["visual_agent_llm_model"] is None


def test_agent_mode_planner_composition_guide_parses_chinese_candidate_count():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "現在用 openai 幫我產出構圖，一樣產出四張不同構圖讓我挑選，"
        "可以是動作、特寫、或是某個情境下的某一個當下動作",
        attachments=["/tmp/ref1.png", "/tmp/ref2.png"],
    )

    assert plan["reason"] == "composition_guide_request"
    assert plan["arguments"]["composition_guide_only"] is True
    assert plan["arguments"]["candidate_budget"] == 4
    assert plan["arguments"]["candidate_budget_source"] == "user"
    assert plan["arguments"]["image_provider"] == "openai-codex"


def test_agent_mode_planner_treats_person_composition_as_abstract_guide():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("繼續用 openai 產出人物構圖，給我四張候選")

    assert plan["reason"] == "composition_guide_request"
    assert plan["arguments"]["composition_guide_only"] is True
    assert plan["arguments"]["candidate_budget"] == 4
    assert plan["arguments"]["candidate_budget_source"] == "user"
    assert plan["arguments"]["image_provider"] == "openai-codex"


def test_agent_mode_planner_uses_current_slack_thread_intent_for_composition_guide():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    prompt = """[Replying to: "用 openai 幫我繪製這位人物的設定圖"]

[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] simon: 用 openai 幫我繪製這位人物的設定圖
simon: 這四張根本看起來就一模一樣，不同畫風是指四個不同繪者的風格，請重新產生
simon: 現在用 openai 幫我產出構圖，一樣產出四張不同構圖讓我挑選
[End of thread context]

用 openai 幫我產出構圖，給我四張構圖候選，每張都有個情境的某個瞬間。請開始"""

    plan = plan_visual_agent_request(prompt)

    assert plan["reason"] == "composition_guide_request"
    assert plan["arguments"]["prompt"].startswith("用 openai 幫我產出構圖")
    assert "Thread context" not in plan["arguments"]["prompt"]
    assert "Replying to" not in plan["arguments"]["prompt"]
    assert plan["arguments"]["composition_guide_only"] is True
    assert "character_design_ref_only" not in plan["arguments"]
    assert plan["arguments"]["candidate_budget"] == 4
    assert plan["arguments"]["candidate_budget_source"] == "user"


def test_agent_mode_planner_composition_guide_default_count_is_not_user_locked():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("先產構圖，低角度全身動態姿勢")

    assert plan["reason"] == "composition_guide_request"
    assert plan["arguments"]["composition_guide_only"] is True
    assert plan["arguments"]["candidate_budget"] == 3
    assert plan["arguments"]["candidate_budget_source"] == "planner_default"


def test_agent_mode_planner_allows_openai_image2_media_override():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請用 OpenAI image2 產出一張乾淨產品圖")

    assert plan["provider_contract"]["visual_media_provider_override"] == "openai-codex"
    assert plan["arguments"]["image_provider"] == "openai-codex"
    assert plan["arguments"]["image_provider_source"] == "prompt_override"


def test_agent_mode_planner_allows_grok_web_imagine_media_override():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請用 Grok Web Imagine 產出一張高品質動漫圖")

    assert plan["provider_contract"]["visual_media_provider_override"] == "grok-web-imagine"
    assert plan["arguments"]["image_provider"] == "grok-web-imagine"
    assert plan["arguments"]["image_provider_source"] == "prompt_override"


def test_agent_mode_planner_routes_grok_web_polish_as_image_polish_not_video():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("用 grok web polish 試試看", attachments=["/tmp/current.png"])

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is False
    assert plan["arguments"]["image_provider"] == "xai"
    assert plan["arguments"]["image_provider_source"] == "visual_agent_default"
    assert plan["arguments"]["polish_provider"] == "grok-web-imagine"
    assert plan["arguments"]["polish_provider_source"] == "prompt_override"

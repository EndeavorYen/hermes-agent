def test_agent_mode_planner_routes_image_plus_video_request():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "請產出一張圖片和一段 6 秒影片：霧黑鋼筆放在白紙上，柔和窗光。",
        attachments=["/tmp/ref.png"],
    )

    assert plan["tool_name"] == "visual_package_generate"
    assert plan["should_use_visual_package"] is True
    assert plan["reason"] == "image_plus_video_request"
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["attachments"] == ["/tmp/ref.png"]
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["video_budget"] == 1
    assert plan["arguments"]["duration"] == 6
    assert "autonomy_level" not in plan["arguments"]


def test_agent_mode_planner_routes_attachment_to_video_image_first():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("讓這張圖動起來，做成 6 秒自然鏡頭", attachments=["/tmp/ref.png"])

    assert plan["should_use_visual_package"] is True
    assert plan["reason"] == "attachment_to_video_image_first_request"
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["video_budget"] == 1
    assert plan["arguments"]["duration"] == 6


def test_agent_mode_planner_routes_text_video_through_image_first_candidates():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆")

    assert plan["should_use_visual_package"] is True
    assert plan["reason"] == "text_to_video_image_first_request"
    assert plan["arguments"]["include_image"] is False
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["video_budget"] == 1
    assert plan["arguments"]["duration"] == 6


def test_agent_mode_planner_infers_aspect_and_provider_override():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    portrait = plan_visual_agent_request("請用 OpenAI image2 產出一張全身時尚寫真")
    assert portrait["arguments"]["aspect_ratio"] == "9:16"
    assert portrait["arguments"]["image_provider"] == "openai-codex"
    assert portrait["arguments"]["image_provider_source"] == "prompt_override"

    grok_web = plan_visual_agent_request("請用 Grok Web Imagine 產出一張高品質動漫圖")
    assert grok_web["arguments"]["image_provider"] == "grok-web-imagine"
    assert grok_web["provider_contract"]["visual_media_provider_override"] == "grok-web-imagine"


def test_agent_mode_planner_ignores_non_generation_text_task():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request(
        "我要公開 Raphael，但不能產圖、不能用工具。請只用六行回答：目標、成功條件、證據門檻。"
    )

    assert plan["should_use_visual_package"] is False
    assert plan["reason"] == "text_only_visual_analysis"

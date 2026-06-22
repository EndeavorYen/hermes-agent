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
    assert plan["arguments"]["candidate_budget"] == 1
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


def test_agent_mode_planner_routes_image_only_request():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("幫我做一張乾淨產品攝影圖")

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is False


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


def test_agent_mode_planner_routes_text_only_video_through_image_first_candidates():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆")

    assert plan["should_use_visual_package"] is True
    assert plan["arguments"]["include_image"] is True
    assert plan["arguments"]["include_video"] is True
    assert plan["arguments"]["candidate_budget"] == 2
    assert plan["arguments"]["video_budget"] == 1
    assert plan["arguments"]["duration"] == 6
    assert plan["reason"] == "text_to_video_image_first_request"


def test_agent_mode_planner_infers_portrait_aspect_for_full_body_fashion_request():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("請產出一張全身時尚寫真和一段 6 秒影片，強調腿部構圖")

    assert plan["arguments"]["aspect_ratio"] == "9:16"


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

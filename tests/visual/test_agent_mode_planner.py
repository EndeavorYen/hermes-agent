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
    assert plan["arguments"]["duration"] == 6


def test_agent_mode_planner_returns_provider_neutral_recovery_policy():
    from agent.visual.agent_mode.planner import plan_visual_agent_request

    plan = plan_visual_agent_request("make a product photo and short video")

    assert plan["recovery_policy"] == {
        "retry_budget": 1,
        "safe_reframe_allowed": True,
        "ask_user_on_low_confidence": True,
    }

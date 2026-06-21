from __future__ import annotations


def test_nearest_supported_aspect_prefers_portrait():
    from agent.visual.aspect_policy import nearest_aspect_ratio

    assert nearest_aspect_ratio(720, 1280, ["16:9", "9:16", "1:1"]) == "9:16"


def test_nearest_supported_aspect_prefers_landscape():
    from agent.visual.aspect_policy import nearest_aspect_ratio

    assert nearest_aspect_ratio(1536, 1024, ["16:9", "3:2", "1:1"]) == "3:2"


def test_plan_center_crop_never_stretches():
    from agent.visual.aspect_policy import plan_center_crop

    plan = plan_center_crop(width=1920, height=1080, target_aspect_ratio="9:16")
    assert plan["action"] == "crop"
    assert plan["width"] < 1920
    assert plan["height"] == 1080
    assert plan["filter"].startswith("crop=")
    assert "scale=" not in plan["filter"]


def test_plan_center_crop_skips_close_match():
    from agent.visual.aspect_policy import plan_center_crop

    plan = plan_center_crop(width=720, height=1280, target_aspect_ratio="9:16")
    assert plan["action"] == "copy"


def test_nearest_aspect_accepts_xai_supported_set():
    from agent.visual.aspect_policy import nearest_aspect_ratio

    assert nearest_aspect_ratio(
        720,
        1280,
        ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
    ) == "9:16"


def test_select_video_aspect_prefers_source_dimensions_over_requested():
    from agent.visual.aspect_policy import select_video_aspect_ratio

    assert select_video_aspect_ratio(
        source_width=720,
        source_height=1280,
        requested_aspect_ratio="16:9",
        supported=["16:9", "9:16", "1:1"],
    ) == "9:16"


def test_select_video_aspect_uses_requested_when_source_unknown():
    from agent.visual.aspect_policy import select_video_aspect_ratio

    assert select_video_aspect_ratio(
        source_width=None,
        source_height=None,
        requested_aspect_ratio="1:1",
        supported=["16:9", "9:16", "1:1"],
    ) == "1:1"

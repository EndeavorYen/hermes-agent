from __future__ import annotations

import json

from agent.tool_executor import _visual_package_route_guard_result


def test_blocks_direct_image_tool_for_chinese_image_video_package():
    result = _visual_package_route_guard_result(
        "image_generate_mission",
        {"prompt": "Create a pen product photo"},
        [
            {
                "role": "user",
                "content": "請幫我產出一張圖片和一段影片：霧黑鋼筆產品攝影",
            }
        ],
        {"image_generate_mission", "video_generate", "visual_agent_generate"},
    )

    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["error_type"] == "wrong_visual_route"
    assert payload["retry_with_tool"] == "visual_agent_generate"


def test_blocks_direct_video_tool_for_english_image_video_package():
    result = _visual_package_route_guard_result(
        "video_generate",
        {"prompt": "animate the new still"},
        [{"role": "user", "content": "Create one image and one short video of a pen."}],
        {"image_generate_mission", "video_generate", "visual_agent_generate"},
    )

    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["retry_with_tool"] == "visual_agent_generate"


def test_blocks_direct_image_tool_for_colloquial_chinese_package_request():
    result = _visual_package_route_guard_result(
        "image_generate",
        {"prompt": "black pen product photo"},
        [{"role": "user", "content": "幫我產圖產影片：霧黑鋼筆放在白紙上，柔和窗光。"}],
        {"image_generate", "video_generate", "visual_agent_generate"},
    )

    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["retry_with_tool"] == "visual_agent_generate"


def test_blocks_direct_image_tool_for_visual_materials_with_clip_request():
    result = _visual_package_route_guard_result(
        "image_generate_mission",
        {"prompt": "black pen product visuals"},
        [{"role": "user", "content": "幫我做一組產品視覺素材，含短片：霧黑鋼筆、白紙、柔和窗光。"}],
        {"image_generate_mission", "video_generate", "visual_agent_generate"},
    )

    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["retry_with_tool"] == "visual_agent_generate"


def test_allows_video_tool_for_existing_selected_image_animation():
    result = _visual_package_route_guard_result(
        "video_generate",
        {"prompt": "animate the first image"},
        [{"role": "user", "content": "第一張產出影片"}],
        {"image_generate_mission", "video_generate", "visual_agent_generate"},
    )

    assert result is None


def test_allows_direct_tools_when_visual_agent_is_unavailable():
    result = _visual_package_route_guard_result(
        "image_generate_mission",
        {"prompt": "Create a pen product photo"},
        [{"role": "user", "content": "請幫我產出一張圖片和一段影片"}],
        {"image_generate_mission", "video_generate"},
    )

    assert result is None

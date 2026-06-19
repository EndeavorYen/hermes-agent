from __future__ import annotations

from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualMissionType


def test_plans_visual_package_when_image_and_video_requested():
    mission = plan_visual_mission(
        "Create a product showcase with three images and one short video.",
        attachments=["/tmp/reference.png"],
        autonomy_level=2,
    )

    assert mission.mission_id.startswith("vms_")
    assert mission.mission_type == VisualMissionType.VISUAL_PACKAGE
    assert mission.input_assets == ["/tmp/reference.png"]
    assert mission.candidate_budget == 3
    assert mission.video_budget == 1
    assert mission.autonomy_level == 2
    assert "image" in mission.requested_outputs
    assert "video" in mission.requested_outputs


def test_plans_image_set_for_image_only_request():
    mission = plan_visual_mission(
        "Generate four editorial image options from this reference.",
        attachments=["/tmp/reference.png"],
    )

    assert mission.mission_type == VisualMissionType.IMAGE_SET
    assert mission.candidate_budget == 4
    assert mission.video_budget == 0


def test_plans_chinese_natural_image_video_package_request():
    mission = plan_visual_mission(
        "請幫我產出一張圖片和一段影片：一支霧黑鋼筆放在白紙上，柔和窗光，乾淨產品攝影。"
    )

    assert mission.mission_type == VisualMissionType.VISUAL_PACKAGE
    assert "image" in mission.requested_outputs
    assert "video" in mission.requested_outputs
    assert mission.candidate_budget == 1
    assert mission.video_budget == 1

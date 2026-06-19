from __future__ import annotations


def test_feedback_parser_detects_positive_selection():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("第二張不錯，保留這個方向")
    assert feedback.feedback_type == "explicit_text"
    assert feedback.polarity > 0
    assert feedback.parsed["selection_hint"] == 2


def test_feedback_parser_detects_english_ordinal_selection():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("3rd, stronger product angle, 加分")
    assert feedback.polarity > 0
    assert feedback.parsed["selection_hint"] == 3


def test_feedback_parser_does_not_treat_generation_count_as_selection():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("請產 4 張乾淨產品攝影圖")
    assert feedback.parsed["selection_hint"] is None


def test_feedback_parser_detects_wrong_face():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("臉不像，全部退貨")
    assert feedback.polarity < 0
    assert "reference_identity_drift" in feedback.parsed["issues"]


def test_feedback_parser_detects_more_motion():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("影片太像 slow motion，要更有動作")
    assert feedback.parsed["requested_direction"] == "more_motion"


def test_feedback_parser_detects_candidate_label_and_not_sexy_enough():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("V5 性感升級不夠，頂多和 V4 持平")
    assert feedback.parsed["candidate_hints"] == ["V5", "V4"]
    assert "not_sexy_enough" in feedback.parsed["issues"]


def test_feedback_parser_detects_stale_or_repeated_artifact():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("這輪又貼到舊圖，而且有重複")
    assert feedback.polarity < 0
    assert "stale_or_repeated_artifact" in feedback.parsed["issues"]


def test_feedback_parser_detects_aspect_stretch_issue():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("影片比例錯誤，被拉伸了")
    assert "aspect_or_stretch_issue" in feedback.parsed["issues"]

from __future__ import annotations

import json


def _burn_report(
    run_id: str,
    *,
    min_score: float,
    provider_failure_count: int = 0,
    video_missing_after_image_count: int = 0,
    image_first_video_source_failure_count: int = 0,
    preference_dimension_failures: list[dict] | None = None,
    quality_issues: list[str] | None = None,
) -> dict:
    preference_dimension_failures = preference_dimension_failures or []
    quality_issues = quality_issues or []
    return {
        "success": not provider_failure_count and min_score >= 0.75,
        "run_id": run_id,
        "generated_at": f"2026-06-22T{run_id[-2:]}:00:00+00:00",
        "summary": {
            "case_count": 2,
            "failed_case_count": 0,
            "min_quality_score": min_score,
            "quality_issue_count": len(quality_issues),
            "quality_issues": quality_issues,
            "provider_failure_count": provider_failure_count,
            "video_missing_after_image_count": video_missing_after_image_count,
            "image_first_video_source_failure_count": image_first_video_source_failure_count,
            "preference_dimension_failure_count": len(preference_dimension_failures),
            "preference_dimension_failures": preference_dimension_failures,
        },
        "suite": {"cases": [{"raw_prompt": "private prompt that must not leak"}]},
    }


def test_live_quality_trends_detect_regression_and_emit_autonomous_actions():
    from agent.visual.live_quality_trends import build_live_quality_trend_report

    report = build_live_quality_trend_report(
        [
            _burn_report("run01", min_score=0.88),
            _burn_report("run02", min_score=0.84),
            _burn_report(
                "run03",
                min_score=0.56,
                provider_failure_count=1,
                video_missing_after_image_count=1,
                preference_dimension_failures=[
                    {"dimension": "subject_beauty", "issue": "subject_not_attractive", "score": 0.31}
                ],
                quality_issues=["subject_not_attractive"],
            ),
            _burn_report(
                "run04",
                min_score=0.50,
                provider_failure_count=2,
                image_first_video_source_failure_count=1,
                preference_dimension_failures=[
                    {"dimension": "fashion_material_quality", "issue": "stockings_bad", "score": 0.28}
                ],
                quality_issues=["stockings_bad"],
            ),
        ],
        baseline_window=2,
        recent_window=2,
    )

    assert report["success"] is False
    assert report["run_count"] == 4
    assert report["summary"]["baseline_avg_min_quality_score"] == 0.86
    assert report["summary"]["recent_avg_min_quality_score"] == 0.53
    assert report["summary"]["quality_score_delta"] == -0.33
    assert report["degradations"] == [
        "quality_score_degraded",
        "video_generation_degraded",
        "provider_failures_spiked",
        "preference_dimension_failures_spiked",
    ]
    assert [action["type"] for action in report["next_actions"]] == [
        "increase_candidate_budget",
        "rerank_before_slack",
        "prefer_image_first_video",
        "safe_reframe_provider_retry",
        "repair_low_preference_dimension",
    ]
    assert {action["track"] for action in report["next_actions"]} == {"aesthetic", "provider"}
    assert all(action["requires_human_feedback"] is False for action in report["next_actions"])
    assert report["self_review"] == {
        "reduces_human_intervention": True,
        "human_feedback_required": False,
        "privacy_safe": True,
        "provider_and_aesthetic_tracks_separated": True,
    }
    assert "private prompt" not in json.dumps(report, ensure_ascii=False)


def test_live_quality_trends_summarizes_recent_slack_conversation_runs():
    from agent.visual.live_quality_trends import build_live_quality_trend_report

    generic_baseline = _burn_report("run01", min_score=0.90, provider_failure_count=1)
    generic_recent = _burn_report("run02", min_score=0.88)
    first_conversation = _burn_report("run03", min_score=0.82)
    first_conversation["source"] = "slack_conversation_e2e"
    first_conversation["self_review"] = {
        "native_video_upload_covered": True,
        "image_first_video_source_covered": True,
    }
    second_conversation = _burn_report("run04", min_score=0.84)
    second_conversation["source"] = "slack_conversation_e2e"
    second_conversation["self_review"] = {
        "native_video_upload_covered": True,
        "image_first_video_source_covered": True,
    }

    report = build_live_quality_trend_report(
        [generic_baseline, generic_recent, first_conversation, second_conversation],
        baseline_window=1,
        recent_window=2,
    )

    assert report["summary"]["recent_slack_conversation_run_count"] == 2
    assert report["summary"]["recent_slack_conversation_run_ids"] == ["run03", "run04"]
    assert report["summary"]["recent_slack_conversation_avg_min_quality_score"] == 0.83
    assert report["summary"]["recent_slack_conversation_native_video_upload_covered_count"] == 2
    assert report["summary"]["recent_slack_conversation_image_first_video_source_failure_count"] == 0
    assert report["summary"]["recent_slack_conversation_provider_failure_count"] == 0
    assert report["summary"]["recent_slack_conversation_latest_generated_at"] == (
        "2026-06-22T04:00:00+00:00"
    )

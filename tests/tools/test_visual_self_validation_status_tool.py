from __future__ import annotations

import json


def test_visual_self_validation_status_tool_returns_summary(monkeypatch, tmp_path):
    from tools import visual_self_validation_status_tool

    latest_path = tmp_path / "latest.json"
    latest_path.write_text(
        json.dumps(
                {
                    "success": True,
                    "run_id": "20260622T101900Z",
                    "generated_at": "2026-06-22T10:19:00+00:00",
                    "mode": "fixture+live",
                    "failures": [],
                    "live_policy": {"mode": "on", "decision": "run", "live_enabled": True},
                    "slack_live_upload_policy": {"decision": "run", "enabled": True},
                    "summary": {
                        "live_quality_suite_success": True,
                        "live_quality_burn_success": True,
                        "live_quality_gate_min_score": 0.82,
                        "live_quality_burn_action_types": ["prefer_image_first_video"],
                        "live_slack_upload_native_delivery_covered": True,
                        "live_slack_upload_uploaded_video_file_count": 1,
                        "slack_duplicate_delivery_count": 0,
                    },
                    "automation": {"self_improvement": {"next_actions": []}},
                }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(visual_self_validation_status_tool, "_default_latest_path", lambda: latest_path)

    raw = visual_self_validation_status_tool._handle_visual_self_validation_status(
        {"stale_after_hours": 999999}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["health_status"] == "pass"
    assert payload["live_e2e_ran"] is True


def test_visual_self_validation_status_tool_is_registered():
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()

    assert "visual_self_validation_status" in registry._tools
    entry = registry._tools["visual_self_validation_status"]
    assert entry.is_async is False
    assert entry.toolset == "image_gen"

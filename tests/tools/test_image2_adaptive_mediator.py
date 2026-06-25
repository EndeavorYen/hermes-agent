from __future__ import annotations

import json


def test_mediate_image2_prompt_preserves_locks_and_sanitizes_sensitive_terms():
    from tools import image2_adaptive_mediator

    mediated = image2_adaptive_mediator.mediate_image2_prompt(
        "台北雨夜 性感美女拿黑色洋桔梗",
        config={"enabled": True},
    )

    assert mediated.strategy in {"codex_direct", "safe_reframe", "lock_preserving_rewrite"}
    assert "black lisianthus" in mediated.final_prompt
    assert "性感" not in mediated.final_prompt
    assert any(lock.canonical.startswith("black lisianthus") for lock in mediated.intent.constraint_locks)


def test_record_and_summarize_image2_mediator_memory(tmp_path):
    from tools import image2_adaptive_mediator

    config = {
        "enabled": True,
        "log_attempts": True,
        "memory_path": str(tmp_path / "image2-memory.jsonl"),
    }
    mediated = image2_adaptive_mediator.mediate_image2_prompt(
        "黑色洋桔梗 editorial portrait",
        config=config,
    )

    image2_adaptive_mediator.record_image2_mediator_attempt(
        mediated,
        image2_status="success",
        feedback_source="visual_inspection",
        failure_class=[],
        config=config,
        notes="accepted",
    )
    summary = image2_adaptive_mediator.summarize_image2_mediator_memory(
        config=config,
        limit=5,
    )

    assert summary["attempt_count"] == 1
    assert summary["status_counts"] == {"success": 1}
    assert summary["recent_attempts"][0]["image2_status"] == "success"
    assert summary["recent_attempts"][0]["strategy"] == mediated.strategy


def test_image2_mediator_memory_tool_reports_and_records_feedback(tmp_path, monkeypatch):
    from tools import image2_adaptive_mediator

    config = {
        "enabled": True,
        "log_attempts": True,
        "memory_path": str(tmp_path / "image2-memory.jsonl"),
    }
    monkeypatch.setattr(
        image2_adaptive_mediator,
        "read_image2_adaptive_mediator_config",
        lambda: config,
    )

    feedback_raw = image2_adaptive_mediator._handle_image2_mediator_memory(
        {"action": "feedback", "feedback": "更接近，但物件漂移"}
    )
    feedback_payload = json.loads(feedback_raw)
    report_raw = image2_adaptive_mediator._handle_image2_mediator_memory(
        {"action": "report", "limit": 5}
    )
    report_payload = json.loads(report_raw)

    assert feedback_payload["success"] is True
    assert feedback_payload["feedback"]["recorded"] is True
    assert report_payload["success"] is True
    assert report_payload["summary"]["feedback_count"] == 1

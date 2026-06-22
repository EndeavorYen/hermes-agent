from __future__ import annotations


def _ready_status() -> dict:
    return {
        "success": True,
        "health_status": "pass",
        "run_id": "20260622T172033Z",
        "generated_at": "2026-06-22T17:20:33+00:00",
        "live_e2e_ran": True,
        "live": {
            "burn_success": True,
            "burn_case_count": 2,
            "burn_min_score": 0.8206,
            "image_first_video_source_covered": True,
            "image_first_video_source_failure_count": 0,
            "trend_degradations": [],
        },
        "delivery": {
            "native_video_upload_covered": True,
            "uploaded_video_file_count": 1,
            "duplicate_delivery_count": 0,
        },
        "promotion_readiness": {
            "ready": True,
            "blocking_reasons": [],
            "candidate": {
                "type": "prefer_strategy",
                "source": "live_quality_burn",
                "track": "aesthetic",
                "strategy_signature": "image_first_rank_then_video",
                "bucket": "live_visual_agent_mode",
                "activation_status": "shadow",
                "confidence": 0.8206,
                "evidence_count": 2,
            },
            "thresholds": {
                "min_live_quality_burn_score": 0.8,
                "min_live_quality_burn_cases": 2,
                "min_strategy_confidence": 0.8,
                "requires_current_live_run": True,
                "requires_native_slack_upload": True,
                "requires_no_live_trend_degradation": True,
            },
        },
    }


def test_activate_ready_visual_promotion_records_audited_controlled_strategy(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.promotion_readiness_activation import activate_ready_visual_promotion
    from agent.visual.strategy_policy import find_controlled_strategy_plan

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    result = activate_ready_visual_promotion(ledger, _ready_status())

    assert result["activated_count"] == 1
    assert result["blocked_count"] == 0
    activation = ledger.get_strategy_activation(result["activation_ids"][0])
    assert activation["activation_status"] == "controlled"
    assert activation["intent_signature"] == "live_visual_agent_mode"
    assert activation["strategy_signature"] == "image_first_rank_then_video"
    assert activation["promotion_decision"]["allowed"] is True
    assert activation["promotion_decision"]["decision"] == "promote_controlled"
    assert activation["promotion_decision"]["observed"]["live_e2e_ran"] is True
    assert activation["metadata"]["source"] == "promotion_readiness_activation"
    assert activation["metadata"]["prompt_mutation_allowed"] is False

    shadow = ledger.get_shadow_update(activation["shadow_update_id"])
    assert shadow["activation_status"] == "shadow"
    assert shadow["proposed_change"]["type"] == "prefer_strategy"
    assert shadow["evidence"]["run_id"] == "20260622T172033Z"

    plan = find_controlled_strategy_plan(ledger, intent_signature="visig_real_prompt")
    assert plan is not None
    assert plan.strategy_signature == "image_first_rank_then_video"
    assert plan.activation_id == activation["id"]


def test_activate_ready_visual_promotion_skips_blocked_readiness(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.promotion_readiness_activation import activate_ready_visual_promotion

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    status = _ready_status()
    status["promotion_readiness"] = {
        **status["promotion_readiness"],
        "ready": False,
        "blocking_reasons": ["live_quality_trend_degraded"],
    }

    result = activate_ready_visual_promotion(ledger, status)

    assert result["activated_count"] == 0
    assert result["blocked_count"] == 1
    assert result["decisions"][0]["reasons"] == ["live_quality_trend_degraded"]
    assert ledger.list_strategy_activations() == []


def test_activate_ready_visual_promotion_is_idempotent_for_existing_strategy(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.promotion_readiness_activation import activate_ready_visual_promotion

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    first = activate_ready_visual_promotion(ledger, _ready_status())
    second = activate_ready_visual_promotion(ledger, _ready_status())

    assert first["activated_count"] == 1
    assert second["activated_count"] == 0
    assert second["skipped_count"] == 1
    assert second["decisions"][0]["reason"] == "strategy_already_controlled"
    assert len(ledger.list_strategy_activations()) == 1

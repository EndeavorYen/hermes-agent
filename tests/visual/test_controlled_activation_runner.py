from __future__ import annotations


def test_controlled_activation_runner_records_allowed_candidate(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.controlled_activation_runner import activate_controlled_visual_candidates

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    result = activate_controlled_visual_candidates(
        ledger,
        [
            {
                "type": "prefer_strategy",
                "bucket": "visig_demo",
                "strategy_signature": "vstrat_demo",
                "confidence": 0.91,
                "activation_status": "shadow",
                "shadow_update_id": "vsh_demo",
                "evidence_counts": {
                    "request_count": 25,
                    "attempt_count": 25,
                    "delivery_count": 12,
                    "judgment_count": 12,
                    "human_veto_count": 0,
                },
            }
        ],
        runtime_checks={
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "prompt_mutation_read_count": 0,
            "unsafe_activation_count": 0,
        },
        autonomy_level=2,
        operator_approved=True,
    )

    assert result["activated_count"] == 1
    assert result["blocked_count"] == 0
    row = ledger.get_strategy_activation(result["activation_ids"][0])
    assert row["activation_status"] == "controlled"
    assert row["promotion_decision"]["allowed"] is True


def test_controlled_activation_runner_blocks_human_veto(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.controlled_activation_runner import activate_controlled_visual_candidates

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    result = activate_controlled_visual_candidates(
        ledger,
        [
            {
                "type": "prefer_strategy",
                "bucket": "visig_demo",
                "strategy_signature": "vstrat_demo",
                "confidence": 0.95,
                "activation_status": "shadow",
                "shadow_update_id": "vsh_demo",
                "evidence_counts": {
                    "request_count": 30,
                    "attempt_count": 30,
                    "delivery_count": 20,
                    "judgment_count": 20,
                    "human_veto_count": 1,
                },
            }
        ],
        runtime_checks={
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "prompt_mutation_read_count": 0,
            "unsafe_activation_count": 0,
        },
        autonomy_level=2,
        operator_approved=True,
    )

    assert result["activated_count"] == 0
    assert result["blocked_count"] == 1
    assert "human_veto_detected" in result["decisions"][0]["reasons"]

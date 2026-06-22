from __future__ import annotations

import json


def test_visual_activate_ready_promotion_cli_from_status_path(capsys, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_activate_ready_promotion import main

    db_path = tmp_path / "visual.sqlite3"
    status_path = tmp_path / "status.json"
    status_path.write_text(
        json.dumps(
            {
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
                },
                "delivery": {
                    "native_video_upload_covered": True,
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
                    "thresholds": {"min_strategy_confidence": 0.8},
                },
            }
        ),
        encoding="utf-8",
    )

    code = main(["--status-path", str(status_path), "--db-path", str(db_path), "--json"])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["activation"]["activated_count"] == 1
    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    assert len(ledger.list_strategy_activations()) == 1


def test_visual_activate_ready_promotion_cli_returns_nonzero_when_blocked(capsys, tmp_path):
    from scripts.visual_activate_ready_promotion import main

    status_path = tmp_path / "status.json"
    status_path.write_text(
        json.dumps(
            {
                "promotion_readiness": {
                    "ready": False,
                    "blocking_reasons": ["current_live_run_required"],
                    "candidate": None,
                }
            }
        ),
        encoding="utf-8",
    )

    code = main(["--status-path", str(status_path), "--db-path", str(tmp_path / "visual.sqlite3"), "--json"])
    out = json.loads(capsys.readouterr().out)

    assert code == 1
    assert out["activation"]["blocked_count"] == 1

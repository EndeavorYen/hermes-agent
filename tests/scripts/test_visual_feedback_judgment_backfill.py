import json


def test_visual_feedback_judgment_backfill_cli_json(monkeypatch, capsys, tmp_path):
    from scripts import visual_feedback_judgment_backfill

    monkeypatch.setattr(
        visual_feedback_judgment_backfill,
        "backfill_feedback_judgments",
        lambda db_path, dry_run=False, limit=None: {
            "success": True,
            "db_path": str(db_path),
            "dry_run": dry_run,
            "limit": limit,
            "backfillable_count": 1,
            "created_count": 0 if dry_run else 1,
            "artifact_ids": ["var_demo"],
        },
    )

    code = visual_feedback_judgment_backfill.main(
        ["--db-path", str(tmp_path / "visual.sqlite3"), "--dry-run", "--limit", "1", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["dry_run"] is True
    assert payload["limit"] == 1
    assert payload["artifact_ids"] == ["var_demo"]

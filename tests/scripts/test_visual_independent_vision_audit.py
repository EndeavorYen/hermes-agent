import json


def test_visual_independent_vision_audit_cli_dry_run_json(monkeypatch, capsys, tmp_path):
    from scripts import visual_independent_vision_audit

    monkeypatch.setattr(
        visual_independent_vision_audit,
        "audit_independent_vision_judgments",
        lambda db_path, analyzer=None, dry_run=False, limit=None: {
            "success": True,
            "db_path": str(db_path),
            "candidate_count": 1,
            "created_count": 0,
            "error_count": 0,
            "artifact_ids": ["var_demo"],
            "dry_run": dry_run,
            "limit": limit,
            "has_analyzer": analyzer is not None,
        },
    )

    code = visual_independent_vision_audit.main(
        ["--db-path", str(tmp_path / "visual.sqlite3"), "--dry-run", "--limit", "1", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["dry_run"] is True
    assert payload["limit"] == 1
    assert payload["has_analyzer"] is False

from __future__ import annotations

import json


def test_visual_autonomous_healthcheck_combines_reports(tmp_path):
    from scripts.visual_autonomous_healthcheck import build_visual_autonomous_healthcheck
    from scripts.visual_learning_replay import build_visual_learning_replay

    db_path = tmp_path / "visual.sqlite3"
    build_visual_learning_replay(db_path)

    report = build_visual_autonomous_healthcheck(db_path, autonomy_level=2)

    assert report["success"] is True
    assert report["health_status"] == "pass"
    assert report["reports"]["autonomous_loop"]["success"] is True
    assert report["reports"]["regression"]["success"] is True
    assert report["reports"]["learning"]["success"] is True
    assert "private prompt" not in json.dumps(report, ensure_ascii=False)


def test_visual_autonomous_healthcheck_cli_json(capsys, tmp_path):
    from scripts.visual_autonomous_healthcheck import main
    from scripts.visual_learning_replay import build_visual_learning_replay

    db_path = tmp_path / "visual.sqlite3"
    build_visual_learning_replay(db_path)

    code = main(["--db-path", str(db_path), "--autonomy-level", "2", "--json"])
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["health_status"] == "pass"


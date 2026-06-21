def test_visual_regression_report_cli_json_success(capsys, tmp_path):
    from scripts.visual_regression_report import main

    code = main(["--db-path", str(tmp_path / "missing.sqlite3"), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out

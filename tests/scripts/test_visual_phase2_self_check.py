def test_phase2_self_check_json_reports_success_for_fixture(capsys, tmp_path, monkeypatch):
    from scripts.visual_phase2_self_check import main

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    code = main(["--fixture", "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out

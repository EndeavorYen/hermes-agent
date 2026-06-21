import json


def test_visual_evidence_self_smoke_passes_in_isolated_home(tmp_path, capsys):
    from scripts.visual_evidence_self_smoke import main

    exit_code = main(["--work-dir", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["success"] is True
    assert payload["proof"]["duplicate_artifact_delivery_count"] == 0
    assert payload["proof"]["missing_source_metadata_count"] == 0
    assert payload["feedback"]["count"] >= 2
    assert "raw_prompt" not in json.dumps(payload).lower()

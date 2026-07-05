import json


def test_visual_learning_replay_generates_safe_shadow_proposals(tmp_path):
    from scripts.visual_learning_replay import build_visual_learning_replay

    report = build_visual_learning_replay(tmp_path / "replay.sqlite3")
    proposal_types = {proposal["type"] for proposal in report["proposals"]}

    assert report["success"] is True
    assert "prefer_strategy" in proposal_types
    assert "prefer_provider_for_bucket" in proposal_types
    assert report["safety"]["prompt_mutation_proposals"] == 0
    assert report["safety"]["unsafe_activation_proposals"] == 0


def test_visual_learning_replay_cli_json_is_privacy_safe(capsys, tmp_path):
    from scripts.visual_learning_replay import main

    code = main(["--db-path", str(tmp_path / "replay.sqlite3"), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out
    assert "private prompt" not in out
    payload = json.loads(out)
    assert payload["outcomes"]["strategy_count"] == 1

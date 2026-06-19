from __future__ import annotations


def test_hard_gate_passes_fresh_valid_artifact():
    from agent.visual.judges.deterministic import score_deterministic_artifact

    score = score_deterministic_artifact(
        {
            "local_path": "/tmp/a.png",
            "content_hash": "sha256:a",
            "mime_type": "image/png",
            "bytes": 1000,
            "freshness_status": "fresh",
            "is_stable": 1,
        }
    )

    assert score["hard_gate"]["passed"] is True
    assert score["hard_gate"]["failed"] == []
    assert score["scores"]["artifact_exists"] == 1.0
    assert score["scores"]["artifact_fresh"] == 1.0


def test_hard_gate_fails_stale_artifact():
    from agent.visual.judges.deterministic import score_deterministic_artifact

    score = score_deterministic_artifact(
        {
            "content_hash": "sha256:a",
            "mime_type": "image/png",
            "bytes": 1000,
            "freshness_status": "stale",
            "is_stable": 1,
        }
    )

    assert score["hard_gate"]["passed"] is False
    assert "artifact_fresh" in score["hard_gate"]["failed"]


def test_aspect_ratio_score_matches_requested_ratio():
    from agent.visual.judges.deterministic import score_deterministic_artifact

    score = score_deterministic_artifact(
        {
            "source_url": "https://example.com/a.png",
            "content_hash": "sha256:a",
            "mime_type": "image/png",
            "bytes": 1000,
            "width": 720,
            "height": 1280,
            "freshness_status": "fresh",
            "is_stable": True,
        },
        requested={"aspect_ratio": "9:16"},
    )

    assert score["hard_gate"]["passed"] is True
    assert score["scores"]["aspect_fit"] == 1.0


def test_invalid_mime_fails_hard_gate():
    from agent.visual.judges.deterministic import score_deterministic_artifact

    score = score_deterministic_artifact(
        {
            "local_path": "/tmp/a.txt",
            "content_hash": "sha256:a",
            "mime_type": "text/plain",
            "bytes": 1000,
            "freshness_status": "fresh",
            "is_stable": True,
        }
    )

    assert score["hard_gate"]["passed"] is False
    assert "mime_valid" in score["hard_gate"]["failed"]

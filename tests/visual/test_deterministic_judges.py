def test_deterministic_judge_hard_gate_fails_stale_artifact():
    from agent.visual.judges.deterministic import judge_artifact

    score = judge_artifact(
        {
            "kind": "image",
            "mime_type": "image/png",
            "bytes": 100,
            "width": 1280,
            "height": 720,
            "freshness_status": "stale",
            "is_stable": True,
        },
        expected_kind="image",
        requested_parameters={"aspect_ratio": "16:9"},
    )

    assert score["hard_gate"]["passed"] is False
    assert score["hard_gate"]["artifact_fresh"] is False


def test_deterministic_judge_scores_fresh_matching_image():
    from agent.visual.judges.deterministic import judge_artifact

    score = judge_artifact(
        {
            "kind": "image",
            "mime_type": "image/png",
            "bytes": 100_000,
            "width": 1280,
            "height": 720,
            "freshness_status": "fresh",
            "is_stable": True,
            "local_path": "/tmp/current.png",
        },
        expected_kind="image",
        requested_parameters={"aspect_ratio": "16:9"},
    )

    assert score["version"] == "deterministic_judge.v0.1"
    assert score["hard_gate"]["passed"] is True
    assert score["scores"]["aspect_match"] == 1.0
    assert score["scores"]["final_score"] >= 0.70


def test_deterministic_judge_hard_gate_fails_provider_error():
    from agent.visual.judges.deterministic import judge_artifact

    score = judge_artifact(
        {
            "kind": "video",
            "mime_type": "video/mp4",
            "bytes": 100_000,
            "freshness_status": "fresh",
            "is_stable": True,
            "local_path": "/tmp/current.mp4",
            "error_type": "provider_rejected",
        },
        expected_kind="video",
        requested_parameters={},
    )

    assert score["hard_gate"]["passed"] is False
    assert score["hard_gate"]["no_provider_error"] is False


def test_deterministic_judge_accepts_source_url_as_deliverable():
    from agent.visual.judges.deterministic import judge_artifact

    score = judge_artifact(
        {
            "kind": "video",
            "mime_type": "video/mp4",
            "content_hash": "refhash:current",
            "source_url": "https://vidgen.x.ai/xai-vidgen-bucket/current.mp4",
            "freshness_status": "fresh",
            "is_stable": True,
        },
        expected_kind="video",
        requested_parameters={"duration_seconds": 6},
    )

    assert score["hard_gate"]["passed"] is True
    assert score["hard_gate"]["delivery_possible"] is True

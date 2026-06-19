from __future__ import annotations


def test_ranker_excludes_failed_hard_gate():
    from agent.visual.ranker import rank_visual_candidates

    result = rank_visual_candidates(
        [
            {
                "artifact_id": "bad",
                "deterministic_score": {
                    "hard_gate": {"passed": False},
                    "scores": {},
                },
            },
            {
                "artifact_id": "good",
                "deterministic_score": {
                    "hard_gate": {"passed": True},
                    "scores": {
                        "artifact_exists": 1.0,
                        "content_hash_present": 1.0,
                        "mime_valid": 1.0,
                        "byte_size_valid": 1.0,
                        "artifact_fresh": 1.0,
                        "artifact_stable": 1.0,
                        "aspect_fit": 1.0,
                        "duration_fit": 1.0,
                        "delivery_possible": 1.0,
                    },
                },
            },
        ]
    )

    assert result["decision"] == "post"
    assert result["selected_artifact_id"] == "good"


def test_ranker_asks_when_confidence_low():
    from agent.visual.ranker import rank_visual_candidates

    result = rank_visual_candidates(
        [
            {
                "artifact_id": "a",
                "deterministic_score": {
                    "hard_gate": {"passed": True},
                    "scores": {
                        "artifact_exists": 0.4,
                        "content_hash_present": 0.4,
                        "mime_valid": 0.4,
                        "byte_size_valid": 0.4,
                        "artifact_fresh": 0.4,
                        "artifact_stable": 0.4,
                        "aspect_fit": 0.4,
                        "duration_fit": 0.4,
                        "delivery_possible": 0.4,
                    },
                },
            },
        ]
    )

    assert result["decision"] == "ask_user"
    assert result["confidence"] < 0.55


def test_ranker_prefers_highest_confidence_candidate():
    from agent.visual.ranker import rank_visual_candidates

    result = rank_visual_candidates(
        [
            _candidate("ok", artifact_fresh=0.7, aspect_fit=0.7),
            _candidate("best", artifact_fresh=1.0, aspect_fit=1.0),
        ]
    )

    assert result["selected_artifact_id"] == "best"
    assert [item["artifact_id"] for item in result["ranked_candidates"]] == [
        "best",
        "ok",
    ]


def test_ranker_retries_when_all_hard_gates_fail_and_candidate_retryable():
    from agent.visual.ranker import rank_visual_candidates

    result = rank_visual_candidates(
        [
            {
                "artifact_id": "bad",
                "retryable": True,
                "deterministic_score": {
                    "hard_gate": {"passed": False},
                    "scores": {},
                },
            }
        ]
    )

    assert result["decision"] == "retry"
    assert result["selected_artifact_id"] is None


def _candidate(artifact_id: str, **overrides):
    scores = {
        "artifact_exists": 1.0,
        "content_hash_present": 1.0,
        "mime_valid": 1.0,
        "byte_size_valid": 1.0,
        "artifact_fresh": 1.0,
        "artifact_stable": 1.0,
        "aspect_fit": 1.0,
        "duration_fit": 1.0,
        "delivery_possible": 1.0,
    }
    scores.update(overrides)
    return {
        "artifact_id": artifact_id,
        "deterministic_score": {
            "hard_gate": {"passed": True},
            "scores": scores,
        },
    }

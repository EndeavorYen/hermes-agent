from memory.layer2_selector import Layer2SelectionPolicy, select_candidates


def test_select_candidates_prefers_scope_query_and_net_support():
    candidates = [
        {
            "canonical_text": "Repository uses uv for dependency management",
            "routing_destination": "prior",
            "kind": "env_fact",
            "support_count": 2,
            "contradict_count": 0,
            "status": "active",
            "subject_scope": "repo",
            "subject_id": "hermes-agent",
            "updated_at": "2026-05-13T00:00:00+00:00",
        },
        {
            "canonical_text": "User likes terse answers",
            "routing_destination": "user",
            "kind": "preference",
            "support_count": 9,
            "contradict_count": 0,
            "status": "active",
            "subject_scope": "user",
            "subject_id": "simon",
            "updated_at": "2026-05-13T00:00:00+00:00",
        },
    ]

    selected = select_candidates(
        candidates,
        query_text="how does this repo manage python dependencies?",
        subject_scope="repo",
        subject_id="hermes-agent",
        policy=Layer2SelectionPolicy(max_items=2),
    )

    assert [item.candidate["canonical_text"] for item in selected] == [
        "Repository uses uv for dependency management",
        "User likes terse answers",
    ]
    assert "scope_match" in selected[0].reason_codes
    assert "subject_match" in selected[0].reason_codes
    assert "query_match" in selected[0].reason_codes


def test_select_candidates_excludes_non_recallable_statuses_and_negative_net_support():
    candidates = [
        {
            "canonical_text": "Quarantined fact",
            "status": "quarantine",
            "support_count": 10,
            "contradict_count": 0,
        },
        {
            "canonical_text": "Contradicted fact",
            "status": "active",
            "support_count": 1,
            "contradict_count": 2,
        },
        {
            "canonical_text": "Good fact",
            "status": "active",
            "support_count": 2,
            "contradict_count": 0,
        },
    ]

    selected = select_candidates(candidates, policy=Layer2SelectionPolicy(max_items=5))

    assert [item.candidate["canonical_text"] for item in selected] == ["Good fact"]

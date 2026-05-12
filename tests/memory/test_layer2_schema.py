from memory.layer2_schema import validate_layer2_payload


def test_validate_layer2_payload_accepts_evidence_linked_candidate():
    result = validate_layer2_payload(
        {
            "observations": [
                {
                    "observation_text": "Tool output showed the repo uses uv.",
                    "source_event_id": "obs-1",
                }
            ],
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Repository uses uv",
                    "kind": "env_fact",
                    "proposed_target": "memory",
                    "source_event_id": "cand-1",
                    "evidence_source_event_id": "obs-1",
                    "counts_for_recurrence": True,
                }
            ],
        }
    )

    assert result.valid is True
    assert result.issues == []
    assert result.payload["candidate_events"][0]["counts_for_recurrence"] is True


def test_validate_layer2_payload_accepts_candidate_source_id_as_observation_evidence():
    result = validate_layer2_payload(
        {
            "observations": [
                {
                    "observation_text": "User directly requested concise answers in this run.",
                    "source_event_id": "obs-1",
                }
            ],
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "User prefers concise answers",
                    "kind": "preference",
                    "proposed_target": "user",
                    "source_event_id": "obs-1",
                    "counts_for_recurrence": True,
                }
            ],
        }
    )

    assert result.valid is True
    assert result.issues == []
    assert result.payload["candidate_events"][0]["counts_for_recurrence"] is True


def test_validate_layer2_payload_demotes_unbacked_recurrence_candidate():
    result = validate_layer2_payload(
        {
            "candidate_events": [
                {
                    "action": "strengthen",
                    "canonical_text": "Summary fluency is learning",
                    "kind": "heuristic",
                    "source_event_id": "cand-1",
                    "counts_for_recurrence": True,
                }
            ]
        }
    )

    assert result.valid is True
    assert result.payload["candidate_events"][0]["counts_for_recurrence"] is False
    assert result.issues[0].code == "unbacked_recurrence_demoted"


def test_validate_layer2_payload_rejects_promotions_on_candidate_only_path():
    result = validate_layer2_payload(
        {
            "promotions": [
                {
                    "canonical_text": "Promote me",
                    "target": "memory",
                    "content": "Promote me",
                }
            ]
        },
        allow_promotions=False,
    )

    assert result.valid is False
    assert result.issues[0].code == "promotions_not_allowed"

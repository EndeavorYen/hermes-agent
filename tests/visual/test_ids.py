from __future__ import annotations


def test_request_attempt_artifact_ids_have_stable_prefixes():
    from agent.visual.ids import new_artifact_id, new_attempt_id, new_request_id

    assert new_request_id().startswith("vrq_")
    assert new_attempt_id().startswith("vat_")
    assert new_artifact_id().startswith("var_")


def test_ids_are_unique():
    from agent.visual.ids import new_request_id

    assert len({new_request_id() for _ in range(100)}) == 100


def test_utc_now_iso_uses_z_suffix():
    from agent.visual.ids import utc_now_iso

    assert utc_now_iso().endswith("Z")

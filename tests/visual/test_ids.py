def test_visual_ids_have_expected_prefixes_and_unique_values():
    from agent.visual.ids import (
        new_artifact_id,
        new_attempt_id,
        new_delivery_id,
        new_feedback_id,
        new_judgment_id,
        new_ranking_id,
        new_request_id,
    )

    ids = {
        new_request_id(),
        new_attempt_id(),
        new_artifact_id(),
        new_judgment_id(),
        new_ranking_id(),
        new_delivery_id(),
        new_feedback_id(),
    }

    assert len(ids) == 7
    assert any(value.startswith("vrq_") for value in ids)
    assert any(value.startswith("vat_") for value in ids)
    assert any(value.startswith("var_") for value in ids)
    assert any(value.startswith("vjg_") for value in ids)
    assert any(value.startswith("vrk_") for value in ids)
    assert any(value.startswith("vdl_") for value in ids)
    assert any(value.startswith("vfb_") for value in ids)

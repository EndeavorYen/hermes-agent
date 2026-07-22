from agent.raphael.runtime_contract import (
    RaphaelTurnOrigin,
    resolve_raphael_turn_origin,
)


def test_background_write_origin_maps_to_background_review():
    assert (
        resolve_raphael_turn_origin(write_origin="background_review")
        is RaphaelTurnOrigin.BACKGROUND_REVIEW
    )


def test_internal_origins_are_explicit_and_foreground_is_default():
    assert (
        resolve_raphael_turn_origin(explicit_origin="cron")
        is RaphaelTurnOrigin.CRON
    )
    assert (
        resolve_raphael_turn_origin(explicit_origin="subagent")
        is RaphaelTurnOrigin.SUBAGENT
    )
    assert (
        resolve_raphael_turn_origin(explicit_origin="replay")
        is RaphaelTurnOrigin.REPLAY
    )
    assert (
        resolve_raphael_turn_origin(write_origin="assistant_tool")
        is RaphaelTurnOrigin.FOREGROUND
    )


def test_explicit_origin_overrides_write_origin():
    assert (
        resolve_raphael_turn_origin(
            explicit_origin=RaphaelTurnOrigin.REPLAY,
            write_origin="background_review",
        )
        is RaphaelTurnOrigin.REPLAY
    )

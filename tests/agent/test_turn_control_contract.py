from __future__ import annotations


def test_turn_origin_is_normalized_for_external_control_plugins() -> None:
    from agent.turn_control import resolve_turn_origin

    assert resolve_turn_origin(explicit_origin="foreground") == "foreground"
    assert resolve_turn_origin(explicit_origin="background_review") == "background"
    assert resolve_turn_origin(explicit_origin="replay") == "resume"
    assert resolve_turn_origin(write_origin="cron:nightly") == "scheduled"
    assert resolve_turn_origin(write_origin="subagent:visual") == "background"


def test_runtime_contract_is_host_generic() -> None:
    from agent.turn_control import resolve_runtime_contract

    contract = resolve_runtime_contract(
        {
            "visual_agent": {"provider": "planner-provider", "model": "planner-model"},
            "image_gen": {"provider": "image-provider", "model": "image-model"},
            "video_gen": {"provider": "video-provider", "model": "video-model"},
            "raphael": {
                "visual_planner": {
                    "provider": "legacy-provider",
                    "model": "legacy-model",
                }
            },
        },
        live_provider="base-provider",
        live_model="base-model",
        live_api_mode="responses",
    )

    assert contract == {
        "base_provider": "base-provider",
        "base_model": "base-model",
        "base_api_mode": "responses",
        "visual_planner_provider": "planner-provider",
        "visual_planner_model": "planner-model",
        "image_provider": "image-provider",
        "image_model": "image-model",
        "video_provider": "video-provider",
        "video_model": "video-model",
        "source": "live_agent",
    }

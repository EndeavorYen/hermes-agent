from agent.raphael.runtime_contract import resolve_raphael_runtime_contract


def test_live_agent_values_override_stale_config_model():
    contract = resolve_raphael_runtime_contract(
        {
            "model": {
                "default": "gpt-5.5",
                "provider": "openai-codex",
                "openai_runtime": "responses",
            },
            "image_gen": {
                "provider": "xai",
                "model": "grok-imagine-image-quality",
            },
            "video_gen": {
                "provider": "xai",
                "model": "grok-imagine-video",
            },
        },
        live_provider="openai-codex",
        live_model="gpt-5.6-terra",
        live_api_mode="codex_app_server",
    )

    assert contract.base_provider == "openai-codex"
    assert contract.base_model == "gpt-5.6-terra"
    assert contract.base_api_mode == "codex_app_server"
    assert contract.image_provider == "xai"
    assert contract.image_model == "grok-imagine-image-quality"
    assert contract.video_provider == "xai"
    assert contract.video_model == "grok-imagine-video"
    assert contract.source == "live_agent"


def test_config_contract_does_not_invent_versioned_visual_planner():
    contract = resolve_raphael_runtime_contract(
        {
            "model": {
                "default": "gpt-5.6-terra",
                "provider": "openai-codex",
            }
        }
    )

    assert contract.base_model == "gpt-5.6-terra"
    assert contract.visual_planner_provider is None
    assert contract.visual_planner_model is None
    assert contract.source == "effective_config"


def test_runtime_contract_round_trips_through_mapping():
    contract = resolve_raphael_runtime_contract(
        {"model": {"default": "model-a", "provider": "provider-a"}}
    )

    assert type(contract).from_mapping(contract.to_dict()) == contract

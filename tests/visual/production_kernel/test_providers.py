from agent.visual.production_kernel.providers import choose_visual_provider


def test_explicit_provider_always_wins():
    decision = choose_visual_provider(
        explicit_provider="openai-codex",
        default_provider="xai",
        authorized_providers=("xai", "openai-codex"),
        profiles={
            "xai": {"sample_count": 100, "first_pass_rate": 1.0},
            "openai-codex": {"sample_count": 10, "first_pass_rate": 0.2},
        },
    )

    assert decision.provider == "openai-codex"
    assert decision.reason == "explicit_override"


def test_sparse_profile_does_not_override_configured_default():
    decision = choose_visual_provider(
        explicit_provider=None,
        default_provider="xai",
        authorized_providers=("xai", "openai-codex"),
        profiles={
            "xai": {"sample_count": 20, "first_pass_rate": 0.7},
            "openai-codex": {"sample_count": 1, "first_pass_rate": 1.0},
        },
    )

    assert decision.provider == "xai"
    assert decision.reason == "configured_default"


def test_measured_profile_can_route_without_dual_provider_generation():
    decision = choose_visual_provider(
        explicit_provider=None,
        default_provider="xai",
        authorized_providers=("xai", "openai-codex"),
        profiles={
            "xai": {
                "sample_count": 20,
                "first_pass_rate": 0.55,
                "failure_rate": 0.1,
            },
            "openai-codex": {
                "sample_count": 12,
                "first_pass_rate": 0.9,
                "failure_rate": 0.05,
            },
        },
    )

    assert decision.provider == "openai-codex"
    assert decision.reason == "measured_quality_profile"
    assert decision.evidence["providers_evaluated"] == 2


def test_unavailable_default_uses_one_authorized_fallback():
    decision = choose_visual_provider(
        explicit_provider=None,
        default_provider="xai",
        authorized_providers=("xai", "openai-codex"),
        profiles={},
        unavailable_providers=("xai",),
    )

    assert decision.provider == "openai-codex"
    assert decision.reason == "provider_unavailable_fallback"


def test_explicit_unavailable_provider_is_not_silently_replaced():
    decision = choose_visual_provider(
        explicit_provider="xai",
        default_provider="openai-codex",
        authorized_providers=("xai", "openai-codex"),
        profiles={},
        unavailable_providers=("xai",),
    )

    assert decision.provider == "xai"
    assert decision.reason == "explicit_override_unavailable"
    assert decision.available is False

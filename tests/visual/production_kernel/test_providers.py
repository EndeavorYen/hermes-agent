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


def test_provider_profiles_use_first_candidate_quality_judgments(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.production_kernel.providers import build_provider_quality_profiles

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    for provider, passing_count in (("xai", 2), ("openai-codex", 5)):
        for index in range(5):
            request_id = ledger.record_request(
                status="completed",
                normalized_intent={"category": "product"},
            )
            attempt_id = ledger.record_attempt(
                request_id=request_id,
                candidate_index=0,
                provider=provider,
                model="image",
                status="completed",
            )
            artifact_id = ledger.record_artifact(
                request_id=request_id,
                attempt_id=attempt_id,
                kind="image",
                content_hash=f"{provider}:{index}",
                freshness_status="fresh",
            )
            passed = index < passing_count
            ledger.record_judgment(
                request_id=request_id,
                attempt_id=attempt_id,
                artifact_id=artifact_id,
                judge_name="visual_quality_judge",
                score=0.9 if passed else 0.3,
                verdict="pass" if passed else "fail",
            )

    profiles = build_provider_quality_profiles(ledger, category="product")
    decision = choose_visual_provider(
        explicit_provider=None,
        default_provider="xai",
        authorized_providers=("xai", "openai-codex"),
        profiles=profiles,
    )

    assert profiles["xai"]["sample_count"] == 5
    assert profiles["xai"]["first_pass_rate"] == 0.4
    assert profiles["openai-codex"]["first_pass_rate"] == 1.0
    assert decision.provider == "openai-codex"
    assert decision.reason == "measured_quality_profile"


def test_provider_profiles_do_not_count_confident_quality_failure_as_pass(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.production_kernel.providers import build_provider_quality_profiles

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        status="completed",
        normalized_intent={"category": "product"},
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="image",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="confident-failure",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.95,
        verdict="pass",
        details={"quality_issues": ["composition_bad"]},
    )

    profiles = build_provider_quality_profiles(ledger, category="product")

    assert profiles["xai"]["sample_count"] == 1
    assert profiles["xai"]["first_pass_rate"] == 0.0


def test_provider_profiles_are_scoped_by_request_category(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.production_kernel.providers import build_provider_quality_profiles

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    for category, provider, passed in (
        ("product", "openai-codex", True),
        ("product", "xai", False),
        ("portrait", "openai-codex", False),
        ("portrait", "xai", True),
    ):
        for index in range(5):
            request_id = ledger.record_request(
                status="completed",
                normalized_intent={"category": category},
            )
            attempt_id = ledger.record_attempt(
                request_id=request_id,
                candidate_index=0,
                provider=provider,
                model="image",
                status="completed",
            )
            artifact_id = ledger.record_artifact(
                request_id=request_id,
                attempt_id=attempt_id,
                kind="image",
                content_hash=f"{category}:{provider}:{index}",
                freshness_status="fresh",
            )
            ledger.record_judgment(
                request_id=request_id,
                attempt_id=attempt_id,
                artifact_id=artifact_id,
                judge_name="visual_quality_judge",
                score=0.9,
                verdict="pass" if passed else "fail",
                details={"quality_issues": [] if passed else ["composition_bad"]},
            )

    product = build_provider_quality_profiles(ledger, category="product")
    portrait = build_provider_quality_profiles(ledger, category="portrait")

    assert product["openai-codex"]["first_pass_rate"] == 1.0
    assert product["xai"]["first_pass_rate"] == 0.0
    assert portrait["openai-codex"]["first_pass_rate"] == 0.0
    assert portrait["xai"]["first_pass_rate"] == 1.0

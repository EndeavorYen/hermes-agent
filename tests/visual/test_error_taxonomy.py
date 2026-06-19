from __future__ import annotations


def test_normalizes_content_moderation():
    from agent.visual.error_taxonomy import normalize_visual_error_type

    assert normalize_visual_error_type("content_moderation") == "content_moderation"
    assert normalize_visual_error_type("policy_refusal") == "content_moderation"


def test_normalizes_timeout_and_auth():
    from agent.visual.error_taxonomy import normalize_visual_error_type

    assert normalize_visual_error_type("read_timeout") == "timeout"
    assert normalize_visual_error_type("auth_required") == "auth_required"


def test_unknown_provider_error_falls_back():
    from agent.visual.error_taxonomy import normalize_visual_error_type

    assert normalize_visual_error_type("SomeNewProviderThing") == "provider_error"


def test_success_passthrough():
    from agent.visual.error_taxonomy import normalize_visual_error_type

    assert normalize_visual_error_type(None, success=True) == "success"

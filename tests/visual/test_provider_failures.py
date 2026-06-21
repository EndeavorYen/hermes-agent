def test_classify_visual_provider_failure_detects_content_moderation_without_raw_body():
    from agent.visual.provider_failures import classify_visual_provider_failure

    result = classify_visual_provider_failure(
        {
            "success": False,
            "error_type": "content_moderation",
            "error": "full raw provider body with unsafe prompt details",
            "provider_response": {"private": "drop me"},
        }
    )

    assert result == {
        "failure_class": "content_moderation",
        "retryable": True,
        "safe_reframe_allowed": True,
        "provider_message_code": "content_moderation",
        "operator_summary": "provider rejected the request for content moderation",
    }


def test_classify_visual_provider_failure_detects_timeout_and_empty_response():
    from agent.visual.provider_failures import classify_visual_provider_failure

    timeout = classify_visual_provider_failure(TimeoutError("240s timeout"))
    empty = classify_visual_provider_failure({"success": False, "error": "empty_response"})

    assert timeout["failure_class"] == "timeout"
    assert timeout["retryable"] is True
    assert timeout["safe_reframe_allowed"] is False
    assert empty["failure_class"] == "empty_response"
    assert empty["retryable"] is True


def test_classify_visual_provider_failure_detects_reference_aspect_rate_and_unavailable():
    from agent.visual.provider_failures import classify_visual_provider_failure

    assert classify_visual_provider_failure({"error": "reference_images not supported"})["failure_class"] == (
        "unsupported_reference"
    )
    assert classify_visual_provider_failure({"error": "invalid aspect ratio 4:5"})["failure_class"] == (
        "unsupported_aspect_ratio"
    )
    assert classify_visual_provider_failure({"status_code": 429, "error": "rate limit"})["failure_class"] == (
        "rate_limited"
    )
    assert classify_visual_provider_failure({"status_code": 503, "error": "service unavailable"})["failure_class"] == (
        "provider_unavailable"
    )


def test_classify_visual_provider_failure_unknown_fails_closed():
    from agent.visual.provider_failures import classify_visual_provider_failure

    result = classify_visual_provider_failure({"success": False, "error": "weird provider thing"})

    assert result["failure_class"] == "unknown"
    assert result["retryable"] is False
    assert result["safe_reframe_allowed"] is False


def test_classify_visual_provider_failure_extracts_nested_provider_code():
    from agent.visual.provider_failures import classify_visual_provider_failure

    result = classify_visual_provider_failure(
        {
            "success": False,
            "provider": "xai",
            "error": {
                "code": "content_policy_violation",
                "message": "Request rejected by the safety system.",
            },
        }
    )

    assert result["failure_class"] == "content_moderation"
    assert result["provider_message_code"] == "content_policy_violation"


def test_classify_visual_provider_failure_allows_reference_fallback_negotiation():
    from agent.visual.provider_failures import classify_visual_provider_failure

    result = classify_visual_provider_failure(
        {"success": False, "error": "xAI Grok Imagine does not support reference_images conditioning"}
    )

    assert result["failure_class"] == "unsupported_reference"
    assert result["retryable"] is True

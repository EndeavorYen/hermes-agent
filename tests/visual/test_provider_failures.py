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


def test_classify_visual_provider_failure_detects_xai_content_moderation_text():
    from agent.visual.provider_failures import classify_visual_provider_failure

    result = classify_visual_provider_failure(
        {
            "success": False,
            "error_type": "api_error",
            "error": (
                'xAI image generation failed (400): {"code":"Client specified an invalid argument",'
                '"error":"Generated image rejected by content moderation."}'
            ),
        }
    )

    assert result["failure_class"] == "content_moderation"
    assert result["retryable"] is True
    assert result["safe_reframe_allowed"] is True


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


def test_classify_visual_provider_failure_detects_xai_connection_refused_503_text():
    from agent.visual.provider_failures import classify_visual_provider_failure

    result = classify_visual_provider_failure(
        {
            "success": False,
            "error_type": "api_error",
            "error": (
                "xAI image generation failed (503): upstream connect error or disconnect/reset "
                "before headers. retried and the latest reset reason: remote connection failure, "
                "transport failure reason: delayed connect error: Connection refused"
            ),
        }
    )

    assert result["failure_class"] == "provider_unavailable"
    assert result["retryable"] is True
    assert result["safe_reframe_allowed"] is False


def test_classify_visual_provider_failure_detects_dns_resolution_failure():
    from agent.visual.provider_failures import classify_visual_provider_failure

    result = classify_visual_provider_failure(
        {
            "success": False,
            "error_type": "connection_error",
            "error": (
                "xAI connection error: HTTPSConnectionPool(host='api.x.ai', port=443): "
                "Max retries exceeded with url: /v1/images/generations "
                "(Caused by NameResolutionError(\"HTTPSConnection(host='api.x.ai', port=443): "
                "Failed to resolve 'api.x.ai' ([Errno 8] nodename nor servname provided, or not known)\"))"
            ),
        }
    )

    assert result["failure_class"] == "provider_unavailable"
    assert result["retryable"] is True
    assert result["safe_reframe_allowed"] is False
    assert result["provider_message_code"] == "connection_error"


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

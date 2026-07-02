from agent.raphael.redaction import REDACTED_VALUE, redact_trace_payload


def test_redacts_secret_like_keys_recursively_without_mutating_input():
    payload = {
        "api_key": "sk-live-secret",
        "headers": {
            "Authorization": "Bearer secret",
            "cookie": "session=secret",
            "safe": "kept",
        },
        "nested": [
            {
                "refresh_token": "refresh-secret",
                "password": "hidden",
            }
        ],
    }

    redacted = redact_trace_payload(payload)

    assert redacted == {
        "api_key": REDACTED_VALUE,
        "headers": {
            "Authorization": REDACTED_VALUE,
            "cookie": REDACTED_VALUE,
            "safe": "kept",
        },
        "nested": [
            {
                "refresh_token": REDACTED_VALUE,
                "password": REDACTED_VALUE,
            }
        ],
    }
    assert payload["api_key"] == "sk-live-secret"
    assert payload["headers"]["Authorization"] == "Bearer secret"


def test_redacts_secret_key_fragments_case_insensitively():
    payload = {
        "clientSecret": "secret",
        "ApiKey": "secret",
        "plain_token": "secret",
        "safe": "value",
    }

    redacted = redact_trace_payload(payload)

    assert redacted["clientSecret"] == REDACTED_VALUE
    assert redacted["ApiKey"] == REDACTED_VALUE
    assert redacted["plain_token"] == REDACTED_VALUE
    assert redacted["safe"] == "value"


def test_truncates_long_strings_and_normalizes_tuples_to_lists():
    payload = {
        "message": "x" * 25,
        "items": ("short", "y" * 18),
    }

    redacted = redact_trace_payload(payload, max_string_length=10)

    assert redacted == {
        "message": "x" * 10 + "[truncated]",
        "items": ["short", "y" * 10 + "[truncated]"],
    }

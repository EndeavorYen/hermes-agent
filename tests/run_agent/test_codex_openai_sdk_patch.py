"""Regression tests for OpenAI Responses SDK compatibility patches."""


def test_openai_loader_patches_responses_parse_null_output():
    """Codex backend can emit response.completed with output=null."""
    import run_agent
    from openai._types import omit
    import openai.lib._parsing._responses as parsing_responses
    import openai.lib.streaming.responses._responses as streaming_responses

    class FakeResponse:
        output = None

        def to_dict(self):
            return {
                "id": "resp_fake",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "output": None,
            }

    run_agent._load_openai_cls()

    parsed = parsing_responses.parse_response(
        text_format=omit,
        input_tools=None,
        response=FakeResponse(),
    )
    parsed_from_streaming_ref = streaming_responses.parse_response(
        text_format=omit,
        input_tools=None,
        response=FakeResponse(),
    )

    assert parsed.output == []
    assert parsed_from_streaming_ref.output == []

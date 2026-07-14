"""Regression tests for bounded parallel image-generation tool batches."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import run_agent
from agent import tool_executor


def _tool_call(name: str, args: dict, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def test_image_generate_batch_routes_to_concurrent_executor():
    agent = SimpleNamespace()
    agent._execute_tool_calls = run_agent.AIAgent._execute_tool_calls.__get__(agent)
    agent._execute_tool_calls_concurrent = MagicMock()
    agent._execute_tool_calls_sequential = MagicMock()
    assistant_message = SimpleNamespace(tool_calls=[
        _tool_call("image_generate", {"prompt": "shot one"}, "img_1"),
        _tool_call("image_generate", {"prompt": "shot two"}, "img_2"),
    ])

    agent._execute_tool_calls(assistant_message, [], "story-video-batch")

    agent._execute_tool_calls_concurrent.assert_called_once()
    agent._execute_tool_calls_sequential.assert_not_called()


def test_story_video_image_parallel_worker_cap_defaults_to_three():
    runnable_calls = [
        (index, _tool_call("image_generate", {"prompt": str(index)}, f"img_{index}"), "image_generate", {})
        for index in range(5)
    ]

    with patch("hermes_cli.config.load_config", return_value={}):
        assert tool_executor._max_workers_for_tool_batch(runnable_calls) == 3


def test_image_parallel_worker_cap_can_be_configured_lower():
    runnable_calls = [
        (index, _tool_call("image_generate", {"prompt": str(index)}, f"img_{index}"), "image_generate", {})
        for index in range(3)
    ]

    with patch(
        "hermes_cli.config.load_config",
        return_value={"image_gen": {"max_parallel_requests": 2}},
    ):
        assert tool_executor._max_workers_for_tool_batch(runnable_calls) == 2

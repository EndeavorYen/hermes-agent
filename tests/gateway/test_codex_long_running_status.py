from types import SimpleNamespace

from gateway.run import _format_long_running_activity_detail


def test_codex_status_uses_real_activity_without_iteration_counter():
    agent = SimpleNamespace(
        api_mode="codex_app_server",
        get_activity_summary=lambda: {
            "api_call_count": 0,
            "max_iterations": 90,
            "current_tool": None,
            "last_activity_desc": (
                "Image progress: target 4, succeeded 1, "
                "failed attempts 2, remaining 3."
            ),
        },
    )

    assert _format_long_running_activity_detail(agent, True) == (
        " — Image progress: target 4, succeeded 1, "
        "failed attempts 2, remaining 3."
    )


def test_non_codex_status_keeps_iteration_counter():
    agent = SimpleNamespace(
        api_mode="chat_completions",
        get_activity_summary=lambda: {
            "api_call_count": 2,
            "max_iterations": 90,
            "current_tool": "web_search",
            "last_activity_desc": "executing tool: web_search",
        },
    )

    assert _format_long_running_activity_detail(agent, True) == (
        " — iteration 2/90, web_search"
    )

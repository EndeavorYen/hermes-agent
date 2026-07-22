from __future__ import annotations


def test_visual_runtime_environment_requires_openai_for_live_e2e():
    from agent.visual.runtime_environment import build_visual_runtime_environment_diagnostic

    def missing_openai(name: str):
        if name == "openai":
            return None
        return object()

    diagnostic = build_visual_runtime_environment_diagnostic(
        include_live=True,
        include_live_slack_upload=False,
        find_spec=missing_openai,
    )

    assert diagnostic["success"] is False
    assert diagnostic["missing_modules"] == ["openai"]
    assert diagnostic["required_modules"] == ["openai"]
    assert diagnostic["next_actions"] == [
        {
            "type": "configure_visual_runtime_dependencies",
            "track": "operator_setup",
            "reason": "visual_runtime_missing_python_modules",
            "requires_human_feedback": False,
            "requires_operator_setup": True,
            "activation_status": "operator_setup",
            "source": "visual_runtime_environment",
            "missing_modules": ["openai"],
            "operator_setup_actions": [
                {
                    "provider": "python_runtime",
                    "missing_env_vars": [],
                    "post_setup": (
                        "Run live visual validation through the project environment: "
                        "rtk uv run --extra dev --extra slack python3 <script>, or sync the Hermes venv."
                    ),
                }
            ],
        }
    ]


def test_visual_runtime_environment_requires_slack_modules_for_live_upload():
    from agent.visual.runtime_environment import build_visual_runtime_environment_diagnostic

    def missing_slack_modules(name: str):
        if name in {"aiohttp", "slack_sdk"}:
            return None
        return object()

    diagnostic = build_visual_runtime_environment_diagnostic(
        include_live=True,
        include_live_slack_upload=True,
        find_spec=missing_slack_modules,
    )

    assert diagnostic["success"] is False
    assert diagnostic["missing_modules"] == ["aiohttp", "slack_sdk"]
    assert diagnostic["required_modules"] == ["aiohttp", "openai", "slack_sdk"]

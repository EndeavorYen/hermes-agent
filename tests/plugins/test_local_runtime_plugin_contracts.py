"""Compatibility tests for Simon's machine-local runtime plugin contracts."""

from __future__ import annotations

from pathlib import Path

import yaml

from hermes_cli.plugins import PluginManager


def _write_plugin(
    hermes_home: Path,
    name: str,
    register_body: str,
    *,
    manifest_extra: dict | None = None,
) -> Path:
    plugin_dir = hermes_home / "plugins" / name
    plugin_dir.mkdir(parents=True)

    manifest = {
        "name": name,
        "version": "0.1.0",
        "description": f"Local runtime plugin {name}",
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    (plugin_dir / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (plugin_dir / "__init__.py").write_text(
        f"from pathlib import Path\n\n{register_body}\n",
        encoding="utf-8",
    )
    return plugin_dir


def test_machine_local_plugins_load_as_external_runtime_surface(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {
                    "enabled": [
                        "rtk-rewrite",
                        "image-reference-library",
                        "visual-arsenal",
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    _write_plugin(
        hermes_home,
        "rtk-rewrite",
        """
def _rewrite(tool_name=None, args=None, **_kwargs):
    if tool_name == "terminal" and isinstance(args, dict):
        args["command"] = "rtk " + args["command"]


def register(ctx):
    ctx.register_hook("pre_tool_call", _rewrite)
""",
        manifest_extra={"provides_hooks": ["pre_tool_call"]},
    )

    image_ref_dir = _write_plugin(
        hermes_home,
        "image-reference-library",
        """
def register(ctx):
    ctx.register_tool(
        name="image_ref_search",
        toolset="image_gen",
        schema={
            "name": "image_ref_search",
            "description": "Search local reference assets",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: "[]",
    )
    ctx.register_skill(
        "image-reference-workflow",
        Path(__file__).parent / "skills" / "image-reference-workflow" / "SKILL.md",
        description="Use local reusable image references",
    )
""",
        manifest_extra={
            "provides_tools": ["image_ref_search"],
            "provides_skills": ["image-reference-workflow"],
        },
    )
    skill_dir = image_ref_dir / "skills" / "image-reference-workflow"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: image-reference-workflow\n---\nUse image references.\n",
        encoding="utf-8",
    )

    _write_plugin(
        hermes_home,
        "visual-arsenal",
        """
def _slack_context(**_kwargs):
    return {"context": "visual arsenal slack context"}


def _attachment_context(**_kwargs):
    return {"action": "allow"}


def register(ctx):
    ctx.register_tool(
        name="visual_arsenal_search",
        toolset="image_gen",
        schema={
            "name": "visual_arsenal_search",
            "description": "Search visual arsenal references",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: "[]",
    )
    ctx.register_tool(
        name="visual_arsenal_generate",
        toolset="image_gen",
        schema={
            "name": "visual_arsenal_generate",
            "description": "Generate from visual arsenal references",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: "{}",
    )
    ctx.register_hook("pre_llm_call", _slack_context)
    ctx.register_hook("pre_gateway_dispatch", _attachment_context)
""",
        manifest_extra={
            "provides_tools": ["visual_arsenal_search", "visual_arsenal_generate"],
            "provides_hooks": ["pre_llm_call", "pre_gateway_dispatch"],
        },
    )

    manager = PluginManager()
    manager.discover_and_load()

    assert manager._plugins["rtk-rewrite"].enabled is True
    assert manager._plugins["image-reference-library"].enabled is True
    assert manager._plugins["visual-arsenal"].enabled is True

    args = {"command": "pwd"}
    manager.invoke_hook("pre_tool_call", tool_name="terminal", args=args)
    assert args == {"command": "rtk pwd"}

    assert manager.list_plugin_skills("image-reference-library") == [
        "image-reference-workflow"
    ]
    assert manager.find_plugin_skill(
        "image-reference-library:image-reference-workflow"
    ) == skill_dir / "SKILL.md"

    assert set(manager._plugins["visual-arsenal"].hooks_registered) == {
        "pre_llm_call",
        "pre_gateway_dispatch",
    }
    assert manager.invoke_hook("pre_llm_call", user_message="image please") == [
        {"context": "visual arsenal slack context"}
    ]
    assert manager.invoke_hook("pre_gateway_dispatch", event=object()) == [
        {"action": "allow"}
    ]

    from tools.registry import registry

    try:
        assert "image_ref_search" in registry._tools
        assert "visual_arsenal_search" in registry._tools
        assert "visual_arsenal_generate" in registry._tools
    finally:
        registry.deregister("image_ref_search")
        registry.deregister("visual_arsenal_search")
        registry.deregister("visual_arsenal_generate")

from __future__ import annotations

import json

import pytest

from plugins.toonflow_control import schemas


def test_dedicated_mcp_server_exposes_only_toonflow_control_tools(monkeypatch):
    from plugins.toonflow_control import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_dispatch",
        lambda name, _args: json.dumps({"success": True, "tool": name}),
    )

    server = mcp_server._build_server()
    exposed = set(server._tool_manager._tools)

    assert exposed == {schema["name"] for schema in schemas.TOOL_SCHEMAS}


@pytest.mark.asyncio
async def test_dedicated_mcp_server_uses_authoritative_schema_and_dispatch(
    monkeypatch,
):
    from plugins.toonflow_control import mcp_server

    calls: list[tuple[str, dict]] = []

    def fake_dispatch(name: str, args: dict) -> str:
        calls.append((name, args))
        return json.dumps({"success": True, "toonflow": {"contract_version": "1.0"}})

    monkeypatch.setattr(mcp_server, "_dispatch", fake_dispatch)
    server = mcp_server._build_server()
    tool = server._tool_manager.get_tool("toonflow_capabilities")

    assert tool is not None
    assert tool.parameters == schemas.TOONFLOW_CAPABILITIES_SCHEMA["parameters"]
    result = await tool.run({})

    assert calls == [("toonflow_capabilities", {})]
    assert '"success": true' in str(result)

"""Dedicated MCP bridge for Toonflow Control Contract 1.0.

Codex app-server owns its tool loop, so Hermes-native plugin tools are not
automatically visible inside a Codex subscription turn. This narrow MCP server
keeps the bridge plugin-owned: it exposes only the six Toonflow control tools
and dispatches directly to the same handlers used by Hermes.
"""

from __future__ import annotations

import inspect
import json
import logging
import sys
from typing import Any, Optional

from . import _TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

_JSON_TO_PY = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}
_HANDLERS = {name: handler for name, _schema, handler in _TOOL_DEFINITIONS}


def _signature_from_schema(
    schema: dict[str, Any],
) -> tuple[inspect.Signature, dict[str, Any]]:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    parameters: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    for name, specification in properties.items():
        python_type = _JSON_TO_PY.get(
            (specification or {}).get("type"),
            Any,
        )
        annotation: Any = python_type if name in required else Optional[python_type]
        annotations[name] = annotation
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=(inspect.Parameter.empty if name in required else None),
            )
        )
    return (
        inspect.Signature(parameters, return_annotation=str),
        annotations,
    )


def _dispatch(name: str, args: dict[str, Any]) -> str:
    handler = _HANDLERS[name]
    return json.dumps(handler(args), ensure_ascii=False)


def _build_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.server.fastmcp.utilities.func_metadata import (
            ArgModelBase,
        )
        from pydantic import ConfigDict
    except ImportError as exc:  # pragma: no cover - install-time failure
        raise ImportError(
            f"toonflow-control MCP server requires the 'mcp' package: {exc}"
        ) from exc

    server = FastMCP(
        "toonflow-control",
        instructions=(
            "Use only Toonflow Control Contract 1.0 for project creation, "
            "story-film execution, run status, cancellation, and selection."
        ),
    )

    class AuthoritativeArguments(ArgModelBase):
        model_config = ConfigDict(
            arbitrary_types_allowed=True,
            extra="allow",
        )

        def model_dump_one_level(self) -> dict[str, Any]:
            values = super().model_dump_one_level()
            values.update(self.model_extra or {})
            return values

    for name, schema, _handler in _TOOL_DEFINITIONS:
        parameters_schema = schema["parameters"]
        signature, annotations = _signature_from_schema(parameters_schema)

        def make_handler(
            tool_name: str,
            description: str,
            tool_signature: inspect.Signature,
            tool_annotations: dict[str, Any],
        ):
            def dispatch(**kwargs: Any) -> str:
                return _dispatch(tool_name, kwargs)

            dispatch.__name__ = tool_name
            dispatch.__doc__ = description
            dispatch.__signature__ = tool_signature
            dispatch.__annotations__ = {
                **tool_annotations,
                "return": str,
            }
            return dispatch

        handler = make_handler(
            name,
            schema["description"],
            signature,
            annotations,
        )
        try:
            server.add_tool(
                handler,
                name=name,
                description=schema["description"],
            )
        except TypeError:
            server.tool(
                name=name,
                description=schema["description"],
            )(handler)

        tool = server._tool_manager.get_tool(name)
        if tool is None:
            raise RuntimeError(f"FastMCP did not register tool {name!r}")
        tool.parameters = json.loads(json.dumps(parameters_schema))
        tool.fn_metadata.arg_model = AuthoritativeArguments

    return server


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
    )
    try:
        server = _build_server()
    except ImportError as exc:
        sys.stderr.write(f"toonflow-control MCP server cannot start: {exc}\n")
        return 2
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

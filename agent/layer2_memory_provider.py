"""Built-in Layer-2 memory provider.

This keeps runtime Layer-2 recall and chat L2 writes behind the same
MemoryManager lifecycle as external memory providers, while preserving the
existing shared store/tool implementations.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.layer2_recall import prefetch_layer2_context
from agent.memory_provider import MemoryProvider
from tools.layer2_memory_tool import LAYER2_MEMORY_SCHEMA, layer2_memory_tool


class Layer2MemoryProvider(MemoryProvider):
    """Built-in local provider for Layer-2 recall and candidate writes."""

    def __init__(
        self,
        *,
        explicit_pack_names: list[str] | None = None,
        auto_select_context_packs: bool = False,
    ) -> None:
        self._session_id = ""
        self._explicit_pack_names = list(explicit_pack_names or [])
        self._auto_select_context_packs = bool(auto_select_context_packs)

    @property
    def name(self) -> str:
        return "layer2"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id or ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        return prefetch_layer2_context(
            query_text=query if isinstance(query, str) else "",
            explicit_pack_names=self._explicit_pack_names,
            auto_select_context_packs=self._auto_select_context_packs,
        ) or ""

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [LAYER2_MEMORY_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name != "layer2_memory":
            raise NotImplementedError(f"Layer2MemoryProvider does not handle {tool_name}")
        session_id = str(kwargs.get("session_id") or self._session_id or "").strip()
        tool_call_id = str(kwargs.get("tool_call_id") or "").strip()
        source_ref = f"chat:layer2:{session_id or 'unknown'}:{tool_call_id or 'call'}"
        return layer2_memory_tool(
            action=args.get("action", ""),
            payload=args.get("payload"),
            source_ref=source_ref,
            session_id=session_id or None,
            tool_call_id=tool_call_id or None,
        )

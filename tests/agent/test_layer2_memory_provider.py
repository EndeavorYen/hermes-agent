import json
from unittest.mock import MagicMock, patch

from agent.memory_manager import MemoryManager


def test_memory_manager_accepts_layer2_provider_and_one_external_provider():
    from agent.layer2_memory_provider import Layer2MemoryProvider

    manager = MemoryManager()
    layer2 = Layer2MemoryProvider()
    external = MagicMock()
    external.name = "external-memory"
    external.get_tool_schemas.return_value = []

    manager.add_provider(layer2)
    manager.add_provider(external)

    assert [provider.name for provider in manager.providers] == ["layer2", "external-memory"]


def test_layer2_provider_prefetch_delegates_to_runtime_recall():
    from agent.layer2_memory_provider import Layer2MemoryProvider

    provider = Layer2MemoryProvider(
        explicit_pack_names=["repo-digest"],
        auto_select_context_packs=False,
    )

    with patch(
        "agent.layer2_memory_provider.prefetch_layer2_context",
        return_value="- [prior/environment] Repository uses uv. (support=2)",
    ) as mock_prefetch:
        result = provider.prefetch("how do tests run?", session_id="session-1")

    assert result == "- [prior/environment] Repository uses uv. (support=2)"
    mock_prefetch.assert_called_once_with(
        query_text="how do tests run?",
        explicit_pack_names=["repo-digest"],
        auto_select_context_packs=False,
    )


def test_layer2_provider_handles_write_tool_with_session_source_ref():
    from agent.layer2_memory_provider import Layer2MemoryProvider

    provider = Layer2MemoryProvider()

    with patch(
        "agent.layer2_memory_provider.layer2_memory_tool",
        return_value='{"success": true}',
    ) as mock_tool:
        result = provider.handle_tool_call(
            "layer2_memory",
            {"action": "write", "payload": {"candidate_events": [{"canonical_text": "x"}]}},
            session_id="session-1",
            tool_call_id="call-1",
        )

    assert json.loads(result) == {"success": True}
    mock_tool.assert_called_once_with(
        action="write",
        payload={"candidate_events": [{"canonical_text": "x"}]},
        source_ref="chat:layer2:session-1:call-1",
        session_id="session-1",
        tool_call_id="call-1",
    )

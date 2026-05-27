"""Codex Responses runtime helpers.

The consumer Codex backend can drift ahead of the OpenAI SDK's typed
``responses.stream()`` state machine.  Keep Hermes on the raw
``responses.create(stream=True)`` event stream and assemble the response from
events that are stable for our downstream code.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Any, List

logger = logging.getLogger(__name__)


_TERMINAL_EVENT_TYPES = frozenset({
    "response.completed",
    "response.incomplete",
    "response.failed",
})


def _event_field(event: Any, name: str, default: Any = None) -> Any:
    """Read event fields from SDK objects or raw dict payloads."""
    value = getattr(event, name, None)
    if value is None and isinstance(event, dict):
        value = event.get(name, default)
    return value if value is not None else default


def _raise_stream_error(event: Any) -> None:
    """Raise Hermes' structured stream error from a wire ``type=error`` frame."""
    from run_agent import _StreamErrorEvent

    message = (_event_field(event, "message", "") or "stream emitted error event").strip()
    raise _StreamErrorEvent(
        message,
        code=_event_field(event, "code"),
        param=_event_field(event, "param"),
    )


def _consume_codex_event_stream(
    event_iter: Any,
    *,
    model: str,
    on_text_delta=None,
    on_reasoning_delta=None,
    on_first_delta=None,
    on_event=None,
    interrupt_check=None,
) -> SimpleNamespace:
    """Consume a Codex Responses SSE stream and return a Responses-like object.

    Content is reconstructed from ``response.output_item.done`` and streamed
    text deltas.  The terminal event is used only for metadata such as usage and
    status, so ``response.completed.response.output = null`` cannot trip the SDK
    parser or erase already streamed content.
    """
    collected_output_items: List[Any] = []
    collected_text_deltas: List[str] = []
    has_tool_calls = False
    first_delta_fired = False
    terminal_status = "completed"
    terminal_usage = None
    terminal_response_id = None
    terminal_incomplete_details = None
    terminal_error = None
    saw_terminal = False

    for event in event_iter:
        if on_event is not None:
            try:
                on_event(event)
            except (TimeoutError, InterruptedError):
                raise
            except Exception:
                logger.debug("Codex stream on_event hook raised", exc_info=True)
        if interrupt_check is not None and interrupt_check():
            break

        event_type = _event_field(event, "type", "")
        if not isinstance(event_type, str):
            event_type = ""

        if event_type == "error":
            _raise_stream_error(event)

        if "output_text.delta" in event_type or event_type == "response.output_text.delta":
            delta_text = _event_field(event, "delta", "")
            if delta_text:
                collected_text_deltas.append(delta_text)
                if not has_tool_calls:
                    if not first_delta_fired:
                        first_delta_fired = True
                        if on_first_delta is not None:
                            try:
                                on_first_delta()
                            except Exception:
                                logger.debug("Codex stream on_first_delta raised", exc_info=True)
                    if on_text_delta is not None:
                        try:
                            on_text_delta(delta_text)
                        except Exception:
                            logger.debug("Codex stream on_text_delta raised", exc_info=True)
            continue

        if "function_call" in event_type:
            has_tool_calls = True

        if "reasoning" in event_type and "delta" in event_type:
            reasoning_text = _event_field(event, "delta", "")
            if reasoning_text and on_reasoning_delta is not None:
                try:
                    on_reasoning_delta(reasoning_text)
                except Exception:
                    logger.debug("Codex stream on_reasoning_delta raised", exc_info=True)
            continue

        if event_type == "response.output_item.done":
            done_item = _event_field(event, "item")
            if done_item is not None:
                collected_output_items.append(done_item)
            continue

        if event_type in _TERMINAL_EVENT_TYPES:
            saw_terminal = True
            resp_obj = _event_field(event, "response")
            if resp_obj is not None:
                terminal_usage = getattr(resp_obj, "usage", None)
                if terminal_usage is None and isinstance(resp_obj, dict):
                    terminal_usage = resp_obj.get("usage")
                terminal_response_id = getattr(resp_obj, "id", None)
                if terminal_response_id is None and isinstance(resp_obj, dict):
                    terminal_response_id = resp_obj.get("id")
                resp_status = getattr(resp_obj, "status", None)
                if resp_status is None and isinstance(resp_obj, dict):
                    resp_status = resp_obj.get("status")
                if isinstance(resp_status, str):
                    terminal_status = resp_status
                if event_type == "response.incomplete":
                    terminal_incomplete_details = getattr(resp_obj, "incomplete_details", None)
                    if terminal_incomplete_details is None and isinstance(resp_obj, dict):
                        terminal_incomplete_details = resp_obj.get("incomplete_details")
                if event_type == "response.failed":
                    terminal_error = getattr(resp_obj, "error", None)
                    if terminal_error is None and isinstance(resp_obj, dict):
                        terminal_error = resp_obj.get("error")
            if event_type == "response.incomplete" and terminal_status == "completed":
                terminal_status = "incomplete"
            elif event_type == "response.failed" and terminal_status == "completed":
                terminal_status = "failed"
            break

    if collected_output_items:
        output = list(collected_output_items)
    elif collected_text_deltas and not has_tool_calls:
        output = [
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        text="".join(collected_text_deltas),
                    )
                ],
            )
        ]
    else:
        output = []

    if not saw_terminal and not output:
        raise RuntimeError("Codex Responses stream did not emit a terminal response")

    return SimpleNamespace(
        output=output,
        output_text="".join(collected_text_deltas),
        usage=terminal_usage,
        status=terminal_status,
        id=terminal_response_id,
        model=model,
        incomplete_details=terminal_incomplete_details,
        error=terminal_error,
    )


def run_codex_stream(agent, api_kwargs: dict, client: Any = None, on_first_delta=None):
    """Execute one Codex Responses streaming request via raw event iteration."""
    import httpx as _httpx

    active_client = client or agent._ensure_primary_openai_client(reason="codex_stream_direct")
    max_stream_retries = 1
    agent._codex_streamed_text_parts = []

    def _on_text_delta(text: str) -> None:
        agent._codex_streamed_text_parts.append(text)
        agent._fire_stream_delta(text)

    def _on_reasoning_delta(text: str) -> None:
        agent._fire_reasoning_delta(text)

    def _on_event(event: Any) -> None:
        agent._codex_stream_last_event_ts = time.time()
        agent._touch_activity("receiving stream response")

    def _interrupt_check() -> bool:
        return bool(agent._interrupt_requested)

    for attempt in range(max_stream_retries + 1):
        if agent._interrupt_requested:
            raise InterruptedError("Agent interrupted before Codex stream retry")

        stream_kwargs = dict(api_kwargs)
        stream_kwargs["stream"] = True

        try:
            event_stream = active_client.responses.create(**stream_kwargs)
        except (_httpx.RemoteProtocolError, _httpx.ReadTimeout, _httpx.ConnectError, ConnectionError) as exc:
            if attempt < max_stream_retries:
                logger.debug(
                    "Codex Responses stream connect failed (attempt %s/%s); retrying. %s error=%s",
                    attempt + 1,
                    max_stream_retries + 1,
                    agent._client_log_context(),
                    exc,
                )
                continue
            raise

        try:
            if hasattr(event_stream, "output") and not hasattr(event_stream, "__iter__"):
                return event_stream
            try:
                final = _consume_codex_event_stream(
                    event_stream,
                    model=api_kwargs.get("model"),
                    on_text_delta=_on_text_delta,
                    on_reasoning_delta=_on_reasoning_delta,
                    on_first_delta=on_first_delta,
                    on_event=_on_event,
                    interrupt_check=_interrupt_check,
                )
            except (_httpx.RemoteProtocolError, _httpx.ReadTimeout, _httpx.ConnectError, ConnectionError) as exc:
                if attempt < max_stream_retries:
                    logger.debug(
                        "Codex Responses stream transport failed mid-iteration "
                        "(attempt %s/%s); retrying. %s error=%s",
                        attempt + 1,
                        max_stream_retries + 1,
                        agent._client_log_context(),
                        exc,
                    )
                    continue
                raise
            except RuntimeError as exc:
                if "did not emit a terminal response" in str(exc) and attempt < max_stream_retries:
                    logger.debug(
                        "Codex Responses stream ended without a terminal event "
                        "(attempt %s/%s); retrying. %s",
                        attempt + 1,
                        max_stream_retries + 1,
                        agent._client_log_context(),
                    )
                    continue
                raise

            if final.status in {"incomplete", "failed"}:
                logger.warning(
                    "Codex Responses stream terminal status=%s "
                    "(incomplete_details=%s, error=%s, streamed_chars=%d). %s",
                    final.status,
                    final.incomplete_details,
                    final.error,
                    sum(len(p) for p in agent._codex_streamed_text_parts),
                    agent._client_log_context(),
                )
            return final
        finally:
            close_fn = getattr(event_stream, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass


def run_codex_create_stream_fallback(agent, api_kwargs: dict, client: Any = None):
    """Backward-compatible name for the unified event-stream path."""
    return run_codex_stream(agent, api_kwargs, client=client)


__all__ = [
    "_consume_codex_event_stream",
    "run_codex_stream",
    "run_codex_create_stream_fallback",
]

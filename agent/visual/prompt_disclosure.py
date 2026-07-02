from __future__ import annotations

from typing import Any

from agent.visual.agent_mode.handoff import is_visual_prompt_disclosure_request
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.prompt_text import strip_visual_prompt_metadata
from agent.visual.tracking import default_visual_ledger_path
from gateway.session_context import get_session_env


def build_visual_prompt_disclosure_response(
    user_message: Any,
    original_user_message: Any = None,
) -> str | None:
    prompt = _extract_text(original_user_message)
    if not prompt:
        prompt = _extract_text(user_message)
    if not is_visual_prompt_disclosure_request(prompt):
        return None

    context = _latest_visual_prompt_context()
    if not context:
        return (
            "我目前找不到上一輪可追溯的 visual prompt 紀錄，所以不能準確提供。"
            "我不會重產圖，也不會編一個假的 prompt。"
        )
    return _format_prompt_context(context)


def _latest_visual_prompt_context() -> dict[str, Any] | None:
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    platform = get_session_env("HERMES_SESSION_PLATFORM", "").strip()
    chat_id = get_session_env("HERMES_SESSION_CHAT_ID", "").strip()
    thread_id = get_session_env("HERMES_SESSION_THREAD_ID", "").strip()

    if platform and chat_id and thread_id:
        return ledger.latest_delivered_prompt_context(
            platform=platform,
            destination_id=chat_id,
            thread_id=thread_id,
        )
    if platform and chat_id:
        context = ledger.latest_delivered_prompt_context(
            platform=platform,
            destination_id=chat_id,
        )
        if context:
            return context
    if platform:
        context = ledger.latest_delivered_prompt_context(platform=platform)
        if context:
            return context
    if not platform and not chat_id:
        return ledger.latest_delivered_prompt_context()
    return None


def _format_prompt_context(context: dict[str, Any]) -> str:
    user_prompt = _clean_text(context.get("user_prompt"))
    prompt_original = _clean_text(context.get("prompt_original"))
    prompt_mediated = _clean_text(context.get("prompt_mediated"))
    provider = _clean_text(context.get("provider"))
    model = _clean_text(context.get("model"))

    prompt_to_show = prompt_mediated or prompt_original or user_prompt
    if not prompt_to_show:
        return (
            "我找到上一輪 visual 交付紀錄，但裡面沒有保存可還原的 prompt。"
            "我不會重產圖，也不會編一個假的 prompt。"
        )

    parts = ["上一輪可追溯的 visual prompt 如下："]
    if provider or model:
        provider_label = provider or "unknown-provider"
        model_label = model or "unknown-model"
        parts.append(f"Provider / model: `{provider_label}` / `{model_label}`")
    if user_prompt and user_prompt not in {prompt_original, prompt_mediated}:
        parts.append("原始使用者需求：\n```text\n" + user_prompt + "\n```")
    if prompt_original and prompt_original != prompt_to_show:
        parts.append("Visual agent 原始 prompt：\n```text\n" + prompt_original + "\n```")
    parts.append("實際送進 image/video provider 的 prompt：\n```text\n" + prompt_to_show + "\n```")
    return "\n\n".join(parts)


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "prompt"):
            text = _extract_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple)):
        chunks = [_extract_text(item) for item in value]
        return "\n".join(chunk for chunk in chunks if chunk).strip()
    return str(value).strip()


def _clean_text(value: Any) -> str:
    return strip_visual_prompt_metadata(value)

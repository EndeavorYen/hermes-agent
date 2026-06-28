from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
from typing import Any

from agent.visual.agent_mode.planner import plan_visual_agent_request
from agent.visual.session_references import prompt_requests_visual_reference_reuse
from gateway.session_context import get_visual_reference_context_entries
from hermes_constants import get_hermes_home


_FALSE_ENV_VALUES = {"0", "false", "no", "off"}
_DATA_IMAGE_URI_RE = re.compile(
    r"^data:image/(?P<extension>[a-zA-Z0-9.+-]+)(?:;[^,]*)*;base64,(?P<payload>.*)$",
    re.DOTALL,
)
_DATA_URI_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
_IMAGE_EXTENSION_ALIASES = {
    "jpg": "jpg",
    "jpeg": "jpg",
    "png": "png",
    "webp": "webp",
    "gif": "gif",
}
logger = logging.getLogger(__name__)


def build_direct_visual_agent_handoff(
    agent: Any,
    user_message: Any,
    original_user_message: Any = None,
) -> dict[str, Any] | None:
    """Return a direct pre-LLM visual-agent handoff plan when it is safe.

    The base LLM may be stricter than the desired visual-agent planning model.
    For clear generation requests, route before the base provider sees the full
    creative prompt so visual mode can own the request.
    """
    if _disabled_by_env():
        return None
    valid_tool_names = set(getattr(agent, "valid_tool_names", None) or ())
    if "visual_agent_generate" not in valid_tool_names:
        return None

    source = original_user_message if original_user_message is not None else user_message
    prompt = _extract_text(source) or _extract_text(user_message)
    attachments = _extract_attachments(source) or _extract_attachments(user_message)
    if is_visual_prompt_disclosure_request(prompt):
        return None
    session_reference_entries: list[dict[str, Any]] = []
    if not attachments and _is_visual_followup_edit_request(prompt):
        session_reference_entries = _session_visual_reference_entries()
        attachments = [str(entry["uri"]) for entry in session_reference_entries]
    if not prompt or not (
        _is_explicit_visual_generation_request(prompt)
        or bool(session_reference_entries)
    ):
        return None

    plan = plan_visual_agent_request(prompt, attachments=attachments)
    if not plan.get("should_use_visual_package"):
        return None

    arguments = dict(plan.get("arguments") or {})
    arguments.setdefault("prompt", prompt)
    if attachments and not arguments.get("attachments"):
        arguments["attachments"] = attachments
    if session_reference_entries:
        arguments["attachments"] = attachments
        arguments["include_image"] = True
        arguments["include_video"] = False
        arguments.setdefault("candidate_budget", 2)
        arguments.setdefault("candidate_budget_source", "planner_default")
        arguments["reference_binding"] = _session_reference_binding(session_reference_entries)
        arguments["prompt"] = _prompt_with_session_edit_context(prompt, session_reference_entries)
    contract = dict(plan.get("provider_contract") or {})
    if contract.get("visual_agent_llm_provider"):
        arguments["visual_agent_llm_provider"] = contract.get("visual_agent_llm_provider")
    if contract.get("visual_agent_llm_model"):
        arguments["visual_agent_llm_model"] = contract.get("visual_agent_llm_model")
    arguments["visual_agent_handoff_mode"] = "pre_llm_direct"

    return {
        "mode": "pre_llm_direct",
        "tool_name": "visual_agent_generate",
        "arguments": arguments,
        "plan": plan,
        "base_llm_provider_bypassed": str(getattr(agent, "provider", "") or ""),
        "base_llm_model_bypassed": str(getattr(agent, "model", "") or ""),
        "visual_agent_llm_provider": contract.get("visual_agent_llm_provider"),
        "visual_agent_llm_model": contract.get("visual_agent_llm_model"),
    }


def _is_visual_followup_edit_request(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    if _looks_like_visual_status_message(lowered, compact) or is_visual_prompt_disclosure_request(text):
        return False
    edit_markers = (
        "modify",
        "edit",
        "revise",
        "change",
        "improve",
        "fix",
        "adjust",
        "replace",
        "make it",
        "修改",
        "調整",
        "改進",
        "改善",
        "修正",
        "修一下",
        "補上",
        "改成",
        "換成",
        "不要",
        "不應該",
        "而不是",
    )
    return prompt_requests_visual_reference_reuse(text) and any(marker in lowered for marker in edit_markers)


def is_visual_prompt_disclosure_request(prompt: str) -> bool:
    """Return True when the user is asking about the prompt, not asking to render media."""
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    has_prompt_term = "prompt" in text or "提示詞" in text or "提示词" in text
    if not has_prompt_term:
        return False

    direct_patterns = (
        "what prompt",
        "which prompt",
        "show me the prompt",
        "tell me the prompt",
        "give me the prompt",
        "share the prompt",
        "prompt you used",
        "used prompt",
        "actual prompt",
        "final prompt",
    )
    if any(pattern in text for pattern in direct_patterns):
        return True

    compact_patterns = (
        "給我剛剛產圖用的prompt",
        "给我刚刚产图用的prompt",
        "剛剛產圖用的prompt",
        "刚刚产图用的prompt",
        "產圖用的prompt給我",
        "产图用的prompt给我",
        "你用的prompt",
        "你使用的prompt",
        "使用的prompt",
        "用的prompt",
        "用了什麼prompt",
        "用了什么prompt",
        "prompt是什麼",
        "prompt是什么",
        "給我prompt",
        "给我prompt",
        "貼出prompt",
        "贴出prompt",
        "列出prompt",
        "顯示prompt",
        "显示prompt",
        "你用的提示詞",
        "你用的提示词",
        "使用的提示詞",
        "使用的提示词",
        "用的提示詞",
        "用的提示词",
        "用了什麼提示詞",
        "用了什么提示词",
        "提示詞是什麼",
        "提示词是什么",
        "給我提示詞",
        "给我提示词",
        "列出提示詞",
        "列出提示词",
    )
    if any(pattern in compact for pattern in compact_patterns):
        return True

    asks_to_reveal = any(
        marker in compact
        for marker in (
            "給我",
            "给我",
            "告訴我",
            "告诉我",
            "顯示",
            "显示",
            "列出",
            "貼出",
            "贴出",
            "複製",
            "复制",
        )
    )
    asks_about_used = any(
        marker in compact
        for marker in (
            "剛剛",
            "刚刚",
            "剛才",
            "刚才",
            "上一張",
            "上一张",
            "這次",
            "这次",
            "你用",
            "使用",
            "用的",
        )
    )
    asks_question = any(marker in compact for marker in ("什麼", "什么", "哪個", "哪个", "是什麼", "是什么"))
    return asks_about_used and (asks_to_reveal or asks_question)


def _session_visual_reference_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for entry in get_visual_reference_context_entries():
        if not isinstance(entry, dict):
            continue
        uri = str(entry.get("uri") or "").strip()
        if not uri:
            continue
        item: dict[str, Any] = {
            "uri": uri,
            "role_hint": str(entry.get("role_hint") or "visual_reference").strip()
            or "visual_reference",
            "source": str(entry.get("source") or "session_visual_context").strip()
            or "session_visual_context",
        }
        if entry.get("user_ref_index") not in (None, ""):
            item["user_ref_index"] = entry.get("user_ref_index")
        entries.append(item)
    return entries


def _session_reference_binding(entries: list[dict[str, Any]]) -> dict[str, Any]:
    reference_order: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        item: dict[str, Any] = {
            "index": index,
            "role_hint": str(entry.get("role_hint") or "visual_reference"),
            "attachment": str(entry.get("uri") or ""),
            "source": str(entry.get("source") or "session_visual_context"),
        }
        if entry.get("user_ref_index") not in (None, ""):
            item["user_ref_index"] = entry.get("user_ref_index")
        reference_order.append(item)
    return {
        "mode": "session_visual_context",
        "reference_order_source": "session_visual_context",
        "role_policy": "preserve_session_role_hints",
        "reference_order": reference_order,
    }


def _prompt_with_session_edit_context(prompt: str, entries: list[dict[str, Any]]) -> str:
    if not entries:
        return prompt
    lines = [prompt.rstrip(), "", "Session visual context:"]
    for index, entry in enumerate(entries, start=1):
        role = str(entry.get("role_hint") or "visual_reference")
        if role == "edit_anchor":
            lines.append(f"- attachment {index}: edit target, the previous selected image to modify.")
        else:
            lines.append(f"- attachment {index}: {role} reference; preserve its role only when relevant.")
    return "\n".join(lines).strip()


def attach_direct_visual_agent_handoff_metadata(
    raw_tool_result: str,
    handoff: dict[str, Any],
) -> str:
    try:
        payload = json.loads(raw_tool_result)
    except Exception:
        return raw_tool_result
    if not isinstance(payload, dict):
        return raw_tool_result

    payload["direct_visual_agent_handoff"] = {
        "mode": handoff.get("mode"),
        "base_llm_provider_bypassed": handoff.get("base_llm_provider_bypassed"),
        "base_llm_model_bypassed": handoff.get("base_llm_model_bypassed"),
        "visual_agent_llm_provider": handoff.get("visual_agent_llm_provider"),
        "visual_agent_llm_model": handoff.get("visual_agent_llm_model"),
    }
    return json.dumps(payload, ensure_ascii=False)


def format_direct_visual_agent_handoff_response(raw_tool_result: str) -> str:
    """Return user-facing prose for direct visual handoff results.

    The rich JSON payload stays in the tool message for delivery extraction,
    audit, and debugging. The assistant message should stay compact and should
    not expose candidate paths or internal ranking metadata to chat users.
    """
    try:
        payload = json.loads(raw_tool_result)
    except Exception:
        return raw_tool_result
    if not isinstance(payload, dict):
        return raw_tool_result

    package_status = str(payload.get("package_status") or "").strip().lower()
    if payload.get("success") is False or package_status in {"failed", "failure", "error"}:
        recovery_detail = _format_delivery_recovery_detail(payload.get("delivery_recovery"))
        if recovery_detail:
            return recovery_detail
        detail = _short_error_detail(
            payload.get("error") or payload.get("message") or payload.get("error_type")
        )
        return f"視覺生成失敗：{detail}" if detail else "視覺生成失敗。"

    images = _string_list(payload.get("images"))
    videos = _string_list(payload.get("videos"))
    if images and videos:
        return "已產出圖片和影片。"
    if images:
        return "已產出圖片。"
    if videos:
        return "已產出影片。"
    if payload.get("success"):
        return "視覺生成已完成。"
    return raw_tool_result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _short_error_detail(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if text == "visual candidate blocked by active-learning delivery gate":
        return "候選圖未通過品質檢查，已停止交付。"
    if text == "reference role transfer did not pass visual quality validation after repair":
        return "參考圖角色/姿勢對應仍未通過品質檢查，已停止交付。"
    return text[:180].rstrip()


def _format_delivery_recovery_detail(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if str(value.get("status") or "") != "blocked":
        return ""
    if value.get("generated_candidate_available") is not True:
        return ""
    actions = value.get("actions")
    if not isinstance(actions, list):
        return ""
    recommended_actions = {
        str(action.get("recommended_action") or "")
        for action in actions
        if isinstance(action, dict)
    }
    blocked_modalities = set(_string_list(value.get("blocked_modalities")))
    if "image" in blocked_modalities:
        if "rerun_reference_repair_or_grok_web_polish" in recommended_actions:
            return "視覺生成暫停交付：已產生候選圖，但參考圖對應仍未通過品質檢查；下一步會重新修復或改用 Grok Web polish。"
        return "視覺生成暫停交付：已產生候選圖，但品質檢查未通過；下一步會重新修復或改用 Grok Web polish。"
    if "video" in blocked_modalities:
        return "視覺生成暫停交付：已產生候選影片，但品質檢查未通過；下一步會用選中來源重新修復影片。"
    return ""


def _disabled_by_env() -> bool:
    return os.environ.get("HERMES_VISUAL_AGENT_DIRECT_HANDOFF", "").strip().lower() in _FALSE_ENV_VALUES


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _extract_text(value.get("content"))
    if not isinstance(value, (list, tuple)):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
        elif isinstance(item, dict):
            if item.get("type") in {"text", "input_text"}:
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
            elif isinstance(item.get("content"), (str, list, tuple, dict)):
                text = _extract_text(item.get("content"))
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _extract_attachments(value: Any) -> list[str]:
    if isinstance(value, dict):
        return _extract_attachments(value.get("content"))
    if not isinstance(value, (list, tuple)):
        return []
    attachments: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image_url":
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "").strip()
            else:
                url = str(image_url or item.get("url") or "").strip()
            attachment = normalise_visual_agent_attachment(url)
            if attachment:
                attachments.append(attachment)
        elif item.get("type") in {"input_image", "image"}:
            url = str(item.get("image_url") or item.get("url") or item.get("path") or "").strip()
            attachment = normalise_visual_agent_attachment(url)
            if attachment:
                attachments.append(attachment)
    return attachments


def normalise_visual_agent_attachment(value: str) -> str | None:
    attachment = str(value or "").strip()
    if not attachment:
        return None
    if not attachment.lower().startswith("data:image/"):
        return attachment
    return _materialize_data_image_uri_attachment(attachment)


def _materialize_data_image_uri_attachment(data_uri: str) -> str | None:
    match = _DATA_IMAGE_URI_RE.match(data_uri)
    if not match:
        logger.warning("Dropping unsupported visual-agent data URI attachment")
        return None

    encoded = re.sub(r"\s+", "", match.group("payload") or "")
    if not encoded:
        logger.warning("Dropping empty visual-agent data URI attachment")
        return None

    estimated_bytes = len(encoded) * 3 // 4
    if estimated_bytes > _DATA_URI_ATTACHMENT_MAX_BYTES:
        logger.warning("Dropping oversized visual-agent data URI attachment")
        return None

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("Dropping invalid visual-agent data URI attachment")
        return None

    if not raw:
        logger.warning("Dropping empty visual-agent decoded attachment")
        return None
    if len(raw) > _DATA_URI_ATTACHMENT_MAX_BYTES:
        logger.warning("Dropping oversized decoded visual-agent attachment")
        return None

    extension = _normalise_image_extension(match.group("extension"))
    digest = hashlib.sha256(raw).hexdigest()
    cache_dir = get_hermes_home() / "cache" / "visual-agent-attachments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"handoff_{digest[:16]}.{extension}"
    if not path.exists():
        path.write_bytes(raw)
    return str(path)


def _normalise_image_extension(value: str) -> str:
    lowered = str(value or "").strip().lower().split("+", 1)[0]
    return _IMAGE_EXTENSION_ALIASES.get(lowered, "bin")


def _is_explicit_visual_generation_request(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    if _looks_like_visual_status_message(lowered, compact) or is_visual_prompt_disclosure_request(prompt):
        return False

    english_generation = (
        "create ",
        "generate ",
        "make ",
        "draw ",
        "illustrate ",
        "render ",
        "produce ",
        "animate ",
        "text-to-image",
        "image-to-video",
        "make it move",
        "turn this into",
        "visual agent mode",
        "grok imagine",
    )
    chinese_generation = (
        "產出",
        "生成",
        "產生",
        "製作",
        "做成",
        "做一張",
        "做圖",
        "畫",
        "繪製",
        "產圖",
        "生圖",
        "產影片",
        "生成影片",
        "製作影片",
        "動起來",
        "動態化",
        "轉成影片",
        "轉影片",
    )
    if any(token in lowered for token in english_generation):
        return True
    return any(token in compact for token in chinese_generation)


def _looks_like_visual_status_message(lowered: str, compact: str) -> bool:
    status_prefixes = (
        "視覺生成失敗",
        "視覺生成已完成",
        "已產出圖片",
        "已產出影片",
        "已產出圖片和影片",
        "visual generation failed",
        "visual generation completed",
    )
    if any(compact.startswith(prefix) for prefix in status_prefixes):
        return True
    status_fragments = (
        "候選圖未通過品質檢查",
        "參考圖角色/姿勢對應仍未通過品質檢查",
        "visualcandidateblockedbyactive-learningdeliverygate",
        "referenceroletransferdidnotpassvisualqualityvalidation",
    )
    return any(fragment in compact for fragment in status_fragments) or (
        "visual generation failed" in lowered
        and "quality" in lowered
        and ("gate" in lowered or "validation" in lowered)
    )

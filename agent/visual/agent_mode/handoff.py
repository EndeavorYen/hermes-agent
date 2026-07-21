from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from agent.visual.agent_mode.planner import _requests_visual_polish
from agent.visual.agent_mode.planner import plan_visual_agent_request, planned_candidate_budget
from agent.visual.prompt_text import (
    strip_visual_prompt_metadata,
    strip_visual_runtime_metadata,
)
from agent.visual.session_references import filter_visual_reference_entries_for_prompt
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
    *,
    raphael_decision: dict[str, Any] | None = None,
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
    raw_prompt = _extract_raw_text(source) or _extract_raw_text(user_message)
    prompt = strip_visual_prompt_metadata(raw_prompt) or _extract_text(source) or _extract_text(user_message)
    attachments = _extract_attachments(source) or _extract_attachments(user_message)
    if not prompt and attachments:
        recovered_prompt = _attachment_only_thread_visual_request(raw_prompt)
        if recovered_prompt:
            prompt = recovered_prompt
            raw_prompt = recovered_prompt
    if _is_long_form_story_video_pipeline_request(raw_prompt, prompt):
        return None
    if (
        is_visual_prompt_disclosure_request(prompt)
        or is_visual_prompt_builder_request(prompt)
        or is_text_only_visual_analysis_request(prompt)
    ):
        return None
    session_reference_entries: list[dict[str, Any]] = []
    polish_request = _is_visual_polish_request(prompt)
    followup_request = _is_visual_followup_edit_request(prompt) or _is_current_result_regenerate_request(prompt)
    candidate_output_request = _requests_visual_candidate_output(prompt)
    explicit_generation_request = _is_explicit_visual_generation_request(prompt)
    if not attachments and (
        followup_request or polish_request or explicit_generation_request
    ):
        session_reference_entries = _session_visual_reference_entries(prompt)
        if polish_request:
            session_reference_entries = _promote_first_reference_to_edit_anchor(session_reference_entries)
        attachments = [str(entry["uri"]) for entry in session_reference_entries]
    elif attachments and (followup_request or polish_request):
        session_reference_entries = _current_attachment_polish_entries(attachments)
    if not prompt or not (
        explicit_generation_request
        or (bool(attachments) and polish_request)
        or bool(session_reference_entries)
    ):
        return None

    plan = plan_visual_agent_request(
        raw_prompt or prompt,
        attachments=attachments,
        force_image_output=bool(session_reference_entries or candidate_output_request),
    )
    if not plan.get("should_use_visual_package"):
        return None
    raphael_control = (
        dict(raphael_decision)
        if isinstance(raphael_decision, dict) and raphael_decision
        else None
    )
    if raphael_control is None and _raphael_handoff_control_enabled():
        try:
            from agent.raphael.control import build_raphael_control_decision

            raphael_control = build_raphael_control_decision(
                prompt,
                attachments=attachments,
                visual_plan=plan,
            ).to_dict()
        except Exception as exc:
            logger.debug("Raphael visual handoff control decision skipped: %s", exc)
    if isinstance(raphael_control, dict):
        raphael_mode = str(raphael_control.get("mode") or "")
        if raphael_mode != "needs_clarification" and not raphael_mode.startswith("visual_agent"):
            logger.info(
                "direct visual-agent handoff vetoed by Raphael control mode=%s",
                raphael_mode,
            )
            return None

    arguments = dict(plan.get("arguments") or {})
    arguments.setdefault("prompt", prompt)
    if attachments and not arguments.get("attachments"):
        arguments["attachments"] = attachments
    if session_reference_entries:
        arguments["attachments"] = attachments
        if followup_request or polish_request:
            arguments["include_image"] = True
            arguments["include_video"] = False
        arguments.setdefault("candidate_budget", 2)
        arguments.setdefault("candidate_budget_source", "planner_default")
        if (
            _is_current_result_regenerate_request(prompt)
            and arguments.get("candidate_budget_source") == "planner_default"
        ):
            inherited_budget, inherited_source = planned_candidate_budget(
                raw_prompt,
                composition_guide_only=False,
            )
            if inherited_source == "user":
                arguments["candidate_budget"] = inherited_budget
                arguments["candidate_budget_source"] = "thread_context"
        arguments["reference_binding"] = _session_reference_binding(session_reference_entries)
        arguments["prompt"] = _prompt_with_session_edit_context(prompt, session_reference_entries)
        if followup_request or polish_request:
            reference_roles = {
                str(entry.get("role_hint") or "").strip()
                for entry in session_reference_entries
                if isinstance(entry, dict)
            }
            semantic_pose_transfer = (
                "character_identity" in reference_roles
                and "pose_composition" in reference_roles
                and "edit_anchor" not in reference_roles
            )
            if semantic_pose_transfer:
                arguments["reference_conditioning_policy"] = "semantic_pose_transfer"
                arguments["reference_strategy"] = {
                    "mode": "semantic_pose_transfer",
                    "source": "visual_agent_handoff",
                    "requires_new_composition": True,
                    "edit_anchor": False,
                }
            else:
                arguments["reference_conditioning_policy"] = "role_locked_originals"
                arguments["reference_strategy"] = {
                    "mode": "direct_edit_anchor",
                    "source": "visual_agent_handoff",
                    "requires_new_composition": False,
                    "edit_anchor": True,
                }
    contract = dict(plan.get("provider_contract") or {})
    control_route = (
        raphael_control.get("route")
        if isinstance(raphael_control, dict)
        and isinstance(raphael_control.get("route"), dict)
        else {}
    )
    for key in ("visual_agent_llm_provider", "visual_agent_llm_model"):
        if control_route.get(key):
            contract[key] = control_route[key]
    runtime_contract = (
        raphael_control.get("runtime_contract")
        if isinstance(raphael_control, dict)
        and isinstance(raphael_control.get("runtime_contract"), dict)
        else {}
    )
    if (
        str(control_route.get("visual_media_provider_source") or "") != "prompt_override"
        and str(arguments.get("image_provider_source") or "") != "prompt_override"
    ):
        media_values = {
            "image_provider": control_route.get("visual_media_provider")
            or runtime_contract.get("image_provider"),
            "image_model": control_route.get("visual_media_model")
            or runtime_contract.get("image_model"),
            "video_provider": runtime_contract.get("video_provider"),
            "video_model": runtime_contract.get("video_model"),
        }
        for key, value in media_values.items():
            if not str(value or "").strip():
                continue
            contract[key] = value
            arguments[key] = value
        if media_values.get("image_provider"):
            arguments["image_provider_source"] = "runtime_contract"
        if media_values.get("video_provider"):
            arguments["video_provider_source"] = "runtime_contract"
    plan["provider_contract"] = contract
    if contract.get("visual_agent_llm_provider"):
        arguments["visual_agent_llm_provider"] = contract.get("visual_agent_llm_provider")
    if contract.get("visual_agent_llm_model"):
        arguments["visual_agent_llm_model"] = contract.get("visual_agent_llm_model")
    _apply_grok_web_current_result_operation(
        arguments,
        prompt=prompt,
        session_reference_entries=session_reference_entries,
    )
    arguments["visual_agent_handoff_mode"] = "pre_llm_direct"

    if isinstance(raphael_control, dict) and raphael_control.get("mode") == "needs_clarification":
        return {
            "mode": "pre_llm_clarification",
            "tool_name": None,
            "arguments": {},
            "plan": plan,
            "base_llm_provider_bypassed": str(getattr(agent, "provider", "") or ""),
            "base_llm_model_bypassed": str(getattr(agent, "model", "") or ""),
            "visual_agent_llm_provider": contract.get("visual_agent_llm_provider"),
            "visual_agent_llm_model": contract.get("visual_agent_llm_model"),
            "raphael_control": raphael_control,
            "clarification_response": raphael_control.get("clarification_question")
            or "請先補充 reference 對應後我再繼續。",
        }

    return {
        "mode": "pre_llm_direct",
        "tool_name": "visual_agent_generate",
        "arguments": arguments,
        "plan": plan,
        "base_llm_provider_bypassed": str(getattr(agent, "provider", "") or ""),
        "base_llm_model_bypassed": str(getattr(agent, "model", "") or ""),
        "visual_agent_llm_provider": contract.get("visual_agent_llm_provider"),
        "visual_agent_llm_model": contract.get("visual_agent_llm_model"),
        "raphael_control": raphael_control,
    }


def _raphael_handoff_control_enabled() -> bool:
    try:
        from hermes_cli.config import load_config

        config = load_config()
    except Exception:
        return False
    try:
        from agent.raphael.config import raphael_effective_enabled

        return raphael_effective_enabled(config)
    except Exception:
        return False


def _is_visual_followup_edit_request(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    if (
        _looks_like_visual_status_message(lowered, compact)
        or is_visual_prompt_disclosure_request(text)
        or is_text_only_visual_analysis_request(text)
    ):
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
        "幫我換",
        "帮我换",
        "試試",
        "试试",
        "換個",
        "换个",
        "移除",
        "去掉",
        "脫掉",
        "脱掉",
        "脫了",
        "脱了",
        "不要",
        "不應該",
        "而不是",
        "polish",
        "refine",
        "enhance",
        "精修",
        "修圖",
        "潤飾",
        "美化",
    )
    return prompt_requests_visual_reference_reuse(text) and any(marker in lowered for marker in edit_markers)


def _is_current_result_regenerate_request(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    if (
        _looks_like_visual_status_message(lowered, compact)
        or is_visual_prompt_disclosure_request(text)
        or is_text_only_visual_analysis_request(text)
    ):
        return False
    markers = (
        "regenerate",
        "reroll",
        "retry",
        "redo",
        "try again",
        "重新產生",
        "重新產出",
        "再產出",
        "重新出圖",
        "重新生成",
        "重新产出",
        "再产出",
        "再產",
        "再产",
        "重新出图",
        "再生成",
        "重試",
        "重试",
        "重做",
        "再抽",
        "重抽",
    )
    return any(marker in lowered for marker in markers) or any(marker in compact for marker in markers)


def _apply_grok_web_current_result_operation(
    arguments: dict[str, Any],
    *,
    prompt: str,
    session_reference_entries: list[dict[str, Any]],
) -> None:
    if not session_reference_entries:
        return
    if str(arguments.get("image_provider") or "").strip() != "grok-web-imagine":
        return
    if any(str(arguments.get(key) or "").strip() for key in ("image_operation", "grok_web_operation", "operation")):
        return
    arguments["image_operation"] = (
        "regenerate_current" if _is_current_result_regenerate_request(prompt) else "continue_current"
    )
    arguments["candidate_budget"] = 1
    arguments["candidate_budget_source"] = "grok_web_current_result_operation"


def _is_visual_polish_request(prompt: str) -> bool:
    return _requests_visual_polish(prompt)


def is_visual_prompt_builder_request(prompt: str) -> bool:
    """Return True when the user wants a new visual prompt as the deliverable."""
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    has_prompt_term = "prompt" in text or "提示詞" in text or "提示词" in text
    if not has_prompt_term:
        return False
    prompt_edit_request = any(
        marker in compact
        for marker in (
            "修改prompt",
            "改prompt",
            "調整prompt",
            "调整prompt",
            "優化prompt",
            "优化prompt",
            "替換prompt",
            "替换prompt",
            "補prompt",
            "补prompt",
            "改進prompt",
            "改进prompt",
            "改良prompt",
            "改進的prompt",
            "改进的prompt",
            "更好的prompt",
            "加強prompt",
            "加强prompt",
            "修改提示詞",
            "修改提示词",
            "改提示詞",
            "改提示词",
            "調整提示詞",
            "调整提示词",
            "優化提示詞",
            "优化提示词",
            "替換提示詞",
            "替换提示词",
            "補提示詞",
            "补提示词",
            "改進提示詞",
            "改进提示词",
            "改良提示詞",
            "改良提示词",
            "改進的提示詞",
            "改进的提示词",
            "更好的提示詞",
            "更好的提示词",
            "加強提示詞",
            "加强提示词",
        )
    ) or (
        any(marker in compact for marker in ("修改", "改成", "改為", "改为", "替換", "替换", "補上", "补上", "加上"))
        and has_prompt_term
    ) or any(
        marker in text
        for marker in (
            "modify the prompt",
            "edit the prompt",
            "revise the prompt",
            "rewrite the prompt",
            "update the prompt",
            "improve the prompt",
            "improved prompt",
            "better prompt",
        )
    )
    if prompt_edit_request:
        return True
    if _mentions_prior_or_used_prompt(compact):
        return False

    prompt_as_artifact = any(
        marker in compact
        for marker in (
            "prompt就好",
            "prompt即可",
            "只要prompt",
            "只給prompt",
            "只给prompt",
            "給我prompt就好",
            "给我prompt就好",
            "請給我合適的prompt",
            "请给我合适的prompt",
            "請給我適合的prompt",
            "请给我适合的prompt",
            "給我合適的prompt",
            "给我合适的prompt",
            "給我適合的prompt",
            "给我适合的prompt",
            "幫我寫prompt",
            "帮我写prompt",
            "幫我產生prompt",
            "帮我产生prompt",
            "幫我生成prompt",
            "帮我生成prompt",
            "提示詞就好",
            "提示词就好",
            "提示詞即可",
            "提示词即可",
            "只要提示詞",
            "只要提示词",
            "只給提示詞",
            "只给提示词",
            "給我提示詞就好",
            "给我提示词就好",
            "請給我合適的提示詞",
            "请给我合适的提示词",
            "請給我適合的提示詞",
            "请给我适合的提示词",
            "給我合適的提示詞",
            "给我合适的提示词",
            "給我適合的提示詞",
            "给我适合的提示词",
            "幫我寫提示詞",
            "帮我写提示词",
            "幫我產生提示詞",
            "帮我产生提示词",
            "幫我生成提示詞",
            "帮我生成提示词",
        )
    ) or any(
        marker in text
        for marker in (
            "prompt only",
            "only prompt",
            "only the prompt",
            "give me a prompt",
            "give me a suitable prompt",
            "give me an appropriate prompt",
            "write a prompt",
            "make a prompt",
        )
    )
    no_generation = any(
        marker in compact
        for marker in (
            "不須產圖",
            "不需產圖",
            "不用產圖",
            "不必產圖",
            "不要產圖",
            "不須生圖",
            "不需生圖",
            "不用生圖",
            "不須生成圖片",
            "不需生成圖片",
            "不用生成圖片",
            "不要生成圖片",
            "不须产图",
            "不需产图",
            "不用产图",
            "不要产图",
            "不须生成图片",
            "不用生成图片",
        )
    ) or any(
        marker in text
        for marker in (
            "do not generate",
            "don't generate",
            "no image generation",
            "no need to generate",
            "without generating",
        )
    )
    asks_for_prompt = any(
        marker in compact
        for marker in (
            "給我prompt",
            "给我prompt",
            "產生prompt",
            "生成prompt",
            "寫prompt",
            "写prompt",
            "做prompt",
            "給我提示詞",
            "给我提示词",
            "產生提示詞",
            "生成提示詞",
            "寫提示詞",
            "写提示词",
            "做提示詞",
            "做提示词",
        )
    )
    return prompt_as_artifact or (no_generation and asks_for_prompt)


def is_visual_prompt_disclosure_request(prompt: str) -> bool:
    """Return True when the user is asking about the prompt, not asking to render media."""
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    has_prompt_term = "prompt" in text or "提示詞" in text or "提示词" in text
    if not has_prompt_term:
        return False
    if is_visual_prompt_builder_request(prompt):
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
    asks_about_used = _mentions_prior_or_used_prompt(compact)
    asks_question = any(marker in compact for marker in ("什麼", "什么", "哪個", "哪个", "是什麼", "是什么"))
    return asks_about_used and (asks_to_reveal or asks_question)


def _mentions_prior_or_used_prompt(compact_text: str) -> bool:
    return any(
        marker in compact_text
        for marker in (
            "剛剛",
            "刚刚",
            "剛才",
            "刚才",
            "上一輪",
            "上一轮",
            "上一張",
            "上一张",
            "這次",
            "这次",
            "你用",
            "你使用",
            "使用",
            "用的",
            "用到的",
        )
    )


def is_text_only_visual_analysis_request(prompt: str) -> bool:
    """Return True when visual media is being analyzed, not generated."""
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    has_visual_term = any(
        marker in text
        for marker in (
            "image",
            "video",
            "visual",
            "photo",
            "picture",
            "grok imagine",
        )
    ) or any(
        marker in compact
        for marker in (
            "圖片",
            "图像",
            "圖像",
            "影片",
            "視覺",
            "视觉",
            "產圖",
            "产图",
            "生圖",
            "生图",
            "生成圖",
            "生成图",
            "生成影片",
        )
    )
    if not has_visual_term:
        return False
    wants_text_only = any(
        marker in text
        for marker in (
            "text-only",
            "text only",
            "no tools",
            "no-tool",
            "without tools",
            "do not use tools",
            "do not call tools",
            "don't use tools",
            "don't call tools",
            "no image generation",
            "no video generation",
        )
    ) or any(
        marker in compact
        for marker in (
            "純文字",
            "纯文字",
            "只做llm判斷",
            "只做llm判断",
            "llm判斷",
            "llm判断",
            "不使用工具",
            "不要使用工具",
            "不能使用工具",
            "不得使用工具",
            "不准使用工具",
            "不要呼叫工具",
            "不能呼叫工具",
            "不得呼叫工具",
            "不准呼叫工具",
            "不要用工具",
            "不能用工具",
            "不得用工具",
            "不准用工具",
            "不要調用工具",
            "不要调用工具",
            "不要呼叫任何產圖",
            "不要呼叫任何产图",
            "不要呼叫任何生成",
            "不要產圖",
            "不要产图",
            "不能產圖",
            "不能产图",
            "不得產圖",
            "不准產圖",
            "不能生圖",
            "不能生图",
            "禁止產圖",
            "禁止产图",
            "禁止生成",
            "不要生成圖片",
            "不要生成图片",
            "不能生成圖片",
            "不能生成图片",
            "不要生成影片",
            "不能生成影片",
        )
    )
    analysis_terms = (
        "route",
        "routing",
        "provider",
        "proof",
        "proof gate",
        "proof-gate",
        "mode",
        "handoff",
        "clarify",
        "clarification",
    )
    compact_analysis_terms = (
        "路由",
        "判斷",
        "判断",
        "分析",
        "provider",
        "mode",
        "澄清",
        "證據",
        "证据",
        "驗證",
        "验证",
        "proofgate",
    )
    has_analysis_term = any(marker in text for marker in analysis_terms) or any(
        marker in compact for marker in compact_analysis_terms
    )
    if not has_analysis_term:
        return False
    meta_framing = any(
        marker in text
        for marker in (
            "analyze",
            "analyse",
            "if the user",
            "if i",
            "should route",
            "would route",
            "later",
            "not actually generate",
        )
    ) or any(
        marker in compact
        for marker in (
            "分析",
            "如果",
            "應該",
            "应该",
            "判斷",
            "判断",
            "先不要實際做圖",
            "先不要实际做图",
            "不要實際做圖",
            "不要实际做图",
            "之後",
            "之后",
        )
    )
    return wants_text_only or meta_framing


def _session_visual_reference_entries(prompt: str = "") -> list[dict[str, Any]]:
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
    return filter_visual_reference_entries_for_prompt(entries, prompt)


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


def _current_attachment_polish_entries(attachments: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, attachment in enumerate(attachments, start=1):
        if index == 1:
            entries.append(
                {
                    "uri": attachment,
                    "role_hint": "edit_anchor",
                    "source": "current_visual_context",
                    "user_ref_index": "previous_selected_output",
                }
            )
            continue
        entries.append(
            {
                "uri": attachment,
                "role_hint": "visual_reference",
                "source": "current_visual_context",
            }
        )
    return entries


def _promote_first_reference_to_edit_anchor(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_edit_anchor = any(
        isinstance(entry, dict) and str(entry.get("role_hint") or "") == "edit_anchor"
        for entry in entries
    )
    promoted: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        if index == 1 and not has_edit_anchor:
            item["role_hint"] = "edit_anchor"
            item["source"] = str(item.get("source") or "session_visual_context")
            item["user_ref_index"] = item.get("user_ref_index") or "previous_selected_output"
        promoted.append(item)
    return promoted


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
    if isinstance(handoff.get("raphael_control"), dict):
        payload["direct_visual_agent_handoff"]["raphael_control"] = handoff[
            "raphael_control"
        ]
        gate = _evaluate_raphael_evidence_gate(
            handoff["raphael_control"],
            payload,
        )
        review_only_delivery = _review_only_candidate_delivery_allowed(payload, gate)
        if review_only_delivery:
            gate["delivery_disposition"] = "review_only"
        payload["direct_visual_agent_handoff"]["raphael_evidence_gate"] = gate
        if payload.get("success") is True and gate.get("passed") is True:
            _record_successful_raphael_visual_handoff_mission(
                payload,
                handoff["raphael_control"],
                gate,
            )
        if (
            payload.get("success") is True
            and gate.get("passed") is not True
            and not review_only_delivery
        ):
            blocked_images = _string_list(payload.get("images"))
            blocked_videos = _string_list(payload.get("videos"))
            if blocked_images or blocked_videos:
                payload["blocked_delivery"] = {
                    "images": blocked_images,
                    "videos": blocked_videos,
                    "reason": "raphael_evidence_gate_failed",
                }
            payload["images"] = []
            payload["videos"] = []
            payload["success"] = False
            payload["package_status"] = "failed"
            payload["error_type"] = "raphael_evidence_gate_failed"
            missing = ", ".join(gate.get("missing_proofs") or ())
            payload["error"] = (
                "Raphael evidence gate failed"
                + (f": missing {missing}" if missing else "")
            )
            payload["failure_layer"] = gate.get("failure_layer") or "artifact_quality"
    return json.dumps(payload, ensure_ascii=False)


def _review_only_candidate_delivery_allowed(
    payload: dict[str, Any],
    gate: dict[str, Any],
) -> bool:
    if (
        payload.get("success") is not True
        or payload.get("package_status") != "partial"
        or payload.get("error_type") != "candidate_options_review_required"
    ):
        return False
    image_gate = (payload.get("delivery_gate") or {}).get("image")
    options = image_gate.get("candidate_options") if isinstance(image_gate, dict) else None
    if not isinstance(options, dict) or options.get("review_only") is not True:
        return False
    if not _string_list(payload.get("images")) or _string_list(payload.get("videos")):
        return False
    allowed_missing = {"artifact_quality_evidence", "delivery_cleanliness"}
    missing = set(_string_list(gate.get("missing_proofs")))
    return bool(missing) and missing.issubset(allowed_missing)


def _record_successful_raphael_visual_handoff_mission(
    payload: dict[str, Any],
    raphael_control: dict[str, Any],
    gate: dict[str, Any],
) -> None:
    selected_ids = sorted(_selected_visual_artifact_ids(payload))
    if not selected_ids:
        return
    try:
        from agent.raphael.mission import RaphaelMissionState
        from agent.raphael.state import read_mission_state, write_mission_state

        current = read_mission_state()
        goal = (
            raphael_control.get("goal")
            if isinstance(raphael_control.get("goal"), dict)
            else {}
        )
        goal_summary = str(goal.get("summary") or "visual agent handoff").strip()
        mission_id = (
            current.mission_id
            if current is not None
            else _visual_handoff_mission_id(goal_summary, selected_ids[0])
        )
        write_mission_state(
            RaphaelMissionState(
                mission_id=mission_id,
                goal=goal_summary,
                phase="proof_passed",
                selected_strategy_id="visual_agent_handoff",
                active_artifact_id=selected_ids[0],
                blockers=(),
                next_action="deliver_selected_visual_artifact",
                proof_status="passed",
                required_proofs=tuple(
                    str(item)
                    for item in gate.get("required_proofs", ())
                    if str(item).strip()
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )
    except Exception as exc:  # noqa: BLE001 - mission continuity must not break delivery.
        logger.debug("Raphael visual handoff mission update skipped: %s", exc)


def _visual_handoff_mission_id(goal: str, artifact_id: str) -> str:
    digest = hashlib.sha256(f"{goal}|{artifact_id}".encode("utf-8")).hexdigest()[:12]
    return f"mission-{digest}"


def _evaluate_raphael_evidence_gate(
    raphael_control: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    from agent.raphael.proof import build_raphael_evidence_event

    evidence = (
        raphael_control.get("evidence")
        if isinstance(raphael_control.get("evidence"), dict)
        else {}
    )
    required = [
        str(proof)
        for proof in evidence.get("required_proofs", ())
        if str(proof).strip()
    ]
    proof_results = {
        proof: _raphael_required_proof_present(proof, raphael_control, payload)
        for proof in required
    }
    mission_id = str(raphael_control.get("mission_id") or "")
    turn_id = str(raphael_control.get("turn_id") or "")
    selected_ids = sorted(_selected_visual_artifact_ids(payload))
    artifact_id = selected_ids[0] if selected_ids else ""
    provider = _raphael_evidence_provider(payload, raphael_control)
    identity_missing = [
        label
        for label, value in (
            ("mission_identity", mission_id),
            ("turn_identity", turn_id),
            ("artifact_identity", artifact_id),
            ("provider_identity", provider),
        )
        if not value
    ]
    missing = [
        proof for proof, present in proof_results.items() if not present
    ] + identity_missing
    payload_digest = _raphael_evidence_payload_digest(
        proof_results=proof_results,
        selected_ids=selected_ids,
        provider=provider,
        payload=payload,
    )
    observed_at = datetime.now(timezone.utc).isoformat()
    evidence_events = [
        build_raphael_evidence_event(
            mission_id=mission_id,
            turn_id=turn_id,
            proof_type=proof,
            source="visual_agent_handoff",
            status="passed" if present and not identity_missing else "missing",
            command="visual_agent_generate",
            artifact_id=artifact_id,
            provider=provider,
            payload_digest=payload_digest,
            observed_at=observed_at,
        ).to_dict()
        for proof, present in proof_results.items()
    ]
    return {
        "passed": not missing,
        "required_proofs": required,
        "missing_proofs": missing,
        "failure_layer": "artifact_quality" if missing else None,
        "evidence_events": evidence_events,
    }


def _raphael_evidence_provider(
    payload: dict[str, Any],
    raphael_control: dict[str, Any],
) -> str:
    contract = payload.get("visual_agent_provider_contract")
    if isinstance(contract, dict) and str(contract.get("provider") or "").strip():
        return str(contract["provider"])
    generation_payloads = payload.get("generation_payloads")
    if isinstance(generation_payloads, dict):
        for candidate in generation_payloads.values():
            if isinstance(candidate, dict) and str(candidate.get("provider") or "").strip():
                return str(candidate["provider"])
    route = raphael_control.get("route")
    if isinstance(route, dict) and str(route.get("visual_media_provider") or "").strip():
        return str(route["visual_media_provider"])
    runtime_contract = raphael_control.get("runtime_contract")
    if isinstance(runtime_contract, dict):
        provider_key = "video_provider" if payload.get("videos") else "image_provider"
        if str(runtime_contract.get(provider_key) or "").strip():
            return str(runtime_contract[provider_key])
    return ""


def _raphael_evidence_payload_digest(
    *,
    proof_results: dict[str, bool],
    selected_ids: list[str],
    provider: str,
    payload: dict[str, Any],
) -> str:
    quality = payload.get("delivery_metadata")
    quality = quality.get("visual_quality_run") if isinstance(quality, dict) else None
    recovery = payload.get("delivery_recovery")
    safe_summary = {
        "proof_results": proof_results,
        "selected_artifact_ids": selected_ids,
        "provider": provider,
        "quality_success": quality.get("success") if isinstance(quality, dict) else None,
        "delivery_status": recovery.get("status") if isinstance(recovery, dict) else None,
        "success": payload.get("success") is True,
    }
    encoded = json.dumps(safe_summary, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _raphael_required_proof_present(
    proof: str,
    raphael_control: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    if proof == "direct_handoff_metadata":
        return isinstance(payload.get("direct_visual_agent_handoff"), dict)
    if proof == "provider_attempt_evidence":
        return bool(payload.get("generation_payloads")) or isinstance(
            payload.get("visual_agent_provider_contract"),
            dict,
        )
    if proof == "artifact_quality_evidence":
        return _has_passing_artifact_quality_evidence(payload)
    if proof == "selected_current_artifact_only":
        return _selected_current_visual_artifacts_verified(payload)
    if proof == "stale_artifact_guard":
        return _selected_current_visual_artifacts_are_fresh(payload)
    if proof == "delivery_cleanliness":
        recovery = payload.get("delivery_recovery")
        if not isinstance(recovery, dict):
            return False
        return (
            _selected_current_visual_artifacts_verified(payload)
            and recovery.get("deliver_rejected_artifact") is False
            and not _delivery_gate_explicitly_failed(payload.get("delivery_gate"))
            and not payload.get("missing_delivery_artifact_ids")
            and not payload.get("unexpected_delivery_artifact_ids")
        )
    if proof == "reference_mapping_evidence":
        return bool(payload.get("reference_binding")) or bool(payload.get("rankings"))
    if proof == "multi_candidate_validation":
        strategy = payload.get("generation_strategy")
        if isinstance(strategy, dict):
            try:
                if int(strategy.get("candidate_budget") or 0) >= 2:
                    return True
            except (TypeError, ValueError):
                pass
        rankings = payload.get("rankings")
        return isinstance(rankings, dict) and bool(rankings.get("candidates"))
    if proof == "image_first_video_source_evidence":
        return _has_image_first_video_source_evidence(payload)
    if proof == "single_ranked_video_source_image":
        return _has_single_ranked_video_source_image(payload)
    if proof in {
        "artifact_continuity",
        "feedback_attribution",
        "learning_trace_candidate",
        "prompt_trace_available",
        "no_generation_tool_call",
    }:
        return True
    return False


def _has_image_first_video_source_evidence(payload: dict[str, Any]) -> bool:
    strategy = payload.get("generation_strategy")
    if not isinstance(strategy, dict):
        return False
    if strategy.get("image_first_for_video") is not True:
        return False
    if not str(strategy.get("video_source_image") or "").strip():
        return False
    metadata = payload.get("delivery_metadata")
    quality_run = metadata.get("visual_quality_run") if isinstance(metadata, dict) else None
    if not isinstance(quality_run, dict):
        return False
    summary = quality_run.get("summary")
    self_review = quality_run.get("self_review")
    if isinstance(summary, dict):
        try:
            covered = int(summary.get("image_first_video_source_covered_count") or 0)
            failures = int(summary.get("image_first_video_source_failure_count") or 0)
        except (TypeError, ValueError):
            covered = 0
            failures = 1
        if covered >= 1 and failures == 0:
            return True
    return isinstance(self_review, dict) and self_review.get("image_first_video_source_covered") is True


def _has_single_ranked_video_source_image(payload: dict[str, Any]) -> bool:
    strategy = payload.get("generation_strategy")
    if not isinstance(strategy, dict):
        return False
    try:
        source_count = int(strategy.get("video_source_image_count") or 0)
    except (TypeError, ValueError):
        source_count = 0
    if source_count != 1:
        return False
    if str(strategy.get("video_source_policy") or "") != "single_ranked_selected_image":
        return False
    metadata = payload.get("delivery_metadata")
    quality_run = metadata.get("visual_quality_run") if isinstance(metadata, dict) else None
    if not isinstance(quality_run, dict):
        return False
    summary = quality_run.get("summary")
    self_review = quality_run.get("self_review")
    if isinstance(summary, dict):
        try:
            if int(summary.get("video_source_image_count") or 0) != 1:
                return False
        except (TypeError, ValueError):
            return False
    return isinstance(self_review, dict) and self_review.get("single_video_source_image") is True


def _has_passing_artifact_quality_evidence(payload: dict[str, Any]) -> bool:
    if _delivery_gate_explicitly_failed(payload.get("delivery_gate")):
        return False
    if _autonomous_validation_explicitly_failed(payload.get("autonomous_validation")):
        return False
    return _visual_quality_run_passed(payload)


def _visual_quality_run_passed(payload: dict[str, Any]) -> bool:
    metadata = payload.get("delivery_metadata")
    if not isinstance(metadata, dict):
        return False
    quality_run = metadata.get("visual_quality_run")
    if not isinstance(quality_run, dict) or quality_run.get("success") is not True:
        return False
    summary = quality_run.get("summary")
    if not isinstance(summary, dict):
        return False
    try:
        case_count = int(summary.get("case_count") or 0)
        failed_case_count = int(summary.get("failed_case_count") or 0)
        quality_issue_count = int(summary.get("quality_issue_count") or 0)
    except (TypeError, ValueError):
        return False
    return (
        case_count >= 1
        and failed_case_count == 0
        and quality_issue_count == 0
        and _selected_current_visual_artifacts_verified(payload)
    )


def _selected_current_visual_artifacts_verified(payload: dict[str, Any]) -> bool:
    selected_ids = _selected_visual_artifact_ids(payload)
    if not selected_ids:
        return False
    current_entries = _selected_current_visual_artifact_entries(payload)
    current_ids = {
        str(entry.get("artifact_id") or "")
        for entry in current_entries
        if str(entry.get("artifact_id") or "")
    }
    return bool(current_ids) and selected_ids <= current_ids


def _selected_current_visual_artifacts_are_fresh(payload: dict[str, Any]) -> bool:
    if not _selected_current_visual_artifacts_verified(payload):
        return False
    for entry in _selected_current_visual_artifact_entries(payload):
        if _visual_artifact_entry_is_stale_or_unstable(entry):
            return False
    recovery = payload.get("delivery_recovery")
    return not (isinstance(recovery, dict) and recovery.get("deliver_rejected_artifact") is True)


def _selected_visual_artifact_ids(payload: dict[str, Any]) -> set[str]:
    metadata = payload.get("delivery_metadata")
    if not isinstance(metadata, dict):
        return set()
    raw_ids = (
        metadata.get("selected_visual_artifact_ids")
        or metadata.get("selected_artifact_ids")
        or metadata.get("artifact_ids")
        or []
    )
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return set()
    return {str(item) for item in raw_ids if str(item or "").strip()}


def _selected_current_visual_artifact_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = payload.get("delivery_metadata")
    if not isinstance(metadata, dict):
        return []
    artifacts = metadata.get("visual_artifacts")
    if not isinstance(artifacts, dict):
        return []
    current_refs = set(_string_list(payload.get("images"))) | set(_string_list(payload.get("videos")))
    selected_ids = _selected_visual_artifact_ids(payload)
    entries: list[dict[str, Any]] = []
    for ref, entry in artifacts.items():
        if str(ref) not in current_refs or not isinstance(entry, dict):
            continue
        artifact_id = str(entry.get("artifact_id") or "")
        if artifact_id and artifact_id in selected_ids:
            entries.append(entry)
    return entries


def _visual_artifact_entry_is_stale_or_unstable(entry: dict[str, Any]) -> bool:
    freshness = entry.get("freshness_status")
    if freshness is not None and str(freshness).strip().lower() != "fresh":
        return True
    stable = entry.get("is_stable")
    if stable is False or stable == 0 or str(stable).strip().lower() in {"0", "false", "no"}:
        return True
    return False


def _delivery_gate_passed(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    gate_values = [gate for gate in value.values() if isinstance(gate, dict)]
    if not gate_values:
        return False
    return all(gate.get("allowed") is True for gate in gate_values)


def _delivery_gate_explicitly_failed(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        isinstance(gate, dict) and gate.get("allowed") is False
        for gate in value.values()
    )


def _autonomous_validation_passed(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    decision = str(value.get("decision") or value.get("status") or "").strip().lower()
    return value.get("valid") is True or decision in {"accept", "accepted", "pass", "passed"}


def _autonomous_validation_explicitly_failed(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    decision = str(value.get("decision") or value.get("status") or "").strip().lower()
    failures = value.get("failures")
    return (
        value.get("valid") is False
        or decision in {"reject", "rejected", "fail", "failed", "blocked"}
        or (isinstance(failures, list) and bool(failures))
    )


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
    payload_error = payload.get("error") or payload.get("error_type")
    if (
        payload.get("success") is False
        or package_status in {"failed", "failure", "error"}
        or (payload.get("success") is not True and payload_error)
    ):
        recovery_detail = _format_delivery_recovery_detail(payload.get("delivery_recovery"))
        if recovery_detail:
            return recovery_detail
        if payload.get("error_type") == "visual_package_resource_exhaustion":
            return "視覺生成失敗：本機 visual package 資源耗盡，已停止避免重複產生；請重啟 gateway 後再試。"
        detail = _short_error_detail(
            payload.get("error") or payload.get("message") or payload.get("error_type")
        )
        return f"視覺生成失敗：{detail}" if detail else "視覺生成失敗。"

    images = _string_list(payload.get("images"))
    videos = _string_list(payload.get("videos"))
    labels = [
        str(item.get("label") or "").strip()
        for item in payload.get("session_visual_artifacts") or []
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    ]
    image_gate = (payload.get("delivery_gate") or {}).get("image")
    candidate_options = (
        image_gate.get("candidate_options") if isinstance(image_gate, dict) else None
    )
    if (
        package_status == "partial"
        and payload.get("error_type") == "candidate_options_review_required"
        and isinstance(candidate_options, dict)
        and candidate_options.get("review_only") is True
        and images
    ):
        suffix = f"：{'、'.join(labels)}" if labels else ""
        return (
            f"已交付尚未通過品質檢查的候選圖供你評選{suffix}。"
            "這些圖片不視為 QC PASS；後續可直接指定編號繼續修正。"
        )
    if (
        package_status == "partial"
        and payload.get("error_type") == "candidate_option_shortfall"
        and images
    ):
        if labels:
            return (
                f"已交付通過品質檢查的候選圖：{'、'.join(labels)}；"
                "合格數少於原要求，其餘已淘汰。後續可直接指定編號繼續編輯。"
            )
        return "已交付通過品質檢查的候選圖；合格數少於原要求，其餘已淘汰。"
    if images and videos:
        return "已產出圖片和影片。"
    if images:
        if labels:
            return f"已產出圖片：{'、'.join(labels)}。後續可直接指定編號繼續編輯。"
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
    blocked_modalities = set(_string_list(value.get("blocked_modalities")))
    if "image" in blocked_modalities:
        action = next(
            (
                item
                for item in actions
                if isinstance(item, dict) and str(item.get("modality") or "") == "image"
            ),
            {},
        )
        provider = str(action.get("provider") or "").strip()
        provider_label = "xAI" if provider.lower() == "xai" else provider
        generation = f"{provider_label} 已產生候選圖" if provider_label else "已產生候選圖"
        repair_rounds = _coerce_nonnegative_int(action.get("repair_rounds_attempted"))
        repair = f"並執行 {repair_rounds} 次有界修復" if repair_rounds else ""
        details: list[str] = []
        quality_issues = _string_list(action.get("quality_issues"))
        if quality_issues:
            details.append(", ".join(quality_issues))
        stop_reason = str(action.get("quality_loop_stop_reason") or "").strip()
        if stop_reason:
            details.append(f"停止原因 {stop_reason}")
        detail = f"（{'；'.join(details)}）" if details else ""
        return f"視覺生成未交付：{generation}{repair}，但仍未通過品質檢查{detail}。未切換 provider。"
    if "video" in blocked_modalities:
        return "視覺生成暫停交付：已產生候選影片，但品質檢查未通過；下一步會用選中來源重新修復影片。"
    return ""


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _disabled_by_env() -> bool:
    return os.environ.get("HERMES_VISUAL_AGENT_DIRECT_HANDOFF", "").strip().lower() in _FALSE_ENV_VALUES


def _attachment_only_thread_visual_request(raw_prompt: str) -> str:
    """Recover the latest explicit visual request when the current turn only adds a ref."""
    blocks = re.findall(
        r"\[Thread context[^\]]*\](.*?)(?:\[End of thread context\]|$)",
        str(raw_prompt or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    candidates: list[str] = []
    for block in blocks:
        current_lines: list[str] = []
        current_is_user = False

        def flush_current() -> None:
            nonlocal current_lines
            if current_is_user and current_lines:
                candidate = "\n".join(current_lines).strip()
                if candidate:
                    candidates.append(candidate)
            current_lines = []

        for line in block.splitlines():
            match = re.match(
                r"^\s*(?:\[thread parent\]\s*)?([^:\n]{1,80}):\s*(.+?)\s*$",
                line,
                flags=re.IGNORECASE,
            )
            if not match:
                if current_is_user and line.strip():
                    current_lines.append(line.strip())
                continue
            flush_current()
            speaker = match.group(1).strip().lower()
            current_is_user = speaker not in {
                "assistant",
                "hermes agent",
                "newhermes agent",
                "agent",
            }
            current_lines = [match.group(2).strip()] if current_is_user else []
        flush_current()

    for candidate in reversed(candidates):
        if (
            _is_explicit_visual_generation_request(candidate)
            or _is_visual_polish_request(candidate)
        ):
            return candidate
    for candidate in reversed(candidates):
        if (
            _is_visual_followup_edit_request(candidate)
            or _is_current_result_regenerate_request(candidate)
        ):
            return candidate
    return ""


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return strip_visual_prompt_metadata(value)
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
    return strip_visual_prompt_metadata("\n".join(parts))


def _extract_raw_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _extract_raw_text(value.get("content"))
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
                text = _extract_raw_text(item.get("content"))
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
    from tools.story_video_provider_guard import explicit_visual_agent_request_detected

    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    if (
        _looks_like_visual_status_message(lowered, compact)
        or is_visual_prompt_disclosure_request(prompt)
        or is_text_only_visual_analysis_request(prompt)
    ):
        return False
    if _looks_like_negative_visual_generation_instruction(lowered, compact):
        return False
    if explicit_visual_agent_request_detected(prompt):
        return True
    if _requests_visual_candidate_output(prompt):
        return True

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


def _requests_visual_candidate_output(prompt: str) -> bool:
    """Return True when the user explicitly asks for image options to choose from."""
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    chinese_count = re.search(r"(?:[2-4]|[二兩两三四])(?:張|张)(?:圖|图|圖片|图片)?", compact)
    chinese_selection = any(
        marker in compact
        for marker in (
            "讓我挑",
            "让我挑",
            "讓我選",
            "让我选",
            "供我挑",
            "供我選",
            "供我选",
            "給我",
            "给我",
        )
    )
    if chinese_count and chinese_selection:
        return True

    english_count = re.search(r"\b[2-4]\s+(?:image|picture|option|candidate)s?\b", lowered)
    english_selection = re.search(r"\b(?:choose|pick|select|compare|give|show|provide)\b", lowered)
    return bool(english_count and english_selection)


def _is_long_form_story_video_pipeline_request(raw_prompt: Any, prompt: str) -> bool:
    """Let story-video/long-form documentary requests use their production skill.

    ``visual_agent_generate`` is a short-form image/video package route. Slack
    follow-ups include the parent thread text in ``raw_prompt``; keep using that
    parent contract so "continue/generate video" replies do not detach into a
    generic 6-second visual package.
    """
    from tools.story_video_provider_guard import story_video_request_detected

    thread_contract = strip_visual_runtime_metadata(raw_prompt)
    combined = f"{thread_contract}\n{prompt or ''}".strip()
    return story_video_request_detected(combined, preserve_thread_context=True)


def _looks_like_negative_visual_generation_instruction(lowered: str, compact: str) -> bool:
    negative_english = (
        "do not generate image",
        "do not generate images",
        "do not generate video",
        "do not generate videos",
        "don't generate image",
        "don't generate images",
        "don't generate video",
        "don't generate videos",
        "do not create image",
        "do not create images",
        "do not create video",
        "do not create videos",
        "no image generation",
        "no video generation",
        "text-only visual",
        "text only visual",
    )
    if any(pattern in lowered for pattern in negative_english):
        return True
    negative_chinese = (
        "不要產圖",
        "不要生圖",
        "不要生成圖片",
        "不要產生圖片",
        "不要製作圖片",
        "不要生成影片",
        "不要產生影片",
        "不要製作影片",
        "先不用產圖",
        "先不用生圖",
        "不用產圖",
        "不用生圖",
        "不能產圖",
        "不能生圖",
        "不得產圖",
        "不准產圖",
        "不能生成圖片",
        "不能生成影片",
        "禁止產圖",
        "禁止产图",
        "禁止生成",
        "不使用工具",
        "不要使用工具",
        "純文字",
        "纯文字",
    )
    return any(pattern in compact for pattern in negative_chinese)


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

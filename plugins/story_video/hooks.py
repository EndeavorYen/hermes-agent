from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .audit import ProviderAudit, ProviderAuditEvent
from .policy import guard_tool_call
from .state import OperatorCall, StoryVideoRunContext, StoryVideoStateStore, parse_operator_call


_STORE = StoryVideoStateStore()
_MARKER = "STORY_VIDEO_OPERATOR_CONTEXT"
_MARKER_RE = re.compile(rf"{_MARKER}\s+(\{{.*\}})\s*$", re.DOTALL)
_SESSION_PHASE_AT_LLM_START: dict[str, str] = {}


def _digest_source(parts: list[str]) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"gateway:{digest[:24]}"


def _legacy_source_key(event: Any) -> str:
    source = getattr(event, "source", None)
    parts = [
        str(getattr(source, "platform", "") or ""),
        str(getattr(source, "scope_id", "") or ""),
        str(getattr(source, "chat_id", "") or ""),
        str(getattr(source, "thread_id", "") or ""),
        str(getattr(source, "user_id", "") or ""),
    ]
    return _digest_source(parts)


def _source_key(event: Any) -> str:
    source = getattr(event, "source", None)
    thread_id = str(
        getattr(source, "thread_id", "")
        or getattr(event, "reply_to_message_id", "")
        or ""
    )
    return _digest_source(
        [
            str(getattr(source, "platform", "") or ""),
            str(getattr(source, "chat_id", "") or ""),
            thread_id,
        ]
    )


def _marker_payload(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    match = _MARKER_RE.search(text.strip())
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_project_contract(context: StoryVideoRunContext) -> None:
    path = context.project_dir / "PROJECT_CONTRACT.md"
    if path.exists():
        return
    path.write_text(
        "\n".join(
            [
                "# Project Contract",
                "",
                f"- Run ID: `{context.run_id}`",
                f"- Topic: {context.topic}",
                f"- Duration: {context.duration}",
                f"- Visual style: {context.visual_style}",
                "- Workflow: `story-video-production-pipeline`",
                "- LLM provider: `openai-codex`",
                "- Source image provider: `openai-codex`",
                "- Generic video provider: forbidden",
                "- Render provider: local deterministic renderer",
                "- TTS provider: OpenAI when configured, otherwise locked local narration; no Edge/xAI fallback",
                "- Timeline: narration duration + 0.85s; max unreasoned hold 1.5s",
                "- Motion: stable center zoom 1.0 -> 1.025",
                "- Quality mode: quality-first shot-driven production",
                "- Five-minute shot target: 40-60 purpose-built shots",
                "- Candidate selection: OpenAI vision, threshold 80/100, no first-success promotion",
                "",
                "## Original Request",
                "",
                context.original_request.strip(),
                "",
            ]
        ),
        encoding="utf-8",
    )


def pre_gateway_dispatch(*, event: Any, **_: Any) -> dict[str, Any] | None:
    text = str(getattr(event, "text", "") or "")
    source_key = _source_key(event)
    context = _STORE.for_source(source_key)
    if context is None:
        context = _STORE.for_source(_legacy_source_key(event))
        if context is not None:
            _STORE.bind_source(context, source_key)
    call = parse_operator_call(text, has_active_project=context is not None)
    if call is None:
        return None
    payload = {
        "action": call.action,
        "topic": call.topic,
        "duration": call.duration,
        "visual_style": call.visual_style,
        "repair_request": call.repair_request,
        "source_key": source_key,
        "original_request": text,
    }
    rewritten = f"{text}\n\n{_MARKER} {json.dumps(payload, ensure_ascii=False)}"
    return {"action": "rewrite", "text": rewritten}


def pre_llm_call(
    *,
    session_id: str = "",
    user_message: Any = "",
    **_: Any,
) -> dict[str, str] | None:
    payload = _marker_payload(user_message)
    if payload is None:
        context = _STORE.for_session(session_id)
        if context is None:
            call = parse_operator_call(str(user_message or ""), has_active_project=False)
            if call is None:
                return None
            context = _STORE.create_or_load(
                source_key=f"session:{session_id}",
                session_id=session_id,
                call=call,
                original_request=str(user_message or ""),
            )
            _write_project_contract(context)
            action = call.action
        else:
            action = "continue"
    else:
        call = OperatorCall(
            action=str(payload.get("action") or "continue"),
            topic=str(payload.get("topic") or ""),
            duration=str(payload.get("duration") or ""),
            visual_style=str(payload.get("visual_style") or ""),
            repair_request=str(payload.get("repair_request") or ""),
        )
        context = _STORE.create_or_load(
            source_key=str(payload.get("source_key") or f"session:{session_id}"),
            session_id=session_id,
            call=call,
            original_request=str(payload.get("original_request") or user_message),
        )
        _write_project_contract(context)
        action = str(payload.get("action") or "continue")

    if session_id:
        _SESSION_PHASE_AT_LLM_START[session_id] = context.phase

    instruction = (
        f"STORY_VIDEO_RUN_CONTEXT run_id={context.run_id} phase={context.phase} "
        f"project_dir={context.project_dir}. Operator action={action}. "
        "This structured session is authoritative even when individual scene prompts "
        "do not mention story video. Every image_generate call MUST pass "
        "provider=openai-codex. Never call generic video_generate for the body, "
        "and never use xAI/Grok through terminal or delegation. Use local locked "
        "narration/render components only; generic text_to_speech is forbidden. "
        "Complete the current phase in this turn; do not stop after announcing "
        "what you will do. During planning, immediately create script.md, storyboard.md, "
        "scene_ledger.json, production_checklist.json, script_quality_report.json, "
        "and pronunciation_lexicon.json in project_dir from the original request "
        "and a proactive zh-TW risk-term scan; PROJECT_CONTRACT.md already exists. "
        "pronunciation_lexicon.json MUST use schema "
        "story_video_pronunciation_lexicon_v1, \"language\": \"zh-TW\", "
        "\"review_status\": \"PASS\", and entries containing display, spoken, "
        "expected_pinyin, source, and risk. Because local Qwen has no phoneme input, "
        "high-risk spoken aliases MUST differ from display text, for example "
        "三疊紀 -> 三碟紀. "
        "Apply the story-video-script-director and story-video-production-pipeline "
        "quality contracts. A scene is a narrative unit and MUST contain purpose-built "
        "shots with narration spans, viewer takeaway, subject, action, evidence detail, "
        "shot scale, focal point, acceptance criteria, and risk class. Quality-first "
        "five-minute productions target 40-60 shots with close-up evidence coverage. "
        "During voice, compile display text to low-ambiguity spoken text with the "
        "project pronunciation lexicon and require qc/pronunciation_qc_report.json. "
        "Do not inspect other story-video projects, source code, memory, or unrelated "
        "skills, and do not "
        "invoke brainstorming, nested Hermes sessions, web research, or media "
        "generation unless the operator explicitly requests them. The output gate "
        "validates the phase automatically. Use story_video_control only when it "
        "is exposed as a direct tool; never invoke it through terminal."
    )
    return {"context": instruction}


def _provider_from_args(args: dict[str, Any]) -> str:
    return str(
        args.get("provider")
        or args.get("_provider")
        or args.get("image_provider")
        or ""
    )


def pre_tool_call(
    *,
    tool_name: str = "",
    args: dict[str, Any] | None = None,
    session_id: str = "",
    turn_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> dict[str, str] | None:
    context = _STORE.for_session(session_id)
    if context is None:
        return None
    payload = dict(args or {})
    message = guard_tool_call(context, tool_name, payload)
    if message is None:
        return None
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="tool",
            phase=context.phase,
            provider=_provider_from_args(payload),
            model=str(payload.get("model") or payload.get("_model") or ""),
            status="blocked",
            tool=tool_name,
            session_id=session_id,
            turn_id=turn_id,
            request_id=tool_call_id,
            detail={"reason": message},
        )
    )
    return {"action": "block", "message": message}


def pre_api_request(
    *,
    session_id: str = "",
    turn_id: str = "",
    api_request_id: str = "",
    provider: str = "",
    model: str = "",
    **_: Any,
) -> None:
    context = _STORE.for_session(session_id)
    if context is None:
        return
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase=context.phase,
            provider=provider,
            model=model,
            status="sent",
            session_id=session_id,
            turn_id=turn_id,
            request_id=api_request_id,
        )
    )


def post_api_request(**kwargs: Any) -> None:
    _record_api_result("ok", kwargs)


def api_request_error(**kwargs: Any) -> None:
    _record_api_result("error", kwargs)


def _record_api_result(status: str, payload: dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "")
    context = _STORE.for_session(session_id)
    if context is None:
        return
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api_result",
            phase=context.phase,
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("response_model") or payload.get("model") or ""),
            status=status,
            session_id=session_id,
            turn_id=str(payload.get("turn_id") or ""),
            request_id=str(payload.get("api_request_id") or ""),
        )
    )


def post_tool_call(
    *,
    tool_name: str = "",
    result: Any = None,
    status: str = "",
    session_id: str = "",
    turn_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> None:
    context = _STORE.for_session(session_id)
    if context is None or tool_name not in {
        "image_generate",
        "video_generate",
        "visual_package_generate",
        "text_to_speech",
    }:
        return
    parsed: dict[str, Any] = {}
    if isinstance(result, dict):
        parsed = result
    elif isinstance(result, str):
        try:
            candidate = json.loads(result)
            parsed = candidate if isinstance(candidate, dict) else {}
        except json.JSONDecodeError:
            parsed = {}
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="image" if tool_name == "image_generate" else "tool",
            phase=context.phase,
            provider=str(parsed.get("provider") or ""),
            model=str(parsed.get("model") or ""),
            status=status or ("ok" if parsed.get("success") else "error"),
            tool=tool_name,
            session_id=session_id,
            turn_id=turn_id,
            request_id=tool_call_id,
        )
    )


def subagent_start(
    *,
    parent_session_id: str = "",
    child_session_id: str = "",
    **_: Any,
) -> None:
    context = _STORE.for_session(parent_session_id)
    if context is not None and child_session_id:
        _STORE.bind_session(context, child_session_id)


def transform_llm_output(
    *,
    response_text: str,
    session_id: str = "",
    **_: Any,
) -> str | None:
    context = _STORE.for_session(session_id)
    if context is None:
        return None
    text = re.sub(
        r"\n*Raphael (?:提示|下一步)：[^\n]*$",
        "",
        str(response_text or "").rstrip(),
    )
    phase_at_start = _SESSION_PHASE_AT_LLM_START.pop(session_id, None)
    if phase_at_start == context.phase and context.phase != "complete":
        from .tools import story_video_control

        validation = json.loads(
            story_video_control(
                {"action": "validate"},
                session_id=session_id,
                store=_STORE,
            )
        )
        context = _STORE.for_session(session_id) or context
        proof = str(validation.get("proof") or "")
        if validation.get("success") is True:
            text = f"{text}\n\n{proof}" if proof else text
        else:
            details = [
                *validation.get("missing", []),
                *validation.get("violations", []),
            ]
            detail = "、".join(str(item) for item in details if item) or "缺少 phase proof"
            text = "\n".join(
                [
                    f"狀態：故事影片 {phase_at_start} 尚未通過 phase proof。",
                    f"風險：{detail}",
                    proof,
                ]
            ).rstrip()
    text = _guard_render_delivery(text, context)
    if not context.next_call:
        return text
    return f"{text}\n\nRaphael 下一步：回覆「{context.next_call}」。"


_VIDEO_PATH_RE = re.compile(
    r"(?:MEDIA:)?((?:/|~/)[^\s`\"'<>]+\.(?:mp4|mov|m4v|webm))",
    re.IGNORECASE,
)


def _selected_render_path(context: StoryVideoRunContext) -> Path | None:
    for relative in ("render_manifest.json", "manifests/render_manifest.json"):
        manifest_path = context.project_dir / relative
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        output = manifest.get("output") if isinstance(manifest, dict) else None
        value = output.get("path") if isinstance(output, dict) else None
        if not str(value or "").strip():
            continue
        selected = Path(str(value))
        if not selected.is_absolute():
            selected = context.project_dir / selected
        return selected.expanduser().resolve()
    return None


def _guard_render_delivery(text: str, context: StoryVideoRunContext) -> str:
    matches = list(_VIDEO_PATH_RE.finditer(text))
    if not matches:
        return text
    selected = _selected_render_path(context) if context.phase == "complete" else None
    referenced = {Path(match.group(1)).expanduser().resolve() for match in matches}
    if selected is not None and referenced == {selected} and selected.is_file():
        return text
    return "\n".join(
        [
            "STORY_VIDEO_DELIVERY_BLOCKED",
            "狀態：拒絕上傳未經目前 render manifest 選中的影片。",
            "風險：可能是舊成品、跨專案成品，或尚未通過 render proof。",
        ]
    )

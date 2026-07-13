from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .audit import ProviderAudit, ProviderAuditEvent
from .policy import guard_tool_call
from .state import OperatorCall, StoryVideoRunContext, StoryVideoStateStore, parse_operator_call
from .visual_judge import _next_batch_work


_STORE = StoryVideoStateStore()
_MARKER = "STORY_VIDEO_OPERATOR_CONTEXT"
_MARKER_RE = re.compile(rf"{_MARKER}\s+(\{{.*\}})\s*$", re.DOTALL)
_SESSION_PHASE_AT_LLM_START: dict[str, str] = {}
_SETUP_BLOCKER_RE = re.compile(
    r"(?:(?:quota|rate.?limit|配額|額度).{0,32}"
    r"(?:exhausted|exceeded|blocked|required|耗盡|用完|不足)|"
    r"(?:missing|invalid|expired|缺少|失效|過期).{0,32}"
    r"(?:credential|authentication|authorization|subscription|"
    r"憑證|认证|認證|授權|订阅|訂閱)|setup.?required)",
    re.IGNORECASE,
)
_PHASE_BLOCKED_RE = re.compile(
    r"STORY_VIDEO_PHASE_PROOF:\s+[a-z]+\s+BLOCKED",
    re.IGNORECASE,
)
_AUTOPILOT_STALL_LIMIT = 3


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
        "auto_mode": call.auto_mode,
        "new_project": call.new_project,
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
            call = parse_operator_call(
                str(user_message or ""), has_active_project=True
            )
            if call is None:
                action = "continue"
            else:
                context = _STORE.create_or_load(
                    source_key=context.source_key,
                    session_id=session_id,
                    call=call,
                    original_request=str(user_message or ""),
                )
                action = call.action
    else:
        call = OperatorCall(
            action=str(payload.get("action") or "continue"),
            topic=str(payload.get("topic") or ""),
            duration=str(payload.get("duration") or ""),
            visual_style=str(payload.get("visual_style") or ""),
            repair_request=str(payload.get("repair_request") or ""),
            auto_mode=payload.get("auto_mode") is True,
            new_project=payload.get("new_project") is True,
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
        "quality contracts. scene_ledger.json MUST use exact machine keys: root schema="
        "story_video_scene_ledger_v2, quality_contract_version=3, production_type, "
        "target_duration_sec, visual_style, audience_profile, engagement_profile, "
        "and scenes. audience_profile MUST declare age_band, knowledge_level, "
        "attention_style, and safety_intensity. engagement_profile MUST declare mode, "
        "energy, humor, and sensationalism_forbidden=true. Each scenes item MUST contain scene_id, "
        "narrative_role, viewer_takeaway, and a scene.shots array; never put shot "
        "objects directly in scenes. A scene is a narrative unit; every purpose-built "
        "shot MUST use shot_id, narration_text, narrative_role, viewer_takeaway, "
        "subject, action, evidence_detail, shot_scale, camera_angle, focal_point, "
        "subtitle_safe_area, acceptance_criteria, risk_class, engagement_role, "
        "attention_hook, story_moment, action_consequence, composition_energy, "
        "viewer_emotion, engagement_criteria, and visual_truth_mode. "
        "visual_truth_mode MUST distinguish direct_evidence, reconstruction, inference, "
        "process, comparison, or mixed_evidence_reconstruction. A breathe shot requires "
        "calm_reason; mixed evidence and reconstruction requires evidence_bridge. Do not translate "
        "these keys. acceptance_criteria MUST be a non-empty JSON array of strings. "
        "shot_scale MUST be exactly one of "
        "establishing|wide|medium|close_up|macro|insert. Quality-first density is "
        "8-12 shots per minute, so 30 seconds requires 4-6 shots and five-minute "
        "productions require 40-60, with close-up evidence coverage. "
        "script_quality_report.json MUST use schema=story_video_script_quality_v1, "
        "quality_contract_version=3, status=PASS, production_type, shot_count, and "
        "checks. checks MUST be an object whose visual_evidence, narrative_roles, "
        "claim_confidence, audience_engagement, and visual_truth values are PASS, not a list. "
        "script.md MUST contain narration-only sections headed exactly ### S00, "
        "### S01, and so on for the local voice parser. Preserve correct display "
        "spelling in all narration and never write spoken aliases into script.md; "
        "aliases belong only in pronunciation_lexicon.json and are compiled at voice time. "
        "During batch, first call story_video_quality_control "
        "action=next_batch_work and execute only the returned shot. Existing "
        "repair_required work always takes priority over generating a new shot. After "
        "an operation=rejudge_existing response, do not generate an image; pass the "
        "returned candidate and repair_round directly to judge_candidates so legacy "
        "selected art receives the current engagement QC without image quota burn. After "
        "judging that candidate, call next_batch_work again and repeat until it reports "
        "work_status=complete. During keyframes, choose representative ledger shots "
        "until the keyframe scale-coverage gate passes. In both phases, generate "
        "exactly one candidate per shot at a time, "
        "always use the candidate_id_hint returned by compile_prompt, and carry its "
        "repair directive into generation. If compile_prompt returns strategy_reset=true, "
        "pass strategy_reset=true with that single candidate; this is a one-candidate "
        "layout reset and must never restart the normal five-round budget. "
        "Always pass the returned repair_strategy with the candidate so QC history can "
        "advance anatomy, scientific, layout, and contextual repair independently. Always "
        "pass the exact returned shot_contract_hash with the generated candidate; never "
        "judge a candidate against a changed scene-ledger contract. "
        "then call story_video_quality_control action=judge_candidates. That tool is the "
        "only writer of the canonical shot_candidate_manifest.json outputs[] contract; "
        "never edit shot_candidate_manifest.json manually and never invent judge scores "
        "or vision evidence. Complete every required shot in the current phase before "
        "stopping. "
        "During voice, compile display text to low-ambiguity spoken text with the "
        "project pronunciation lexicon and require qc/pronunciation_qc_report.json. "
        "During render, call story_video_quality_control action=prepare_render; it is "
        "the only writer of render_input.json. Never hand-edit render_input.json or "
        "invent renderer aliases. Then run the story-video production pipeline's "
        "render_story_video.py for project_dir and validate render. "
        "Do not inspect other story-video projects, source code, memory, or unrelated "
        "skills, and do not "
        "invoke brainstorming, nested Hermes sessions, web research, or media "
        "generation unless the operator explicitly requests them. The output gate "
        "validates the phase automatically. Use story_video_control only when it "
        "is exposed as a direct tool; never invoke it through terminal."
    )
    if action == "package":
        instruction += (
            " The operator requested a YouTube review package. Do not upload. Use the "
            "story-video-production-pipeline release packaging scripts to create one "
            "dedicated OpenAI/openai-codex release-art source with no baked-in text, "
            "then compose exact Traditional Chinese thumbnail/opening/ending typography "
            "locally. Produce polished title, description, tags, pinned comment, and a "
            "REVIEW_REQUIRED manifest bound to artifact hashes. If release cards changed, "
            "rerender and rerun render QC before reporting the review package."
        )
    elif action == "approve_upload":
        instruction += (
            " The operator explicitly approved YouTube upload, but not public release. "
            "Verify the current review package hashes, create the approval record, upload "
            "with privacy=private, and verify the persisted YouTube record. Never infer "
            "public visibility from this command; public release requires a separate "
            "explicit approval."
        )
    if context.auto_mode:
        instruction += (
            " STORY_VIDEO AUTOPILOT is enabled. Continue autonomously through planning, "
            "keyframes, batch, voice, render, and complete. Call story_video_control "
            "action=validate after finishing each phase. If validation is BLOCKED, "
            "execute the exact repair_request immediately and validate again. Do not ask "
            "the operator to reply with continue or repair. Stop only for an operator "
            "setup blocker such as missing credentials, exhausted quota, or unavailable "
            "required provider; otherwise finish the production and delivery."
        )
    return {"context": instruction}


def _autopilot_progress_token(context: StoryVideoRunContext) -> str:
    evidence: dict[str, Any] = {"phase": context.phase}
    if context.phase in {"keyframes", "batch"}:
        path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        evidence["outputs"] = [
            (
                str(row.get("shot_id") or ""),
                str(row.get("candidate_id") or ""),
                str(row.get("status") or ""),
                row.get("selected") is True,
            )
            for row in payload.get("outputs") or []
            if isinstance(row, dict)
        ]
    elif context.phase == "voice":
        path = context.project_dir / "manifests" / "narration_manifest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        evidence["outputs"] = [
            str(row.get("scene_id") or "")
            for row in payload.get("outputs") or []
            if isinstance(row, dict)
        ]
    elif context.phase == "render":
        evidence["artifacts"] = [
            (name, (context.project_dir / name).is_file())
            for name in (
                "render_input.json",
                "manifests/render_manifest.json",
                "render_qc.json",
                "video/final.mp4",
            )
        ]
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def auto_continue_llm_output(
    *,
    session_id: str = "",
    response_text: str = "",
    recoverable_transport_error: bool = False,
    turn_error: str = "",
    **_: Any,
) -> dict[str, str] | None:
    context = _STORE.for_session(session_id)
    if context is None or not context.auto_mode or not context.next_call:
        return None
    if _SETUP_BLOCKER_RE.search(
        f"{response_text or ''}\n{turn_error or ''}"
    ):
        return None
    if (
        _PHASE_BLOCKED_RE.search(str(response_text or ""))
        or recoverable_transport_error
    ):
        reason = "transport" if recoverable_transport_error else "blocked"
        signature = (
            f"{context.phase}:{reason}:{context.next_call}:"
            f"{_autopilot_progress_token(context)}"
        )
        stall_count = (
            context.autopilot_stall_count + 1
            if context.autopilot_last_signature == signature
            else 1
        )
        context = _STORE.update(
            context,
            autopilot_last_signature=signature,
            autopilot_stall_count=stall_count,
        )
        if stall_count >= _AUTOPILOT_STALL_LIMIT:
            return None
    elif context.autopilot_stall_count:
        context = _STORE.update(
            context,
            autopilot_last_signature="",
            autopilot_stall_count=0,
        )
    next_action = context.next_call
    next_work_instruction = ""
    if context.phase == "batch":
        try:
            next_work = _next_batch_work(context)
        except (OSError, TypeError, ValueError):
            next_work = {}
        if next_work.get("work_status") == "ready":
            if next_work.get("operation") == "rejudge_existing":
                candidate = json.dumps(
                    next_work["candidate"],
                    ensure_ascii=False,
                    sort_keys=True,
                )
                next_action = (
                    "story_video_quality_control action=judge_candidates "
                    f"shot_id={next_work['shot_id']} "
                    f"repair_round={next_work['repair_round']} "
                    f"candidates=[{candidate}]"
                )
                next_work_instruction = (
                    " This is operation=rejudge_existing with candidate_budget=0. "
                    "Judge that exact existing candidate; do not call compile_prompt, "
                    "invoke image generation, or contact any image provider."
                )
            else:
                next_action = (
                    "story_video_quality_control action=compile_prompt "
                    f"shot_id={next_work['shot_id']}"
                )
                next_work_instruction = (
                    f" Use candidate_id_hint={next_work['candidate_id_hint']} to "
                    f"perform the {next_work['operation']} image/QC cycle with "
                    f"repair_strategy={next_work['repair_strategy']}. "
                    "Do not generate another shot first."
                )
        elif next_work.get("work_status") == "human_review_required":
            return None
    return {
        "action": "continue",
        "message": (
            f"STORY_VIDEO_AUTOPILOT run_id={context.run_id} phase={context.phase}. "
            f"Execute the next action now: {next_action}.{next_work_instruction} "
            "Do not merely report "
            "status; complete the phase, repair every gate failure that is locally "
            "actionable, validate it, and continue toward final delivery."
        ),
    }


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
    payload = args if isinstance(args, dict) else {}
    message: str | None = None
    if str(tool_name or "").strip().lower() == "image_generate":
        explicit_provider = payload.get("provider") or payload.get("_provider")
        if explicit_provider:
            message = guard_tool_call(context, tool_name, payload)
        if message is None:
            payload["_provider"] = "openai-codex"
    if message is None:
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
    if _SETUP_BLOCKER_RE.search(text):
        pass
    elif phase_at_start == context.phase == "batch":
        try:
            next_work = _next_batch_work(context)
        except (OSError, TypeError, ValueError):
            next_work = {}
        work_status = str(next_work.get("work_status") or "")
        if work_status == "ready":
            shot_id = str(next_work.get("shot_id") or "unknown")
            operation = str(next_work.get("operation") or "work")
            remaining = int(next_work.get("remaining_shot_count") or 0)
            text = "\n".join(
                (
                    f"故事影片 batch 自動製作中：目前處理 {shot_id}（{operation}）。",
                    f"STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS shot_id={shot_id} remaining={remaining}",
                )
            )
        elif work_status == "human_review_required":
            shot_id = str(next_work.get("shot_id") or "unknown")
            error = str(next_work.get("error") or "目前鏡頭需要人工判斷")
            text = "\n".join(
                (
                    f"故事影片 batch 需要處理目前鏡頭 {shot_id}：{error}",
                    f"STORY_VIDEO_PHASE_ATTENTION: batch REVIEW_REQUIRED shot_id={shot_id}",
                )
            )
        elif work_status == "complete":
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
            text = f"{text}\n\n{proof}" if proof else text
    elif phase_at_start == context.phase and context.phase != "complete":
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
    if not context.next_call or context.auto_mode:
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

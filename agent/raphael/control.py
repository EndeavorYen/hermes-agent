from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import re
from typing import Any

from agent.raphael.artifacts import latest_selected_artifact_id

BASE_LLM_PROVIDER = "openai-codex"
BASE_LLM_MODEL = ""
VISUAL_AGENT_LLM_PROVIDER = "xai-oauth"
VISUAL_AGENT_LLM_MODEL = ""
VISUAL_MEDIA_PROVIDER_DEFAULT = "xai"
VISUAL_MEDIA_MODEL_DEFAULT = "grok-imagine-image-quality"


@dataclass(frozen=True)
class RaphaelGoalDecision:
    summary: str
    target_artifact: str
    success_conditions: tuple[str, ...]
    phase: str
    blockers: tuple[str, ...] = ()
    active_artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RaphaelRouteDecision:
    base_llm_provider: str = BASE_LLM_PROVIDER
    base_llm_model: str = BASE_LLM_MODEL
    visual_agent_llm_provider: str | None = None
    visual_agent_llm_model: str | None = None
    visual_media_provider: str | None = None
    visual_media_model: str | None = None
    visual_media_provider_source: str | None = None
    handoff_tool: str | None = None
    bypass_base_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RaphaelEvidenceDecision:
    required_proofs: tuple[str, ...]
    failure_layer: str | None = None
    next_repair_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RaphaelControlDecision:
    mode: str
    goal: RaphaelGoalDecision
    route: RaphaelRouteDecision
    evidence: RaphaelEvidenceDecision
    next_action: str
    reference_resolution: str = "not_applicable"
    clarification_question: str | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "goal": self.goal.to_dict(),
            "route": self.route.to_dict(),
            "evidence": self.evidence.to_dict(),
            "next_action": self.next_action,
            "reference_resolution": self.reference_resolution,
            "clarification_question": self.clarification_question,
            "confidence": self.confidence,
        }


_EDIT_MARKERS = (
    "modify",
    "edit",
    "revise",
    "change",
    "improve",
    "fix",
    "adjust",
    "replace",
    "make it",
    "再修",
    "修改",
    "調整",
    "改進",
    "改善",
    "修正",
    "補上",
    "改成",
    "換成",
    "亮一點",
    "暗一點",
    "微笑",
    "比例",
    "不要變",
    "不要",
    "而不是",
    "精修",
    "修圖",
    "潤飾",
    "美化",
)
_TOOL_TASK_MARKERS = (
    "install",
    "delete",
    "remove",
    "patch",
    "commit",
    "push",
    "deploy",
    "release",
    "cron",
    "skill",
    "memory",
    "plugin",
    "runtime",
    "bug",
    "log",
    "安裝",
    "刪除",
    "部署",
    "發布",
    "上線",
    "實作",
    "修復",
    "設定",
    "檢查",
    "检查",
)
_TEXT_ONLY_ANALYSIS_MARKERS = (
    "llm-only",
    "llm only",
    "text-only",
    "text only",
    "純文字",
    "文字分析",
    "只分析",
    "只回答",
    "不要呼叫任何工具",
    "不呼叫工具",
    "不要用工具",
    "不用工具",
    "no tool",
    "no-tools",
    "without tools",
)
_NO_TOOL_ANALYSIS_MARKERS = (
    "不要呼叫任何工具",
    "不要呼叫工具",
    "不呼叫工具",
    "不能呼叫工具",
    "不得呼叫工具",
    "不准呼叫工具",
    "不要用工具",
    "不用工具",
    "不能用工具",
    "不得用工具",
    "不准用工具",
    "no tools",
    "no tool",
    "no-tools",
    "without tools",
)
_NO_MEDIA_ANALYSIS_MARKERS = (
    "不要產圖",
    "不要生圖",
    "不要圖片",
    "不要影片",
    "不產圖",
    "不能產圖",
    "不得產圖",
    "不准產圖",
    "不能生圖",
    "不得生圖",
    "不准生圖",
    "不生成圖片",
    "不生成影片",
    "不能生成圖片",
    "不能生成影片",
    "不得生成圖片",
    "不得生成影片",
    "不准生成圖片",
    "不准生成影片",
    "no image",
    "no images",
    "no video",
    "no media",
)
_RUNTIME_ANALYSIS_MARKERS = (
    "runtime",
    "routing",
    "route",
    "agent",
    "provider",
    "gateway",
    "bug",
    "failure",
    "模式",
    "路由",
    "故障",
    "修復",
    "驗證",
    "分析",
)
_LEARN_INTENT_MARKERS = (
    "/learn",
    "learn this",
    "learn from this",
    "learn the workflow",
    "learn this workflow",
    "distill this",
    "學起來",
    "學成",
    "學一下",
    "記成",
    "整理成",
)
_LEARN_SKILL_TARGET_MARKERS = (
    "skill",
    "skills",
    "skill.md",
    "技能",
    "流程",
    "workflow",
    "runbook",
    "playbook",
    "procedure",
    "可重用",
    "可複用",
    "reusable",
)


def build_raphael_control_decision(
    user_message: Any,
    *,
    active_mission: Any | None = None,
    attachments: Sequence[str] | None = None,
    conversation_history: Sequence[Mapping[str, Any]] | None = None,
    visual_plan: Mapping[str, Any] | None = None,
    visual_result: Mapping[str, Any] | None = None,
) -> RaphaelControlDecision:
    prompt = _extract_text(user_message)
    attachment_list = tuple(
        str(item).strip()
        for item in (attachments or ())
        if str(item).strip() and _is_visual_attachment_ref(str(item))
    )
    active_artifact_id = latest_selected_artifact_id(conversation_history)

    if active_mission is not None and _looks_like_mission_followup(prompt):
        mission_goal = str(getattr(active_mission, "goal", "") or prompt)
        mission_proofs = tuple(getattr(active_mission, "required_proofs", ()) or ())
        return RaphaelControlDecision(
            mode="tool_task",
            goal=RaphaelGoalDecision(
                summary=mission_goal,
                target_artifact="active_mission",
                active_artifact_id=getattr(active_mission, "active_artifact_id", None),
                success_conditions=tuple(
                    getattr(active_mission, "success_conditions", ()) or ()
                ),
                phase="continue_active_mission",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=mission_proofs or ("focused_tests", "diff_hygiene")
            ),
            next_action=str(
                getattr(active_mission, "next_action", "") or "continue_active_mission"
            ),
            confidence=0.94,
        )

    if not attachment_list and _looks_like_ambiguous_goal(prompt):
        question = "請補充要處理的目標、範圍與預期成品。"
        return RaphaelControlDecision(
            mode="needs_clarification",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="pending_goal",
                success_conditions=("goal_scope_confirmed",),
                phase="clarify_goal",
                blockers=("ambiguous_goal",),
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=("clarification_question_present",),
                failure_layer="intent_routing",
                next_repair_action="ask_precise_clarification",
            ),
            next_action="ask_precise_clarification",
            clarification_question=question,
            confidence=0.91,
        )

    if _looks_like_story_video_implementation_task(prompt):
        return RaphaelControlDecision(
            mode="tool_task",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="runtime_or_repo_state",
                success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
                phase="plan_execute_verify",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=("focused_tests", "runtime_smoke_when_live_wiring"),
            ),
            next_action="plan_execute_verify",
            confidence=0.9,
        )

    if _looks_like_story_video_orchestration(prompt):
        return RaphaelControlDecision(
            mode="general_conversation",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="story_video_workflow",
                success_conditions=("story_video_phase_proof",),
                phase="story_video_orchestration",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=("story_video_phase_proof",),
            ),
            next_action="continue_story_video_workflow",
            confidence=0.98,
        )

    if _looks_like_visual_prompt_edit_task(prompt):
        return RaphaelControlDecision(
            mode="general_conversation",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="answer",
                success_conditions=("answer_matches_user_intent", "no_generation_tool_call"),
                phase="answer",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(required_proofs=("answer_grounded_in_user_prompt",)),
            next_action="answer_directly",
            confidence=0.82,
        )

    if _is_visual_prompt_disclosure_request(prompt):
        return RaphaelControlDecision(
            mode="prompt_disclosure",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="latest_visual_prompt_trace",
                success_conditions=(
                    "answer_from_recorded_prompt_trace",
                    "do_not_regenerate_media",
                ),
                phase="prompt_trace_lookup",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=("prompt_trace_available", "no_generation_tool_call"),
            ),
            next_action="answer_from_latest_visual_prompt_trace",
            confidence=0.96,
        )

    if _looks_like_text_only_runtime_analysis(prompt):
        return RaphaelControlDecision(
            mode="runtime_analysis",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="answer",
                success_conditions=(
                    "text_only_plan",
                    "no_tool_call",
                    "no_provider_attempt",
                ),
                phase="text_only_analysis",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=(
                    "text_only_plan",
                    "no_tool_call",
                    "no_provider_attempt",
                ),
            ),
            next_action="answer_with_runtime_analysis",
            confidence=0.86,
        )

    missing_reference = _missing_reference_index(prompt, len(attachment_list))
    if missing_reference is not None:
        question = (
            f"你提到 ref{missing_reference}，但目前只看到 "
            f"{len(attachment_list)} 個 reference；請補上 ref{missing_reference} "
            "或說明要改用哪一張。"
        )
        return RaphaelControlDecision(
            mode="needs_clarification",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="pending_visual_artifact",
                success_conditions=("reference_mapping_confirmed",),
                phase="clarify_reference_mapping",
                blockers=(f"missing_ref{missing_reference}",),
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=("reference_mapping_evidence",),
                failure_layer="intent_routing",
                next_repair_action="ask_precise_clarification",
            ),
            next_action="ask_precise_clarification",
            reference_resolution="clarify_missing_reference",
            clarification_question=question,
            confidence=0.9,
        )

    plan = dict(visual_plan or _plan_visual_agent_request(prompt, attachments=list(attachment_list)))
    plan_args = dict(plan.get("arguments") or {})
    if active_artifact_id and _looks_like_followup_edit(prompt):
        plan_args.setdefault("include_image", True)
        plan_args.setdefault("include_video", False)
        plan_args.setdefault("image_provider", VISUAL_MEDIA_PROVIDER_DEFAULT)
        plan_args.setdefault("image_provider_source", "visual_agent_default")
        plan = {
            **plan,
            "should_use_visual_package": True,
            "confidence": max(float(plan.get("confidence") or 0.0), 0.84),
            "reason": "current_artifact_followup_edit",
            "arguments": plan_args,
            "provider_contract": plan.get("provider_contract")
            or _default_provider_contract(plan_args.get("image_provider")),
        }

    if plan.get("should_use_visual_package"):
        mode = "visual_agent_edit" if active_artifact_id and _looks_like_followup_edit(prompt) else "visual_agent_generation"
        reference_resolution, extra_proofs = _reference_resolution(prompt, attachment_list, plan_args)
        if (
            reference_resolution == "multi_candidate_validation"
            and not _explicitly_allows_multi_candidate_reference_validation(prompt)
        ):
            mentioned = _mentioned_ref_indices(prompt)
            ref_text = "/".join(f"ref{index}" for index in mentioned) or "多張 reference"
            question = (
                f"你提到 {ref_text}，但沒有明確指定每張 reference 要當角色、姿勢、服裝還是風格；"
                "請補充對應，或明確允許我用多候選策略自行驗證。"
            )
            return RaphaelControlDecision(
                mode="needs_clarification",
                goal=RaphaelGoalDecision(
                    summary=_summary(prompt),
                    target_artifact="pending_visual_artifact",
                    success_conditions=("reference_mapping_confirmed",),
                    phase="clarify_reference_mapping",
                    blockers=("ambiguous_reference_roles",),
                ),
                route=RaphaelRouteDecision(),
                evidence=RaphaelEvidenceDecision(
                    required_proofs=("reference_mapping_evidence",),
                    failure_layer="intent_routing",
                    next_repair_action="ask_precise_clarification",
                ),
                next_action="ask_precise_clarification",
                reference_resolution="clarify_ambiguous_reference_roles",
                clarification_question=question,
                confidence=0.88,
            )
        return RaphaelControlDecision(
            mode=mode,
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact=(
                    "current_visual_artifact"
                    if mode == "visual_agent_edit"
                    else "new_visual_package"
                ),
                active_artifact_id=active_artifact_id if mode == "visual_agent_edit" else None,
                success_conditions=(
                    "artifact_continuity",
                    "selected_current_artifact_only",
                    "quality_gate_passed",
                )
                if mode == "visual_agent_edit"
                else (
                    "selected_current_artifact_only",
                    "quality_gate_passed",
                    "clean_delivery",
                ),
                phase="route_and_handoff",
            ),
            route=_route_from_visual_plan(plan_args, plan),
            evidence=RaphaelEvidenceDecision(
                required_proofs=tuple(
                    dict.fromkeys(
                        (
                            "direct_handoff_metadata",
                            "provider_attempt_evidence",
                            "artifact_quality_evidence",
                            "selected_current_artifact_only",
                            "stale_artifact_guard",
                            "delivery_cleanliness",
                            *_video_required_proofs(plan_args),
                            *extra_proofs,
                        )
                    )
                ),
                failure_layer=classify_visual_failure_layer(visual_result),
                next_repair_action="classify_failure_then_repair_or_fallback",
            ),
            next_action="call_visual_agent_generate",
            reference_resolution=reference_resolution,
            confidence=float(plan.get("confidence") or 0.0),
        )

    if _is_visual_feedback_only_text(prompt):
        return RaphaelControlDecision(
            mode="visual_feedback",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="current_visual_artifact",
                active_artifact_id=active_artifact_id,
                success_conditions=("feedback_attributed", "no_generation_tool_call"),
                phase="feedback_attribution",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=("feedback_attribution", "learning_trace_candidate"),
            ),
            next_action="record_visual_feedback",
            confidence=0.86,
        )

    if _looks_like_learn_skill_request(prompt):
        return RaphaelControlDecision(
            mode="learn_skill",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="reusable_skill",
                success_conditions=(
                    "source_and_requirements_preserved",
                    "skill_authoring_standards_applied",
                    "durable_skill_write_auditable",
                ),
                phase="learn_from_current_context",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=(
                    "learn_request_preserved",
                    "skill_authoring_standards_applied",
                    "skill_manage_write_evidence",
                ),
            ),
            next_action="dispatch_learn_skill",
            confidence=0.84,
        )

    if _contains_any(prompt, _TOOL_TASK_MARKERS):
        return RaphaelControlDecision(
            mode="tool_task",
            goal=RaphaelGoalDecision(
                summary=_summary(prompt),
                target_artifact="runtime_or_repo_state",
                success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
                phase="plan_execute_verify",
            ),
            route=RaphaelRouteDecision(),
            evidence=RaphaelEvidenceDecision(
                required_proofs=("focused_tests", "runtime_smoke_when_live_wiring"),
            ),
            next_action="plan_execute_verify",
            confidence=0.72,
        )

    return RaphaelControlDecision(
        mode="general_conversation",
        goal=RaphaelGoalDecision(
            summary=_summary(prompt),
            target_artifact="answer",
            success_conditions=("answer_matches_user_intent",),
            phase="answer",
        ),
        route=RaphaelRouteDecision(),
        evidence=RaphaelEvidenceDecision(required_proofs=("answer_grounded_in_context",)),
        next_action="answer_directly",
        confidence=0.55,
    )


def render_raphael_control_context(decision: RaphaelControlDecision) -> str:
    lines = [
        "Raphael Control Layer (ephemeral, internal):",
        f"mode: {decision.mode}",
        f"target_artifact: {decision.goal.target_artifact}",
        f"phase: {decision.goal.phase}",
        f"next_action: {decision.next_action}",
        f"reference_resolution: {decision.reference_resolution}",
    ]
    if decision.route.handoff_tool:
        lines.extend(
            [
                f"handoff_tool: {decision.route.handoff_tool}",
                f"bypass_base_llm: {'true' if decision.route.bypass_base_llm else 'false'}",
                (
                    "visual_agent_llm: "
                    f"{decision.route.visual_agent_llm_provider}/"
                    f"{decision.route.visual_agent_llm_model}"
                ),
                (
                    "visual_media_provider: "
                    f"{decision.route.visual_media_provider}"
                    f" ({decision.route.visual_media_provider_source or 'default'})"
                ),
            ]
        )
    if decision.clarification_question:
        lines.append(f"clarification_question: {decision.clarification_question}")
    if decision.evidence.required_proofs:
        lines.append("required_proofs: " + ", ".join(decision.evidence.required_proofs))
    if decision.evidence.failure_layer:
        lines.append(f"failure_layer: {decision.evidence.failure_layer}")
    if decision.mode == "learn_skill":
        lines.append("learn_command: /learn")
    return "\n".join(lines)


def classify_visual_failure_layer(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    provider_classes = payload.get("provider_failure_classes")
    if isinstance(provider_classes, Mapping):
        keys = {str(key).lower() for key in provider_classes}
        if keys & {"moderation_refusal", "content_policy", "safety_refusal"}:
            return "prompt_moderation"
        if any(
            token in key
            for key in keys
            for token in ("quota", "auth", "rate", "timeout", "provider", "account")
        ):
            return "provider_health"

    grok_web = payload.get("grok_web")
    if isinstance(grok_web, Mapping):
        doctor = str(grok_web.get("doctor_status") or "").lower()
        if doctor and doctor not in {"ok", "ready", "passed"}:
            return "browser_automation"

    delivery_recovery = payload.get("delivery_recovery")
    if isinstance(delivery_recovery, Mapping) and str(delivery_recovery.get("status") or "") == "blocked":
        return "delivery"
    if payload.get("missing_delivery_artifact_ids") or payload.get("unexpected_delivery_artifact_ids"):
        return "delivery"

    text = " ".join(
        str(payload.get(key) or "")
        for key in ("error", "message", "error_type", "package_status")
    ).lower()
    if any(token in text for token in ("quality gate", "candidate", "artifact quality", "visual quality")):
        return "artifact_quality"
    if any(token in text for token in ("browser", "composer", "cdp", "grok web")):
        return "browser_automation"
    if any(token in text for token in ("moderation", "content policy", "safety refusal")):
        return "prompt_moderation"
    if any(token in text for token in ("quota", "auth", "provider", "timeout", "rate limit")):
        return "provider_health"
    return "unknown"


def _route_from_visual_plan(
    arguments: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> RaphaelRouteDecision:
    contract = plan.get("provider_contract")
    contract = contract if isinstance(contract, Mapping) else {}
    provider_source = str(
        arguments.get("image_provider_source") or "visual_agent_default"
    )
    prompt_override = provider_source == "prompt_override"
    planner_model = _optional_route_text(contract.get("visual_agent_llm_model"))
    return RaphaelRouteDecision(
        visual_agent_llm_provider=(
            _optional_route_text(contract.get("visual_agent_llm_provider"))
            if planner_model
            else None
        ),
        visual_agent_llm_model=planner_model,
        visual_media_provider=(
            _optional_route_text(
                arguments.get("image_provider")
                or contract.get("visual_media_provider_override")
            )
            if prompt_override
            else None
        ),
        visual_media_model=None,
        visual_media_provider_source=provider_source,
        handoff_tool="visual_agent_generate",
        bypass_base_llm=True,
    )


def _optional_route_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _video_required_proofs(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    if arguments.get("include_video") is True:
        return (
            "image_first_video_source_evidence",
            "single_ranked_video_source_image",
        )
    return ()


def _reference_resolution(
    prompt: str,
    attachments: tuple[str, ...],
    arguments: Mapping[str, Any],
) -> tuple[str, tuple[str, ...]]:
    if not attachments:
        return "not_applicable", ()
    binding = arguments.get("reference_binding")
    if isinstance(binding, Mapping) and binding.get("reference_order"):
        if _ambiguous_multi_reference_roles(prompt, binding):
            return (
                "multi_candidate_validation",
                ("reference_mapping_evidence", "multi_candidate_validation"),
            )
        return "semantic_reference_roles", ("reference_mapping_evidence",)
    if _mentioned_ref_indices(prompt):
        return (
            "multi_candidate_validation",
            ("reference_mapping_evidence", "multi_candidate_validation"),
        )
    return (
        "collective_reference_set",
        ("reference_mapping_evidence", "multi_candidate_validation"),
    )


def _ambiguous_multi_reference_roles(prompt: str, binding: Mapping[str, Any]) -> bool:
    items = [item for item in binding.get("reference_order") or [] if isinstance(item, Mapping)]
    if len(items) < 2:
        return False
    mentioned = _mentioned_ref_indices(prompt)
    if len(mentioned) < 2:
        return False
    roles = {str(item.get("role_hint") or "") for item in items}
    if len(roles) != 1:
        return False
    return not _has_explicit_reference_role_assignment(prompt)


def _explicitly_allows_multi_candidate_reference_validation(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    markers = (
        "multi-candidate",
        "multi candidate",
        "candidate validation",
        "多候選",
        "多個候選",
        "候選策略",
        "自行判斷",
        "自動判斷",
        "由你判斷",
        "你來判斷",
        "如果對應不確定",
        "如果不確定",
    )
    return any(marker in lowered or marker in compact for marker in markers)


def _has_explicit_reference_role_assignment(prompt: str) -> bool:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    role_terms = (
        "角色",
        "人物",
        "身份",
        "臉",
        "髮型",
        "姿勢",
        "動作",
        "構圖",
        "鏡頭",
        "服裝",
        "衣服",
        "穿搭",
        "風格",
        "背景",
        "character",
        "identity",
        "person",
        "face",
        "hair",
        "pose",
        "composition",
        "camera",
        "wardrobe",
        "outfit",
        "style",
        "background",
    )
    role_alt = "|".join(re.escape(term) for term in role_terms)
    return bool(
        re.search(rf"(?:ref|reference|參考圖?|第)\d+(?:的|是|為|为|當作|当作|作為|作为|as|for|=|:)[^，,。.;；\n]*({role_alt})", compact)
        or re.search(rf"(?:ref|reference|參考圖?|第)\d+[^，,。.;；\n]*(?:都是|皆是|both|all)[^，,。.;；\n]*({role_alt})", compact)
    )


def _default_provider_contract(image_provider: Any) -> dict[str, Any]:
    provider = str(image_provider or VISUAL_MEDIA_PROVIDER_DEFAULT)
    return {
        "base_llm_provider": BASE_LLM_PROVIDER,
        "base_llm_model": BASE_LLM_MODEL,
        "visual_agent_llm_provider": VISUAL_AGENT_LLM_PROVIDER,
        "visual_agent_llm_model": VISUAL_AGENT_LLM_MODEL,
        "visual_media_provider_default": VISUAL_MEDIA_PROVIDER_DEFAULT,
        "visual_media_model_default": VISUAL_MEDIA_MODEL_DEFAULT,
        "visual_media_provider_override": None if provider == VISUAL_MEDIA_PROVIDER_DEFAULT else provider,
    }


def _plan_visual_agent_request(
    prompt: str,
    *,
    attachments: list[str],
) -> Mapping[str, Any]:
    return _fallback_visual_plan(prompt, attachments=attachments)


def _fallback_visual_plan(
    prompt: str,
    *,
    attachments: list[str],
) -> dict[str, Any]:
    lowered = str(prompt or "").lower()
    should_use_visual = bool(attachments) or any(
        marker in lowered
        for marker in (
            "image",
            "picture",
            "photo",
            "video",
            "clip",
            "motion",
            "visual",
            "圖片",
            "照片",
            "影像",
            "影片",
            "短片",
            "動畫",
            "動態",
            "產圖",
            "生成圖",
        )
    )
    image_provider = "openai-codex" if "openai" in lowered or "image2" in lowered else VISUAL_MEDIA_PROVIDER_DEFAULT
    arguments: dict[str, Any] = {
        "include_image": should_use_visual,
        "include_video": any(
            marker in lowered
            for marker in ("video", "clip", "motion", "影片", "短片", "動畫", "動態")
        ),
        "image_provider": image_provider,
        "image_provider_source": (
            "prompt_override"
            if image_provider != VISUAL_MEDIA_PROVIDER_DEFAULT
            else "visual_agent_default"
        ),
    }
    mentioned = _mentioned_ref_indices(prompt)
    if attachments and mentioned:
        arguments["reference_binding"] = {
            "reference_order": [
                {
                    "index": index,
                    "role_hint": _reference_role_hint(prompt, index),
                }
                for index in mentioned
                if 1 <= index <= len(attachments)
            ]
        }
    return {
        "should_use_visual_package": should_use_visual,
        "confidence": 0.72 if should_use_visual else 0.0,
        "reason": "raphael_llm_slice_fallback_visual_plan",
        "arguments": arguments,
        "provider_contract": _default_provider_contract(image_provider),
    }


def _is_visual_feedback_only_text(prompt: str) -> bool:
    return _looks_like_followup_edit(prompt) and not _looks_like_visual_generation(prompt)


def _looks_like_mission_followup(prompt: str) -> bool:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    return any(
        marker in compact
        for marker in (
            "繼續剛剛",
            "繼續剛才",
            "接著做",
            "接下來請繼續",
            "continueprevious",
            "continueearlier",
            "continuethatgoal",
        )
    )


def _looks_like_story_video_orchestration(prompt: str) -> bool:
    lowered = str(prompt or "").casefold()
    return any(
        marker in lowered
        for marker in (
            "story_video_operator_context",
            "story_video_run_context",
            "故事影片：",
            "故事影片:",
            "story-video:",
            "story video:",
        )
    )


def _looks_like_story_video_implementation_task(prompt: str) -> bool:
    lowered = str(prompt or "").casefold()
    story_video_markers = ("story-video", "story_video", "story video", "故事影片")
    implementation_markers = (
        "plugin",
        "runtime",
        "routing",
        "route bug",
        "程式",
        "代碼",
        "代码",
    )
    return any(marker in lowered for marker in story_video_markers) and any(
        marker in lowered for marker in implementation_markers
    )


def _looks_like_ambiguous_goal(prompt: str) -> bool:
    compact = re.sub(r"[\s，。,.!?！？]+", "", str(prompt or "").lower())
    return compact in {
        "請處理這個",
        "處理這個",
        "幫我處理",
        "handlethis",
        "takecareofthis",
    }


def _is_visual_prompt_disclosure_request(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    if _looks_like_code_or_runtime_prompt_question(lowered):
        return False
    if "prompt" not in lowered:
        return False
    if not _looks_like_visual_generation(lowered):
        return False
    if any(marker in lowered for marker in ("剛剛", "剛才", "使用")):
        return True
    return re.search(r"\b(?:used|last)\b", lowered) is not None


def _looks_like_visual_prompt_edit_task(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    if _looks_like_code_or_runtime_prompt_question(lowered):
        return False
    compact = re.sub(r"\s+", "", lowered)
    if "prompt" not in lowered and "提示詞" not in lowered and "提示词" not in lowered:
        return False
    return any(
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
            "加強提示詞",
            "加强提示词",
            "再修改",
            "幫我修改",
            "帮我修改",
        )
    ) or any(
        marker in lowered
        for marker in (
            "modify the prompt",
            "edit the prompt",
            "revise the prompt",
            "rewrite the prompt",
            "update the prompt",
            "improve the prompt",
        )
    )


def _looks_like_code_or_runtime_prompt_question(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    return any(
        marker in lowered
        for marker in (
            ".py",
            "agent/",
            "hermes_cli/",
            "prompt_builder",
            "system prompt",
            "code",
            "runtime",
            "程式",
            "代碼",
            "代码",
        )
    )


def _looks_like_visual_generation(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    return any(
        marker in lowered
        for marker in ("image", "picture", "photo", "video", "圖片", "照片", "影片", "產圖")
    )


def _is_visual_attachment_ref(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith(("data:image/", "image:", "file:image")):
        return True
    return lowered.endswith((
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".heic",
        ".heif",
    ))


def _reference_role_hint(prompt: str, index: int) -> str:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    role_terms = (
        "角色",
        "人物",
        "姿勢",
        "動作",
        "服裝",
        "衣服",
        "風格",
        "背景",
        "character",
        "pose",
        "wardrobe",
        "outfit",
        "style",
        "background",
    )
    for role in role_terms:
        if re.search(rf"(?:ref|reference|參考圖?|第){index}[^，,。.;；\n]*{re.escape(role)}", compact):
            return role
    return "reference"


def _missing_reference_index(prompt: str, attachment_count: int) -> int | None:
    indices = _mentioned_ref_indices(prompt)
    if not indices:
        return None
    if attachment_count <= 0:
        return min(indices)
    missing = [index for index in indices if index > attachment_count]
    return min(missing) if missing else None


def _mentioned_ref_indices(prompt: str) -> list[int]:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    indices = {
        int(match.group(1))
        for match in re.finditer(r"(?:ref|reference|參考圖?|第)(\d+)", compact)
    }
    for value, numeral in {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }.items():
        if f"第{numeral}張" in compact:
            indices.add(value)
    return sorted(indices)


def _looks_like_followup_edit(prompt: str) -> bool:
    return _contains_any(prompt, _EDIT_MARKERS)


def _looks_like_text_only_runtime_analysis(prompt: str) -> bool:
    has_text_only = _contains_any(prompt, _TEXT_ONLY_ANALYSIS_MARKERS)
    has_no_tool = _contains_any(prompt, _NO_TOOL_ANALYSIS_MARKERS)
    has_no_media = _contains_any(prompt, _NO_MEDIA_ANALYSIS_MARKERS)
    has_runtime = _contains_any(prompt, _RUNTIME_ANALYSIS_MARKERS)
    if has_no_tool and has_no_media:
        return True
    if has_runtime:
        return has_text_only or has_no_tool or has_no_media
    return has_text_only and (has_no_tool or has_no_media)


def _looks_like_learn_skill_request(prompt: str) -> bool:
    return _contains_any(prompt, _LEARN_INTENT_MARKERS) and _contains_any(
        prompt,
        _LEARN_SKILL_TARGET_MARKERS,
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    return any(marker in lowered or marker in compact for marker in markers)


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return _extract_text(value.get("content"))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                if item.get("type") in {"text", "input_text"}:
                    text = str(item.get("text") or "").strip()
                    if text:
                        parts.append(text)
                elif "content" in item:
                    text = _extract_text(item.get("content"))
                    if text:
                        parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
        return "\n".join(parts).strip()
    return ""


def _summary(prompt: str) -> str:
    text = re.sub(r"\s+", " ", str(prompt or "")).strip()
    return text[:160]


__all__ = [
    "RaphaelControlDecision",
    "RaphaelEvidenceDecision",
    "RaphaelGoalDecision",
    "RaphaelRouteDecision",
    "build_raphael_control_decision",
    "classify_visual_failure_layer",
    "render_raphael_control_context",
]

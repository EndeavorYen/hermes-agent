from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen

from agent.visual.active_learning import decide_visual_action
from agent.visual.artifact_observation import build_artifact_observation
from agent.visual.aspect_policy import select_video_aspect_ratio
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.autonomous_orchestration import build_post_generation_orchestration
from agent.visual.autonomous_validation import validate_visual_generation_payload
from agent.visual.feedback_policy import resolve_visual_feedback_policy
from agent.visual.intent_signature import build_intent_signature
from agent.visual.judges.deterministic import judge_artifact
from agent.visual.judges.quality import judge_visual_quality
from agent.visual.media_probe import probe_media_reference
from agent.visual.preference_profile import build_preference_profile
from agent.visual.provider_failures import classify_visual_provider_failure
from agent.visual.provider_stats import compute_provider_reliability
from agent.visual.ranker import rank_visual_candidates
from agent.visual.recovery import plan_visual_recovery
from agent.visual.reward_model import score_visual_candidate
from agent.visual.shadow_learning import record_shadow_update
from agent.visual.strategy_policy import StrategyPlan
from agent.visual.strategy_policy import find_controlled_strategy_plan
from agent.visual.strategy_policy import select_strategy_plan
from agent.visual.tracking import default_visual_ledger_path
from agent.visual.tracking import visual_delivery_metadata
from agent.visual.video_hardening import build_hardened_video_request
from agent.visual.vision_evaluator import build_candidate_vision_observation
from tools.registry import registry
from tools.registry import tool_error

logger = logging.getLogger(__name__)

MAX_REMOTE_MEDIA_BYTES = 150 * 1024 * 1024
ALWAYS_BLOCKING_QUALITY_ISSUES = {
    "composition_bad",
    "reference_identity_drift",
}
VIDEO_BLOCKING_QUALITY_ISSUES = {
    "aspect_integrity_bad",
    "motion_bad",
}
PORTRAIT_BLOCKING_QUALITY_ISSUES = {
    "subject_not_attractive",
    "not_beautiful",
    "stockings_bad",
}
PREFERENCE_DIMENSION_DELIVERY_THRESHOLD = 0.5
INLINE_VISION_JUDGE_PROMPT = """\
Evaluate this generated visual artifact for automated quality ranking.
Return only a JSON object with numeric values from 0.0 to 1.0:
{
  "reference_adherence": 0.5,
  "subject_quality": 0.5,
  "face_quality": 0.5,
  "visual_appeal": 0.5,
  "glamour_impact": 0.5,
  "composition": 0.5,
  "pose_composition": 0.5,
  "pose_novelty": 0.5,
  "fashion_material_quality": 0.5,
  "stocking_quality": 0.5
}
Do not include names, private prompt text, file paths, or prose.
"""


VISUAL_PACKAGE_SCHEMA: dict[str, Any] = {
    "name": "visual_package_generate",
    "description": (
        "Generate a coordinated visual package when the user naturally asks "
        "for both an image and a video, a set of visual assets, a product photo "
        "plus short clip, a 寫真影片, or similar. Use this instead of separate image_generate "
        "and video_generate calls for requests like '請產出一張圖片和一段影片', "
        "'做一組視覺素材', 'image plus short video', 'fashion portrait video', "
        "or 'product photo and 6 second clip'. For text-only visual video requests, "
        "this tool uses the image-first route: generate image candidates, rank/select "
        "one, then animate the selected image. "
        "The tool generates candidates, records evidence, ranks artifacts, and "
        "returns only selected current media plus delivery metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Natural-language visual package request.",
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional image paths or URLs supplied by the user.",
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Optional shared aspect ratio, e.g. 16:9, 9:16, 1:1, landscape, portrait, square.",
            },
            "duration": {
                "type": "integer",
                "description": "Optional desired video duration in seconds.",
            },
            "candidate_budget": {
                "type": "integer",
                "description": "Optional image candidate budget. Defaults to 2.",
            },
            "video_budget": {
                "type": "integer",
                "description": "Optional video candidate budget. Defaults to 1.",
            },
            "autonomy_level": {
                "type": "integer",
                "description": "Optional advanced autonomy level reserved for learning gates.",
            },
        },
        "required": ["prompt"],
    },
}


def check_visual_package_requirements() -> bool:
    try:
        from tools.image_generation_tool import check_image_generation_requirements
        from tools.video_generation_tool import check_video_generation_requirements

        return check_image_generation_requirements() and check_video_generation_requirements()
    except Exception:
        return False


def generate_image(**kwargs: Any) -> dict[str, Any]:
    from tools.image_generation_tool import _handle_image_generate

    return json.loads(_handle_image_generate(kwargs))


def generate_video(**kwargs: Any) -> dict[str, Any]:
    from tools.video_generation_tool import _handle_video_generate

    return json.loads(_handle_video_generate(kwargs))


def analyze_candidate_with_vision_tool(candidate: dict[str, Any]) -> dict[str, Any]:
    source = _candidate_visual_source(candidate)
    if not source:
        raise ValueError("candidate has no analyzable image source")
    from model_tools import _run_async
    from tools.vision_tools import vision_analyze_tool

    raw = _run_async(vision_analyze_tool(source, INLINE_VISION_JUDGE_PROMPT))
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"analysis": raw}
    return raw if isinstance(raw, dict) else {"analysis": str(raw)}


async def _handle_visual_package_generate(args: dict[str, Any], **_kw: Any) -> str:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required for visual package generation")
    try:
        payload = _visual_package_generate(args, prompt=prompt)
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - tool should surface structured failure
        logger.warning("visual package generation failed: %s", exc)
        return json.dumps(
            {
                "success": False,
                "package_status": "failed",
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
            ensure_ascii=False,
        )


def _visual_package_generate(args: dict[str, Any], *, prompt: str) -> dict[str, Any]:
    attachments = _normalise_attachments(args.get("attachments"))
    aspect_ratio = str(args.get("aspect_ratio") or "16:9").strip() or "16:9"
    image_aspect_ratio = _image_tool_aspect_ratio(aspect_ratio)
    duration = _coerce_int(args.get("duration")) or 6
    requested_image = _wants_image(prompt, args)
    wants_video = _wants_video(prompt, args)
    explicit_image_url = str(args.get("image_url") or "").strip() or None
    attachment_video_source = attachments[0] if attachments and not requested_image else None
    explicit_video_source = explicit_image_url or attachment_video_source
    image_first_for_video = wants_video and not requested_image and not explicit_video_source
    should_generate_image = requested_image or image_first_for_video
    if not should_generate_image and not wants_video:
        requested_image = True
        should_generate_image = True
        wants_video = True
    feedback_policy = _visual_feedback_policy(
        args,
        wants_image=should_generate_image,
        wants_video=wants_video,
    )
    policy_image_first_for_video = (
        wants_video
        and not requested_image
        and feedback_policy.get("prefer_image_first_video") is True
    )
    if policy_image_first_for_video:
        image_first_for_video = True
        should_generate_image = True
    provider_retry_budget = _provider_retry_budget(feedback_policy)
    candidate_budget = int(feedback_policy.get("candidate_budget") or 0) if should_generate_image else 0
    candidate_budget_source = (
        str(feedback_policy.get("candidate_budget_source") or "default")
        if should_generate_image
        else "not_requested"
    )
    video_budget = _video_budget(args, wants_video=wants_video)
    inline_vision_judge = _inline_vision_judge_mode(args)
    request_category = _visual_request_category(prompt)
    quality_guidance = _quality_guidance_plan(feedback_policy, request_category=request_category)
    normalized_intent = {
        "kind": "visual_package",
        "wants_image": requested_image,
        "wants_video": wants_video,
        "generates_image": should_generate_image,
        "image_first_for_video": image_first_for_video,
        "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
        "category": request_category,
    }
    intent_signature = build_intent_signature(
        {
            **normalized_intent,
            "modality": "package",
            "operation": "visual_package_generate",
        }
    )

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt=prompt,
        normalized_intent=normalized_intent,
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={"intent_signature": intent_signature},
    )

    selected_artifact_ids: list[str] = []
    selected_images: list[str] = []
    selected_videos: list[str] = []
    video_source_image: str | None = None
    video_source_artifact_id: str | None = None
    rankings: dict[str, dict[str, Any]] = {}
    generation_payloads: dict[str, Any] = {}
    delivery_gate: dict[str, dict[str, Any]] = {}
    preference_profile = build_preference_profile(ledger, bucket=intent_signature)
    strategy_plan = select_strategy_plan(
        intent_signature,
        provider_stats={},
        preference_profile=preference_profile,
        exploration_rate=0.0,
    )
    controlled_strategy_plan = find_controlled_strategy_plan(
        ledger,
        intent_signature=intent_signature,
    )
    feedback_strategy_plan = None
    if controlled_strategy_plan is not None:
        strategy_plan = controlled_strategy_plan
    else:
        feedback_strategy_plan = _strategy_plan_from_feedback_preference(
            strategy_plan,
            feedback_policy=feedback_policy,
            intent_signature=intent_signature,
        )
        if feedback_strategy_plan is not None:
            strategy_plan = feedback_strategy_plan
    learning: dict[str, Any] = {
        "mode": _learning_mode(
            controlled_strategy_plan=controlled_strategy_plan,
            feedback_strategy_plan=feedback_strategy_plan,
        ),
        "strategy_plan": strategy_plan.to_record(),
        "active_learning": {},
    }

    if should_generate_image:
        image_payloads = []
        image_candidates = []
        image_generation_prompt = _apply_first_pass_quality_guidance(prompt, quality_guidance["image"])
        for candidate_index in range(candidate_budget):
            image_kwargs = {
                "prompt": image_generation_prompt,
                "aspect_ratio": image_aspect_ratio,
                "reference_image_urls": attachments or None,
            }
            image_request = {
                "prompt": image_generation_prompt,
                "arguments": image_kwargs,
                "source_media": _source_media_from_attachments(attachments),
            }
            image_payload = generate_image(**image_kwargs)
            if not image_payload.get("success"):
                _annotate_generation_failure(
                    image_payload,
                    base_kwargs=image_kwargs,
                    request=image_request,
                    retry_budget_remaining=provider_retry_budget,
                )
            image_payloads.append(image_payload)
            image_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=image_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=image_generation_prompt,
                provider=str(image_payload.get("provider") or ""),
                model=str(image_payload.get("model") or ""),
                requested_parameters={"aspect_ratio": _judge_aspect_ratio(aspect_ratio)},
                candidate_index=candidate_index,
            )
            if image_candidate:
                image_candidates.append(image_candidate)
            elif not image_payload.get("success"):
                for retry_offset, retry_payload in enumerate(_retry_generation_payloads(
                    generator=generate_image,
                    payload=image_payload,
                    base_kwargs=image_kwargs,
                    request=image_request,
                    retry_budget_remaining=provider_retry_budget,
                    retry_of=candidate_index,
                )):
                    image_payloads.append(retry_payload)
                    retry_candidate = _record_payload_candidate(
                        ledger,
                        request_id=request_id,
                        payload=retry_payload,
                        artifact_key="image",
                        expected_kind="image",
                        prompt=str(retry_payload.get("prompt") or prompt),
                        provider=str(retry_payload.get("provider") or ""),
                        model=str(retry_payload.get("model") or ""),
                        requested_parameters={"aspect_ratio": _judge_aspect_ratio(aspect_ratio)},
                        candidate_index=candidate_index + (candidate_budget * (retry_offset + 1)),
                    )
                    if retry_candidate:
                        image_candidates.append(retry_candidate)
                        break
        generation_payloads["image"] = image_payloads[0] if len(image_payloads) == 1 else image_payloads
        _score_candidates(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            modality="image",
            has_reference_image=bool(attachments),
            request_category=request_category,
            candidates=image_candidates,
            inline_vision_judge=inline_vision_judge,
            vision_analyzer=analyze_candidate_with_vision_tool,
        )
        image_decision = rank_visual_candidates(
            request_id=request_id,
            candidates=image_candidates,
            post_threshold=0.0,
            ask_threshold=0.0,
        )
        rankings["image"] = image_decision.__dict__
        image_learning = _record_learning_trace(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            strategy_plan=strategy_plan.to_record(),
            modality="image",
            rank_decision=image_decision.__dict__,
            candidates=image_candidates,
            has_reference_image=bool(attachments),
        )
        learning["active_learning"]["image"] = image_learning
        selected_image = _selected_candidate(image_candidates, image_decision.selected_artifact_id)
        image_gate = _delivery_gate_decision(image_learning, selected_image, prompt=prompt)
        delivery_gate["image"] = image_gate
        if selected_image and not image_gate["allowed"]:
            image_repair_mode = _quality_repair_policy_mode(feedback_policy, "image")
            repair_prompt = _quality_repair_prompt(
                prompt,
                image_gate,
                mode=image_repair_mode,
            )
            repair_kwargs = {
                "prompt": repair_prompt,
                "aspect_ratio": image_aspect_ratio,
                "reference_image_urls": attachments or None,
            }
            repair_payload = generate_image(**repair_kwargs)
            repair_payload["retry_of"] = selected_image.get("attempt_id")
            repair_payload["quality_repair"] = {
                "reason": image_gate.get("reason"),
                "quality_issues": image_gate.get("quality_issues", []),
                "policy_mode": image_repair_mode,
                "policy_actions": feedback_policy.get("applied_action_types", []),
            }
            image_payloads.append(repair_payload)
            if not repair_payload.get("success"):
                _annotate_generation_failure(
                    repair_payload,
                    base_kwargs=repair_kwargs,
                    request={
                        "prompt": repair_prompt,
                        "arguments": repair_kwargs,
                        "source_media": _source_media_from_attachments(attachments),
                        "quality_repair": repair_payload["quality_repair"],
                    },
                    retry_budget_remaining=0,
                )
            repair_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=repair_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=repair_prompt,
                provider=str(repair_payload.get("provider") or ""),
                model=str(repair_payload.get("model") or ""),
                requested_parameters={
                    "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
                    "quality_repair_of": selected_image.get("artifact_id"),
                },
                candidate_index=candidate_budget,
            )
            if repair_candidate:
                image_candidates.append(repair_candidate)
                _score_candidates(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    modality="image",
                    has_reference_image=bool(attachments),
                    request_category=request_category,
                    candidates=[repair_candidate],
                    inline_vision_judge=inline_vision_judge,
                    vision_analyzer=analyze_candidate_with_vision_tool,
                )
                repair_decision = rank_visual_candidates(
                    request_id=request_id,
                    candidates=[repair_candidate],
                    post_threshold=0.0,
                    ask_threshold=0.0,
                )
                rankings["image"] = repair_decision.__dict__
                repair_learning = _record_learning_trace(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    strategy_plan=strategy_plan.to_record(),
                    modality="image",
                    rank_decision=repair_decision.__dict__,
                    candidates=[repair_candidate],
                    has_reference_image=bool(attachments),
                )
                learning["active_learning"]["image"] = repair_learning
                selected_image = _selected_candidate([repair_candidate], repair_decision.selected_artifact_id)
                repaired_gate = _delivery_gate_decision(repair_learning, selected_image, prompt=prompt)
                repaired_gate["repair_attempted"] = True
                repaired_gate["repaired_from"] = image_gate
                image_gate = repaired_gate
                delivery_gate["image"] = image_gate
        generation_payloads["image"] = image_payloads[0] if len(image_payloads) == 1 else image_payloads
        if selected_image and image_gate["allowed"]:
            video_source_image = selected_image["artifact_path"]
            video_source_artifact_id = selected_image["artifact_id"]
            if requested_image:
                selected_artifact_ids.append(selected_image["artifact_id"])
                selected_images.append(selected_image["artifact_path"])

    if wants_video:
        if policy_image_first_for_video and video_source_image:
            video_image_url = video_source_image
        else:
            video_image_url = explicit_video_source or video_source_image
        video_candidates = []
        if not video_image_url:
            video_payload = {
                "success": False,
                "video": None,
                "error": "Image-first video generation requires a selected or supplied source image.",
                "error_type": "missing_video_source_image",
                "prompt": prompt,
                "provider": "",
                "model": "",
            }
            generation_payloads["video"] = video_payload
            _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=video_payload,
                artifact_key="video",
                expected_kind="video",
                prompt=prompt,
                provider="",
                model="",
                requested_parameters={
                    "duration_seconds": duration,
                    "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
                    "motion_mode": None,
                },
            )
        else:
            video_generation_base_prompt = _apply_first_pass_quality_guidance(prompt, quality_guidance["video"])
            hardened_video = build_hardened_video_request(
                prompt=video_generation_base_prompt,
                requested_aspect_ratio=_video_tool_aspect_ratio(
                    requested_aspect_ratio=_judge_aspect_ratio(aspect_ratio),
                    source_ref=video_image_url,
                ),
                source_media=_source_media_from_attachments([video_image_url]),
            )
            video_prompt = hardened_video["prompt"]
            video_aspect_ratio = hardened_video["aspect_ratio"]
            video_payloads = []
            for candidate_index in range(video_budget):
                video_kwargs = {
                    "prompt": video_prompt,
                    "image_url": video_image_url,
                    "duration": duration,
                    "aspect_ratio": video_aspect_ratio,
                }
                video_request = {
                    "prompt": video_generation_base_prompt,
                    "arguments": video_kwargs,
                    "source_media": _source_media_from_attachments([video_image_url]),
                    "video_hardening": hardened_video.get("metadata", {}),
                }
                video_payload = generate_video(**video_kwargs)
                if not video_payload.get("success"):
                    _annotate_generation_failure(
                        video_payload,
                        base_kwargs=video_kwargs,
                        request=video_request,
                        retry_budget_remaining=provider_retry_budget,
                    )
                video_payloads.append(video_payload)
                video_candidate = _record_payload_candidate(
                    ledger,
                    request_id=request_id,
                    payload=video_payload,
                    artifact_key="video",
                    expected_kind="video",
                    prompt=video_prompt,
                    provider=str(video_payload.get("provider") or ""),
                    model=str(video_payload.get("model") or ""),
                    requested_parameters={
                        "duration_seconds": duration,
                        "aspect_ratio": video_aspect_ratio,
                        "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                        "source_image_artifact_id": video_source_artifact_id,
                    },
                    candidate_index=candidate_index,
                )
                if video_candidate:
                    video_candidates.append(video_candidate)
                elif not video_payload.get("success"):
                    for retry_offset, retry_payload in enumerate(_retry_generation_payloads(
                        generator=generate_video,
                        payload=video_payload,
                        base_kwargs=video_kwargs,
                        request=video_request,
                        retry_budget_remaining=provider_retry_budget,
                        retry_of=candidate_index,
                    )):
                        video_payloads.append(retry_payload)
                        retry_candidate = _record_payload_candidate(
                            ledger,
                            request_id=request_id,
                            payload=retry_payload,
                            artifact_key="video",
                            expected_kind="video",
                            prompt=str(retry_payload.get("prompt") or prompt),
                            provider=str(retry_payload.get("provider") or ""),
                            model=str(retry_payload.get("model") or ""),
                            requested_parameters={
                                "duration_seconds": retry_payload.get("duration", duration),
                                "aspect_ratio": video_aspect_ratio,
                                "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                                "source_image_artifact_id": video_source_artifact_id,
                            },
                            candidate_index=candidate_index + (video_budget * (retry_offset + 1)),
                        )
                        if retry_candidate:
                            video_candidates.append(retry_candidate)
                            break
            generation_payloads["video"] = video_payloads[0] if len(video_payloads) == 1 else video_payloads
        _score_candidates(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            modality="video",
            has_reference_image=bool(video_image_url),
            request_category=request_category,
            candidates=video_candidates,
            inline_vision_judge=False,
            vision_analyzer=analyze_candidate_with_vision_tool,
        )
        video_decision = rank_visual_candidates(
            request_id=request_id,
            candidates=video_candidates,
            post_threshold=0.0,
            ask_threshold=0.0,
        )
        rankings["video"] = video_decision.__dict__
        video_learning = _record_learning_trace(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            strategy_plan=strategy_plan.to_record(),
            modality="video",
            rank_decision=video_decision.__dict__,
            candidates=video_candidates,
            has_reference_image=bool(video_image_url),
        )
        learning["active_learning"]["video"] = video_learning
        selected_video = _selected_candidate(video_candidates, video_decision.selected_artifact_id)
        video_gate = _delivery_gate_decision(video_learning, selected_video, prompt=prompt)
        delivery_gate["video"] = video_gate
        if selected_video and not video_gate["allowed"] and video_image_url and _string_list(video_gate.get("quality_issues")):
            video_repair_mode = _quality_repair_policy_mode(feedback_policy, "video")
            repair_prompt = _video_quality_repair_prompt(video_prompt, video_gate, mode=video_repair_mode)
            repair_kwargs = {
                "prompt": repair_prompt,
                "image_url": video_image_url,
                "duration": duration,
                "aspect_ratio": video_aspect_ratio,
            }
            repair_payload = generate_video(**repair_kwargs)
            repair_payload["quality_repair"] = {
                "modality": "video",
                "reason": video_gate.get("reason"),
                "quality_issues": _string_list(video_gate.get("quality_issues")),
                "policy_mode": video_repair_mode,
                "policy_actions": feedback_policy.get("applied_action_types", []),
            }
            if not repair_payload.get("success"):
                _annotate_generation_failure(
                    repair_payload,
                    base_kwargs=repair_kwargs,
                    request={
                        "prompt": prompt,
                        "arguments": repair_kwargs,
                        "source_media": _source_media_from_attachments([video_image_url]),
                        "video_hardening": hardened_video.get("metadata", {}),
                    },
                    retry_budget_remaining=0,
                )
            video_payloads.append(repair_payload)
            repair_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=repair_payload,
                artifact_key="video",
                expected_kind="video",
                prompt=repair_prompt,
                provider=str(repair_payload.get("provider") or ""),
                model=str(repair_payload.get("model") or ""),
                requested_parameters={
                    "duration_seconds": duration,
                    "aspect_ratio": video_aspect_ratio,
                    "motion_mode": hardened_video.get("metadata", {}).get("motion_mode"),
                    "source_image_artifact_id": video_source_artifact_id,
                    "quality_repair": True,
                },
                candidate_index=len(video_candidates),
            )
            if repair_candidate:
                video_candidates.append(repair_candidate)
                _score_candidates(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    modality="video",
                    has_reference_image=bool(video_image_url),
                    request_category=request_category,
                    candidates=[repair_candidate],
                    inline_vision_judge=False,
                    vision_analyzer=analyze_candidate_with_vision_tool,
                )
                repair_decision = rank_visual_candidates(
                    request_id=request_id,
                    candidates=[repair_candidate],
                    post_threshold=0.0,
                    ask_threshold=0.0,
                )
                rankings["video"] = repair_decision.__dict__
                repair_learning = _record_learning_trace(
                    ledger,
                    request_id=request_id,
                    intent_signature=intent_signature,
                    strategy_signature=strategy_plan.strategy_signature,
                    strategy_plan=strategy_plan.to_record(),
                    modality="video",
                    rank_decision=repair_decision.__dict__,
                    candidates=[repair_candidate],
                    has_reference_image=bool(video_image_url),
                )
                learning["active_learning"]["video"] = repair_learning
                selected_video = _selected_candidate([repair_candidate], repair_decision.selected_artifact_id)
                repaired_gate = _delivery_gate_decision(repair_learning, selected_video, prompt=prompt)
                repaired_gate["repair_attempted"] = True
                repaired_gate["repaired_from"] = video_gate
                video_gate = repaired_gate
                delivery_gate["video"] = video_gate
            else:
                video_gate["repair_attempted"] = True
            generation_payloads["video"] = video_payloads[0] if len(video_payloads) == 1 else video_payloads
        if selected_video and video_gate["allowed"]:
            selected_artifact_ids.append(selected_video["artifact_id"])
            selected_videos.append(selected_video["artifact_path"])

    success = (not requested_image or bool(selected_images)) and (not wants_video or bool(selected_videos))
    package_status = "success" if success else ("partial" if selected_images or selected_videos else "failed")
    package_error = _package_error(success=success, delivery_gate=delivery_gate)
    selected_artifact_paths = selected_images + selected_videos
    delivery_metadata = visual_delivery_metadata(
        request_id=request_id,
        attempt_id=None,
        artifact_ids=selected_artifact_ids,
        artifact_paths=selected_artifact_paths,
        selected_artifact_ids=selected_artifact_ids,
    )
    selected_delivery_refs = set(selected_artifact_paths)

    payload = {
        "success": success,
        "package_status": package_status,
        "error_type": package_error.get("error_type"),
        "error": package_error.get("error"),
        "visual_request_id": request_id,
        "images": selected_images,
        "videos": selected_videos,
        "rankings": rankings,
        "generation_strategy": {
            "requested_image": requested_image,
            "generated_image": should_generate_image,
            "image_first_for_video": image_first_for_video,
            "video_source_image": video_source_image,
            "video_source_artifact_id": video_source_artifact_id,
            "candidate_budget": candidate_budget,
            "candidate_budget_source": candidate_budget_source,
            "video_budget": video_budget,
            "feedback_policy": feedback_policy,
            "quality_guidance": quality_guidance,
        },
        "delivery_metadata": delivery_metadata,
        "generation_payloads": _delivery_safe_generation_payloads(
            generation_payloads,
            selected_refs=selected_delivery_refs,
        ),
        "learning": learning,
        "delivery_gate": delivery_gate,
    }
    autonomous_validation = validate_visual_generation_payload(
        payload,
        db_path=default_visual_ledger_path(),
        require_video=wants_video,
    )
    payload["autonomous_validation"] = autonomous_validation
    payload["autonomous_orchestration"] = build_post_generation_orchestration(
        payload,
        db_path=default_visual_ledger_path(),
        require_video=wants_video,
        autonomy_level=_coerce_int(args.get("autonomy_level")) or 2,
        validation=autonomous_validation,
    )
    return payload


def _record_payload_candidate(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    payload: dict[str, Any],
    artifact_key: str,
    expected_kind: str,
    prompt: str,
    provider: str,
    model: str,
    requested_parameters: dict[str, Any],
    candidate_index: int = 0,
) -> dict[str, Any] | None:
    success = bool(payload.get("success"))
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=candidate_index,
        provider=provider,
        model=model,
        prompt_original=prompt,
        prompt_mediated=prompt,
        parameters_requested=requested_parameters,
        parameters_effective=requested_parameters,
        status="completed" if success else "failed",
        error_type=payload.get("error_type") if not success else None,
        error_message=payload.get("error") if not success else None,
        metadata=_attempt_metadata(payload),
    )
    artifact_ref = payload.get(artifact_key)
    if not success or not isinstance(artifact_ref, str) or not artifact_ref.strip():
        return None

    artifact_id, artifact = _record_artifact_ref(
        ledger,
        request_id=request_id,
        attempt_id=attempt_id,
        kind=expected_kind,
        artifact_ref=artifact_ref.strip(),
    )
    score = judge_artifact(
        artifact,
        expected_kind=expected_kind,
        requested_parameters=requested_parameters,
    )
    return {
        "attempt_id": attempt_id,
        "artifact_id": artifact_id,
        "artifact_path": artifact.get("local_path") or artifact.get("uri") or artifact_ref.strip(),
        "kind": expected_kind,
        "provider": provider,
        "model": model,
        "content_hash": artifact.get("content_hash"),
        "width": artifact.get("width"),
        "height": artifact.get("height"),
        "duration_seconds": artifact.get("duration_seconds"),
        "requested_parameters": requested_parameters,
        "hard_gate": score["hard_gate"],
        "scores": score["scores"],
        "vision_observation": _payload_vision_observation(payload),
    }


def _package_error(
    *,
    success: bool,
    delivery_gate: dict[str, dict[str, Any]],
) -> dict[str, str | None]:
    if success:
        return {"error_type": None, "error": None}
    if any(
        isinstance(gate, dict)
        and gate.get("allowed") is False
        and gate.get("reason") == "active_learning_fail_closed"
        for gate in delivery_gate.values()
    ):
        return {
            "error_type": "delivery_gate_blocked",
            "error": "visual candidate blocked by active-learning delivery gate",
        }
    return {"error_type": None, "error": None}


def _retry_generation_payloads(
    *,
    generator,
    payload: dict[str, Any],
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    retry_budget_remaining: int,
    retry_of: int,
) -> list[dict[str, Any]]:
    retries: list[dict[str, Any]] = []
    current_payload = payload
    current_kwargs = dict(base_kwargs)
    remaining = max(0, _coerce_int(retry_budget_remaining) or 0)
    current_retry_of = retry_of
    while remaining > 0:
        _annotate_generation_failure(
            current_payload,
            base_kwargs=current_kwargs,
            request={**request, "arguments": current_kwargs},
            retry_budget_remaining=remaining,
        )
        recovery = current_payload["recovery"]
        if recovery.get("decision") != "retry":
            break
        retry_kwargs = _retry_kwargs_from_recovery(current_kwargs, recovery)
        retry_payload = generator(**retry_kwargs)
        retry_payload["retry_of"] = current_retry_of
        retries.append(retry_payload)
        if retry_payload.get("success"):
            retry_payload["recovery"] = recovery
            break
        remaining -= 1
        _annotate_generation_failure(
            retry_payload,
            base_kwargs=retry_kwargs,
            request={**request, "arguments": retry_kwargs},
            retry_budget_remaining=remaining,
        )
        current_payload = retry_payload
        current_kwargs = retry_kwargs
        current_retry_of = current_retry_of + 1
    return retries


def _retry_generation_payload(
    *,
    generator,
    payload: dict[str, Any],
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    retry_budget_remaining: int,
    retry_of: int,
) -> dict[str, Any] | None:
    retries = _retry_generation_payloads(
        generator=generator,
        payload=payload,
        base_kwargs=base_kwargs,
        request=request,
        retry_budget_remaining=retry_budget_remaining,
        retry_of=retry_of,
    )
    return retries[0] if retries else None


def _retry_kwargs_from_recovery(base_kwargs: dict[str, Any], recovery: dict[str, Any]) -> dict[str, Any]:
    retry_kwargs = {**base_kwargs}
    for key in recovery.get("removed_arguments") or []:
        retry_kwargs.pop(str(key), None)
    retry_kwargs.update(_generator_kwargs(recovery.get("modified_arguments")))
    return retry_kwargs


def _annotate_generation_failure(
    payload: dict[str, Any],
    *,
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    retry_budget_remaining: int,
) -> None:
    if "failure" not in payload:
        payload["failure"] = classify_visual_provider_failure(payload)
    if "recovery" not in payload:
        payload["recovery"] = plan_visual_recovery(
            {**request, "arguments": {**base_kwargs}},
            payload["failure"],
            retry_budget_remaining=retry_budget_remaining,
        )


def _attempt_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("failure", "recovery", "retry_of", "quality_repair"):
        if key in payload:
            metadata[key] = payload[key]
    return metadata


def _payload_vision_observation(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("vision_observation", "visual_quality_observation"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _generator_kwargs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if key in {"prompt", "aspect_ratio", "duration", "candidate_budget", "reference_image_urls", "image_url"}
    }


def _source_media_from_attachments(attachments: list[str]) -> dict[str, Any]:
    for attachment in attachments:
        meta = probe_media_reference(attachment)
        if meta.width and meta.height:
            return {"width": meta.width, "height": meta.height}
    return {}


def _score_candidates(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    intent_signature: str,
    strategy_signature: str,
    modality: str,
    has_reference_image: bool,
    candidates: list[dict[str, Any]],
    request_category: str = "portrait",
    inline_vision_judge: bool | str = "auto",
    vision_analyzer=None,
) -> None:
    if not candidates:
        return
    provider_stats = compute_provider_reliability(ledger, request_id=request_id)
    preference_profile = build_preference_profile(ledger, bucket=intent_signature)
    recent_hashes: set[str] = set()
    for candidate in candidates:
        vision_observation = build_candidate_vision_observation(
            candidate,
            fallback_observation=build_artifact_observation(candidate),
            inline_enabled=_should_run_inline_vision_judge(candidate, inline_vision_judge),
            analyzer=vision_analyzer,
        )
        evidence = vision_observation.get("evidence") if isinstance(vision_observation.get("evidence"), dict) else {}
        candidate["vision_observation_source"] = evidence.get("source")
        quality = judge_visual_quality(
            candidate,
            request_context={
                "has_reference_image": has_reference_image,
                "category": request_category,
            },
            recent_artifact_hashes=recent_hashes,
            vision_observation=vision_observation,
        )
        if evidence.get("source"):
            quality["evidence"] = {
                "source": evidence.get("source"),
                "summary": evidence.get("summary", ""),
            }
        content_hash = candidate.get("content_hash")
        if isinstance(content_hash, str) and content_hash:
            recent_hashes.add(content_hash)
        candidate["judge_scores"] = quality["scores"]
        candidate["quality_issues"] = quality.get("quality_issues", [])
        candidate["preference_dimensions"] = quality.get("preference_dimensions", {})
        ledger.record_judgment(
            request_id=request_id,
            attempt_id=candidate.get("attempt_id"),
            artifact_id=candidate.get("artifact_id"),
            judge_name="visual_quality_judge",
            score=quality.get("confidence"),
            verdict="pass" if quality.get("confidence", 0.0) >= 0.5 else "review",
            details=quality,
            metadata={
                "intent_signature": intent_signature,
                "strategy_signature": strategy_signature,
                "modality": modality,
                "judge_sources": quality.get("judge_sources", {}),
                "uncertainty_reasons": quality.get("uncertainty_reasons", []),
                "vision_observation_source": candidate.get("vision_observation_source"),
            },
        )
        candidate["reward"] = score_visual_candidate(
            candidate,
            provider_stats=provider_stats,
            preference_profile=preference_profile,
        )


def _inline_vision_judge_mode(args: dict[str, Any]) -> bool | str:
    if args.get("inline_vision_judge") is not None:
        return _coerce_bool(args.get("inline_vision_judge"))
    env_value = os.environ.get("HERMES_VISUAL_INLINE_VISION_JUDGE", "auto").strip().lower()
    if env_value in {"0", "false", "no", "off", "disabled"}:
        return False
    if env_value in {"1", "true", "yes", "on", "enabled"}:
        return True
    return "auto"


def _should_run_inline_vision_judge(candidate: dict[str, Any], mode: bool | str) -> bool:
    if mode is True:
        return candidate.get("kind") == "image"
    if mode is False:
        return False
    if candidate.get("kind") != "image":
        return False
    provider = str(candidate.get("provider") or "").strip().lower()
    model = str(candidate.get("model") or "").strip().lower()
    return bool(provider) and provider not in {"fixture", "mock", "test"} and "fixture" not in model


def _record_learning_trace(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    intent_signature: str,
    strategy_signature: str,
    strategy_plan: dict[str, Any],
    modality: str,
    rank_decision: dict[str, Any],
    candidates: list[dict[str, Any]],
    has_reference_image: bool,
) -> dict[str, Any]:
    selected = _selected_candidate(candidates, rank_decision.get("selected_artifact_id"))
    top = selected or _top_ranked_candidate(candidates, rank_decision.get("ranked_artifact_ids"))
    reward = top.get("reward", {}) if top else {}
    active_learning = decide_visual_action(
        {
            "decision": rank_decision.get("decision"),
            "top_score": reward.get("final_score", 0.0),
            "top_confidence": reward.get("confidence", 0.0),
            "uncertainty_reasons": reward.get("uncertainty_reasons", []),
        },
        request_context={
            "has_reference_image": has_reference_image,
            "candidate_count": len(candidates),
            "retry_budget_remaining": 0,
            "failure_type": rank_decision.get("reason"),
        },
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=rank_decision.get("selected_artifact_id"),
        decision=rank_decision.get("decision"),
        scores={
            "reward": reward,
            "ranked_artifact_ids": rank_decision.get("ranked_artifact_ids", []),
        },
        metadata={
            "modality": modality,
            "active_learning": active_learning,
            "strategy_signature": strategy_signature,
            "strategy_plan": strategy_plan,
        },
    )
    record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        proposed_change={
            "type": "strategy_observation",
            "modality": modality,
            "activation": "shadow_only",
        },
        evidence={
            "candidate_count": len(candidates),
            "selected_artifact_id": rank_decision.get("selected_artifact_id"),
            "rank_decision": rank_decision.get("decision"),
        },
        confidence=active_learning.get("top_confidence"),
    )
    return active_learning


def _selected_candidate(
    candidates: list[dict[str, Any]],
    selected_artifact_id: str | None,
) -> dict[str, Any] | None:
    if selected_artifact_id is None:
        return None
    return next(
        (candidate for candidate in candidates if candidate.get("artifact_id") == selected_artifact_id),
        None,
    )


def _delivery_gate_decision(
    active_learning: dict[str, Any],
    candidate: dict[str, Any] | None,
    *,
    prompt: str,
) -> dict[str, Any]:
    if candidate is None:
        return {
            "allowed": False,
            "reason": "no_selected_candidate",
            "active_learning_action": active_learning.get("action"),
            "quality_issues": [],
            "ignored_quality_issues": [],
        }
    quality_issues, ignored_quality_issues = _blocking_quality_issues(
        _string_list(candidate.get("quality_issues")),
        prompt=prompt,
    )
    action = str(active_learning.get("action") or "")
    if action == "fail_closed" and quality_issues:
        return {
            "allowed": False,
            "reason": "active_learning_fail_closed",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
        }
    preference_dimension_fit = _candidate_preference_dimension_fit(candidate)
    if (
        preference_dimension_fit is not None
        and preference_dimension_fit < PREFERENCE_DIMENSION_DELIVERY_THRESHOLD
        and quality_issues
    ):
        return {
            "allowed": False,
            "reason": "pre_slack_preference_dimension_low",
            "active_learning_action": action,
            "quality_issues": quality_issues,
            "ignored_quality_issues": ignored_quality_issues,
            "preference_dimension_fit": preference_dimension_fit,
            "threshold": PREFERENCE_DIMENSION_DELIVERY_THRESHOLD,
        }
    return {
        "allowed": True,
        "reason": "delivery_allowed",
        "active_learning_action": action,
        "quality_issues": quality_issues,
        "ignored_quality_issues": ignored_quality_issues,
    }


def _blocking_quality_issues(issues: list[str], *, prompt: str) -> tuple[list[str], list[str]]:
    portrait_like = _portrait_like_prompt(prompt)
    blocking: list[str] = []
    ignored: list[str] = []
    for issue in issues:
        if issue in ALWAYS_BLOCKING_QUALITY_ISSUES or issue in VIDEO_BLOCKING_QUALITY_ISSUES:
            blocking.append(issue)
        elif issue in PORTRAIT_BLOCKING_QUALITY_ISSUES:
            if portrait_like:
                blocking.append(issue)
            else:
                ignored.append(issue)
    return blocking, ignored


def _candidate_preference_dimension_fit(candidate: dict[str, Any]) -> float | None:
    reward = candidate.get("reward")
    dimensions = reward.get("dimensions") if isinstance(reward, dict) else None
    if not isinstance(dimensions, dict) or dimensions.get("preference_dimension_fit") is None:
        return None
    try:
        return float(dimensions.get("preference_dimension_fit") or 0.0)
    except (TypeError, ValueError):
        return None


def _quality_repair_prompt(prompt: str, gate: dict[str, Any], *, mode: str = "default") -> str:
    issues = _string_list(gate.get("quality_issues"))
    instructions: list[str] = []
    if "subject_not_attractive" in issues or "not_beautiful" in issues:
        instructions.append("render a naturally beautiful subject with clean facial features")
    if "composition_bad" in issues:
        instructions.append("use a stronger editorial composition with clear framing")
    if "stockings_bad" in issues:
        instructions.append("make wardrobe and legwear texture clean, refined, and realistic")
    if "reference_identity_drift" in issues:
        instructions.append("preserve the reference identity and recognizable facial structure")
    if not instructions:
        instructions.append("improve visual quality while preserving the original intent")
    repair = "; ".join(instructions)
    if mode == "preferred":
        policy_instruction = "Proven quality repair strategy: reuse the historically successful repair pattern. "
    elif mode == "escalated":
        policy_instruction = (
            "Escalated quality repair strategy: change the composition path instead of repeating the failed draft. "
        )
    else:
        policy_instruction = ""
    return (
        f"{prompt}\n\n"
        f"{policy_instruction}Quality repair pass: "
        f"{repair}. Avoid distorted anatomy, awkward face rendering, weak composition, "
        "and low-quality surface detail."
    )


def _video_quality_repair_prompt(prompt: str, gate: dict[str, Any], *, mode: str = "default") -> str:
    issues = _string_list(gate.get("quality_issues"))
    instructions: list[str] = []
    if "aspect_integrity_bad" in issues:
        instructions.append("preserve the source image aspect ratio exactly with no horizontal or vertical stretching")
    if "motion_bad" in issues:
        instructions.append("use natural real-time motion, steady subject anatomy, and avoid slow motion or frozen-frame drift")
    if not instructions:
        instructions.append("improve video coherence while preserving the source image and original composition")
    repair = "; ".join(instructions)
    if mode == "preferred":
        policy_instruction = "Proven video quality repair strategy: reuse the historically successful repair pattern. "
    elif mode == "escalated":
        policy_instruction = (
            "Escalated video quality repair strategy: change the motion path instead of repeating the failed clip. "
        )
    else:
        policy_instruction = ""
    return (
        f"{prompt}\n\n"
        f"{policy_instruction}Video quality repair pass: {repair}. "
        "Keep the same subject, framing, lighting, and user intent."
    )


def _quality_repair_policy_mode(feedback_policy: dict[str, Any], modality: str) -> str:
    modes = feedback_policy.get("quality_repair_modes")
    if isinstance(modes, dict):
        mode = str(modes.get(modality) or "default").strip().lower()
        return mode if mode in {"default", "preferred", "escalated"} else "default"
    mode = str(feedback_policy.get("quality_repair_mode") or "default").strip().lower()
    return mode if mode in {"default", "preferred", "escalated"} else "default"


def _quality_guidance_plan(feedback_policy: dict[str, Any], *, request_category: str) -> dict[str, dict[str, Any]]:
    return {
        "image": _quality_guidance_entry(feedback_policy, "image", request_category=request_category),
        "video": _quality_guidance_entry(feedback_policy, "video", request_category=request_category),
    }


def _quality_guidance_entry(
    feedback_policy: dict[str, Any],
    modality: str,
    *,
    request_category: str,
) -> dict[str, Any]:
    mode = _quality_repair_policy_mode(feedback_policy, modality)
    if mode == "default":
        return {
            "enabled": False,
            "mode": mode,
            "prompt_suffix": "",
        }
    dimension_guidance = _dimension_quality_guidance(feedback_policy)
    if modality == "video":
        suffix = (
            "First-pass video quality guidance: use natural real-time motion, "
            "preserve the source aspect ratio, avoid slow motion, avoid stretching, "
            "and keep subject anatomy stable."
        )
    elif _portrait_like_category(request_category):
        suffix = (
            "First-pass visual quality guidance: clean facial features, naturally polished subject, "
            "refined wardrobe and legwear texture, strong editorial composition, realistic details."
        )
    else:
        suffix = (
            "First-pass visual quality guidance: clean product detail, strong composition, "
            "realistic material texture, polished commercial lighting."
        )
    if dimension_guidance:
        suffix = f"{suffix} {dimension_guidance}"
    return {
        "enabled": True,
        "mode": mode,
        "prompt_suffix": suffix,
        "source_action_types": list(feedback_policy.get("applied_action_types") or []),
    }


def _dimension_quality_guidance(feedback_policy: dict[str, Any]) -> str:
    dimensions = feedback_policy.get("repair_dimensions")
    if not isinstance(dimensions, list):
        return ""
    instructions: list[str] = []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        hint = str(item.get("repair_hint") or "").strip()
        instruction = _dimension_quality_instruction(dimension, hint)
        if instruction and instruction not in instructions:
            instructions.append(instruction)
    if not instructions:
        return ""
    return "Dimension-specific quality guidance: " + "; ".join(instructions) + "."


def _dimension_quality_instruction(dimension: str, repair_hint: str) -> str:
    return {
        "subject_beauty": "subject_beauty: raise overall subject attractiveness while keeping natural realism",
        "face_naturalness": "face_naturalness: prioritize natural facial structure, clean eyes, and non-distorted expression",
        "glamour_impact": "glamour_impact: increase polished editorial glamour through pose, lighting, and camera angle",
        "fashion_material_quality": "fashion_material_quality: improve wardrobe and legwear material texture without plastic artifacts",
        "pose_composition": "pose_composition: use a more dynamic pose and cleaner framing",
        "motion_quality": "motion_quality: use clear real-time movement with stable anatomy",
    }.get(dimension, f"{dimension}: {repair_hint}" if repair_hint else "")


def _apply_first_pass_quality_guidance(prompt: str, guidance: dict[str, Any]) -> str:
    suffix = str(guidance.get("prompt_suffix") or "").strip() if isinstance(guidance, dict) else ""
    if not suffix or suffix in prompt:
        return prompt
    return f"{prompt}\n\n{suffix}"


def _portrait_like_category(category: str) -> bool:
    return any(token in str(category or "").lower() for token in ("portrait", "fashion", "character", "cosplay"))


def _portrait_like_prompt(prompt: str) -> bool:
    text = prompt.lower()
    return any(
        token in text
        for token in (
            "portrait",
            "fashion",
            "cosplay",
            "character",
            "girl",
            "woman",
            "model",
            "person",
            "寫真",
            "人像",
            "人物",
            "角色",
            "美少女",
            "美女",
            "性感",
            "絲襪",
            "腿",
            "臉",
        )
    )


def _visual_request_category(prompt: str) -> str:
    if _portrait_like_prompt(prompt):
        return "portrait"
    text = prompt.lower()
    if any(
        token in text
        for token in (
            "product",
            "object",
            "pen",
            "fountain pen",
            "鋼筆",
            "產品",
            "物品",
            "商品",
        )
    ):
        return "product"
    return "scene"


def _top_ranked_candidate(
    candidates: list[dict[str, Any]],
    ranked_artifact_ids: Any,
) -> dict[str, Any] | None:
    if isinstance(ranked_artifact_ids, list) and ranked_artifact_ids:
        return _selected_candidate(candidates, str(ranked_artifact_ids[0]))
    return candidates[0] if candidates else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _delivery_safe_generation_payloads(value: Any, *, selected_refs: set[str]) -> Any:
    if isinstance(value, list):
        return [
            _delivery_safe_generation_payloads(item, selected_refs=selected_refs)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    sanitized: dict[str, Any] = {}
    redacted = False
    for key, item in value.items():
        if key in {"image", "video", "source_video_url"} and isinstance(item, str):
            if item in selected_refs:
                sanitized[key] = item
            else:
                sanitized[key] = None
                redacted = True
            continue
        if key in {"images", "videos"} and isinstance(item, list):
            filtered = [ref for ref in item if isinstance(ref, str) and ref in selected_refs]
            if len(filtered) != len([ref for ref in item if isinstance(ref, str)]):
                redacted = True
            sanitized[key] = filtered
            continue
        sanitized[key] = _delivery_safe_generation_payloads(item, selected_refs=selected_refs)
    if redacted:
        sanitized["unselected_media_redacted"] = True
    return sanitized


def _record_artifact_ref(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    attempt_id: str,
    kind: str,
    artifact_ref: str,
) -> tuple[str, dict[str, Any]]:
    source_ref = artifact_ref
    probe_ref = _materialize_remote_artifact_ref(artifact_ref, kind=kind)
    meta = probe_media_reference(probe_ref)
    content_hash = meta.sha256
    is_stable = meta.is_stable
    freshness_status = meta.freshness_status
    if _is_remote_url(source_ref) and meta.freshness_status == "unknown" and kind != "video":
        content_hash = "refhash:" + hashlib.sha256(artifact_ref.encode("utf-8")).hexdigest()
        is_stable = True
        freshness_status = "fresh"
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind=kind,
        local_path=meta.local_path,
        uri=source_ref,
        content_hash=content_hash,
        mime_type=meta.mime_type,
        bytes=meta.bytes,
        width=meta.width,
        height=meta.height,
        duration_seconds=getattr(meta, "duration_seconds", None),
        is_stable=is_stable,
        freshness_status=freshness_status,
    )
    return artifact_id, ledger.get_artifact(artifact_id)


def _materialize_remote_artifact_ref(artifact_ref: str, *, kind: str) -> str:
    if not _is_remote_url(artifact_ref) or kind != "video":
        return artifact_ref
    try:
        return download_remote_media(artifact_ref, kind=kind)
    except Exception as exc:
        logger.warning("could not materialize remote %s artifact %s: %s", kind, artifact_ref, exc)
        return artifact_ref


def download_remote_media(url: str, *, kind: str) -> str:
    if kind != "video":
        raise ValueError(f"unsupported remote media kind: {kind}")
    request = Request(url, headers={"User-Agent": "Hermes visual package"})
    with urlopen(request, timeout=60) as response:
        raw = response.read(MAX_REMOTE_MEDIA_BYTES + 1)
    if len(raw) > MAX_REMOTE_MEDIA_BYTES:
        raise ValueError("remote media exceeds maximum cache size")
    extension = _remote_media_extension(url, default="mp4")
    from agent.video_gen_provider import save_bytes_video

    return str(save_bytes_video(raw, prefix="visual-package", extension=extension))


def _remote_media_extension(url: str, *, default: str) -> str:
    suffix = urlparse(url).path.rsplit(".", 1)[-1].lower()
    if suffix in {"mp4", "mov", "webm", "mkv"}:
        return suffix
    return default


def _normalise_attachments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _wants_image(prompt: str, args: dict[str, Any]) -> bool:
    if args.get("include_image") is not None:
        return bool(args.get("include_image"))
    prompt_lc = prompt.lower()
    return any(token in prompt_lc for token in ("image", "photo", "picture", "圖片", "圖", "照片", "寫真", "素材"))


def _wants_video(prompt: str, args: dict[str, Any]) -> bool:
    if args.get("include_video") is not None:
        return bool(args.get("include_video"))
    prompt_lc = prompt.lower()
    return any(token in prompt_lc for token in ("video", "clip", "motion", "影片", "視頻", "短片", "動畫"))


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _candidate_visual_source(candidate: dict[str, Any]) -> str:
    for key in ("artifact_path", "local_path", "source_url", "uri"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _learning_mode(
    *,
    controlled_strategy_plan: StrategyPlan | None,
    feedback_strategy_plan: StrategyPlan | None,
) -> str:
    if controlled_strategy_plan is not None:
        return "controlled_read_only"
    if feedback_strategy_plan is not None:
        return "feedback_preferred_read_only"
    return "shadow"


def _strategy_plan_from_feedback_preference(
    base_plan: StrategyPlan,
    *,
    feedback_policy: dict[str, Any],
    intent_signature: str,
) -> StrategyPlan | None:
    preference = feedback_policy.get("strategy_preference")
    if not isinstance(preference, dict):
        return None
    strategy_signature = str(preference.get("strategy_signature") or "").strip()
    if not strategy_signature:
        return None
    return StrategyPlan(
        intent_signature=intent_signature,
        mode="feedback_preferred",
        confidence=_coerce_float(preference.get("confidence")),
        strategy_signature=strategy_signature,
        atom_signatures=list(base_plan.atom_signatures),
        activation_status=str(preference.get("activation_status") or "shadow").strip() or "shadow",
        prompt_mutation_allowed=False,
    )


def _visual_feedback_policy(
    args: dict[str, Any],
    *,
    wants_image: bool,
    wants_video: bool,
) -> dict[str, Any]:
    report = _runtime_visual_feedback_report()
    explicit_candidate_budget, default_candidate_budget = _candidate_budget_policy_inputs(args)
    return resolve_visual_feedback_policy(
        report,
        wants_image=wants_image,
        wants_video=wants_video,
        explicit_candidate_budget=explicit_candidate_budget,
        default_candidate_budget=default_candidate_budget,
    )


def _provider_retry_budget(feedback_policy: dict[str, Any]) -> int:
    value = _coerce_int(feedback_policy.get("provider_retry_budget"))
    return _clamp_budget(value or 1, minimum=1, maximum=2)


def _candidate_budget_policy_inputs(args: dict[str, Any]) -> tuple[int | None, int]:
    value = _coerce_int(args.get("candidate_budget"))
    source = str(args.get("candidate_budget_source") or "").strip().lower()
    if source == "planner_default":
        return None, _clamp_budget(value or 2, minimum=1, maximum=4)
    return value, 2


def _runtime_visual_feedback_report() -> dict[str, Any]:
    policy_sources = ["feedback_loop"]
    try:
        from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

        report = build_visual_feedback_loop_report(default_visual_ledger_path())
    except Exception as exc:  # noqa: BLE001 - feedback loop must never block generation
        logger.debug("visual feedback loop policy unavailable: %s", exc)
        report = {"next_actions": []}
    merged_actions = _action_list(report.get("next_actions"))
    scheduled_actions = _latest_self_validation_next_actions()
    if scheduled_actions:
        policy_sources.append("scheduled_self_validation")
        merged_actions.extend(scheduled_actions)
    merged_report = dict(report)
    merged_report["next_actions"] = merged_actions
    merged_report["policy_sources"] = policy_sources
    return merged_report


def _latest_self_validation_next_actions() -> list[dict[str, Any]]:
    latest_path = default_visual_ledger_path().parent / "self_validation" / "latest.json"
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - stale/missing reports must not block generation
        logger.debug("visual scheduled self-validation policy unavailable: %s", exc)
        return []
    if not isinstance(payload, dict):
        return []
    if payload.get("success") is not True:
        return []
    automation = payload.get("automation") if isinstance(payload.get("automation"), dict) else {}
    self_improvement = (
        automation.get("self_improvement")
        if isinstance(automation.get("self_improvement"), dict)
        else payload.get("self_improvement")
    )
    if not isinstance(self_improvement, dict):
        return []
    return _action_list(self_improvement.get("next_actions"))


def _action_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _video_budget(args: dict[str, Any], *, wants_video: bool) -> int:
    if not wants_video:
        return 0
    value = _coerce_int(args.get("video_budget"))
    return _clamp_budget(value or 1, minimum=1, maximum=2)


def _clamp_budget(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _image_tool_aspect_ratio(value: str) -> str:
    normalized = _judge_aspect_ratio(value)
    return {
        "16:9": "landscape",
        "9:16": "portrait",
        "1:1": "square",
    }.get(normalized, value)


def _judge_aspect_ratio(value: str) -> str:
    lowered = str(value or "").strip().lower()
    return {
        "landscape": "16:9",
        "portrait": "9:16",
        "square": "1:1",
    }.get(lowered, lowered or "16:9")


def _video_tool_aspect_ratio(*, requested_aspect_ratio: str, source_ref: str | None) -> str:
    supported = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
    if source_ref:
        meta = probe_media_reference(source_ref)
        return select_video_aspect_ratio(
            source_width=meta.width,
            source_height=meta.height,
            requested_aspect_ratio=requested_aspect_ratio,
            supported=supported,
            default=requested_aspect_ratio,
        )
    return select_video_aspect_ratio(
        source_width=None,
        source_height=None,
        requested_aspect_ratio=requested_aspect_ratio,
        supported=supported,
        default=requested_aspect_ratio,
    )


def _is_remote_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


registry.register(
    name="visual_package_generate",
    toolset="image_gen",
    schema=VISUAL_PACKAGE_SCHEMA,
    handler=_handle_visual_package_generate,
    check_fn=check_visual_package_requirements,
    requires_env=[],
    is_async=True,
    emoji="🎞️",
)

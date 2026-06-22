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
INLINE_VISION_JUDGE_PROMPT = """\
Evaluate this generated visual artifact for automated quality ranking.
Return only a JSON object with numeric values from 0.0 to 1.0:
{
  "reference_adherence": 0.5,
  "face_quality": 0.5,
  "visual_appeal": 0.5,
  "composition": 0.5,
  "pose_novelty": 0.5,
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
    candidate_budget = _candidate_budget(args, wants_image=should_generate_image)
    video_budget = _video_budget(args, wants_video=wants_video)
    inline_vision_judge = _inline_vision_judge_mode(args)
    normalized_intent = {
        "kind": "visual_package",
        "wants_image": requested_image,
        "wants_video": wants_video,
        "generates_image": should_generate_image,
        "image_first_for_video": image_first_for_video,
        "aspect_ratio": _judge_aspect_ratio(aspect_ratio),
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

    all_artifact_ids: list[str] = []
    all_artifact_paths: list[str] = []
    selected_artifact_ids: list[str] = []
    selected_images: list[str] = []
    selected_videos: list[str] = []
    video_source_image: str | None = None
    rankings: dict[str, dict[str, Any]] = {}
    generation_payloads: dict[str, Any] = {}
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
    if controlled_strategy_plan is not None:
        strategy_plan = controlled_strategy_plan
    learning: dict[str, Any] = {
        "mode": "controlled_read_only" if controlled_strategy_plan is not None else "shadow",
        "strategy_plan": strategy_plan.to_record(),
        "active_learning": {},
    }

    if should_generate_image:
        image_payloads = []
        image_candidates = []
        for candidate_index in range(candidate_budget):
            image_kwargs = {
                "prompt": prompt,
                "aspect_ratio": image_aspect_ratio,
                "reference_image_urls": attachments or None,
            }
            image_payload = generate_image(**image_kwargs)
            if not image_payload.get("success"):
                _annotate_generation_failure(
                    image_payload,
                    base_kwargs=image_kwargs,
                    request={
                        "prompt": prompt,
                        "arguments": image_kwargs,
                        "source_media": _source_media_from_attachments(attachments),
                    },
                    retry_budget_remaining=1,
                )
            image_payloads.append(image_payload)
            image_candidate = _record_payload_candidate(
                ledger,
                request_id=request_id,
                payload=image_payload,
                artifact_key="image",
                expected_kind="image",
                prompt=prompt,
                provider=str(image_payload.get("provider") or ""),
                model=str(image_payload.get("model") or ""),
                requested_parameters={"aspect_ratio": _judge_aspect_ratio(aspect_ratio)},
                candidate_index=candidate_index,
            )
            if image_candidate:
                image_candidates.append(image_candidate)
                all_artifact_ids.append(image_candidate["artifact_id"])
                all_artifact_paths.append(image_candidate["artifact_path"])
            elif not image_payload.get("success"):
                retry_payload = _retry_generation_payload(
                    generator=generate_image,
                    payload=image_payload,
                    base_kwargs=image_kwargs,
                    request={
                        "prompt": prompt,
                        "arguments": image_kwargs,
                        "source_media": _source_media_from_attachments(attachments),
                    },
                    retry_budget_remaining=1,
                    retry_of=candidate_index,
                )
                if retry_payload is not None:
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
                        candidate_index=candidate_index + candidate_budget,
                    )
                    if retry_candidate:
                        image_candidates.append(retry_candidate)
                        all_artifact_ids.append(retry_candidate["artifact_id"])
                        all_artifact_paths.append(retry_candidate["artifact_path"])
        generation_payloads["image"] = image_payloads[0] if len(image_payloads) == 1 else image_payloads
        _score_candidates(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            modality="image",
            has_reference_image=bool(attachments),
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
        learning["active_learning"]["image"] = _record_learning_trace(
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
        selected_image = _selected_candidate(image_candidates, image_decision.selected_artifact_id)
        if selected_image:
            video_source_image = selected_image["artifact_path"]
            if requested_image:
                selected_artifact_ids.append(selected_image["artifact_id"])
                selected_images.append(selected_image["artifact_path"])

    if wants_video:
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
            hardened_video = build_hardened_video_request(
                prompt=prompt,
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
                video_payload = generate_video(**video_kwargs)
                if not video_payload.get("success"):
                    _annotate_generation_failure(
                        video_payload,
                        base_kwargs=video_kwargs,
                        request={
                            "prompt": prompt,
                            "arguments": video_kwargs,
                            "source_media": _source_media_from_attachments([video_image_url]),
                            "video_hardening": hardened_video.get("metadata", {}),
                        },
                        retry_budget_remaining=1,
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
                    },
                    candidate_index=candidate_index,
                )
                if video_candidate:
                    video_candidates.append(video_candidate)
                    all_artifact_ids.append(video_candidate["artifact_id"])
                    all_artifact_paths.append(video_candidate["artifact_path"])
                elif not video_payload.get("success"):
                    retry_payload = _retry_generation_payload(
                        generator=generate_video,
                        payload=video_payload,
                        base_kwargs=video_kwargs,
                        request={
                            "prompt": prompt,
                            "arguments": video_kwargs,
                            "source_media": _source_media_from_attachments([video_image_url]),
                            "video_hardening": hardened_video.get("metadata", {}),
                        },
                        retry_budget_remaining=1,
                        retry_of=candidate_index,
                    )
                    if retry_payload is not None:
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
                            },
                            candidate_index=candidate_index + video_budget,
                        )
                        if retry_candidate:
                            video_candidates.append(retry_candidate)
                            all_artifact_ids.append(retry_candidate["artifact_id"])
                            all_artifact_paths.append(retry_candidate["artifact_path"])
            generation_payloads["video"] = video_payloads[0] if len(video_payloads) == 1 else video_payloads
        _score_candidates(
            ledger,
            request_id=request_id,
            intent_signature=intent_signature,
            strategy_signature=strategy_plan.strategy_signature,
            modality="video",
            has_reference_image=bool(video_image_url),
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
        learning["active_learning"]["video"] = _record_learning_trace(
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
        selected_video = _selected_candidate(video_candidates, video_decision.selected_artifact_id)
        if selected_video:
            selected_artifact_ids.append(selected_video["artifact_id"])
            selected_videos.append(selected_video["artifact_path"])

    success = (not requested_image or bool(selected_images)) and (not wants_video or bool(selected_videos))
    package_status = "success" if success else ("partial" if selected_images or selected_videos else "failed")
    delivery_metadata = visual_delivery_metadata(
        request_id=request_id,
        attempt_id=None,
        artifact_ids=all_artifact_ids,
        artifact_paths=all_artifact_paths,
        selected_artifact_ids=selected_artifact_ids,
    )

    payload = {
        "success": success,
        "package_status": package_status,
        "visual_request_id": request_id,
        "images": selected_images,
        "videos": selected_videos,
        "rankings": rankings,
        "generation_strategy": {
            "requested_image": requested_image,
            "generated_image": should_generate_image,
            "image_first_for_video": image_first_for_video,
            "video_source_image": video_source_image,
        },
        "delivery_metadata": delivery_metadata,
        "generation_payloads": generation_payloads,
        "learning": learning,
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


def _retry_generation_payload(
    *,
    generator,
    payload: dict[str, Any],
    base_kwargs: dict[str, Any],
    request: dict[str, Any],
    retry_budget_remaining: int,
    retry_of: int,
) -> dict[str, Any] | None:
    _annotate_generation_failure(
        payload,
        base_kwargs=base_kwargs,
        request=request,
        retry_budget_remaining=retry_budget_remaining,
    )
    recovery = payload["recovery"]
    if recovery.get("decision") != "retry":
        return None
    retry_kwargs = {**base_kwargs}
    for key in recovery.get("removed_arguments") or []:
        retry_kwargs.pop(str(key), None)
    retry_kwargs.update(_generator_kwargs(recovery.get("modified_arguments")))
    retry_payload = generator(**retry_kwargs)
    retry_payload["retry_of"] = retry_of
    retry_payload["recovery"] = recovery
    return retry_payload


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
    for key in ("failure", "recovery", "retry_of"):
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
            request_context={"has_reference_image": has_reference_image},
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


def _top_ranked_candidate(
    candidates: list[dict[str, Any]],
    ranked_artifact_ids: Any,
) -> dict[str, Any] | None:
    if isinstance(ranked_artifact_ids, list) and ranked_artifact_ids:
        return _selected_candidate(candidates, str(ranked_artifact_ids[0]))
    return candidates[0] if candidates else None


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


def _candidate_budget(args: dict[str, Any], *, wants_image: bool) -> int:
    if not wants_image:
        return 0
    value = _coerce_int(args.get("candidate_budget"))
    return _clamp_budget(value or 2, minimum=1, maximum=4)


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

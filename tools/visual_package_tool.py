from __future__ import annotations

import json
import logging
import hashlib
from typing import Any
from urllib.parse import urlparse

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.judges.deterministic import judge_artifact
from agent.visual.media_probe import probe_media_reference
from agent.visual.ranker import rank_visual_candidates
from agent.visual.tracking import default_visual_ledger_path
from agent.visual.tracking import visual_delivery_metadata
from tools.registry import registry
from tools.registry import tool_error

logger = logging.getLogger(__name__)


VISUAL_PACKAGE_SCHEMA: dict[str, Any] = {
    "name": "visual_package_generate",
    "description": (
        "Generate a coordinated visual package when the user naturally asks "
        "for both an image and a video, a set of visual assets, a product photo "
        "plus short clip, or similar. Use this instead of separate image_generate "
        "and video_generate calls for requests like '請產出一張圖片和一段影片', "
        "'做一組視覺素材', 'image plus short video', or 'product photo and 6 second clip'. "
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
    wants_image = _wants_image(prompt, args)
    wants_video = _wants_video(prompt, args)
    if not wants_image and not wants_video:
        wants_image = True
        wants_video = True

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt=prompt,
        normalized_intent={
            "kind": "visual_package",
            "wants_image": wants_image,
            "wants_video": wants_video,
        },
        modality="package",
        operation="visual_package_generate",
        status="started",
    )

    all_artifact_ids: list[str] = []
    all_artifact_paths: list[str] = []
    selected_artifact_ids: list[str] = []
    selected_images: list[str] = []
    selected_videos: list[str] = []
    rankings: dict[str, dict[str, Any]] = {}
    generation_payloads: dict[str, Any] = {}

    if wants_image:
        image_payload = generate_image(
            prompt=prompt,
            aspect_ratio=image_aspect_ratio,
            reference_image_urls=attachments or None,
        )
        generation_payloads["image"] = image_payload
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
        )
        if image_candidate:
            all_artifact_ids.append(image_candidate["artifact_id"])
            all_artifact_paths.append(image_candidate["artifact_path"])
            image_decision = rank_visual_candidates(
                request_id=request_id,
                candidates=[image_candidate],
                post_threshold=0.0,
                ask_threshold=0.0,
            )
            rankings["image"] = image_decision.__dict__
            if image_decision.selected_artifact_id == image_candidate["artifact_id"]:
                selected_artifact_ids.append(image_candidate["artifact_id"])
                selected_images.append(image_candidate["artifact_path"])

    if wants_video:
        video_image_url = str(args.get("image_url") or "").strip() or (selected_images[0] if selected_images else None)
        video_payload = generate_video(
            prompt=prompt,
            image_url=video_image_url,
            duration=duration,
            aspect_ratio=_judge_aspect_ratio(aspect_ratio),
        )
        generation_payloads["video"] = video_payload
        video_candidate = _record_payload_candidate(
            ledger,
            request_id=request_id,
            payload=video_payload,
            artifact_key="video",
            expected_kind="video",
            prompt=prompt,
            provider=str(video_payload.get("provider") or ""),
            model=str(video_payload.get("model") or ""),
            requested_parameters={"duration_seconds": duration},
        )
        if video_candidate:
            all_artifact_ids.append(video_candidate["artifact_id"])
            all_artifact_paths.append(video_candidate["artifact_path"])
            video_decision = rank_visual_candidates(
                request_id=request_id,
                candidates=[video_candidate],
                post_threshold=0.0,
                ask_threshold=0.0,
            )
            rankings["video"] = video_decision.__dict__
            if video_decision.selected_artifact_id == video_candidate["artifact_id"]:
                selected_artifact_ids.append(video_candidate["artifact_id"])
                selected_videos.append(video_candidate["artifact_path"])

    success = (not wants_image or bool(selected_images)) and (not wants_video or bool(selected_videos))
    package_status = "success" if success else ("partial" if selected_images or selected_videos else "failed")
    delivery_metadata = visual_delivery_metadata(
        request_id=request_id,
        attempt_id=None,
        artifact_ids=all_artifact_ids,
        artifact_paths=all_artifact_paths,
        selected_artifact_ids=selected_artifact_ids,
    )

    return {
        "success": success,
        "package_status": package_status,
        "visual_request_id": request_id,
        "images": selected_images,
        "videos": selected_videos,
        "rankings": rankings,
        "delivery_metadata": delivery_metadata,
        "generation_payloads": generation_payloads,
    }


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
) -> dict[str, Any] | None:
    success = bool(payload.get("success"))
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider=provider,
        model=model,
        prompt_original=prompt,
        prompt_mediated=prompt,
        parameters_requested=requested_parameters,
        parameters_effective=requested_parameters,
        status="completed" if success else "failed",
        error_type=payload.get("error_type") if not success else None,
        error_message=payload.get("error") if not success else None,
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
        "hard_gate": score["hard_gate"],
        "scores": score["scores"],
    }


def _record_artifact_ref(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    attempt_id: str,
    kind: str,
    artifact_ref: str,
) -> tuple[str, dict[str, Any]]:
    meta = probe_media_reference(artifact_ref)
    content_hash = meta.sha256
    is_stable = meta.is_stable
    freshness_status = meta.freshness_status
    if _is_remote_url(artifact_ref) and meta.freshness_status == "unknown":
        content_hash = "refhash:" + hashlib.sha256(artifact_ref.encode("utf-8")).hexdigest()
        is_stable = True
        freshness_status = "fresh"
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind=kind,
        local_path=meta.local_path,
        uri=artifact_ref,
        content_hash=content_hash,
        mime_type=meta.mime_type,
        bytes=meta.bytes,
        width=meta.width,
        height=meta.height,
        is_stable=is_stable,
        freshness_status=freshness_status,
    )
    return artifact_id, ledger.get_artifact(artifact_id)


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

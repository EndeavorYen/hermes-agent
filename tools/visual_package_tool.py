from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from agent.visual.prompt_disclosure import is_visual_prompt_disclosure_request
from tools.registry import registry, tool_error


VISUAL_PACKAGE_SCHEMA: dict[str, Any] = {
    "name": "visual_package_generate",
    "description": (
        "Generate a coordinated visual package when the user asks for images, "
        "video, or image plus video. For text-only video requests, use an "
        "image-first route: generate still source candidates, select one, then "
        "animate that single source image."
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
                "description": "Optional image paths, data URIs, or URLs supplied by the user.",
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Optional shared aspect ratio: 16:9, 9:16, 1:1, landscape, portrait, or square.",
            },
            "duration": {
                "type": "integer",
                "description": "Optional desired video duration in seconds.",
            },
            "candidate_budget": {
                "type": "integer",
                "description": "Optional still-image candidate budget.",
            },
            "candidate_budget_source": {
                "type": "string",
                "description": "Optional source marker for planner-provided candidate budgets.",
            },
            "include_image": {
                "type": "boolean",
                "description": (
                    "Whether to deliver a selected image. Video-only requests may "
                    "still generate internal source images for image-first video."
                ),
            },
            "include_video": {
                "type": "boolean",
                "description": "Whether to generate and deliver selected video output.",
            },
            "video_budget": {
                "type": "integer",
                "description": "Optional video candidate budget. Defaults to 1.",
            },
            "image_provider": {
                "type": "string",
                "description": "Optional image backend override, for example xai or openai-codex.",
            },
            "image_provider_source": {
                "type": "string",
                "description": "Optional source marker for the image provider override.",
            },
            "storyboard": {
                "type": "object",
                "description": (
                    "Optional multi-shot video contract. Each shot should use one "
                    "ranked source image, not a collage or candidate grid."
                ),
            },
        },
        "required": ["prompt"],
    },
}

_DATA_URI_RE = re.compile(r"^data:(image/([a-z0-9.+-]+));base64,(.*)$", re.IGNORECASE | re.DOTALL)
_IMAGE_TOKENS = ("image", "photo", "picture", "圖片", "照片", "寫真", "圖")
_VIDEO_TOKENS = ("video", "clip", "motion", "animate", "影片", "視頻", "短片", "動畫", "動起來")


def check_visual_package_requirements() -> bool:
    try:
        from tools.image_generation_tool import check_image_generation_requirements

        if not check_image_generation_requirements():
            return False
    except Exception:
        return False
    try:
        from tools.video_generation_tool import check_video_generation_requirements

        return bool(check_video_generation_requirements())
    except Exception:
        return False


def generate_image(**kwargs: Any) -> dict[str, Any]:
    from tools.image_generation_tool import _handle_image_generate

    return _loads_tool_payload(_handle_image_generate(kwargs))


def generate_video(**kwargs: Any) -> dict[str, Any]:
    from tools.video_generation_tool import _handle_video_generate

    return _loads_tool_payload(_handle_video_generate(kwargs))


async def _handle_visual_package_generate(args: dict[str, Any], **_kw: Any) -> str:
    prompt = str((args or {}).get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required for visual package generation")
    if is_visual_prompt_disclosure_request(prompt):
        return tool_error(
            "visual_package_generate is for image/video generation, not prompt disclosure",
            request_type="visual_prompt_disclosure",
        )

    attachments = _normalise_attachments((args or {}).get("attachments"))
    wants_image = _wants_image(prompt, args or {})
    wants_video = _wants_video(prompt, args or {})
    if not wants_image and not wants_video:
        return tool_error("visual_package_generate requires an image or video request")

    request_id = f"vrq_{uuid.uuid4().hex[:12]}"
    aspect_ratio = _normalise_aspect_ratio((args or {}).get("aspect_ratio"))
    duration = _coerce_int((args or {}).get("duration")) or _duration_seconds(prompt) or 6
    image_provider = _image_provider_override(args or {})
    candidate_budget = _candidate_budget(args or {}, wants_image=wants_image, wants_video=wants_video)
    video_budget = _video_budget(args or {}, wants_video=wants_video)

    image_payloads: list[dict[str, Any]] = []
    image_candidates: list[dict[str, Any]] = []
    if wants_image or (wants_video and not attachments):
        for index in range(candidate_budget):
            image_kwargs = _image_kwargs(
                prompt=prompt,
                args=args or {},
                attachments=attachments,
                aspect_ratio=aspect_ratio,
                image_provider=image_provider,
                video_source_only=wants_video and not wants_image,
            )
            payload = generate_image(**image_kwargs)
            image_payloads.append(
                _public_generation_payload(payload, hide_artifact=not wants_image)
            )
            image_ref = _payload_ref(payload, "image")
            if payload.get("success") and image_ref:
                artifact_id = f"{request_id}_img_{index + 1}"
                image_candidates.append(
                    {
                        "artifact_id": artifact_id,
                        "path": image_ref,
                        "payload": payload,
                    }
                )

    selected_image = image_candidates[0] if image_candidates else None
    video_source_image = _video_source_image(
        selected_image=selected_image,
        attachments=attachments,
        wants_video=wants_video,
    )

    video_payloads: list[dict[str, Any]] = []
    video_candidates: list[dict[str, Any]] = []
    if wants_video:
        for index in range(video_budget):
            video_kwargs = _video_kwargs(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                duration=duration,
                image_url=video_source_image,
            )
            payload = generate_video(**video_kwargs)
            video_payloads.append(payload)
            video_ref = _payload_ref(payload, "video")
            if payload.get("success") and video_ref:
                artifact_id = f"{request_id}_vid_{index + 1}"
                video_candidates.append(
                    {
                        "artifact_id": artifact_id,
                        "path": video_ref,
                        "payload": payload,
                    }
                )

    selected_video = video_candidates[0] if video_candidates else None
    images = [selected_image["path"]] if wants_image and selected_image else []
    videos = [selected_video["path"]] if wants_video and selected_video else []
    selected_ids = []
    if wants_image and selected_image:
        selected_ids.append(selected_image["artifact_id"])
    if wants_video and selected_video:
        selected_ids.append(selected_video["artifact_id"])

    success = (not wants_image or bool(images)) and (not wants_video or bool(videos))
    payload = {
        "success": success,
        "visual_request_id": request_id,
        "images": images,
        "videos": videos,
        "package_status": "success" if success else ("partial" if images or videos else "failed"),
        "generation_strategy": {
            "include_image": wants_image,
            "include_video": wants_video,
            "image_first_for_video": bool(wants_video and video_source_image),
            "video_source_image": video_source_image,
            "video_source_image_count": 1 if video_source_image else 0,
            "video_source_policy": (
                "single_ranked_selected_image" if video_source_image else "none"
            ),
        },
        "generation_payloads": {
            "image": image_payloads,
            "video": video_payloads,
        },
        "rankings": {
            "image": {
                "selected_artifact_id": selected_image["artifact_id"] if selected_image else None,
                "ranked_artifact_ids": [item["artifact_id"] for item in image_candidates],
            },
            "video": {
                "selected_artifact_id": selected_video["artifact_id"] if selected_video else None,
                "ranked_artifact_ids": [item["artifact_id"] for item in video_candidates],
            },
        },
        "delivery_metadata": {
            "selected_visual_artifact_ids": selected_ids,
            "visual_artifacts": _visual_artifacts(
                request_id=request_id,
                image_candidates=image_candidates,
                video_candidates=video_candidates,
            ),
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _loads_tool_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {"success": False, "error": "tool returned a non-string response"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"tool returned invalid JSON: {exc}"}
    if isinstance(payload, dict):
        return payload
    return {"success": False, "error": "tool returned non-object JSON"}


def _normalise_attachments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    attachments: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        attachments.append(_materialize_data_uri(text) or text)
    return attachments


def _materialize_data_uri(value: str) -> str | None:
    match = _DATA_URI_RE.match(value)
    if not match:
        return None
    mime_type = match.group(1).lower()
    extension = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(mime_type, match.group(2).lower())
    try:
        data = base64.b64decode(match.group(3), validate=True)
    except (binascii.Error, ValueError):
        return None
    digest = hashlib.sha256(data).hexdigest()[:16]
    root = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    out_dir = root / "cache" / "visual-agent-attachments"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{digest}.{extension}"
    out_path.write_bytes(data)
    return str(out_path)


def _wants_image(prompt: str, args: dict[str, Any]) -> bool:
    if args.get("include_image") is not None:
        return _coerce_bool(args.get("include_image"))
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    return any(token in lowered for token in _IMAGE_TOKENS) or any(
        token in compact for token in ("產出一張", "生成一張", "畫一", "幫我畫")
    )


def _wants_video(prompt: str, args: dict[str, Any]) -> bool:
    if args.get("include_video") is not None:
        return _coerce_bool(args.get("include_video"))
    lowered = prompt.lower()
    return any(token in lowered for token in _VIDEO_TOKENS)


def _candidate_budget(args: dict[str, Any], *, wants_image: bool, wants_video: bool) -> int:
    if not wants_image and not wants_video:
        return 0
    explicit = _coerce_int(args.get("candidate_budget"))
    if explicit is not None:
        return _clamp(explicit, 1, 4)
    return 1


def _video_budget(args: dict[str, Any], *, wants_video: bool) -> int:
    if not wants_video:
        return 0
    return _clamp(_coerce_int(args.get("video_budget")) or 1, 1, 2)


def _image_kwargs(
    *,
    prompt: str,
    args: dict[str, Any],
    attachments: list[str],
    aspect_ratio: str,
    image_provider: str | None,
    video_source_only: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "prompt": _source_frame_prompt(prompt) if video_source_only else prompt,
        "aspect_ratio": _image_tool_aspect_ratio(aspect_ratio),
    }
    if attachments:
        kwargs["reference_image_urls"] = attachments
    if image_provider:
        kwargs["_provider"] = image_provider
    image_model = str(args.get("image_model") or args.get("_image_model") or "").strip()
    if image_model:
        kwargs["_model"] = image_model
    return kwargs


def _video_kwargs(
    *,
    prompt: str,
    aspect_ratio: str,
    duration: int,
    image_url: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "prompt": _video_motion_prompt(prompt),
        "aspect_ratio": aspect_ratio,
        "duration": duration,
    }
    if image_url:
        kwargs["image_url"] = image_url
        kwargs["source_media"] = {
            "reference_count": 1,
            "references": [image_url],
        }
    return kwargs


def _source_frame_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Create a single still source frame for image-first video. "
        "This is not a video storyboard. Do not create a collage, contact sheet, "
        "grid, split-screen, or four-panel layout."
    )


def _video_motion_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Animate the selected still as a coherent short clip with natural "
        "real-time motion, not slow motion, and visible subject, camera, or "
        "environmental movement."
    )


def _image_provider_override(args: dict[str, Any]) -> str | None:
    raw = str(args.get("image_provider") or args.get("_provider") or args.get("provider") or "").strip()
    return raw or None


def _normalise_aspect_ratio(value: Any) -> str:
    text = str(value or "").strip().lower()
    return {
        "landscape": "16:9",
        "horizontal": "16:9",
        "wide": "16:9",
        "portrait": "9:16",
        "vertical": "9:16",
        "square": "1:1",
    }.get(text, text or "16:9")


def _image_tool_aspect_ratio(value: str) -> str:
    return {
        "16:9": "landscape",
        "9:16": "portrait",
        "1:1": "square",
    }.get(value, value)


def _duration_seconds(prompt: str) -> int | None:
    match = re.search(r"(\d{1,2})\s*(?:秒|seconds?|sec|s)", prompt.lower())
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _video_source_image(
    *,
    selected_image: dict[str, Any] | None,
    attachments: list[str],
    wants_video: bool,
) -> str | None:
    if not wants_video:
        return None
    if selected_image:
        return selected_image["path"]
    return attachments[0] if attachments else None


def _payload_ref(payload: dict[str, Any], kind: str) -> str | None:
    keys = ("video", "url", "public_url") if kind == "video" else ("image", "host_image", "agent_visible_image")
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _public_generation_payload(payload: dict[str, Any], *, hide_artifact: bool) -> dict[str, Any]:
    public = dict(payload)
    if hide_artifact:
        for key in ("image", "host_image", "agent_visible_image"):
            if key in public:
                public[key] = None
    return public


def _visual_artifacts(
    *,
    request_id: str,
    image_candidates: list[dict[str, Any]],
    video_candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for item in image_candidates:
        artifacts[item["path"]] = {
            "request_id": request_id,
            "artifact_id": item["artifact_id"],
            "kind": "image",
        }
    for item in video_candidates:
        artifacts[item["path"]] = {
            "request_id": request_id,
            "artifact_id": item["artifact_id"],
            "kind": "video",
        }
    return artifacts


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


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


registry.register(
    name="visual_package_generate",
    toolset="image_gen",
    schema=VISUAL_PACKAGE_SCHEMA,
    handler=_handle_visual_package_generate,
    check_fn=check_visual_package_requirements,
    requires_env=[],
    is_async=True,
    emoji="VP",
)

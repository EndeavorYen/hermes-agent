#!/usr/bin/env python3
"""
Video Generation Tool
=====================

Single ``video_generate`` tool that dispatches to a plugin-registered
video generation provider. Mirrors the ``image_generate`` design:

- ``agent/video_gen_provider.py`` defines the :class:`VideoGenProvider` ABC.
- ``agent/video_gen_registry.py`` holds the active providers (populated by
  plugins at import time).
- Each provider lives under ``plugins/video_gen/<name>/``.

The tool itself is intentionally backend-agnostic and ships **no in-tree
provider** — turn on a backend by enabling a plugin (``hermes plugins
enable video_gen/<name>``) and selecting it in ``hermes tools`` → Video
Generation.

Unified surface
---------------
One tool covers the common cases — text-to-video, image-to-video, video
edit, video extend — with a compact schema:

    prompt                   text instruction (required for generate/edit)
    operation                "generate" | "edit" | "extend"
    image_url                drives image-to-video when operation=generate
    video_url                source video for edit/extend
    reference_image_urls     list, up to provider-declared cap
    duration                 seconds (provider clamps)
    aspect_ratio             "16:9" | "9:16" | "1:1" | ...
    resolution               "480p" | "540p" | "720p" | "1080p"
    negative_prompt          optional (Pixverse/Kling style)
    audio                    optional (Veo3/Pixverse pricing tier)
    seed                     optional
    model                    optional, override the active provider's default

Providers ignore parameters they do not support. The tool layer does
**lightweight** validation (type/required-prompt) and lets each provider
do its own clamping inside :meth:`VideoGenProvider.generate` — that keeps
the tool surface stable as new providers ship with different capabilities.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional

from agent.video_gen_provider import (
    COMMON_ASPECT_RATIOS,
    COMMON_RESOLUTIONS,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_RESOLUTION,
    error_response,
)
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)
MAX_REMOTE_VIDEO_BYTES = 150 * 1024 * 1024

_IMAGE_FIRST_VISUAL_VIDEO_TOKENS = (
    "portrait",
    "fashion",
    "glamour",
    "photoshoot",
    "photo shoot",
    "product",
    "model",
    "runway",
    "beauty",
    "cosplay",
    "寫真",
    "時尚",
    "人物",
    "角色",
    "美女",
    "模特",
    "產品",
    "商品",
    "黑絲",
    "絲襪",
    "禮服",
)

_IMAGE_REQUEST_TOKENS = ("image", "photo", "picture", "圖片", "圖", "照片", "寫真")


VIDEO_GENERATE_SCHEMA: Dict[str, Any] = {
    "name": "video_generate",
    # Placeholder — the real description is built dynamically at
    # get_tool_definitions() time so it reflects the active backend's
    # actual capabilities (which modalities / resolutions / duration
    # ranges the user's currently-selected model supports).
    # See _build_dynamic_video_schema() below and the dynamic-tool-schemas
    # skill at github/hermes-agent-dev/references/dynamic-tool-schemas.md.
    "description": "(rebuilt at get_definitions() time — see _build_dynamic_video_schema)",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Text instruction describing the desired video, motion, "
                    "subject, style, camera movement, etc."
                ),
            },
            "image_url": {
                "type": "string",
                "description": (
                    "Optional public URL of a still image. When provided, "
                    "the active backend routes to its image-to-video "
                    "endpoint (animate the image); when omitted, it routes "
                    "to text-to-video. Pass either a URL the user supplied "
                    "or a path/URL from the conversation."
                ),
            },
            "reference_image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of reference image URLs (style or "
                    "character refs). Only supported by some backends; "
                    "the active backend's description below indicates whether "
                    "this is honored and what the max is."
                ),
            },
            "duration": {
                "type": "integer",
                "description": (
                    "Desired video duration in seconds. Providers clamp to "
                    "their supported range (commonly 4-15s). Omit to use the "
                    "provider's default."
                ),
            },
            "aspect_ratio": {
                "type": "string",
                "enum": list(COMMON_ASPECT_RATIOS),
                "description": (
                    "Output aspect ratio. Providers clamp to their supported "
                    "set."
                ),
                "default": DEFAULT_ASPECT_RATIO,
            },
            "resolution": {
                "type": "string",
                "enum": list(COMMON_RESOLUTIONS),
                "description": (
                    "Output resolution. Providers clamp to their supported "
                    "set."
                ),
                "default": DEFAULT_RESOLUTION,
            },
            "negative_prompt": {
                "type": "string",
                "description": (
                    "Optional negative prompt — content to avoid in the "
                    "output. Supported by Pixverse, Kling, and similar; "
                    "ignored by providers that do not support it."
                ),
            },
            "audio": {
                "type": "boolean",
                "description": (
                    "Optional audio generation toggle. Supported by Veo3 and "
                    "Pixverse (affects pricing tier); ignored elsewhere."
                ),
            },
            "seed": {
                "type": "integer",
                "description": (
                    "Optional seed for reproducible outputs (provider-"
                    "dependent)."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Optional model override. If omitted, the user's "
                    "configured ``video_gen.model`` (set via `hermes tools` "
                    "→ Video Generation) is used. Models that the active "
                    "provider does not know are rejected."
                ),
            },
        },
        "required": ["prompt"],
    },
}


# ---------------------------------------------------------------------------
# Config readers (mirror image_generation_tool.py)
# ---------------------------------------------------------------------------


def _read_video_gen_section() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("video_gen") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:
        logger.debug("Could not read video_gen config: %s", exc)
        return {}


def _read_configured_video_provider() -> Optional[str]:
    value = _read_video_gen_section().get("provider")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_configured_video_model() -> Optional[str]:
    value = _read_video_gen_section().get("model")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def check_video_generation_requirements() -> bool:
    """Return True when at least one registered provider reports available.

    Triggers plugin discovery (idempotent) so user-installed plugins are
    visible to the toolset gate.
    """
    try:
        from agent.video_gen_registry import list_providers
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        for provider in list_providers():
            try:
                if provider.is_available():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _resolve_active_provider():
    """Return the active provider object or None.

    Forces plugin discovery before checking the registry — handles cases
    where a long-lived session was started before a plugin was installed.
    """
    try:
        from agent.video_gen_registry import get_active_provider
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        provider = get_active_provider()
        if provider is None:
            _ensure_plugins_discovered(force=True)
            provider = get_active_provider()
        return provider
    except Exception as exc:
        logger.debug("video_gen provider resolution failed: %s", exc)
        return None


def _missing_provider_error(configured: Optional[str]) -> str:
    if configured:
        msg = (
            f"video_gen.provider='{configured}' is set but no plugin "
            f"registered that name. Run `hermes plugins list` to see "
            f"installed video gen backends, or `hermes tools` → Video "
            f"Generation to pick one."
        )
        return json.dumps(error_response(
            error=msg, error_type="provider_not_registered",
            provider=configured,
        ))
    msg = (
        "No video generation backend is configured. Run `hermes tools` → "
        "Video Generation to enable one (xAI, FAL, or Google Veo)."
    )
    return json.dumps(error_response(
        error=msg, error_type="no_provider_configured",
    ))


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "on"}:
            return True
        if v in {"false", "0", "no", "off"}:
            return False
    return None


def _normalize_reference_images(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return None
    out: List[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out or None


def _track_video_generate_payload(
    payload: Dict[str, Any],
    *,
    prompt: str,
    image_url: Optional[str],
    provider: str,
    model: str,
    aspect_ratio: str,
    duration: Optional[int],
    resolution: str,
) -> Dict[str, Any]:
    try:
        from agent.visual.tracking import record_visual_generation_attempt

        operation = "image_to_video" if image_url else "text_to_video"
        modality = str(payload.get("modality") or ("image" if image_url else "text"))
        return record_visual_generation_attempt(
            payload,
            user_prompt=prompt,
            prompt_original=prompt,
            prompt_mediated=prompt,
            modality=modality,
            operation=operation,
            artifact_key="video",
            kind="video",
            provider=provider,
            model=model,
            parameters_requested={
                "aspect_ratio": aspect_ratio,
                "duration": duration,
                "resolution": resolution,
            },
            parameters_effective={
                "aspect_ratio": payload.get("aspect_ratio") or aspect_ratio,
                "duration": payload.get("duration") or duration,
                "resolution": payload.get("resolution") or resolution,
            },
        )
    except Exception as exc:  # noqa: BLE001 - video generation must not depend on tracking
        logger.warning("Video generation tracking skipped: %s", exc)
        return payload


def _handle_video_generate(args: Dict[str, Any], **_kw: Any) -> str:
    prompt = (args.get("prompt") or "").strip()
    image_url = (args.get("image_url") or "").strip() or None
    reference_image_urls = _normalize_reference_images(args.get("reference_image_urls"))
    duration = _coerce_int(args.get("duration"))
    aspect_ratio = (args.get("aspect_ratio") or DEFAULT_ASPECT_RATIO).strip() or DEFAULT_ASPECT_RATIO
    resolution = (args.get("resolution") or DEFAULT_RESOLUTION).strip() or DEFAULT_RESOLUTION
    negative_prompt = (args.get("negative_prompt") or "").strip() or None
    audio = _coerce_bool(args.get("audio"))
    seed = _coerce_int(args.get("seed"))
    model_override = (args.get("model") or "").strip() or None

    # Soft validation — providers do their own. Prompt is required by the
    # schema; the backend may still accept image-only on its image-to-video
    # endpoint but our surface always needs a prompt.
    if not prompt:
        return tool_error("prompt is required for video generation")

    # Resolve the active provider.
    configured = _read_configured_video_provider()
    provider = _resolve_active_provider()
    if provider is None:
        return _missing_provider_error(configured)

    # Resolve model: explicit arg wins, then config, then provider default.
    model = model_override or _read_configured_video_model() or provider.default_model()

    kwargs: Dict[str, Any] = {
        "model": model,
        "_model_override_explicit": bool(model_override),
        "image_url": image_url,
        "reference_image_urls": reference_image_urls,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "negative_prompt": negative_prompt,
        "audio": audio,
        "seed": seed,
    }
    # Drop None entries so providers see clean defaults.
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    if _should_defer_to_visual_package(
        prompt=prompt,
        image_url=image_url,
        reference_image_urls=reference_image_urls,
        provider_name=str(getattr(provider, "name", "")),
        model=model,
    ):
        return json.dumps(_route_visual_video_to_package(
            prompt=prompt,
            provider=str(getattr(provider, "name", "")),
            model=model or "",
            aspect_ratio=aspect_ratio,
            duration=duration,
            resolution=resolution,
        ))

    try:
        result = provider.generate(prompt=prompt, **kwargs)
    except TypeError as exc:
        # A provider that hasn't widened its signature is a bug, not a
        # caller error — log and surface a clear contract message.
        logger.warning(
            "video_gen provider '%s' rejected kwargs (signature too narrow): %s",
            getattr(provider, "name", "?"), exc,
        )
        payload = error_response(
            error=(
                f"Provider '{getattr(provider, 'name', '?')}' signature is "
                f"out of date with the video_generate schema. Report this "
                f"to the plugin author."
            ),
            error_type="provider_contract",
            provider=getattr(provider, "name", ""),
            model=model or "",
            prompt=prompt,
        )
        tracked = _track_video_generate_payload(
            payload,
            prompt=prompt,
            image_url=image_url,
            provider=getattr(provider, "name", ""),
            model=model or "",
            aspect_ratio=aspect_ratio,
            duration=duration,
            resolution=resolution,
        )
        return json.dumps(tracked)
    except Exception as exc:
        logger.warning(
            "video_gen provider '%s' raised: %s",
            getattr(provider, "name", "?"), exc,
        )
        payload = error_response(
            error=f"Provider '{getattr(provider, 'name', '?')}' error: {exc}",
            error_type="provider_exception",
            provider=getattr(provider, "name", ""),
            model=model or "",
            prompt=prompt,
        )
        tracked = _track_video_generate_payload(
            payload,
            prompt=prompt,
            image_url=image_url,
            provider=getattr(provider, "name", ""),
            model=model or "",
            aspect_ratio=aspect_ratio,
            duration=duration,
            resolution=resolution,
        )
        return json.dumps(tracked)

    if not isinstance(result, dict):
        payload = error_response(
            error="Provider returned a non-dict result",
            error_type="provider_contract",
            provider=getattr(provider, "name", ""),
            model=model or "",
            prompt=prompt,
        )
        tracked = _track_video_generate_payload(
            payload,
            prompt=prompt,
            image_url=image_url,
            provider=getattr(provider, "name", ""),
            model=model or "",
            aspect_ratio=aspect_ratio,
            duration=duration,
            resolution=resolution,
        )
        return json.dumps(tracked)

    materialized = _materialize_remote_video_result(
        result,
        provider_name=str(result.get("provider") or getattr(provider, "name", "")),
    )
    tracked = _track_video_generate_payload(
        materialized,
        prompt=prompt,
        image_url=image_url,
        provider=str(materialized.get("provider") or getattr(provider, "name", "")),
        model=str(materialized.get("model") or model or ""),
        aspect_ratio=aspect_ratio,
        duration=duration,
        resolution=resolution,
    )
    return json.dumps(tracked)


def _materialize_remote_video_result(result: Dict[str, Any], *, provider_name: str) -> Dict[str, Any]:
    if result.get("success") is not True:
        return result
    video_ref = result.get("video")
    if not isinstance(video_ref, str) or not _is_remote_video_url(video_ref):
        return result
    if provider_name.strip().lower() != "xai":
        return result
    payload = dict(result)
    payload["source_video_url"] = video_ref
    try:
        payload["video"] = download_remote_video(video_ref)
    except Exception as exc:  # noqa: BLE001 - preserve provider evidence in structured failure
        payload["success"] = False
        payload["video"] = None
        payload["error_type"] = "remote_video_materialization_failed"
        payload["error"] = f"Could not download generated video for native upload: {exc}"
    return payload


def download_remote_video(url: str) -> str:
    from urllib.request import urlopen

    with urlopen(url, timeout=60) as response:  # noqa: S310 - provider-generated media URL
        raw = response.read(MAX_REMOTE_VIDEO_BYTES + 1)
    if len(raw) > MAX_REMOTE_VIDEO_BYTES:
        raise ValueError("remote video exceeds maximum cache size")
    from agent.video_gen_provider import save_bytes_video

    return str(save_bytes_video(raw, prefix="video-generate", extension=_remote_video_extension(url)))


def _is_remote_video_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and _remote_video_extension(value) in {
        "mp4",
        "mov",
        "webm",
        "mkv",
    }


def _remote_video_extension(url: str) -> str:
    path = urlparse(url).path
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return suffix or "mp4"


def _should_defer_to_visual_package(
    *,
    prompt: str,
    image_url: str | None,
    reference_image_urls: List[str],
    provider_name: str,
    model: str | None,
) -> bool:
    if image_url or reference_image_urls:
        return False
    if not _uses_image_first_visual_package_auto_route(provider_name, model):
        return False
    return _looks_like_image_first_visual_video(prompt)


def _uses_image_first_visual_package_auto_route(provider_name: str, model: str | None) -> bool:
    if provider_name.lower() != "xai":
        return False
    model_lc = str(model or "").lower()
    return "grok-imagine-video" in model_lc


def _route_visual_video_to_package(
    *,
    prompt: str,
    provider: str,
    model: str,
    aspect_ratio: str,
    duration: int | None,
    resolution: str,
) -> Dict[str, Any]:
    package_args: Dict[str, Any] = {
        "prompt": prompt,
        "include_image": _prompt_requests_image(prompt),
        "include_video": True,
        "candidate_budget": 2,
        "candidate_budget_source": "planner_default",
        "video_budget": 1,
        "aspect_ratio": aspect_ratio,
    }
    if duration is not None:
        package_args["duration"] = duration
    try:
        from model_tools import _run_async
        from tools.visual_package_tool import _handle_visual_package_generate

        package_raw = _run_async(_handle_visual_package_generate(package_args))
        package_payload = json.loads(package_raw) if isinstance(package_raw, str) else package_raw
    except Exception as exc:  # noqa: BLE001 - surface structured route failure
        return {
            "success": False,
            "video": None,
            "error": f"visual_package_generate auto-route failed: {exc}",
            "error_type": "visual_package_route_failed",
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "route": "image_first_visual_package",
            "source_tool": "video_generate",
            "recommended_tool": "visual_package_generate",
            "recommended_arguments": package_args,
        }
    if not isinstance(package_payload, dict):
        return {
            "success": False,
            "video": None,
            "error": "visual_package_generate returned a non-dict payload",
            "error_type": "visual_package_contract",
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "route": "image_first_visual_package",
            "source_tool": "video_generate",
            "recommended_tool": "visual_package_generate",
            "recommended_arguments": package_args,
        }
    videos = [
        item
        for item in package_payload.get("videos", [])
        if isinstance(item, str) and item.strip()
    ]
    video_ref = videos[0] if videos else None
    success = bool(package_payload.get("success")) and bool(video_ref)
    video_generation_payload = _selected_visual_package_video_payload(package_payload)
    actual_provider = str(video_generation_payload.get("provider") or provider)
    actual_model = str(video_generation_payload.get("model") or model)
    payload: Dict[str, Any] = {
        "success": success,
        "video": video_ref,
        "videos": videos,
        "images": package_payload.get("images", []),
        "error": None if success else package_payload.get("error") or "visual_package_generate did not return a selected video",
        "error_type": None if success else package_payload.get("error_type") or "visual_package_no_video",
        "provider": actual_provider,
        "model": actual_model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "resolution": resolution,
        "route": "image_first_visual_package",
        "source_tool": "video_generate",
        "recommended_tool": "visual_package_generate",
        "recommended_arguments": package_args,
        "visual_request_id": package_payload.get("visual_request_id"),
        "package_status": package_payload.get("package_status"),
        "delivery_metadata": package_payload.get("delivery_metadata"),
        "generation_strategy": package_payload.get("generation_strategy"),
        "rankings": package_payload.get("rankings"),
        "autonomous_validation": package_payload.get("autonomous_validation"),
        "autonomous_orchestration": package_payload.get("autonomous_orchestration"),
    }
    return payload


def _selected_visual_package_video_payload(package_payload: Dict[str, Any]) -> Dict[str, Any]:
    generation_payloads = package_payload.get("generation_payloads")
    if not isinstance(generation_payloads, dict):
        return {}
    video_payload = generation_payloads.get("video")
    if isinstance(video_payload, dict):
        return video_payload
    if isinstance(video_payload, list):
        for item in video_payload:
            if isinstance(item, dict) and item.get("success") is True and item.get("video"):
                return item
        for item in video_payload:
            if isinstance(item, dict):
                return item
    return {}


def _looks_like_image_first_visual_video(prompt: str) -> bool:
    prompt_lc = str(prompt or "").lower()
    return any(token in prompt_lc for token in _IMAGE_FIRST_VISUAL_VIDEO_TOKENS)


def _prompt_requests_image(prompt: str) -> bool:
    prompt_lc = str(prompt or "").lower()
    return any(token in prompt_lc for token in _IMAGE_REQUEST_TOKENS)


# ---------------------------------------------------------------------------
# Dynamic schema — reflect the active backend's actual capabilities
# ---------------------------------------------------------------------------
#
# Why dynamic: the user's configured backend determines which operations
# (generate/edit/extend), modalities (text / image / refs), aspect ratios,
# resolutions, durations, and audio/negative-prompt flags are real. A model
# that calls video_generate without knowing the active backend wastes a
# turn on something like "fal-ai/veo3.1/image-to-video requires image_url".
# Surfacing the per-model surface in the description means the model
# usually gets the call right on the first try.
#
# Memoization: model_tools.get_tool_definitions() keys its cache on
# config.yaml mtime, so when the user changes provider/model via
# `hermes tools` or `/skills`, the schema rebuilds automatically.


_GENERIC_DESCRIPTION = (
    "Generate a video from a text prompt (text-to-video) or animate a "
    "still image (image-to-video) using the user's configured video "
    "generation backend. Pass `image_url` to animate that image; omit it "
    "to generate from text alone. The backend auto-routes to the right "
    "endpoint. The backend and model family are user-configured via "
    "`hermes tools` → Video Generation; the agent does not pick them. "
    "Long-running generations may take 30 seconds to several minutes — "
    "the call blocks until the video is ready. Returns either an HTTP "
    "URL or an absolute file path in the `video` field; display it with "
    "markdown ![description](url-or-path) and the gateway will deliver it."
)


def _format_model_caveats(
    model_meta: Dict[str, Any],
    backend_caps: Dict[str, Any],
) -> List[str]:
    """Pull human-readable caveats out of one model's catalog metadata.

    Only surfaces things that meaningfully differ from the backend's
    overall capabilities — repeating defaults is noise.
    """
    caveats: List[str] = []

    modalities = set(model_meta.get("modalities") or [])
    modality = model_meta.get("modality")  # FAL's plugin uses this key for single-modality entries
    if modality:
        modalities.add(modality)

    if "image" in modalities and "text" not in modalities:
        caveats.append(
            "this model is image-to-video only — image_url is REQUIRED; "
            "text-only calls will be rejected"
        )
    elif "text" in modalities and "image" not in modalities:
        caveats.append(
            "this model is text-to-video only — image_url is not supported"
        )

    return caveats


def _build_dynamic_video_schema() -> Dict[str, Any]:
    """Build a description that reflects the active backend's actual surface.

    Cheap: reads config (already memoized by the caller), asks the active
    provider for `capabilities()` and the active model's catalog entry,
    and formats a few lines of prose. Falls back to the generic
    description when no provider is configured or registered.
    """
    parts: List[str] = [_GENERIC_DESCRIPTION]

    configured = _read_configured_video_provider()
    configured_model = _read_configured_video_model()

    if not configured:
        parts.append(
            "\nNo video backend is configured. Calls will return an error "
            "until the user picks one via `hermes tools` → Video Generation."
        )
        return {"description": "\n".join(parts)}

    try:
        from agent.video_gen_registry import get_provider
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()
        provider = get_provider(configured)
    except Exception:
        provider = None

    if provider is None:
        parts.append(
            f"\nActive backend: {configured} (plugin not yet loaded — the "
            f"tool will retry discovery on first call)."
        )
        return {"description": "\n".join(parts)}

    try:
        caps = provider.capabilities() or {}
    except Exception:
        caps = {}
    try:
        models = provider.list_models() or []
    except Exception:
        models = []

    active_model = configured_model or provider.default_model()
    model_meta = next(
        (m for m in models if isinstance(m, dict) and m.get("id") == active_model),
        {},
    )

    backend_label = provider.display_name
    line = f"\nActive backend: {backend_label}"
    if active_model:
        line += f" · model: {active_model}"
    parts.append(line)
    if _uses_image_first_visual_package_auto_route(provider.name, active_model):
        parts.append(
            "- text-only visual video requests automatically use the "
            "image-first visual package route via visual_package_generate: "
            "generate image candidates, rank/select one, then animate it."
        )

    # Model-specific caveats (the high-signal stuff)
    for c in _format_model_caveats(model_meta, caps):
        parts.append(f"- {c}")

    # Backend modality summary — only useful when the backend supports
    # both text and image. Single-modality backends are already covered by
    # the model caveat above.
    modalities = set(caps.get("modalities") or [])
    if "text" in modalities and "image" in modalities and not model_meta.get("modality"):
        parts.append(
            "- supports both text-to-video (omit image_url) and "
            "image-to-video (pass image_url) — routes automatically"
        )

    if caps.get("aspect_ratios"):
        parts.append(f"- aspect_ratio choices: {', '.join(caps['aspect_ratios'])}")
    if caps.get("resolutions"):
        parts.append(f"- resolution choices: {', '.join(caps['resolutions'])}")
    if caps.get("min_duration") and caps.get("max_duration"):
        parts.append(
            f"- duration range: {caps['min_duration']}-{caps['max_duration']}s"
        )
    if caps.get("supports_audio"):
        parts.append("- audio: pass `audio=true` to enable native audio (pricing tier)")
    if caps.get("supports_negative_prompt"):
        parts.append("- negative_prompt: supported")
    max_refs = caps.get("max_reference_images") or 0
    if max_refs:
        parts.append(f"- reference_image_urls: up to {max_refs} images")

    return {"description": "\n".join(parts)}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


registry.register(
    name="video_generate",
    toolset="video_gen",
    schema=VIDEO_GENERATE_SCHEMA,
    handler=_handle_video_generate,
    check_fn=check_video_generation_requirements,
    requires_env=[],
    is_async=False,
    emoji="🎬",
    dynamic_schema_overrides=_build_dynamic_video_schema,
)

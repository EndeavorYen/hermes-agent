"""xAI Grok-Imagine video generation backend.

Surface: text-to-video and image-to-video (animate an input image)
through xAI's ``/videos/generations`` endpoint. Edit and extend are not
exposed in this unified surface — xAI is the only backend that supports
them and the inconsistency would force per-backend prose in the agent's
tool description.

Originally salvaged from PR #10600 by @Jaaneek; reshaped into the
:class:`VideoGenProvider` plugin interface and trimmed to the
generate-only surface.

Authentication: xAI Grok OAuth tokens (preferred — billed against the
user's SuperGrok or X Premium+ subscription) or ``XAI_API_KEY``. Both routes are
resolved through ``tools.xai_http.resolve_xai_http_credentials`` so a
single login covers chat + TTS + image gen + video gen + transcription.
Output is an HTTPS URL from xAI's CDN; the gateway downloads and
delivers it.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx

from agent.video_gen_provider import (
    VideoGenProvider,
    error_response,
    save_bytes_video,
    success_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_TEXT_TO_VIDEO_MODEL = "grok-imagine-video"
DEFAULT_IMAGE_TO_VIDEO_MODEL = "grok-imagine-video-1.5"
DEFAULT_MODEL = DEFAULT_TEXT_TO_VIDEO_MODEL
DEFAULT_DURATION = 8
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_RESOLUTION = "720p"
DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_POLL_INTERVAL_SECONDS = 5
MAX_TIMEOUT_SECONDS = 1800

VALID_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
VALID_RESOLUTIONS = {"480p", "720p"}
MAX_REFERENCE_IMAGES = 7
_ASPECT_RATIO_VALUES = {
    "1:1": 1.0,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
}


_MODELS: Dict[str, Dict[str, Any]] = {
    "grok-imagine-video": {
        "display": "Grok Imagine Video",
        "speed": "~60-240s",
        "strengths": "Text-to-video; legacy image-to-video fallback.",
        "price": "see https://docs.x.ai/developers/models/grok-imagine-video",
        "modalities": ["text", "image"],
    },
    "grok-imagine-video-1.5": {
        "display": "Grok Imagine Video 1.5",
        "speed": "~25-240s",
        "strengths": "Generally available xAI image-to-video model.",
        "price": "see https://docs.x.ai/developers/models/grok-imagine-video-1.5",
        "modalities": ["image"],
        "aliases": [
            "grok-imagine-video-1.5-preview",
            "grok-imagine-video-1.5-2026-05-30",
        ],
    },
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _resolve_xai_credentials() -> Tuple[str, str]:
    """Return ``(api_key, base_url)`` from the shared xAI credential resolver.

    Order: runtime provider (xai-oauth pool entry) → singleton ``auth.json``
    OAuth tokens → ``XAI_API_KEY`` env var. ``api_key`` is empty when no
    credential source is available; callers must check before using it.
    """
    try:
        from tools.xai_http import resolve_xai_http_credentials

        creds = resolve_xai_http_credentials() or {}
    except Exception as exc:
        logger.debug("xAI credential resolver failed: %s", exc)
        creds = {}

    api_key = str(creds.get("api_key") or os.getenv("XAI_API_KEY", "")).strip()
    base_url = str(
        creds.get("base_url")
        or os.getenv("XAI_BASE_URL")
        or DEFAULT_XAI_BASE_URL
    ).strip().rstrip("/")
    return api_key, base_url


def _read_xai_video_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
    except Exception:
        return {}
    video_gen = cfg.get("video_gen") if isinstance(cfg, dict) else {}
    if not isinstance(video_gen, dict):
        return {}
    xai = video_gen.get("xai")
    merged = dict(video_gen)
    if isinstance(xai, dict):
        merged.update(xai)
    return merged


def _configured_timeout_seconds() -> int:
    raw = _read_xai_video_config().get("timeout_seconds")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(60, min(value, MAX_TIMEOUT_SECONDS))


def _with_error_details(
    *,
    error: str,
    error_type: str,
    provider: str,
    model: str,
    prompt: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = error_response(
        error=error,
        error_type=error_type,
        provider=provider,
        model=model,
        prompt=prompt,
    )
    for key, value in (extra or {}).items():
        if value is not None and value != "":
            result[key] = value
    return result


def _json_body(response: Any) -> Dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _xai_error_fields(body: Dict[str, Any]) -> Tuple[Optional[str], str]:
    code = body.get("code") if isinstance(body.get("code"), str) else None
    message = ""
    error_value = body.get("error")
    if isinstance(error_value, dict):
        code = code or error_value.get("code") or error_value.get("type")
        message = (
            error_value.get("message")
            or error_value.get("error")
            or error_value.get("detail")
            or ""
        )
    elif isinstance(error_value, str):
        message = error_value

    if not message:
        for key in ("message", "detail"):
            if isinstance(body.get(key), str):
                message = body[key]
                break
    return code, message


def _classify_xai_error(
    *,
    http_status: int = 0,
    error_code: Optional[str] = None,
    message: str = "",
    xai_status: str = "",
) -> str:
    haystack = f"{error_code or ''} {message} {xai_status}".lower()
    if any(term in haystack for term in ("moderation", "rejected", "safety")):
        return "content_moderation"
    if http_status == 401:
        return "auth_required"
    if http_status == 403:
        return "permission_denied"
    if http_status == 429:
        return "rate_limited"
    if 400 <= http_status < 500:
        return "invalid_request"
    if http_status >= 500:
        return "provider_unavailable"
    if xai_status:
        return f"xai_{xai_status}"
    return "api_error"


def _http_error_response(
    exc: httpx.HTTPStatusError,
    *,
    phase: str,
    provider: str,
    model: str,
    prompt: str,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    response = exc.response
    http_status = int(getattr(response, "status_code", 0) or 0)
    body = _json_body(response)
    error_code, message = _xai_error_fields(body)
    if not message:
        try:
            message = response.text[:500]
        except Exception:
            message = str(exc)
    error_code = error_code or (f"http_{http_status}" if http_status else "http_error")
    xai_status = str(body.get("status") or "").lower()
    error_type = _classify_xai_error(
        http_status=http_status,
        error_code=error_code,
        message=message,
        xai_status=xai_status,
    )
    return _with_error_details(
        error=f"xAI {phase} failed ({http_status}, {error_code}): {message}",
        error_type=error_type,
        provider=provider,
        model=model,
        prompt=prompt,
        extra={
            "error_phase": phase,
            "http_status": http_status,
            "error_code": error_code,
            "provider_error_message": message,
            "request_id": request_id,
            "xai_status": xai_status,
        },
    )


def _request_error_code(exc: httpx.RequestError) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.WriteTimeout):
        return "write_timeout"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool_timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.NetworkError):
        return "network_error"
    return "request_error"


def _request_error_response(
    exc: httpx.RequestError,
    *,
    phase: str,
    provider: str,
    model: str,
    prompt: str,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    error_code = _request_error_code(exc)
    message = str(exc).strip() or exc.__class__.__name__
    error_type = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection_error"
    return _with_error_details(
        error=f"xAI {phase} failed ({error_code}): {message}",
        error_type=error_type,
        provider=provider,
        model=model,
        prompt=prompt,
        extra={
            "error_phase": phase,
            "error_code": error_code,
            "provider_error_message": message,
            "request_id": request_id,
        },
    )


def _xai_user_agent() -> str:
    try:
        from tools.xai_http import hermes_xai_user_agent

        return hermes_xai_user_agent()
    except Exception:
        return "hermes-agent/video_gen"


def _xai_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": _xai_user_agent(),
    }


def _image_ref_to_xai_url(value: str) -> str:
    """Return a URL/data URI accepted by xAI for image inputs."""
    ref = (value or "").strip()
    if not ref:
        return ""
    lower = ref.lower()
    if lower.startswith(("http://", "https://", "data:image/")):
        return ref

    path = Path(ref).expanduser()
    if not path.is_file():
        return ref

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not mime.startswith("image/"):
        return ref

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _closest_supported_aspect_ratio(width: int, height: int) -> Optional[str]:
    if width <= 0 or height <= 0:
        return None

    actual = width / height
    return min(
        _ASPECT_RATIO_VALUES,
        key=lambda label: abs(actual - _ASPECT_RATIO_VALUES[label]),
    )


def _local_image_path_from_ref(value: str) -> Optional[Path]:
    ref = (value or "").strip()
    if not ref:
        return None

    lower = ref.lower()
    if lower.startswith(("http://", "https://", "data:image/")):
        return None
    if lower.startswith("file://"):
        parsed = urlparse(ref)
        path = Path(unquote(parsed.path)).expanduser()
    else:
        path = Path(ref).expanduser()

    return path if path.is_file() else None


def _infer_aspect_ratio_from_image_ref(value: str) -> Optional[str]:
    ref = (value or "").strip()
    if not ref:
        return None

    try:
        from PIL import Image

        if ref.lower().startswith("data:image/") and "," in ref:
            _, encoded = ref.split(",", 1)
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
                return _closest_supported_aspect_ratio(*image.size)

        path = _local_image_path_from_ref(ref)
        if path is None:
            return None
        with Image.open(path) as image:
            return _closest_supported_aspect_ratio(*image.size)
    except Exception as exc:
        logger.debug("Could not infer xAI video aspect ratio from image ref: %s", exc)
        return None


def _normalize_reference_images(reference_image_urls: Optional[List[str]]):
    refs = []
    for url in reference_image_urls or []:
        normalized = _image_ref_to_xai_url(url)
        if normalized:
            refs.append({"url": normalized})
    return refs or None


def _clamp_duration(duration: Optional[int], has_reference_images: bool) -> int:
    value = duration if duration is not None else DEFAULT_DURATION
    if value < 1:
        value = 1
    if value > 15:
        value = 15
    if has_reference_images and value > 10:
        value = 10
    return value


def _resolve_model_for_modality(
    model: Optional[str],
    *,
    modality: str,
    explicit_model: bool,
) -> str:
    """Select xAI's text/video model without treating config as a prompt override.

    ``grok-imagine-video-1.5`` currently rejects text-only video
    generation, but it is the desired image-to-video backend. Explicit tool
    ``model=`` still wins for users who intentionally request another model.
    """
    requested = (model or "").strip()
    if modality == "image":
        if explicit_model and requested and requested != DEFAULT_TEXT_TO_VIDEO_MODEL:
            return requested
        return DEFAULT_IMAGE_TO_VIDEO_MODEL
    if explicit_model and requested:
        return requested
    if requested == DEFAULT_IMAGE_TO_VIDEO_MODEL:
        return DEFAULT_TEXT_TO_VIDEO_MODEL
    return requested or DEFAULT_TEXT_TO_VIDEO_MODEL


async def _submit(
    client: httpx.AsyncClient,
    payload: Dict[str, Any],
    *,
    api_key: str,
    base_url: str,
) -> str:
    """POST to /videos/generations — xAI's only public endpoint for our
    text-to-video and image-to-video surface."""
    response = await client.post(
        f"{base_url}/videos/generations",
        headers={**_xai_headers(api_key), "x-idempotency-key": str(uuid.uuid4())},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    request_id = body.get("request_id")
    if not request_id:
        raise RuntimeError("xAI video response did not include request_id")
    return request_id


async def _poll(
    client: httpx.AsyncClient,
    request_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: int,
    poll_interval: int,
) -> Dict[str, Any]:
    elapsed = 0.0
    last_status = "queued"
    while elapsed < timeout_seconds:
        response = await client.get(
            f"{base_url}/videos/{request_id}",
            headers=_xai_headers(api_key),
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        last_status = (body.get("status") or "").lower()

        if last_status == "done":
            return {"status": "done", "body": body}
        if last_status in {"failed", "error", "expired", "cancelled"}:
            return {"status": last_status, "body": body}

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    return {"status": "timeout", "body": {"status": last_status}}


async def _download_video_url_to_cache(
    client: httpx.AsyncClient,
    url: str,
    *,
    model: str,
) -> Path:
    response = await client.get(
        url,
        headers={
            "User-Agent": _xai_user_agent(),
            "Accept": "video/*,*/*;q=0.8",
        },
        timeout=120,
    )
    response.raise_for_status()
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".") or "mp4"
    if suffix == "mpeg":
        suffix = "mp4"
    return save_bytes_video(
        response.content,
        prefix=f"xai_{model}",
        extension=suffix,
    )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class XAIVideoGenProvider(VideoGenProvider):
    """xAI Grok Imagine video backend (text-to-video + image-to-video)."""

    @property
    def name(self) -> str:
        return "xai"

    @property
    def display_name(self) -> str:
        return "xAI"

    def is_available(self) -> bool:
        api_key, _ = _resolve_xai_credentials()
        return bool(api_key)

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"id": mid, **meta} for mid, meta in _MODELS.items()]

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        # Auth resolution lives entirely in the shared ``xai_grok`` post_setup
        # hook (``hermes_cli/tools_config.py``) so the picker doesn't blindly
        # prompt for an API key when the user is already signed in via xAI
        # Grok OAuth (SuperGrok / Premium+) — TTS / image gen / video gen
        # all share the same credential resolver. The hook offers an
        # OAuth-vs-API-key choice when neither is configured.
        return {
            "name": "xAI Grok Imagine",
            "badge": "paid",
            "tag": "grok-imagine-video for text-to-video; grok-imagine-video-1.5 for image-to-video; uses xAI Grok OAuth or XAI_API_KEY",
            "env_vars": [],
            "post_setup": "xai_grok",
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "aspect_ratios": sorted(VALID_ASPECT_RATIOS),
            "resolutions": sorted(VALID_RESOLUTIONS),
            "max_duration": 15,
            "min_duration": 1,
            "supports_audio": False,
            "supports_negative_prompt": False,
            "max_reference_images": MAX_REFERENCE_IMAGES,
        }

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        duration: Optional[int] = None,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        resolution: str = DEFAULT_RESOLUTION,
        negative_prompt: Optional[str] = None,
        audio: Optional[bool] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._generate_async(
                    prompt=prompt,
                    model=model,
                    explicit_model=bool(kwargs.get("_model_override_explicit")),
                    image_url=image_url,
                    reference_image_urls=reference_image_urls,
                    duration=duration,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                ))
            finally:
                loop.close()
        except Exception as exc:
            logger.warning("xAI video gen unexpected failure: %s", exc, exc_info=True)
            return error_response(
                error=f"xAI video generation failed: {exc}",
                error_type="api_error",
                provider="xai",
                model=model or DEFAULT_MODEL,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )

    async def _generate_async(
        self,
        *,
        prompt: str,
        model: Optional[str],
        explicit_model: bool,
        image_url: Optional[str],
        reference_image_urls: Optional[List[str]],
        duration: Optional[int],
        aspect_ratio: str,
        resolution: str,
    ) -> Dict[str, Any]:
        api_key, base_url = _resolve_xai_credentials()
        if not api_key:
            return error_response(
                error=(
                    "No xAI credentials found. Sign in via `hermes auth add xai-oauth` "
                    "(SuperGrok / Premium+) or set XAI_API_KEY from "
                    "https://console.x.ai/."
                ),
                error_type="auth_required",
                provider="xai", prompt=prompt,
            )

        prompt = (prompt or "").strip()
        image_url_norm = _image_ref_to_xai_url(image_url or "") or None
        normalized_aspect_ratio = (aspect_ratio or DEFAULT_ASPECT_RATIO).strip()
        normalized_resolution = (resolution or DEFAULT_RESOLUTION).strip().lower()
        modality_used = "image" if image_url_norm else "text"
        if modality_used == "image":
            inferred_aspect_ratio = _infer_aspect_ratio_from_image_ref(image_url or "")
            normalized_aspect_ratio = inferred_aspect_ratio or ""
        resolved_model = _resolve_model_for_modality(
            model,
            modality=modality_used,
            explicit_model=explicit_model,
        )

        if not prompt:
            return error_response(
                error=(
                    "prompt is required for xAI video generation "
                    "(text-to-video or image-to-video)"
                ),
                error_type="missing_prompt",
                provider="xai", prompt=prompt,
            )

        refs = _normalize_reference_images(reference_image_urls)
        if refs and len(refs) > MAX_REFERENCE_IMAGES:
            return error_response(
                error=f"reference_image_urls supports at most {MAX_REFERENCE_IMAGES} images on xAI",
                error_type="too_many_references",
                provider="xai", prompt=prompt,
            )
        if image_url_norm and refs:
            return error_response(
                error="image_url and reference_image_urls cannot be combined on xAI",
                error_type="conflicting_inputs",
                provider="xai", prompt=prompt,
            )

        clamped_duration = _clamp_duration(duration, has_reference_images=bool(refs))

        if (
            modality_used != "image"
            and normalized_aspect_ratio not in VALID_ASPECT_RATIOS
        ):
            normalized_aspect_ratio = DEFAULT_ASPECT_RATIO
        if normalized_resolution not in VALID_RESOLUTIONS:
            normalized_resolution = DEFAULT_RESOLUTION

        payload: Dict[str, Any] = {
            "model": resolved_model,
            "prompt": prompt,
            "duration": clamped_duration,
            "resolution": normalized_resolution,
        }
        if modality_used != "image":
            payload["aspect_ratio"] = normalized_aspect_ratio
        if image_url_norm:
            payload["image"] = {"url": image_url_norm}
        if refs:
            payload["reference_images"] = refs

        async with httpx.AsyncClient() as client:
            try:
                request_id = await _submit(
                    client, payload, api_key=api_key, base_url=base_url
                )
            except httpx.HTTPStatusError as exc:
                return _http_error_response(
                    exc,
                    phase="submit",
                    provider="xai",
                    model=resolved_model,
                    prompt=prompt,
                )
            except httpx.RequestError as exc:
                return _request_error_response(
                    exc,
                    phase="submit",
                    provider="xai",
                    model=resolved_model,
                    prompt=prompt,
                )

            try:
                poll_result = await _poll(
                    client, request_id,
                    api_key=api_key, base_url=base_url,
                    timeout_seconds=_configured_timeout_seconds(),
                    poll_interval=DEFAULT_POLL_INTERVAL_SECONDS,
                )
            except httpx.HTTPStatusError as exc:
                return _http_error_response(
                    exc,
                    phase="poll",
                    provider="xai",
                    model=resolved_model,
                    prompt=prompt,
                    request_id=request_id,
                )
            except httpx.RequestError as exc:
                return _request_error_response(
                    exc,
                    phase="poll",
                    provider="xai",
                    model=resolved_model,
                    prompt=prompt,
                    request_id=request_id,
                )

            status = poll_result["status"]
            body = poll_result["body"]

            if status == "done":
                video = body.get("video") or {}
                url = video.get("url")
                if not url:
                    return error_response(
                        error="xAI video generation completed without a video URL",
                        error_type="empty_response",
                        provider="xai",
                        model=body.get("model") or resolved_model,
                        prompt=prompt,
                    )
                extra: Dict[str, Any] = {
                    "request_id": request_id,
                    "resolution": normalized_resolution,
                    "remote_video_url": url,
                }
                delivered_video = url
                try:
                    delivered_video = str(await _download_video_url_to_cache(
                        client,
                        url,
                        model=body.get("model") or resolved_model,
                    ))
                except Exception as exc:
                    logger.warning(
                        "xAI video download failed; returning remote URL fallback: %s",
                        exc,
                    )
                    extra["video_download_error"] = str(exc)
                if body.get("usage"):
                    extra["usage"] = body["usage"]
                return success_response(
                    video=delivered_video,
                    model=body.get("model") or resolved_model,
                    prompt=prompt,
                    modality=modality_used,
                    aspect_ratio=normalized_aspect_ratio,
                    duration=video.get("duration") or clamped_duration,
                    provider="xai",
                    extra=extra,
                )

        if status == "timeout":
            timeout_seconds = _configured_timeout_seconds()
            xai_status = str(body.get("status") or "").lower()
            return _with_error_details(
                error=(
                    f"Timed out waiting for video generation after {timeout_seconds}s"
                    + (f" (last xAI status: {xai_status})" if xai_status else "")
                ),
                error_type="timeout",
                provider="xai",
                model=resolved_model,
                prompt=prompt,
                extra={
                    "error_phase": "poll",
                    "error_code": "hermes_poll_timeout",
                    "request_id": request_id,
                    "xai_status": xai_status,
                    "timeout_seconds": timeout_seconds,
                    "retryable": True,
                },
            )

        error_code, provider_message = _xai_error_fields(body)
        message = (
            provider_message
            or body.get("message")
            or f"xAI video generation ended with status '{status}'"
        )
        return _with_error_details(
            error=message,
            error_type=_classify_xai_error(
                error_code=error_code,
                message=message,
                xai_status=status,
            ),
            provider="xai",
            model=resolved_model,
            prompt=prompt,
            extra={
                "error_phase": "poll",
                "error_code": error_code or f"xai_{status}",
                "request_id": request_id,
                "xai_status": status,
                "provider_error_message": provider_message,
            },
        )


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Plugin entry point — wire ``XAIVideoGenProvider`` into the registry."""
    ctx.register_video_gen_provider(XAIVideoGenProvider())

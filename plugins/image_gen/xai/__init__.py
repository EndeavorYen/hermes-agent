"""xAI image generation backend.

Exposes xAI's ``grok-imagine-image`` model as an
:class:`ImageGenProvider` implementation.

Features:
- Text-to-image generation
- Multiple aspect ratios (1:1, 16:9, 9:16, etc.)
- Multiple resolutions (1K, 2K)
- Base64 output saved to cache

Selection precedence (first hit wins):
1. ``XAI_IMAGE_MODEL`` env var
2. ``image_gen.xai.model`` in ``config.yaml``
3. :data:`DEFAULT_MODEL`
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    resolve_aspect_ratio,
    save_b64_image,
    save_url_image,
    success_response,
)
from tools.xai_http import (
    build_xai_storage_options,
    hermes_xai_user_agent,
    maybe_mark_xai_storage_notice_seen,
    read_xai_imagine_storage_config,
    resolve_xai_http_credentials,
    xai_storage_notice_text,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------

_MODELS: Dict[str, Dict[str, Any]] = {
    "grok-imagine-image": {
        "display": "Grok Imagine Image",
        "speed": "~5-10s",
        "strengths": "Fast, high-quality",
    },
    "grok-imagine-image-quality": {
        "display": "Grok Imagine Image (Quality)",
        "speed": "~10-20s",
        "strengths": "Higher fidelity / detail; slower than the standard model.",
    },
}

DEFAULT_MODEL = "grok-imagine-image"

# xAI aspect ratios (more options than FAL/OpenAI)
_XAI_ASPECT_RATIOS = {
    "landscape": "16:9",
    "square": "1:1",
    "portrait": "9:16",
    "4:3": "4:3",
    "3:4": "3:4",
    "3:2": "3:2",
    "2:3": "2:3",
}

# xAI resolutions
_XAI_RESOLUTIONS = {"1k", "2k"}

DEFAULT_RESOLUTION = "1k"
GROK_BUILD_TRANSPORT = "grok-build"
GROK_BUILD_MODEL = "grok-build-native-image"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_xai_config() -> Dict[str, Any]:
    """Read ``image_gen.xai`` from config.yaml."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        xai_section = section.get("xai") if isinstance(section, dict) else None
        return xai_section if isinstance(xai_section, dict) else {}
    except Exception as exc:
        logger.debug("Could not load image_gen.xai config: %s", exc)
        return {}


def _resolve_model() -> Tuple[str, Dict[str, Any]]:
    """Decide which model to use and return ``(model_id, meta)``."""
    env_override = os.environ.get("XAI_IMAGE_MODEL")
    if env_override and env_override in _MODELS:
        return env_override, _MODELS[env_override]

    cfg = _load_xai_config()
    candidate = cfg.get("model") if isinstance(cfg.get("model"), str) else None
    if candidate and candidate in _MODELS:
        return candidate, _MODELS[candidate]

    return DEFAULT_MODEL, _MODELS[DEFAULT_MODEL]


def _resolve_resolution() -> str:
    """Get configured resolution."""
    cfg = _load_xai_config()
    res = cfg.get("resolution") if isinstance(cfg.get("resolution"), str) else None
    if res and res in _XAI_RESOLUTIONS:
        return res
    return DEFAULT_RESOLUTION


def _configured_transport(config: Optional[Dict[str, Any]] = None) -> str:
    cfg = config if isinstance(config, dict) else _load_xai_config()
    value = str(cfg.get("transport") or "http").strip().lower().replace("_", "-")
    return GROK_BUILD_TRANSPORT if value in {"grok-build", "grokbuild", "cli"} else "http"


def _grok_build_binary(config: Optional[Dict[str, Any]] = None) -> str:
    cfg = config if isinstance(config, dict) else _load_xai_config()
    configured = str(
        cfg.get("grok_binary")
        or os.environ.get("GROK_BUILD_BINARY")
        or ""
    ).strip()
    if configured:
        return configured
    discovered = shutil.which("grok")
    if discovered:
        return discovered
    return str(Path.home() / ".local" / "bin" / "grok")


def _grok_build_available(config: Optional[Dict[str, Any]] = None) -> bool:
    binary = _grok_build_binary(config)
    binary_path = Path(binary).expanduser()
    executable = binary_path.is_file() and os.access(binary_path, os.X_OK)
    if not executable and os.path.sep not in binary:
        executable = bool(shutil.which(binary))
    return executable and (Path.home() / ".grok" / "auth.json").is_file()


def _grok_build_workdir(config: Dict[str, Any]) -> Path:
    configured = str(config.get("workdir") or "").strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        path = home / "cache" / "grok-build-image"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _iter_output_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_output_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_output_strings(item)


def _grok_build_image_path_candidates(value: Any) -> List[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    candidates = [raw, unquote(raw)]
    for source in (raw, unquote(raw)):
        for match in re.finditer(
            r"(?:vscode-file|file)://[^\s`'\"<>]+",
            source,
            re.IGNORECASE,
        ):
            uri = match.group(0).rstrip(").,;]")
            parsed = urlparse(uri)
            path = unquote(parsed.path)
            if path.startswith("//"):
                path = path[1:]
            if path:
                candidates.append(path)
    return list(dict.fromkeys(candidates))


def _extract_grok_build_image(
    stdout: str,
    *,
    workdir: Optional[Path] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    candidates: List[str] = []
    text = str(stdout or "").strip()
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
            candidates.extend(_iter_output_strings(parsed))
        except json.JSONDecodeError:
            for line in reversed(text.splitlines()):
                try:
                    candidates.extend(_iter_output_strings(json.loads(line)))
                except json.JSONDecodeError:
                    continue
        candidates.extend(
            match.group(1)
            for match in re.finditer(
                r"(?:^|[\s\"'])(/[^\n\"']+?\.(?:png|jpe?g|webp))(?:$|[\s\"'])",
                text,
                re.IGNORECASE,
            )
        )
    candidates = [
        path
        for candidate in candidates
        for path in _grok_build_image_path_candidates(candidate)
    ]
    for candidate in candidates:
        path = Path(str(candidate).strip().strip("`'\"")).expanduser()
        if path.suffix.lower() in _IMAGE_SUFFIXES and path.is_file():
            return str(path.resolve())
    if isinstance(parsed, dict) and workdir is not None:
        session_id = str(parsed.get("sessionId") or parsed.get("session_id") or "").strip()
        if session_id:
            cfg = config if isinstance(config, dict) else {}
            grok_home = Path(
                str(cfg.get("grok_home") or Path.home() / ".grok")
            ).expanduser()
            session_roots = (
                workdir.resolve() / session_id,
                grok_home
                / "sessions"
                / quote(str(workdir.resolve()), safe="")
                / session_id,
            )
            for candidate in candidates:
                relative = Path(str(candidate).strip())
                if (
                    relative.is_absolute()
                    or relative.suffix.lower() not in _IMAGE_SUFFIXES
                    or ".." in relative.parts
                ):
                    continue
                for session_root in session_roots:
                    path = session_root / relative
                    if path.is_file():
                        return str(path.resolve())
    return None


def _generate_with_grok_build(
    *,
    prompt: str,
    aspect_ratio: str,
    source_images: List[str],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    aspect = resolve_aspect_ratio(aspect_ratio)
    if not _grok_build_available(config):
        return error_response(
            error="Grok Build OAuth transport is unavailable or not signed in.",
            error_type="missing_oauth",
            provider="xai",
            model=GROK_BUILD_MODEL,
            prompt=prompt,
            aspect_ratio=aspect,
        )

    operation = "image_edit" if source_images else "image_gen"
    reference_lines = "\n".join(f"- {path}" for path in source_images)
    instruction = (
        "Use exactly one native xAI Grok Imagine tool call. "
        f"Call `{operation}` and do not use web, shell, code execution, or subagents.\n"
        f"Aspect ratio: {aspect}.\n"
        f"Creative request: {prompt.strip()}\n"
    )
    if source_images:
        instruction += (
            "Use the following real source images as image inputs. The first image is the "
            "identity/edit anchor; preserve its identity and requested locked traits. "
            "Additional images are supporting visual references. Do not replace image "
            "conditioning with a text-only description.\n"
            f"Source images:\n{reference_lines}\n"
        )
    instruction += (
        "After the native image tool succeeds, return its exact generated local path. "
        "Never invent or predict a path. If the tool fails, state the tool error."
    )
    workdir = _grok_build_workdir(config)
    command = [
        _grok_build_binary(config),
        "--cwd",
        str(workdir),
        "--single",
        instruction,
        "--output-format",
        "json",
        "--disallowed-tools",
        (
            "run_terminal_cmd,read_file,grep,list_dir,search_replace,web_search,"
            "web_fetch,todo_write,task,Agent"
        ),
        "--disable-web-search",
        "--no-subagents",
        "--no-memory",
        "--max-turns",
        str(max(2, min(6, int(config.get("max_turns") or 4)))),
        "--reasoning-effort",
        str(config.get("reasoning_effort") or "medium"),
        "--always-approve",
        "--verbatim",
    ]
    timeout = max(60, min(600, int(config.get("timeout_seconds") or 300)))
    try:
        completed = subprocess.run(
            command,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return error_response(
            error=f"xAI Grok Build image generation timed out ({timeout}s)",
            error_type="timeout",
            provider="xai",
            model=GROK_BUILD_MODEL,
            prompt=prompt,
            aspect_ratio=aspect,
        )
    except OSError as exc:
        return error_response(
            error=f"Could not start Grok Build: {exc}",
            error_type="transport_error",
            provider="xai",
            model=GROK_BUILD_MODEL,
            prompt=prompt,
            aspect_ratio=aspect,
        )

    image = _extract_grok_build_image(
        completed.stdout,
        workdir=workdir,
        config=config,
    )
    if completed.returncode != 0 or not image:
        detail = str(completed.stderr or completed.stdout or "").strip()[-500:]
        return error_response(
            error=(
                f"xAI Grok Build image generation failed ({completed.returncode})"
                + (f": {detail}" if detail else "")
            ),
            error_type="transport_error" if completed.returncode else "empty_response",
            provider="xai",
            model=GROK_BUILD_MODEL,
            prompt=prompt,
            aspect_ratio=aspect,
        )

    return success_response(
        image=image,
        model=GROK_BUILD_MODEL,
        prompt=prompt,
        aspect_ratio=aspect,
        provider="xai",
        modality="image" if source_images else "text",
        extra={
            "transport": GROK_BUILD_TRANSPORT,
            "reference_conditioning": "native_image_edit" if source_images else "none",
            "reference_image_count": len(source_images),
        },
    )


def _xai_image_field(source: str) -> Dict[str, str]:
    """Build the xAI ``image`` field for an edit request.

    xAI's ``/v1/images/edits`` accepts a public HTTPS URL or a base64 data URI.
    Local file paths are read and encoded into a ``data:`` URI.
    """
    source = source.strip()
    lower = source.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return {"url": source, "type": "image_url"}
    # Local file path → base64 data URI.
    import base64
    import os as _os

    # Enforce the shared credential-read guard before reading local bytes
    # (same boundary the OpenAI / OpenRouter / Codex image providers apply).
    from agent.file_safety import raise_if_read_blocked

    raise_if_read_blocked(source)
    with open(_os.path.expanduser(source), "rb") as fh:  # windows-footgun: ok
        raw = fh.read()
    ext = (_os.path.splitext(source)[1].lstrip(".") or "png").lower()
    if ext == "jpg":
        ext = "jpeg"
    b64 = base64.b64encode(raw).decode("utf-8")
    return {"url": f"data:image/{ext};base64,{b64}", "type": "image_url"}


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class XAIImageGenProvider(ImageGenProvider):
    """xAI ``grok-imagine-image`` backend."""

    @property
    def name(self) -> str:
        return "xai"

    @property
    def display_name(self) -> str:
        return "xAI (Grok)"

    def is_available(self) -> bool:
        cfg = _load_xai_config()
        if _configured_transport(cfg) == GROK_BUILD_TRANSPORT:
            return _grok_build_available(cfg)
        creds = resolve_xai_http_credentials()
        return bool(creds.get("api_key"))

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": model_id,
                "display": meta.get("display", model_id),
                "speed": meta.get("speed", ""),
                "strengths": meta.get("strengths", ""),
            }
            for model_id, meta in _MODELS.items()
        ]

    def get_setup_schema(self) -> Dict[str, Any]:
        # Auth resolution is delegated to the shared ``xai_grok`` post_setup
        # hook (``hermes_cli/tools_config.py``); identical to the TTS / video
        # gen entries so users see the same OAuth-or-API-key choice for every
        # xAI service.
        storage_notice = xai_storage_notice_text("image_gen")
        tag = (
            "grok-imagine-image - text-to-image & image editing; uses xAI "
            "Grok OAuth or XAI_API_KEY"
        )
        if storage_notice:
            tag += f". {storage_notice}"
        return {
            "name": "xAI Grok Imagine (image)",
            "badge": "paid",
            "tag": tag,
            "env_vars": [],
            "post_setup": "xai_grok",
        }

    def capabilities(self) -> Dict[str, Any]:
        # xAI's /v1/images/edits supports image editing via grok-imagine-image
        # -quality, including up to 3 total source images.
        return {
            "modalities": ["text", "image"],
            "max_reference_images": 2,
            "max_source_images": 3,
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate an image (text-to-image) or edit a source image (image-to-image).

        Routing: when ``image_url`` is provided, POST to ``/v1/images/edits``
        with the source image; otherwise POST to ``/v1/images/generations``.
        Per xAI docs, editing uses the ``grok-imagine-image-quality`` model and
        a JSON body (the OpenAI SDK's multipart ``images.edit()`` is NOT
        supported by xAI).
        """
        cfg = _load_xai_config()
        if _configured_transport(cfg) == GROK_BUILD_TRANSPORT:
            source_images: List[str] = []
            if isinstance(image_url, str) and image_url.strip():
                source_images.append(image_url.strip())
            refs = normalize_reference_images(reference_image_urls)
            if refs:
                source_images.extend(refs)
            if len(source_images) > 3:
                return error_response(
                    error="xAI image editing supports at most 3 source images",
                    error_type="too_many_references",
                    provider="xai",
                    model=GROK_BUILD_MODEL,
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                )
            for source in source_images:
                if not Path(source).expanduser().is_file():
                    return error_response(
                        error=f"Grok Build reference image is not a readable local file: {source}",
                        error_type="invalid_image_url",
                        provider="xai",
                        model=GROK_BUILD_MODEL,
                        prompt=prompt,
                        aspect_ratio=aspect_ratio,
                    )
            return _generate_with_grok_build(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                source_images=source_images,
                config=cfg,
            )

        creds = resolve_xai_http_credentials()
        api_key = str(creds.get("api_key") or "").strip()
        provider_name = str(creds.get("provider") or "xai").strip() or "xai"
        if not api_key:
            return error_response(
                error="No xAI credentials found. Configure xAI OAuth in `hermes model` or set XAI_API_KEY.",
                error_type="missing_api_key",
                provider=provider_name,
                aspect_ratio=aspect_ratio,
            )

        model_id, meta = _resolve_model()
        aspect = resolve_aspect_ratio(aspect_ratio)
        xai_ar = _XAI_ASPECT_RATIOS.get(aspect, "1:1")
        resolution = _resolve_resolution()
        xai_res = resolution if resolution in _XAI_RESOLUTIONS else DEFAULT_RESOLUTION

        source_images: List[str] = []
        if isinstance(image_url, str) and image_url.strip():
            source_images.append(image_url.strip())
        refs = normalize_reference_images(reference_image_urls)
        if refs:
            source_images.extend(refs)
        if len(source_images) > 3:
            return error_response(
                error="xAI image editing supports at most 3 source images",
                error_type="too_many_references",
                provider=provider_name,
                model="grok-imagine-image-quality",
                prompt=prompt,
                aspect_ratio=aspect,
            )
        for index, source in enumerate(source_images):
            field = "image_url" if index == 0 and image_url and image_url.strip() == source else "reference_image_urls"
            lower = source.lower()
            if not lower.startswith(("http://", "https://", "data:")):
                path = Path(source).expanduser()
                if not path.is_file():
                    return error_response(
                        error=(
                            f"{field} must be a public HTTPS URL or data URI "
                            "(e.g. the `image`/`public_url` from a prior Imagine result)"
                        ),
                        error_type="invalid_image_url",
                        provider=provider_name,
                        model="grok-imagine-image-quality",
                        prompt=prompt,
                        aspect_ratio=aspect,
                    )
        is_edit = bool(source_images)
        modality = "image" if is_edit else "text"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": hermes_xai_user_agent(),
        }

        base_url = str(creds.get("base_url") or "https://api.x.ai/v1").strip().rstrip("/")
        storage_options = build_xai_storage_options(
            "image_gen",
            filename_prefix="hermes-xai-image",
            extension="png",
        )
        storage_notice = maybe_mark_xai_storage_notice_seen("image_gen")
        storage_cfg = read_xai_imagine_storage_config("image_gen")

        if is_edit:
            # Editing requires the quality model per xAI docs. The source
            # image may be a public URL or a base64 data URI; local file paths
            # are converted to a data URI here.
            edit_model = "grok-imagine-image-quality"
            try:
                image_fields = [_xai_image_field(source) for source in source_images]
            except Exception as exc:
                return error_response(
                    error=f"Could not load source image for editing: {exc}",
                    error_type="io_error",
                    provider=provider_name,
                    model=edit_model,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            payload: Dict[str, Any] = {
                "model": edit_model,
                "prompt": prompt,
            }
            if len(image_fields) == 1:
                payload["image"] = image_fields[0]
            else:
                payload["images"] = image_fields
            endpoint_url = f"{base_url}/images/edits"
            model_id = edit_model
        else:
            payload = {
                "model": model_id,
                "prompt": prompt,
                "aspect_ratio": xai_ar,
                "resolution": xai_res,
            }
            endpoint_url = f"{base_url}/images/generations"
        if storage_options is not None:
            payload["storage_options"] = storage_options

        try:
            response = requests.post(
                endpoint_url,
                headers=headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else 0
            try:
                err_msg = response.json().get("error", {}).get("message", response.text[:300])
            except Exception:
                err_msg = response.text[:300] if response is not None else str(exc)
            logger.error("xAI image gen failed (%d): %s", status, err_msg)
            return error_response(
                error=f"xAI image generation failed ({status}): {err_msg}",
                error_type="api_error",
                provider=provider_name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.Timeout:
            return error_response(
                error="xAI image generation timed out (120s)",
                error_type="timeout",
                provider=provider_name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.ConnectionError as exc:
            return error_response(
                error=f"xAI connection error: {exc}",
                error_type="connection_error",
                provider=provider_name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            result = response.json()
        except Exception as exc:
            return error_response(
                error=f"xAI returned invalid JSON: {exc}",
                error_type="invalid_response",
                provider=provider_name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Parse response - xAI returns data[0].b64_json, data[0].url, and
        # optionally data[0].file_output when storage_options were requested.
        data = result.get("data", [])
        if not data:
            return error_response(
                error="xAI returned no image data",
                error_type="empty_response",
                provider=provider_name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        first = data[0]
        b64 = first.get("b64_json")
        url = first.get("url")
        file_output = first.get("file_output") if isinstance(first, dict) else None
        file_output = file_output if isinstance(file_output, dict) else {}
        public_url = file_output.get("public_url") if isinstance(file_output.get("public_url"), str) else None

        if public_url:
            try:
                saved_path = save_url_image(
                    public_url,
                    prefix=f"xai_{model_id}",
                )
            except Exception as exc:
                logger.warning(
                    "xAI stored image URL could not be cached safely: %s",
                    type(exc).__name__,
                )
                return error_response(
                    error=(
                        "Could not safely cache xAI image output: "
                        f"{type(exc).__name__}"
                    ),
                    error_type="io_error",
                    provider=provider_name,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            else:
                image_ref = str(saved_path)
        elif b64:
            try:
                saved_path = save_b64_image(b64, prefix=f"xai_{model_id}")
            except Exception as exc:
                return error_response(
                    error=f"Could not save image to cache: {exc}",
                    error_type="io_error",
                    provider="xai",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            image_ref = str(saved_path)
        elif url:
            # xAI's grok-imagine-image returns ephemeral ``imgen.x.ai/xai-tmp-*``
            # URLs that 404 within minutes — by the time Telegram's
            # ``send_photo`` or any downstream consumer fetches them, the
            # asset is gone (#26942).  Materialise the bytes locally at
            # tool-completion time so the gateway has a stable file path to
            # upload, mirroring the b64 branch above and the audio_cache
            # pattern used by text_to_speech.
            try:
                saved_path = save_url_image(url, prefix=f"xai_{model_id}")
            except Exception as exc:
                logger.warning(
                    "xAI image URL could not be cached safely: %s",
                    type(exc).__name__,
                )
                return error_response(
                    error=(
                        "Could not safely cache xAI image output: "
                        f"{type(exc).__name__}"
                    ),
                    error_type="io_error",
                    provider=provider_name,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            else:
                image_ref = str(saved_path)
        else:
            return error_response(
                error="xAI response contained neither b64_json nor URL",
                error_type="empty_response",
                provider="xai",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        extra: Dict[str, Any] = {
            "storage_enabled": bool(storage_cfg["enabled"]),
        }
        if not is_edit:
            extra["resolution"] = xai_res
        if storage_notice:
            extra["storage_notice"] = storage_notice
        if public_url:
            extra["public_url"] = public_url
        if file_output:
            for key in (
                "filename",
                "expires_at",
                "public_url_expires_at",
                "public_url_error",
                "storage_error",
            ):
                if key in file_output:
                    extra[key] = file_output[key]
        if result.get("usage"):
            extra["usage"] = result["usage"]

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider="xai",
            modality=modality,
            extra=extra,
        )


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def register(ctx: Any) -> None:
    """Register this provider with the image gen registry."""
    ctx.register_image_gen_provider(XAIImageGenProvider())

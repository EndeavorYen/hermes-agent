"""Remote Z-Image worker backend.

This provider keeps Hermes as the control plane and calls a private GPU
worker for async ``/txt2img`` generation. The worker owns CUDA/model runtime;
Hermes owns prompt composition, Visual Arsenal provenance, review, polling,
and cached output materialization.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_b64_image,
    success_response,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "Tongyi-MAI/Z-Image-Turbo"

_ASPECT_DIMENSIONS: Dict[str, Tuple[int, int]] = {
    "landscape": (1024, 576),
    "square": (1024, 1024),
    "portrait": (576, 1024),
}

_REFERENCE_KEYS = (
    "reference_images",
    "input_image",
    "input_images",
    "image_style_references",
)

_URL_IMAGE_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


class _RemoteTransportError(RuntimeError):
    """Raised when the curl transport cannot reach or parse the worker."""


class _CurlResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers: Dict[str, str] = headers or {}

    def json(self) -> Any:
        return json.loads(self.text)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _env_flag(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def _disabled() -> bool:
    return _env_flag("ZIMAGE_REMOTE_DISABLED")


def _base_url() -> str:
    return _env("ZIMAGE_REMOTE_BASE_URL").rstrip("/")


def _model() -> str:
    return _env("ZIMAGE_REMOTE_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def _timeout_seconds() -> float:
    value = _env("ZIMAGE_REMOTE_TIMEOUT_SECONDS")
    if not value:
        return 120.0
    try:
        return max(1.0, float(value))
    except ValueError:
        return 120.0


def _poll_timeout_seconds() -> float:
    value = _env("ZIMAGE_REMOTE_POLL_TIMEOUT_SECONDS")
    if not value:
        return 300.0
    try:
        return max(1.0, float(value))
    except ValueError:
        return 300.0


def _poll_interval_seconds() -> float:
    value = _env("ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS")
    if not value:
        return 2.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 2.0


def _route_retry_attempts() -> int:
    value = _env("ZIMAGE_REMOTE_ROUTE_RETRY_ATTEMPTS")
    if not value:
        return 4
    try:
        return max(1, min(10, int(value)))
    except ValueError:
        return 4


def _route_retry_delay_seconds() -> float:
    value = _env("ZIMAGE_REMOTE_ROUTE_RETRY_DELAY_SECONDS")
    if not value:
        return 2.0
    try:
        return max(0.0, min(30.0, float(value)))
    except ValueError:
        return 2.0


def _transport() -> str:
    value = _env("ZIMAGE_REMOTE_TRANSPORT", "auto").lower()
    if value in {"auto", "requests", "curl", "system-python"}:
        return value
    return "auto"


def _curl_path() -> str:
    return _env("ZIMAGE_REMOTE_CURL_PATH", "/usr/bin/curl") or "/usr/bin/curl"


def _system_python_path() -> str:
    configured = _env("ZIMAGE_REMOTE_SYSTEM_PYTHON")
    if configured:
        return configured
    if Path("/usr/bin/python3").exists():
        return "/usr/bin/python3"
    return shutil.which("python3") or "python3"


def _looks_like_local_route_block(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "no route to host" in text or "errno 65" in text or "[errno 65]" in text


def _retry_route_block(operation, *, label: str):
    attempts = _route_retry_attempts()
    delay = _route_retry_delay_seconds()
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except (requests.RequestException, _RemoteTransportError) as exc:
            if not _looks_like_local_route_block(exc) or attempt >= attempts:
                raise
            last_exc = exc
            logger.warning(
                "Z-Image %s route-blocked; retrying (%s/%s): %s",
                label,
                attempt + 1,
                attempts,
                exc,
            )
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise _RemoteTransportError(f"Z-Image {label} retry loop exited unexpectedly")


def _curl_headers(headers: Dict[str, str]) -> List[str]:
    args: List[str] = []
    for key, value in headers.items():
        args.extend(["-H", f"{key}: {value}"])
    return args


_SYSTEM_PYTHON_JSON_SCRIPT = r"""
import json
import sys
import urllib.error
import urllib.request

request_data = json.loads(sys.stdin.read())
payload = request_data.get("payload")
body = None
if payload is not None:
    body = json.dumps(payload).encode("utf-8")

request = urllib.request.Request(
    request_data["url"],
    data=body,
    headers=request_data.get("headers") or {},
    method=request_data.get("method") or "GET",
)

try:
    with urllib.request.urlopen(request, timeout=float(request_data.get("timeout") or 120.0)) as response:
        text = response.read().decode("utf-8", "replace")
        status_code = int(response.getcode())
        headers = dict(response.headers.items())
except urllib.error.HTTPError as exc:
    text = exc.read().decode("utf-8", "replace")
    status_code = int(exc.code)
    headers = dict(exc.headers.items())
except Exception as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)

print(json.dumps({
    "status_code": status_code,
    "text": text,
    "headers": headers,
}))
"""


_SYSTEM_PYTHON_DOWNLOAD_SCRIPT = r"""
import json
import sys
import urllib.request

request_data = json.loads(sys.stdin.read())
request = urllib.request.Request(
    request_data["url"],
    headers=request_data.get("headers") or {},
    method="GET",
)
max_bytes = int(request_data.get("max_bytes") or 26214400)

try:
    with urllib.request.urlopen(request, timeout=float(request_data.get("timeout") or 120.0)) as response:
        total = 0
        chunks = []
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                print("image exceeds configured byte limit", file=sys.stderr)
                raise SystemExit(2)
            chunks.append(chunk)
except Exception as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)

sys.stdout.buffer.write(b"".join(chunks))
"""


def _run_system_python(script: str, payload: Dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [_system_python_path(), "-c", script],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=_timeout_seconds() + 2.0,
        check=False,
    )


def _system_python_json_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
) -> _CurlResponse:
    proc = _run_system_python(
        _SYSTEM_PYTHON_JSON_SCRIPT,
        {
            "method": method,
            "url": url,
            "headers": headers,
            "payload": payload,
            "timeout": _timeout_seconds(),
        },
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", "replace")
        raise _RemoteTransportError(
            f"system-python transport failed ({proc.returncode}): {detail[:200]}"
        )
    try:
        parsed = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise _RemoteTransportError(f"system-python transport returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise _RemoteTransportError("system-python transport returned non-object JSON")
    return _CurlResponse(
        status_code=int(parsed.get("status_code") or 0),
        text=str(parsed.get("text") or ""),
        headers=parsed.get("headers") if isinstance(parsed.get("headers"), dict) else None,
    )


def _image_download_headers(headers: Dict[str, str]) -> Dict[str, str]:
    download_headers = {"Accept": "image/*"}
    authorization = headers.get("Authorization")
    if authorization:
        download_headers["Authorization"] = authorization
    return download_headers


def _curl_json_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
) -> _CurlResponse:
    marker = "\n__HERMES_ZIMAGE_STATUS__:"
    cmd = [
        _curl_path(),
        "-sS",
        "--max-time",
        str(_timeout_seconds()),
        "-X",
        method,
        url,
        "-w",
        marker + "%{http_code}",
    ]
    cmd.extend(_curl_headers(headers))
    body: Optional[bytes] = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        cmd.extend(["--data-binary", "@-"])

    proc = subprocess.run(
        cmd,
        input=body,
        capture_output=True,
        timeout=_timeout_seconds() + 2.0,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", "replace")
        raise _RemoteTransportError(
            f"curl transport failed ({proc.returncode}): {detail[:200]}"
        )

    stdout = proc.stdout.decode("utf-8", "replace")
    marker_index = stdout.rfind(marker)
    if marker_index < 0:
        raise _RemoteTransportError("curl transport did not include an HTTP status marker")
    response_text = stdout[:marker_index]
    status_text = stdout[marker_index + len(marker):].strip()
    try:
        status_code = int(status_text)
    except ValueError as exc:
        raise _RemoteTransportError(
            f"curl transport returned invalid HTTP status: {status_text!r}"
        ) from exc
    return _CurlResponse(status_code=status_code, text=response_text)


def _requests_json_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    if method == "POST":
        return requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=_timeout_seconds(),
        )
    return requests.get(
        url,
        headers=headers,
        timeout=_timeout_seconds(),
    )


def _json_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
) -> Any:
    transport = _transport()
    if transport == "system-python":
        return _retry_route_block(
            lambda: _system_python_json_request(method, url, headers=headers, payload=payload),
            label=f"system-python {method}",
        )
    if transport == "curl":
        return _curl_json_request(method, url, headers=headers, payload=payload)
    try:
        return _requests_json_request(method, url, headers=headers, payload=payload)
    except requests.RequestException as exc:
        if transport == "auto" and _looks_like_local_route_block(exc):
            logger.warning("Z-Image requests transport route-blocked; retrying with system-python")
            try:
                return _retry_route_block(
                    lambda: _system_python_json_request(
                        method,
                        url,
                        headers=headers,
                        payload=payload,
                    ),
                    label=f"system-python {method}",
                )
            except _RemoteTransportError as system_exc:
                logger.warning(
                    "Z-Image system-python transport failed; retrying with curl: %s",
                    system_exc,
                )
                return _curl_json_request(method, url, headers=headers, payload=payload)
        raise


def _prefix_for_model(model: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_")
    return f"zimage_remote_{safe or 'image'}"


def _has_reference_input(kwargs: Dict[str, Any]) -> bool:
    for key in _REFERENCE_KEYS:
        value = kwargs.get(key)
        if isinstance(value, (list, tuple, set)) and len(value) > 0:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _extract_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        data = None
    if isinstance(data, dict):
        for key in ("error", "message", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = data.get("error")
        if isinstance(nested, dict):
            message = nested.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    text = getattr(response, "text", "") or ""
    return text.strip() or f"Remote Z-Image worker returned HTTP {response.status_code}"


def _extract_error_type(response: requests.Response) -> str:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        data = None
    if isinstance(data, dict):
        value = data.get("error_type") or data.get("errorType")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "remote_worker_error"


def _join_worker_url(base: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    return urllib.parse.urljoin(f"{base.rstrip('/')}/", text)


def _json_response(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError(f"Remote Z-Image worker returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Remote Z-Image worker returned a non-object response")
    return data


def _is_async_submit(data: Dict[str, Any]) -> bool:
    status = str(data.get("status") or "").lower()
    return bool(data.get("job_id") or data.get("jobId")) and status in {
        "queued",
        "pending",
        "running",
        "submitted",
        "processing",
        "started",
    }


def _poll_job(
    *,
    base: str,
    submit_data: Dict[str, Any],
    headers: Dict[str, str],
    model: str,
    prompt: str,
    aspect_ratio: str,
) -> Dict[str, Any]:
    job_id = str(submit_data.get("job_id") or submit_data.get("jobId") or "").strip()
    poll_url = submit_data.get("poll_url") or submit_data.get("pollUrl") or f"/jobs/{job_id}"
    deadline = time.monotonic() + _poll_timeout_seconds()

    while True:
        try:
            response = _json_request(
                "GET",
                _join_worker_url(base, poll_url),
                headers=headers,
            )
        except (requests.RequestException, _RemoteTransportError) as exc:
            return error_response(
                error=f"Remote Z-Image worker poll failed: {exc}",
                error_type="remote_worker_error",
                provider="zimage_remote",
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )

        if response.status_code >= 400:
            result = error_response(
                error=_extract_error_message(response),
                error_type=_extract_error_type(response),
                provider="zimage_remote",
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )
            result["status_code"] = response.status_code
            return result

        try:
            data = _json_response(response)
        except ValueError as exc:
            return error_response(
                error=str(exc),
                error_type="provider_contract",
                provider="zimage_remote",
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )

        status = str(data.get("status") or "").lower()
        if status == "succeeded":
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            merged = {**submit_data, **result}
            merged["job_id"] = data.get("job_id") or data.get("jobId") or job_id
            if submit_data.get("worker_id") or submit_data.get("workerId"):
                merged["worker_id"] = submit_data.get("worker_id") or submit_data.get("workerId")
            if result.get("file_url") or result.get("fileUrl"):
                merged["image_url"] = _join_worker_url(base, result.get("file_url") or result.get("fileUrl"))
            return merged

        if status in {"failed", "error", "cancelled", "canceled"}:
            return error_response(
                error=str(data.get("error") or data.get("message") or f"Remote Z-Image job {job_id} failed"),
                error_type=str(data.get("error_type") or data.get("errorType") or "remote_worker_error"),
                provider="zimage_remote",
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )

        if time.monotonic() >= deadline:
            return error_response(
                error=f"Remote Z-Image job {job_id} timed out while polling",
                error_type="timeout",
                provider="zimage_remote",
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )

        interval = _poll_interval_seconds()
        if interval:
            time.sleep(interval)


def _extension_for_image(url: str, content_type: str = "") -> str:
    clean_content_type = content_type.split(";", 1)[0].strip().lower()
    extension = _URL_IMAGE_CONTENT_TYPES.get(clean_content_type)
    if extension:
        return extension
    url_path = url.split("?", 1)[0].lower()
    for ext in ("png", "jpg", "jpeg", "webp", "gif"):
        if url_path.endswith(f".{ext}"):
            return "jpg" if ext == "jpeg" else ext
    return "png"


def _image_cache_path(prefix: str, extension: str) -> Path:
    from hermes_constants import get_hermes_home

    cache_dir = get_hermes_home() / "cache" / "images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:8]
    return cache_dir / f"{prefix}_{timestamp}_{short}.{extension}"


def _save_url_image_with_requests(
    url: str,
    *,
    prefix: str,
    headers: Dict[str, str],
    max_bytes: int = 25 * 1024 * 1024,
) -> Path:
    response = requests.get(
        url,
        headers=headers,
        timeout=_timeout_seconds(),
        stream=True,
    )
    response.raise_for_status()

    extension = _extension_for_image(url, response.headers.get("Content-Type") or "")
    path = _image_cache_path(prefix, extension)
    bytes_written = 0
    with path.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            bytes_written += len(chunk)
            if bytes_written > max_bytes:
                fh.close()
                try:
                    path.unlink()
                except OSError:
                    pass
                raise ValueError(
                    f"Image at {url} exceeds {max_bytes // (1024 * 1024)}MB cap; refusing to cache."
                )
            fh.write(chunk)

    if bytes_written == 0:
        try:
            path.unlink()
        except OSError:
            pass
        raise ValueError(f"Image at {url} returned 0 bytes; refusing to cache.")
    return path


def _save_url_image_with_curl(
    url: str,
    *,
    prefix: str,
    headers: Optional[Dict[str, str]] = None,
    max_bytes: int = 25 * 1024 * 1024,
) -> Path:
    cmd = [
        _curl_path(),
        "-fL",
        "-sS",
        "--max-time",
        str(_timeout_seconds()),
        url,
    ]
    cmd.extend(_curl_headers(headers or {}))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=_timeout_seconds() + 2.0,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", "replace")
        raise _RemoteTransportError(
            f"curl image download failed ({proc.returncode}): {detail[:200]}"
        )
    if len(proc.stdout) > max_bytes:
        raise ValueError(
            f"Image at {url} exceeds {max_bytes // (1024 * 1024)}MB cap; refusing to cache."
        )
    if not proc.stdout:
        raise ValueError(f"Image at {url} returned 0 bytes; refusing to cache.")

    path = _image_cache_path(prefix, _extension_for_image(url))
    path.write_bytes(proc.stdout)
    return path


def _save_url_image_with_system_python(
    url: str,
    *,
    prefix: str,
    headers: Optional[Dict[str, str]] = None,
    max_bytes: int = 25 * 1024 * 1024,
) -> Path:
    proc = _run_system_python(
        _SYSTEM_PYTHON_DOWNLOAD_SCRIPT,
        {
            "url": url,
            "headers": headers or {},
            "timeout": _timeout_seconds(),
            "max_bytes": max_bytes,
        },
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", "replace")
        raise _RemoteTransportError(
            f"system-python image download failed ({proc.returncode}): {detail[:200]}"
        )
    if len(proc.stdout) > max_bytes:
        raise ValueError(
            f"Image at {url} exceeds {max_bytes // (1024 * 1024)}MB cap; refusing to cache."
        )
    if not proc.stdout:
        raise ValueError(f"Image at {url} returned 0 bytes; refusing to cache.")

    path = _image_cache_path(prefix, _extension_for_image(url))
    path.write_bytes(proc.stdout)
    return path


def _save_worker_url_image(url: str, *, prefix: str, headers: Dict[str, str]) -> Path:
    transport = _transport()
    if transport == "system-python":
        return _retry_route_block(
            lambda: _save_url_image_with_system_python(url, prefix=prefix, headers=headers),
            label="system-python image download",
        )
    if transport == "curl":
        return _save_url_image_with_curl(url, prefix=prefix, headers=headers)
    try:
        return _save_url_image_with_requests(url, prefix=prefix, headers=headers)
    except requests.RequestException as exc:
        if transport == "auto" and _looks_like_local_route_block(exc):
            logger.warning("Z-Image image download route-blocked; retrying with system-python")
            try:
                return _retry_route_block(
                    lambda: _save_url_image_with_system_python(
                        url,
                        prefix=prefix,
                        headers=headers,
                    ),
                    label="system-python image download",
                )
            except _RemoteTransportError as system_exc:
                logger.warning(
                    "Z-Image system-python image download failed; retrying with curl: %s",
                    system_exc,
                )
                return _save_url_image_with_curl(url, prefix=prefix, headers=headers)
        raise


def _materialize_worker_image(
    data: Dict[str, Any],
    model: str,
    headers: Dict[str, str],
) -> tuple[Optional[str], Optional[str]]:
    """Return local image path plus the original remote image reference."""
    image_url = (
        data.get("image_url")
        or data.get("imageUrl")
        or data.get("url")
        or data.get("image")
    )
    if isinstance(image_url, str) and image_url.strip():
        remote_image = image_url.strip()
        if remote_image.startswith(("http://", "https://")):
            path = _save_worker_url_image(
                remote_image,
                prefix=_prefix_for_model(model),
                headers=_image_download_headers(headers),
            )
            return str(path), remote_image
        return remote_image, remote_image

    image_path = data.get("image_path") or data.get("imagePath")
    if isinstance(image_path, str) and image_path.strip():
        return image_path.strip(), image_path.strip()

    b64_data = data.get("image_b64") or data.get("image_base64") or data.get("b64_json")
    if isinstance(b64_data, str) and b64_data.strip():
        path = save_b64_image(b64_data.strip(), prefix=_prefix_for_model(model), extension="png")
        return str(path), "inline_base64"

    return None, None


class ZImageRemoteProvider(ImageGenProvider):
    """Image generation backend for Simon's private Z-Image GPU worker."""

    @property
    def name(self) -> str:
        return "zimage_remote"

    @property
    def display_name(self) -> str:
        return "Z-Image Remote"

    def is_available(self) -> bool:
        return bool(_base_url()) and not _disabled()

    def list_models(self) -> List[Dict[str, Any]]:
        model = _model()
        return [
            {
                "id": model,
                "display": "Z-Image Turbo (remote GPU)",
                "speed": "remote",
                "strengths": "Private local-GPU candidate generation",
                "price": "local GPU",
            }
        ]

    def default_model(self) -> Optional[str]:
        return _model()

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Z-Image Remote",
            "badge": "local-gpu",
            "tag": "Private remote GPU worker for Z-Image candidate generation.",
            "env_vars": [
                {
                    "key": "ZIMAGE_REMOTE_BASE_URL",
                    "prompt": "Z-Image worker base URL",
                    "url": "http://remote-host:7869",
                },
                {
                    "key": "ZIMAGE_REMOTE_TOKEN",
                    "prompt": "Z-Image worker bearer token",
                    "url": "local-secret",
                },
            ],
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt_text = str(prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)
        model = _model()

        if not prompt_text:
            return error_response(
                error="prompt is required",
                error_type="invalid_argument",
                provider=self.name,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )

        if _disabled():
            return error_response(
                error="zimage_remote is disabled by ZIMAGE_REMOTE_DISABLED",
                error_type="provider_disabled",
                provider=self.name,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )

        base = _base_url()
        if not base:
            return error_response(
                error="ZIMAGE_REMOTE_BASE_URL is required for zimage_remote",
                error_type="configuration_required",
                provider=self.name,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )

        if _has_reference_input(kwargs):
            response = error_response(
                error=(
                    "zimage_remote currently supports txt2img only; "
                    "reference_images/input_image are unsupported until the "
                    "remote worker exposes a verified identity/reference path."
                ),
                error_type="unsupported_feature",
                provider=self.name,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )
            response["reference_conditioning"] = "unsupported"
            return response

        width, height = _ASPECT_DIMENSIONS[aspect]
        payload: Dict[str, Any] = {
            "prompt": prompt_text,
            "aspect_ratio": aspect,
            "width": width,
            "height": height,
            "model": model,
            "num_inference_steps": kwargs.get("num_inference_steps", 8),
            "guidance_scale": kwargs.get("guidance_scale", 0.0),
            "num_images": kwargs.get("num_images", 1),
            "output_format": kwargs.get("output_format", "png"),
        }
        if kwargs.get("seed") is not None:
            payload["seed"] = kwargs["seed"]
        if kwargs.get("negative_prompt"):
            payload["negative_prompt"] = str(kwargs["negative_prompt"])

        headers = {"Content-Type": "application/json"}
        token = _env("ZIMAGE_REMOTE_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = _json_request(
                "POST",
                f"{base}/txt2img",
                headers=headers,
                payload=payload,
            )
        except (requests.RequestException, _RemoteTransportError) as exc:
            return error_response(
                error=f"Remote Z-Image worker request failed: {exc}",
                error_type="remote_worker_error",
                provider=self.name,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )

        if response.status_code >= 400:
            result = error_response(
                error=_extract_error_message(response),
                error_type=_extract_error_type(response),
                provider=self.name,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )
            result["status_code"] = response.status_code
            return result

        try:
            data = _json_response(response)
        except ValueError as exc:
            return error_response(
                error=str(exc),
                error_type="provider_contract",
                provider=self.name,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )

        if _is_async_submit(data):
            data = _poll_job(
                base=base,
                submit_data=data,
                headers=headers,
                model=model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )
            if data.get("success") is False:
                return data

        if data.get("success") is False:
            return error_response(
                error=str(data.get("error") or data.get("message") or "Remote Z-Image generation failed"),
                error_type=str(data.get("error_type") or "remote_worker_error"),
                provider=self.name,
                model=str(data.get("model") or model),
                prompt=prompt_text,
                aspect_ratio=aspect,
            )

        if data.get("file_url") or data.get("fileUrl"):
            data["image_url"] = _join_worker_url(base, data.get("file_url") or data.get("fileUrl"))

        result_model = str(data.get("model") or data.get("model_id") or data.get("modelId") or model)
        try:
            image, remote_image = _materialize_worker_image(data, result_model, headers)
        except (requests.RequestException, _RemoteTransportError, ValueError) as exc:
            return error_response(
                error=f"Remote Z-Image worker image download failed: {exc}",
                error_type="remote_worker_error",
                provider=self.name,
                model=result_model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )
        if not image:
            return error_response(
                error="Remote Z-Image worker response did not include an image",
                error_type="provider_contract",
                provider=self.name,
                model=result_model,
                prompt=prompt_text,
                aspect_ratio=aspect,
            )

        reference_conditioning = str(data.get("reference_conditioning") or "none")
        generation_metadata = {
            "remote_image": remote_image,
            "model_revision": data.get("model_revision") or data.get("modelRevision"),
            "elapsed_ms": data.get("elapsed_ms") or data.get("elapsedMs"),
            "vram_peak_mb": data.get("vram_peak_mb") or data.get("vramPeakMb"),
            "worker_id": data.get("worker_id") or data.get("workerId"),
            "job_id": data.get("job_id") or data.get("jobId"),
            "reference_conditioning": reference_conditioning,
        }
        generation_metadata = {
            key: value for key, value in generation_metadata.items() if value is not None
        }

        extra = {
            "seed": data.get("seed", payload.get("seed")),
            "model_revision": generation_metadata.get("model_revision"),
            "elapsed_ms": generation_metadata.get("elapsed_ms"),
            "vram_peak_mb": generation_metadata.get("vram_peak_mb"),
            "worker_id": generation_metadata.get("worker_id"),
            "job_id": generation_metadata.get("job_id"),
            "reference_conditioning": reference_conditioning,
            "generation_metadata": generation_metadata,
        }
        extra = {key: value for key, value in extra.items() if value is not None}

        return success_response(
            image=str(image),
            model=result_model,
            prompt=prompt_text,
            aspect_ratio=aspect,
            provider=self.name,
            extra=extra,
        )


def register(ctx) -> None:
    """Plugin entry point."""
    if _disabled():
        return
    ctx.register_image_gen_provider(ZImageRemoteProvider())

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_TERMINAL_STATUSES = {"completed", "review_required", "failed", "cancelled"}


class VisualEngineClient:
    """Minimal HTTP client for the standalone Visual Production Engine."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        poll_interval: float = 0.5,
        timeout: float = 600.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("VISUAL_ENGINE_URL")
            or "http://127.0.0.1:8788"
        ).rstrip("/")
        self.poll_interval = poll_interval
        self.timeout = timeout

    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        submitted = self._request("POST", "/v1/runs", payload)
        run_id = str(submitted.get("run_id") or "")
        if not run_id:
            raise RuntimeError("Visual Engine did not return a run_id")
        deadline = time.monotonic() + self.timeout
        run = self._request("GET", f"/v1/runs/{_quote(run_id)}")
        while run.get("status") not in _TERMINAL_STATUSES:
            if time.monotonic() >= deadline:
                return {
                    "success": False,
                    "run": run,
                    "error": "Visual Engine execution deadline exceeded",
                }
            time.sleep(self.poll_interval)
            run = self._request("GET", f"/v1/runs/{_quote(run_id)}")
        artifact_id = str(run.get("selected_artifact_id") or "")
        if run.get("status") != "completed" or not artifact_id:
            return {
                "success": False,
                "run": run,
                "error": str(
                    run.get("stop_reason")
                    or f"Visual Engine stopped with status {run.get('status')}"
                ),
            }
        artifact = self._request("GET", f"/v1/artifacts/{_quote(artifact_id)}")
        return {"success": True, "run": run, "artifact": artifact}

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            data=data,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data else {}),
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=min(self.timeout, 30.0),
            ) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(
                f"Visual Engine returned HTTP {exc.code}: {detail}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Visual Engine returned a non-object response")
        return payload


def generate_story_video_image(
    args: dict[str, Any],
    *,
    task_id: str = "",
    client: Any = None,
) -> dict[str, Any]:
    """Generate one OpenAI story-video keyframe through the standalone Engine."""

    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {
            "success": False,
            "image": None,
            "error_type": "provider_contract",
            "error": "Story-video keyframe prompt is required.",
        }
    references = _references(args)
    effective = {
        "task_id": str(task_id),
        "prompt": prompt,
        "provider": "openai-codex",
        "candidate_count": 1,
        "aspect_ratio": str(args.get("aspect_ratio") or "16:9"),
        "references": references,
        "max_repairs": 1,
    }
    digest = hashlib.sha256(
        json.dumps(effective, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    payload = {
        key: value for key, value in effective.items() if key != "task_id"
    }
    payload["idempotency_key"] = f"story-video:{task_id}:{digest}"
    try:
        result = (client or VisualEngineClient()).generate(payload)
    except Exception as exc:  # noqa: BLE001 - preserve provider-safe result shape
        detail = f"{exc.__class__.__name__}: {exc}"
        return {
            "success": False,
            "image": None,
            "error_type": _failure_type(detail),
            "error": detail,
        }
    if not result.get("success"):
        detail = str(result.get("error") or "Visual Engine generation failed")
        return {
            "success": False,
            "image": None,
            "error_type": _failure_type(detail),
            "error": detail,
            "engine_run_id": str((result.get("run") or {}).get("run_id") or ""),
        }
    run = result.get("run") or {}
    artifact = result.get("artifact") or {}
    image = str(artifact.get("local_path") or "")
    if not image or not Path(image).is_file():
        return {
            "success": False,
            "image": None,
            "error_type": "visual_engine_artifact_missing",
            "error": "Selected Visual Engine artifact is unavailable.",
        }
    return {
        "success": True,
        "image": image,
        "provider": "openai-codex",
        "model": str(artifact.get("model") or ""),
        "response_id": str(run.get("run_id") or ""),
        "artifact_id": str(artifact.get("artifact_id") or ""),
    }


def _references(args: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[tuple[str, str]] = []
    source = str(args.get("image_url") or "").strip()
    if source:
        values.append((source, "primary_edit"))
    values.extend(
        (str(value), "style")
        for value in args.get("reference_image_urls") or []
        if str(value).strip()
    )
    return [
        {
            "index": index,
            "artifact_id": f"story-video-reference:{index}",
            "role": role,
            "source_path": path,
        }
        for index, (path, role) in enumerate(values, start=1)
    ]


def _failure_type(detail: str) -> str:
    lowered = detail.lower()
    if any(marker in lowered for marker in ("401", "auth", "credential")):
        return "authentication_required"
    if any(marker in lowered for marker in ("429", "quota", "rate limit")):
        return "quota_exceeded"
    if "timeout" in lowered or "deadline" in lowered:
        return "provider_timeout"
    return "visual_engine_failed"


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


__all__ = ["VisualEngineClient", "generate_story_video_image"]

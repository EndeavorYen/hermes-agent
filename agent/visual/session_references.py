from __future__ import annotations

import json
import re
from typing import Any

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_SESSION_VISUAL_REFERENCES = 3

_IMAGE_REF_RE = re.compile(
    r"((?:file://|https?://|/|~/)[^\s\]~)'\"]+\.(?:png|jpe?g|webp|gif))",
    re.IGNORECASE,
)


def _as_json_object(value: Any) -> dict[str, Any] | None:
    try:
        loaded = json.loads(value) if isinstance(value, str) else value
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def _clean_reference(value: str) -> str | None:
    ref = value.strip().strip("\"'`")
    ref = ref.rstrip(".,;:)]}~")
    if not ref:
        return None
    lowered = ref.lower()
    if lowered.startswith(("http://", "https://", "file://", "/", "~/")) and lowered.endswith(IMAGE_EXTENSIONS):
        return ref
    return None


def _append_unique(refs: list[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    ref = _clean_reference(value)
    if ref and ref not in refs:
        refs.append(ref)


def normalise_visual_reference_paths(values: Any, *, limit: int | None = None) -> list[str]:
    refs: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            _append_unique(refs, value)
            for match in _IMAGE_REF_RE.finditer(value):
                _append_unique(refs, match.group(1))
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)

    walk(values)
    if limit is not None:
        return refs[: max(0, limit)]
    return refs


def prompt_requests_visual_reference_reuse(prompt: Any) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    markers = (
        "previous",
        "last image",
        "last picture",
        "this image",
        "same character",
        "same person",
        "keep the",
        "preserve",
        "modify",
        "edit",
        "revise",
        "change",
        "variation",
        "reference",
        "上一張",
        "上張",
        "上回",
        "上一輪",
        "剛剛",
        "剛才",
        "這張",
        "這位角色",
        "原圖",
        "參考圖",
        "固定",
        "保持",
        "沿用",
        "延續",
        "修改",
        "調整",
        "改成",
        "換成",
        "姿勢",
        "場景",
        "一致",
    )
    compact_markers = (
        "makeit",
        "keepit",
        "samecharacter",
        "sameperson",
        "lastimage",
        "thisimage",
    )
    return any(marker in text for marker in markers) or any(
        marker in compact for marker in compact_markers
    )


def _refs_from_tool_payload(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    if not payload.get("success"):
        return refs

    delivery = payload.get("delivery_metadata")
    if isinstance(delivery, dict):
        selected_ids = {
            str(item)
            for item in delivery.get("selected_visual_artifact_ids", [])
            if item not in (None, "")
        }
        artifacts = delivery.get("visual_artifacts")
        if selected_ids and isinstance(artifacts, dict):
            for ref, metadata in artifacts.items():
                if not isinstance(metadata, dict):
                    continue
                if str(metadata.get("kind") or "").lower() != "image":
                    continue
                if str(metadata.get("artifact_id") or "") in selected_ids:
                    _append_unique(refs, ref)

    for field in ("host_image", "image", "agent_visible_image"):
        _append_unique(refs, payload.get(field))
    for field in ("images", "reference_image_urls", "attachments"):
        for ref in normalise_visual_reference_paths(payload.get(field)):
            _append_unique(refs, ref)
    return refs


def _refs_from_tool_calls(msg: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for call in msg.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        args = _as_json_object(fn.get("arguments") or call.get("arguments"))
        if not args:
            continue
        for ref in normalise_visual_reference_paths(
            {
                "image_url": args.get("image_url") or args.get("input_image"),
                "reference_image_urls": args.get("reference_image_urls"),
                "reference_images": args.get("reference_images"),
                "image_style_references": args.get("image_style_references"),
                "attachments": args.get("attachments"),
            }
        ):
            _append_unique(refs, ref)
    return refs


def _refs_from_message_content(content: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(content, str):
        return normalise_visual_reference_paths(content)
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                _append_unique(refs, image_url.get("url"))
            else:
                _append_unique(refs, image_url)
    return refs


def collect_recent_visual_reference_paths(
    messages: list[dict[str, Any]],
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[str]:
    refs: list[str] = []
    for msg in reversed(messages or []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role in {"tool", "function"}:
            payload = _as_json_object(msg.get("content"))
            if payload:
                for ref in _refs_from_tool_payload(payload):
                    _append_unique(refs, ref)
        elif role == "assistant":
            for ref in _refs_from_tool_calls(msg):
                _append_unique(refs, ref)
        elif role == "user":
            for ref in _refs_from_message_content(msg.get("content")):
                _append_unique(refs, ref)
        if len(refs) >= limit:
            break
    return refs[: max(0, limit)]


def session_visual_reference_paths_for_prompt(
    prompt: Any,
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[str]:
    if not prompt_requests_visual_reference_reuse(prompt):
        return []
    try:
        from gateway.session_context import get_visual_reference_context
    except Exception:
        return []
    return normalise_visual_reference_paths(get_visual_reference_context(), limit=limit)

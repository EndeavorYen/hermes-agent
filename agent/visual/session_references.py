from __future__ import annotations

import json
from pathlib import Path
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


def _coerce_user_ref_index(value: Any) -> int | str | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        clean = value.strip()
        if not clean:
            return None
        if clean.isdigit():
            return int(clean)
        return clean
    return None


def _make_entry(
    uri: Any,
    *,
    role_hint: str = "visual_reference",
    source: str = "visual_reference",
    user_ref_index: Any = None,
) -> dict[str, Any] | None:
    if not isinstance(uri, str):
        return None
    ref = _clean_reference(uri)
    if not ref:
        return None
    entry: dict[str, Any] = {
        "uri": ref,
        "role_hint": str(role_hint or "visual_reference").strip() or "visual_reference",
        "source": str(source or "visual_reference").strip() or "visual_reference",
    }
    coerced_user_ref = _coerce_user_ref_index(user_ref_index)
    if coerced_user_ref is not None:
        entry["user_ref_index"] = coerced_user_ref
    return entry


def _append_unique_entry(entries: list[dict[str, Any]], entry: dict[str, Any] | None) -> None:
    if not entry:
        return
    uri = str(entry.get("uri") or "").strip()
    if not uri:
        return
    if any(str(existing.get("uri") or "").strip() == uri for existing in entries):
        return
    entries.append(entry)


def normalise_visual_reference_entries(
    values: Any,
    *,
    limit: int | None = None,
    default_role_hint: str = "visual_reference",
    default_source: str = "visual_reference",
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            _append_unique_entry(
                entries,
                _make_entry(
                    value,
                    role_hint=default_role_hint,
                    source=default_source,
                ),
            )
            for match in _IMAGE_REF_RE.finditer(value):
                _append_unique_entry(
                    entries,
                    _make_entry(
                        match.group(1),
                        role_hint=default_role_hint,
                        source=default_source,
                    ),
                )
            return
        if isinstance(value, dict):
            uri = (
                value.get("uri")
                or value.get("path")
                or value.get("attachment")
                or value.get("url")
                or value.get("image")
            )
            entry = _make_entry(
                uri,
                role_hint=str(value.get("role_hint") or default_role_hint),
                source=str(value.get("source") or default_source),
                user_ref_index=value.get("user_ref_index"),
            )
            if entry:
                _append_unique_entry(entries, entry)
                return
            for item in value.values():
                walk(item)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)

    walk(values)
    if limit is not None:
        return entries[: max(0, limit)]
    return entries


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
        "參考",
        "参考",
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
        "改進",
        "改善",
        "修正",
        "修一下",
        "補上",
        "改成",
        "換成",
        "不要",
        "不應該",
        "而不是",
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


def prompt_requests_original_visual_references(prompt: Any) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    return (
        "original reference" in text
        or "original ref" in text
        or "原圖" in text
        or "原图" in text
        or "原始" in text
        or "原ref" in compact
        or "原reference" in compact
    )


def entry_is_generated_visual_output(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    source = str(entry.get("source") or "").strip()
    if source in {
        "previous_selected_artifact",
        "previous_tool_output",
        "previous_visual_arsenal_output",
        "generated_output",
    }:
        return True
    uri = str(entry.get("uri") or entry.get("path") or entry.get("attachment") or "").strip()
    if not uri:
        return False
    normalized = uri.replace("\\", "/")
    generated_markers = (
        "/cache/images/grok_web_imagine_",
        "/cache/images/visual-package",
        "/cache/images/openai_",
        "/cache/images/xai_",
    )
    return any(marker in normalized for marker in generated_markers)


def filter_visual_reference_entries_for_prompt(
    entries: list[dict[str, Any]],
    prompt: Any,
) -> list[dict[str, Any]]:
    filtered = list(entries)
    if prompt_requests_original_visual_references(prompt):
        filtered = [
            entry for entry in filtered if not entry_is_generated_visual_output(entry)
        ]
    mentioned_indices = {
        int(match)
        for match in re.findall(
            r"(?<![a-z0-9])g\s*([1-9][0-9]*)",
            str(prompt or "").lower(),
        )
    }
    if mentioned_indices:
        named = [
            entry
            for entry in filtered
            if _coerce_user_ref_index(entry.get("user_ref_index"))
            in mentioned_indices
        ]
        if named:
            return named
    return filtered


def _entries_from_tool_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    library_root = str(payload.get("library_root") or "").strip()
    output_paths = normalise_visual_reference_paths(
        payload.get("absolute_output_image_paths")
    )
    is_visual_arsenal_payload = bool(
        library_root
        and output_paths
        and Path(library_root).expanduser().name == "visual-arsenal"
    )
    if not payload.get("success") and not is_visual_arsenal_payload:
        return entries

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
                    _append_unique_entry(
                        entries,
                        _make_entry(
                            ref,
                            role_hint="edit_anchor",
                            source="previous_selected_artifact",
                        ),
                    )

    for field in ("host_image", "image", "agent_visible_image"):
        _append_unique_entry(
            entries,
            _make_entry(
                payload.get(field),
                role_hint="edit_anchor",
                source="previous_tool_output",
            ),
        )
    for field in ("images", "reference_image_urls", "attachments"):
        for entry in normalise_visual_reference_entries(
            payload.get(field),
            default_role_hint="visual_reference",
            default_source="previous_tool_reference",
        ):
            _append_unique_entry(entries, entry)
    if is_visual_arsenal_payload:
        try:
            root = Path(library_root).expanduser().resolve(strict=False)
        except Exception:
            root = None
        for index, output_path in enumerate(output_paths, start=1):
            try:
                resolved = Path(output_path).expanduser().resolve(strict=False)
                if root is None:
                    continue
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            _append_unique_entry(
                entries,
                _make_entry(
                    output_path,
                    role_hint="visual_reference",
                    source="previous_visual_arsenal_output",
                    user_ref_index=index,
                ),
            )
    return entries


def _refs_from_tool_payload(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for entry in _entries_from_tool_payload(payload):
        _append_unique(refs, str(entry.get("uri") or ""))
    return refs


def _role_by_reference_index(binding: Any) -> dict[int, str]:
    if not isinstance(binding, dict):
        return {}
    roles: dict[int, str] = {}
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except Exception:
            continue
        role_hint = str(item.get("role_hint") or "").strip()
        if index > 0 and role_hint:
            roles[index] = role_hint
    return roles


def _entries_from_tool_calls(msg: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for call in msg.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        args = _as_json_object(fn.get("arguments") or call.get("arguments"))
        if not args:
            continue
        binding = args.get("reference_binding")
        role_by_index = _role_by_reference_index(binding)
        ordered_refs = normalise_visual_reference_paths(args.get("attachments"))
        if not ordered_refs:
            ordered_refs = normalise_visual_reference_paths(
                args.get("reference_image_urls") or args.get("reference_images")
            )
        for index, ref in enumerate(ordered_refs, start=1):
            _append_unique_entry(
                entries,
                _make_entry(
                    ref,
                    role_hint=role_by_index.get(index, "visual_reference"),
                    source="previous_tool_reference",
                    user_ref_index=index if role_by_index else None,
                ),
            )
        for entry in normalise_visual_reference_entries(
            {
                "image_url": args.get("image_url") or args.get("input_image"),
                "reference_image_urls": args.get("reference_image_urls"),
                "reference_images": args.get("reference_images"),
                "image_style_references": args.get("image_style_references"),
            },
            default_role_hint="visual_reference",
            default_source="previous_tool_reference",
        ):
            _append_unique_entry(entries, entry)
    return entries


def _refs_from_tool_calls(msg: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for entry in _entries_from_tool_calls(msg):
        _append_unique(refs, str(entry.get("uri") or ""))
    return refs


def _entries_from_message_content(content: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if isinstance(content, str):
        return normalise_visual_reference_entries(
            content,
            default_role_hint="visual_reference",
            default_source="current_message_reference",
        )
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                uri = image_url.get("url")
            else:
                uri = image_url
            _append_unique_entry(
                entries,
                _make_entry(
                    uri,
                    role_hint="visual_reference",
                    source="current_message_reference",
                ),
            )
    return entries


def _refs_from_message_content(content: Any) -> list[str]:
    refs: list[str] = []
    for entry in _entries_from_message_content(content):
        _append_unique(refs, str(entry.get("uri") or ""))
    return refs


def collect_recent_visual_reference_entries(
    messages: list[dict[str, Any]],
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for msg in reversed(messages or []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role in {"tool", "function"}:
            payload = _as_json_object(msg.get("content"))
            if payload:
                for entry in _entries_from_tool_payload(payload):
                    _append_unique_entry(entries, entry)
        elif role == "assistant":
            for entry in _entries_from_tool_calls(msg):
                _append_unique_entry(entries, entry)
        elif role == "user":
            for entry in _entries_from_message_content(msg.get("content")):
                _append_unique_entry(entries, entry)
        if len(entries) >= limit:
            break
    return entries[: max(0, limit)]


def collect_recent_original_visual_reference_entries(
    messages: list[dict[str, Any]],
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for msg in reversed(messages or []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        candidate_entries: list[dict[str, Any]] = []
        if role == "assistant":
            candidate_entries = _entries_from_tool_calls(msg)
        elif role == "user":
            candidate_entries = _entries_from_message_content(msg.get("content"))
        for entry in candidate_entries:
            if entry_is_generated_visual_output(entry):
                continue
            _append_unique_entry(entries, entry)
        if len(entries) >= limit:
            break
    return entries[: max(0, limit)]


def collect_recent_visual_reference_paths(
    messages: list[dict[str, Any]],
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[str]:
    refs: list[str] = []
    for entry in collect_recent_visual_reference_entries(messages, limit=limit):
        _append_unique(refs, str(entry.get("uri") or ""))
    return refs[: max(0, limit)]


def session_visual_reference_entries_for_prompt(
    prompt: Any,
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[dict[str, Any]]:
    if not prompt_requests_visual_reference_reuse(prompt):
        return []
    try:
        from gateway.session_context import (
            get_visual_reference_context,
            get_visual_reference_context_entries,
        )
    except Exception:
        return []
    entries = normalise_visual_reference_entries(
        get_visual_reference_context_entries(),
        limit=limit,
        default_role_hint="visual_reference",
        default_source="session_visual_context",
    )
    entries = filter_visual_reference_entries_for_prompt(entries, prompt)
    if entries:
        return entries
    fallback_entries = normalise_visual_reference_entries(
        get_visual_reference_context(),
        limit=limit,
        default_role_hint="visual_reference",
        default_source="session_visual_context",
    )
    return filter_visual_reference_entries_for_prompt(fallback_entries, prompt)


def session_visual_reference_paths_for_prompt(
    prompt: Any,
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[str]:
    refs: list[str] = []
    for entry in session_visual_reference_entries_for_prompt(prompt, limit=limit):
        _append_unique(refs, str(entry.get("uri") or ""))
    return refs

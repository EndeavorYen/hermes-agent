from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_SESSION_VISUAL_REFERENCES = 3
_NAMED_VISUAL_REFERENCE_RE = re.compile(
    r"(?<![a-z0-9])g\s*([1-9][0-9]*)",
    re.IGNORECASE,
)
_NAMED_ORIGINAL_REFERENCE_RE = re.compile(
    r"(?<![a-z0-9])(?:ref(?:erence)?|參考圖?)\s*([1-9][0-9]*)",
    re.IGNORECASE,
)

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
    for existing in entries:
        if str(existing.get("uri") or "").strip() != uri:
            continue
        if existing.get("user_ref_index") in (None, "") and entry.get(
            "user_ref_index"
        ) not in (None, ""):
            existing["user_ref_index"] = entry["user_ref_index"]
        if existing.get("role_hint") in (None, "", "visual_reference") and entry.get(
            "role_hint"
        ) not in (None, "", "visual_reference"):
            existing["role_hint"] = entry["role_hint"]
            existing["source"] = entry.get("source", existing.get("source"))
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
        "基於",
        "基于",
        "沿著",
        "沿着",
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
    return bool(_NAMED_VISUAL_REFERENCE_RE.search(text)) or any(
        marker in text for marker in markers
    ) or any(
        marker in compact for marker in compact_markers
    )


def prompt_requests_original_visual_references(prompt: Any) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    explicit_chinese_reference_markers = (
        "原ref",
        "原reference",
        "原本ref",
        "原本的ref",
        "原本reference",
        "原本的reference",
        "原來ref",
        "原來的ref",
        "原來reference",
        "原來的reference",
        "原来ref",
        "原来的ref",
        "原来reference",
        "原来的reference",
    )
    return (
        bool(_NAMED_ORIGINAL_REFERENCE_RE.search(text))
        or "original reference" in text
        or "original ref" in text
        or "原圖" in text
        or "原图" in text
        or "原始" in text
        or any(marker in compact for marker in explicit_chinese_reference_markers)
    )


def entry_is_generated_visual_output(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    source = str(entry.get("source") or "").strip()
    if source in {
        "previous_selected_artifact",
        "previous_tool_output",
        "previous_visual_arsenal_output",
        "session_visual_artifact",
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
    named_requests = _named_visual_reference_requests(prompt)
    if named_requests:
        entries_by_index = {
            index: entry
            for entry in filtered
            if isinstance(
                index := _coerce_user_ref_index(entry.get("user_ref_index")),
                int,
            )
        }
        named: list[dict[str, Any]] = []
        for index, role_hint in named_requests:
            entry = entries_by_index.get(index)
            if not entry:
                continue
            selected = dict(entry)
            if role_hint:
                selected["role_hint"] = role_hint
            named.append(selected)
        return named
    return filtered


def _named_visual_reference_requests(prompt: Any) -> list[tuple[int, str | None]]:
    text = str(prompt or "")
    matches = sorted(
        [
            *_NAMED_VISUAL_REFERENCE_RE.finditer(text),
            *_NAMED_ORIGINAL_REFERENCE_RE.finditer(text),
        ],
        key=lambda match: match.start(),
    )
    requests: list[tuple[int, str | None]] = []
    seen: set[int] = set()
    for position, match in enumerate(matches):
        index = int(match.group(1))
        if index in seen:
            continue
        seen.add(index)
        segment_end = (
            matches[position + 1].start() if position + 1 < len(matches) else len(text)
        )
        segment = text[match.end() : segment_end].lower()
        role_hint: str | None = None
        if any(
            marker in segment
            for marker in (
                "人物", "角色", "身分", "身份", "臉", "脸",
                "identity", "character", "face",
            )
        ):
            role_hint = "character_identity"
        elif any(
            marker in segment
            for marker in (
                "動作", "动作", "姿勢", "姿势", "構圖", "构图",
                "pose", "action", "composition",
            )
        ):
            role_hint = "pose_composition"
        requests.append((index, role_hint))
    return requests


def named_original_visual_reference_indices(prompt: Any) -> list[int]:
    return [int(match.group(1)) for match in _NAMED_ORIGINAL_REFERENCE_RE.finditer(str(prompt or ""))]


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

    for item in payload.get("session_visual_artifacts") or []:
        if not isinstance(item, dict):
            continue
        _append_unique_entry(
            entries,
            _make_entry(
                item.get("uri"),
                role_hint="edit_anchor",
                source="session_visual_artifact",
                user_ref_index=item.get("user_ref_index"),
            ),
        )

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
    for entry in normalise_visual_reference_entries(
        payload.get("images"),
        default_role_hint="edit_anchor",
        default_source="previous_tool_output",
    ):
        _append_unique_entry(entries, entry)
    for field in ("reference_image_urls", "attachments"):
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
    limit: int | None = MAX_SESSION_VISUAL_REFERENCES,
) -> list[dict[str, Any]]:
    generated_indices = _generated_visual_indices(messages)
    entries: list[dict[str, Any]] = []
    for msg in reversed(messages or []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role in {"tool", "function"}:
            payload = _as_json_object(msg.get("content"))
            if payload:
                for entry in _entries_from_tool_payload(payload):
                    uri = str(entry.get("uri") or "").strip()
                    if (
                        entry_is_generated_visual_output(entry)
                        and entry.get("user_ref_index") in (None, "")
                        and uri in generated_indices
                    ):
                        entry = dict(entry)
                        entry["user_ref_index"] = generated_indices[uri]
                    _append_unique_entry(entries, entry)
        elif role == "assistant":
            for entry in _entries_from_tool_calls(msg):
                _append_unique_entry(entries, entry)
        elif role == "user":
            for entry in _entries_from_message_content(msg.get("content")):
                _append_unique_entry(entries, entry)
        if limit is not None and len(entries) >= limit:
            break
    if limit is None:
        return entries
    return entries[: max(0, limit)]


def label_visual_payload_images(
    payload: dict[str, Any],
    *,
    start_index: int,
) -> list[dict[str, Any]]:
    """Persist stable, user-facing session labels for selected images."""
    existing = payload.get("session_visual_artifacts")
    if isinstance(existing, list) and existing:
        return [dict(item) for item in existing if isinstance(item, dict)]
    try:
        next_index = max(1, int(start_index))
    except (TypeError, ValueError):
        next_index = 1
    artifacts: list[dict[str, Any]] = []
    for uri in normalise_visual_reference_paths(
        [payload.get("images"), payload.get("image")]
    ):
        artifacts.append(
            {
                "label": f"G{next_index}",
                "user_ref_index": next_index,
                "uri": uri,
            }
        )
        next_index += 1
    if artifacts:
        payload["session_visual_artifacts"] = artifacts
    return artifacts


def _generated_visual_indices(messages: list[dict[str, Any]]) -> dict[str, int]:
    indices: dict[str, int] = {}
    next_index = 1
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") not in {"tool", "function"}:
            continue
        payload = _as_json_object(msg.get("content"))
        if not payload or not payload.get("success"):
            continue
        explicit = payload.get("session_visual_artifacts")
        if isinstance(explicit, list) and explicit:
            for item in explicit:
                if not isinstance(item, dict):
                    continue
                uri = _clean_reference(str(item.get("uri") or ""))
                index = _coerce_user_ref_index(item.get("user_ref_index"))
                if not uri or not isinstance(index, int) or index <= 0:
                    continue
                indices.setdefault(uri, index)
                next_index = max(next_index, index + 1)
            continue
        for uri in normalise_visual_reference_paths(payload.get("images")):
            if uri in indices:
                continue
            indices[uri] = next_index
            next_index += 1
    return indices


def next_session_visual_artifact_index(messages: list[dict[str, Any]]) -> int:
    indices = _generated_visual_indices(messages)
    return max(indices.values(), default=0) + 1


def collect_recent_original_visual_reference_entries(
    messages: list[dict[str, Any]],
    *,
    limit: int = MAX_SESSION_VISUAL_REFERENCES,
) -> list[dict[str, Any]]:
    generated_output_uris: set[str] = set()
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") not in {"tool", "function"}:
            continue
        payload = _as_json_object(msg.get("content"))
        if not payload:
            continue
        for entry in _entries_from_tool_payload(payload):
            if not entry_is_generated_visual_output(entry):
                continue
            uri = str(entry.get("uri") or "").strip()
            if uri:
                generated_output_uris.add(uri)

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
            uri = str(entry.get("uri") or "").strip()
            if entry_is_generated_visual_output(entry) or uri in generated_output_uris:
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

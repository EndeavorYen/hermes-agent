from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VOICE_REGISTRY_SCHEMA = "story_video_voice_profile_registry_v1"
VOICE_BINDING_SCHEMA = "story_video_voice_profile_binding_v1"
DEFAULT_VOICE_PROFILE_ROOT = Path.home() / ".hermes" / "story_video_voice_profiles"
DEFAULT_VOICE_REGISTRY = DEFAULT_VOICE_PROFILE_ROOT / "registry.json"
DEFAULT_ACTIVE_PROFILE = DEFAULT_VOICE_PROFILE_ROOT / "active_narrator.json"
VOICE_BINDING_NAME = "voice_profile_binding.json"


class VoiceProfileError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class VoiceProfileSelection:
    profile_id: str
    profile_path: Path
    profile_sha256: str
    binding_path: Path
    binding_sha256: str
    clone_mode: str = "full_icl"
    language_policy: str = "zh-TW"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, error_type: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceProfileError(error_type, f"cannot read voice profile data: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise VoiceProfileError(error_type, f"voice profile data must be an object: {path}")
    return payload


def _resolved_path(value: str, *, relative_to: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = relative_to / path
    return path.resolve()


def _profile_assessment(
    profile_path: Path,
    *,
    expected_profile_id: str = "",
) -> dict[str, Any]:
    try:
        payload = _load_json(profile_path, error_type="voice_profile_invalid")
    except VoiceProfileError as exc:
        return {
            "selectable": False,
            "reason": str(exc),
            "profile_path": str(profile_path),
        }

    profile_id = str(payload.get("profile_id") or "").strip()
    clone_mode = str(payload.get("clone_mode") or "full_icl").strip()
    reasons: list[str] = []
    if not profile_id:
        reasons.append("profile_id is missing")
    if expected_profile_id and profile_id != expected_profile_id:
        reasons.append(
            f"profile_id is {profile_id or '<missing>'}, expected {expected_profile_id}"
        )
    if payload.get("status") != "locked_by_user":
        reasons.append("status is not locked_by_user")
    if str(payload.get("provider") or "").replace("-", "_") != "local_qwen":
        reasons.append("provider is not local_qwen")
    if payload.get("consent") != "user_confirmed_self_recording":
        reasons.append("self-recording consent is not confirmed")
    if payload.get("inference_mode") != "offline":
        reasons.append("inference_mode is not offline")
    if payload.get("network_fallback") != "forbidden":
        reasons.append("network_fallback is not forbidden")
    if payload.get("language") != "zh-TW":
        reasons.append("language is not zh-TW")
    if clone_mode != "full_icl":
        reasons.append("clone_mode is not full_icl")
    if "base" not in str(payload.get("model_id") or "").casefold():
        reasons.append("model_id is not a Qwen Base voice-clone model")
    if not str(payload.get("reference_transcript") or "").strip():
        reasons.append("reference_transcript is missing")
    reference_value = str(payload.get("reference_audio") or "").strip()
    reference_path = (
        _resolved_path(reference_value, relative_to=profile_path.parent)
        if reference_value
        else None
    )
    if reference_path is None or not reference_path.is_file() or reference_path.stat().st_size == 0:
        reasons.append("reference_audio is missing")

    return {
        "profile_id": profile_id or expected_profile_id,
        "display_name": str(payload.get("display_name") or profile_id or expected_profile_id),
        "profile_path": str(profile_path),
        "profile_sha256": _sha256(profile_path),
        "clone_mode": clone_mode,
        "language": str(payload.get("language") or ""),
        "selectable": not reasons,
        "reason": "; ".join(reasons),
    }


def _registry_catalog(
    registry_path: Path,
    *,
    active_profile_path: Path,
) -> dict[str, Any]:
    if registry_path.is_file():
        payload = _load_json(registry_path, error_type="voice_profile_registry_invalid")
        if payload.get("schema") != VOICE_REGISTRY_SCHEMA:
            raise VoiceProfileError(
                "voice_profile_registry_invalid",
                f"unsupported voice profile registry schema: {registry_path}",
            )
        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, list) or not raw_profiles:
            raise VoiceProfileError(
                "voice_profile_registry_invalid",
                f"voice profile registry has no profiles: {registry_path}",
            )
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_profiles:
            if not isinstance(raw, dict):
                raise VoiceProfileError(
                    "voice_profile_registry_invalid",
                    f"voice profile registry entries must be objects: {registry_path}",
                )
            profile_id = str(raw.get("profile_id") or "").strip()
            profile_value = str(raw.get("profile_path") or "").strip()
            if not profile_id or not profile_value or profile_id in seen:
                raise VoiceProfileError(
                    "voice_profile_registry_invalid",
                    f"voice profile registry has an invalid or duplicate profile_id: {profile_id!r}",
                )
            seen.add(profile_id)
            profile_path = _resolved_path(profile_value, relative_to=registry_path.parent)
            assessment = _profile_assessment(
                profile_path,
                expected_profile_id=profile_id,
            )
            enabled = raw.get("enabled") is not False
            if not enabled:
                assessment["selectable"] = False
                assessment["reason"] = "profile is disabled"
            assessment["enabled"] = enabled
            rows.append(assessment)
        default_profile_id = str(payload.get("default_profile_id") or "").strip()
        return {
            "schema": VOICE_REGISTRY_SCHEMA,
            "registry_path": str(registry_path),
            "source": "registry",
            "default_profile_id": default_profile_id,
            "profiles": rows,
        }

    pointer = _load_json(
        active_profile_path,
        error_type="voice_profile_registry_missing",
    )
    profile_id = str(pointer.get("profile_id") or "").strip()
    profile_value = str(pointer.get("profile_path") or "").strip()
    if not profile_id or not profile_value:
        raise VoiceProfileError(
            "voice_profile_registry_missing",
            f"legacy active narrator pointer is invalid: {active_profile_path}",
        )
    profile_path = _resolved_path(profile_value, relative_to=active_profile_path.parent)
    assessment = _profile_assessment(profile_path, expected_profile_id=profile_id)
    assessment["enabled"] = True
    return {
        "schema": VOICE_REGISTRY_SCHEMA,
        "registry_path": str(registry_path),
        "source": "legacy_active_narrator",
        "default_profile_id": profile_id,
        "profiles": [assessment],
    }


def list_voice_profiles(
    *,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    active_profile_path: str | Path | None = None,
) -> dict[str, Any]:
    registry = Path(registry_path).expanduser().resolve()
    active = (
        Path(active_profile_path).expanduser().resolve()
        if active_profile_path is not None
        else registry.parent / "active_narrator.json"
    )
    return _registry_catalog(registry, active_profile_path=active)


def _selectable_profile(
    profile_id: str,
    *,
    registry_path: str | Path,
    active_profile_path: str | Path | None = None,
) -> dict[str, Any]:
    catalog = list_voice_profiles(
        registry_path=registry_path,
        active_profile_path=active_profile_path,
    )
    row = next(
        (item for item in catalog["profiles"] if item["profile_id"] == profile_id),
        None,
    )
    if row is None:
        raise VoiceProfileError(
            "voice_profile_not_found",
            f"voice profile {profile_id!r} is not registered",
        )
    if not row["selectable"]:
        raise VoiceProfileError(
            "voice_profile_not_selectable",
            f"voice profile {profile_id!r} is not selectable: {row['reason']}",
        )
    return row


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _selection_from_binding(binding_path: Path) -> VoiceProfileSelection:
    binding = _load_json(binding_path, error_type="voice_profile_binding_invalid")
    if binding.get("schema") != VOICE_BINDING_SCHEMA:
        raise VoiceProfileError(
            "voice_profile_binding_invalid",
            f"unsupported voice profile binding schema: {binding_path}",
        )
    profile_id = str(binding.get("profile_id") or "").strip()
    profile_value = str(binding.get("profile_path") or "").strip()
    expected_hash = str(binding.get("profile_sha256") or "").strip()
    clone_mode = str(binding.get("clone_mode") or "").strip()
    if not profile_id or not profile_value or not expected_hash:
        raise VoiceProfileError(
            "voice_profile_binding_invalid",
            f"voice profile binding is incomplete: {binding_path}",
        )
    profile_path = _resolved_path(profile_value, relative_to=binding_path.parent)
    assessment = _profile_assessment(profile_path, expected_profile_id=profile_id)
    if not assessment["selectable"]:
        raise VoiceProfileError(
            "voice_profile_binding_mismatch",
            f"bound voice profile is not selectable: {assessment['reason']}",
        )
    if assessment["profile_sha256"] != expected_hash:
        raise VoiceProfileError(
            "voice_profile_binding_mismatch",
            f"bound voice profile hash mismatch: {profile_path}",
        )
    if clone_mode != "full_icl" or assessment["clone_mode"] != clone_mode:
        raise VoiceProfileError(
            "voice_profile_binding_mismatch",
            f"bound voice profile clone mode mismatch: {profile_path}",
        )
    if binding.get("status") != "locked" or binding.get("language_policy") != "zh-TW":
        raise VoiceProfileError(
            "voice_profile_binding_mismatch",
            f"bound voice profile policy mismatch: {binding_path}",
        )
    return VoiceProfileSelection(
        profile_id=profile_id,
        profile_path=profile_path,
        profile_sha256=expected_hash,
        binding_path=binding_path,
        binding_sha256=_sha256(binding_path),
        clone_mode=clone_mode,
        language_policy="zh-TW",
    )


def _has_narration(project: Path) -> bool:
    if (project / "manifests" / "narration_manifest.json").exists():
        return True
    audio_dir = project / "audio" / "qwen"
    return audio_dir.is_dir() and any(audio_dir.glob("*.wav"))


def bind_project_voice_profile(
    project_dir: str | Path,
    *,
    profile_id: str,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    active_profile_path: str | Path | None = None,
) -> VoiceProfileSelection:
    project = Path(project_dir).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    binding_path = project / VOICE_BINDING_NAME
    if binding_path.is_file():
        try:
            current = _selection_from_binding(binding_path)
        except VoiceProfileError:
            if _has_narration(project):
                raise VoiceProfileError(
                    "voice_profile_revoice_required",
                    "cannot repair voice profile binding with existing narration; start an explicit revoice operation",
                ) from None
            current = None
        if current is not None and current.profile_id == profile_id:
            return current
        if _has_narration(project):
            raise VoiceProfileError(
                "voice_profile_revoice_required",
                "cannot change voice profile with existing narration; start an explicit revoice operation",
            )

    profile = _selectable_profile(
        profile_id,
        registry_path=registry_path,
        active_profile_path=active_profile_path,
    )
    profile_path = Path(profile["profile_path"])
    payload = {
        "schema": VOICE_BINDING_SCHEMA,
        "voice_role": "narrator",
        "profile_id": profile_id,
        "profile_path": str(profile_path),
        "profile_sha256": profile["profile_sha256"],
        "clone_mode": "full_icl",
        "language_policy": "zh-TW",
        "status": "locked",
        "bound_at": _utc_now(),
    }
    _write_json_atomic(binding_path, payload)
    return _selection_from_binding(binding_path)


def resolve_project_voice_profile(
    project_dir: str | Path,
    *,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    active_profile_path: str | Path | None = None,
) -> VoiceProfileSelection:
    project = Path(project_dir).expanduser().resolve()
    binding_path = project / VOICE_BINDING_NAME
    if binding_path.is_file():
        return _selection_from_binding(binding_path)
    catalog = list_voice_profiles(
        registry_path=registry_path,
        active_profile_path=active_profile_path,
    )
    default_profile_id = str(catalog.get("default_profile_id") or "").strip()
    if not default_profile_id:
        raise VoiceProfileError(
            "voice_profile_default_missing",
            "voice profile registry has no default_profile_id",
        )
    return bind_project_voice_profile(
        project,
        profile_id=default_profile_id,
        registry_path=registry_path,
        active_profile_path=active_profile_path,
    )


def inspect_project_voice_profile(
    project_dir: str | Path,
    *,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    active_profile_path: str | Path | None = None,
) -> dict[str, Any]:
    project = Path(project_dir).expanduser().resolve()
    binding_path = project / VOICE_BINDING_NAME
    if not binding_path.is_file():
        catalog = list_voice_profiles(
            registry_path=registry_path,
            active_profile_path=active_profile_path,
        )
        return {
            "bound": False,
            "integrity": "NOT_BOUND",
            "resolved_profile_id": catalog["default_profile_id"],
            "binding_path": str(binding_path),
        }
    selection = _selection_from_binding(binding_path)
    return {
        "bound": True,
        "integrity": "PASS",
        "resolved_profile_id": selection.profile_id,
        "profile_id": selection.profile_id,
        "profile_path": str(selection.profile_path),
        "profile_sha256": selection.profile_sha256,
        "binding_path": str(selection.binding_path),
        "binding_sha256": selection.binding_sha256,
        "clone_mode": selection.clone_mode,
        "language_policy": selection.language_policy,
    }

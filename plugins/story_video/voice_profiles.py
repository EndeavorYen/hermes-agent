from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VOICE_REGISTRY_SCHEMA = "story_video_voice_profile_registry_v1"
VOICE_REGISTRY_SCHEMA_V2 = "story_video_voice_profile_registry_v2"
VOICE_REGISTRY_SCHEMAS = {VOICE_REGISTRY_SCHEMA, VOICE_REGISTRY_SCHEMA_V2}
VOICE_BINDING_SCHEMA = "story_video_voice_profile_binding_v1"
DEFAULT_VOICE_PROFILE_ROOT = Path.home() / ".hermes" / "story_video_voice_profiles"
DEFAULT_VOICE_REGISTRY = DEFAULT_VOICE_PROFILE_ROOT / "registry.json"
DEFAULT_ACTIVE_PROFILE = DEFAULT_VOICE_PROFILE_ROOT / "active_narrator.json"
VOICE_BINDING_NAME = "voice_profile_binding.json"
DEFAULT_MODEL_ID = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
DEFAULT_MODEL_PATH = Path.home() / ".hermes" / "models" / "Qwen3-TTS-12Hz-1.7B-Base-8bit"
DEFAULT_ASR_MODEL_PATH = Path.home() / ".hermes" / "models" / "Qwen3-ASR-0.6B-8bit"
DEFAULT_ALIGNER_MODEL_PATH = (
    Path.home() / ".hermes" / "models" / "Qwen3-ForcedAligner-0.6B-8bit"
)
DEFAULT_RUNTIME_PATH = (
    Path.home() / ".hermes" / ".venvs" / "mlx-audio" / "bin" / "mlx_audio.tts.generate"
)
_VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


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
        "voice_id": str(payload.get("voice_id") or profile_id or expected_profile_id),
        "version": payload.get("version"),
        "display_name": str(payload.get("display_name") or profile_id or expected_profile_id),
        "profile_path": str(profile_path),
        "profile_sha256": _sha256(profile_path),
        "clone_mode": clone_mode,
        "language": str(payload.get("language") or ""),
        "parent_profile_id": str(payload.get("parent_profile_id") or ""),
        "tuning": payload.get("tuning") if isinstance(payload.get("tuning"), dict) else {},
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
        if payload.get("schema") not in VOICE_REGISTRY_SCHEMAS:
            raise VoiceProfileError(
                "voice_profile_registry_invalid",
                f"unsupported voice profile registry schema: {registry_path}",
            )
        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, list) or (
            not raw_profiles and payload.get("schema") == VOICE_REGISTRY_SCHEMA
        ):
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
            assessment["voice_id"] = str(
                raw.get("voice_id") or assessment.get("voice_id") or profile_id
            )
            if raw.get("version") is not None:
                assessment["version"] = raw.get("version")
            assessment["lifecycle_status"] = str(
                raw.get("lifecycle_status") or ("active" if enabled else "archived")
            )
            rows.append(assessment)
        default_profile_id = str(payload.get("default_profile_id") or "").strip()
        return {
            "schema": str(payload.get("schema")),
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
    assessment["lifecycle_status"] = "active"
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
        candidates = [
            item
            for item in catalog["profiles"]
            if str(item.get("voice_id") or "") == profile_id
        ]
        selectable = [item for item in candidates if item.get("selectable")]
        pool = selectable or candidates
        if pool:
            row = max(pool, key=lambda item: int(item.get("version") or 0))
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


def _validate_voice_id(voice_id: str) -> str:
    normalized = str(voice_id or "").strip()
    if not _VOICE_ID_PATTERN.fullmatch(normalized):
        raise VoiceProfileError(
            "voice_profile_id_invalid",
            "voice_id must start with an ASCII letter or number and contain only letters, numbers, underscore, or hyphen",
        )
    return normalized


def _mutable_registry(registry_path: Path) -> dict[str, Any]:
    if not registry_path.is_file():
        return {
            "schema": VOICE_REGISTRY_SCHEMA_V2,
            "default_profile_id": "",
            "profiles": [],
        }
    payload = _load_json(registry_path, error_type="voice_profile_registry_invalid")
    if payload.get("schema") not in VOICE_REGISTRY_SCHEMAS:
        raise VoiceProfileError(
            "voice_profile_registry_invalid",
            f"unsupported voice profile registry schema: {registry_path}",
        )
    if not isinstance(payload.get("profiles"), list):
        raise VoiceProfileError(
            "voice_profile_registry_invalid",
            f"voice profile registry profiles must be an array: {registry_path}",
        )
    payload["schema"] = VOICE_REGISTRY_SCHEMA_V2
    return payload


def _entry_identity(entry: dict[str, Any], registry_path: Path) -> tuple[str, int | None]:
    voice_id = str(entry.get("voice_id") or "").strip()
    version = entry.get("version")
    profile_value = str(entry.get("profile_path") or "").strip()
    if profile_value:
        profile_path = _resolved_path(profile_value, relative_to=registry_path.parent)
        if profile_path.is_file():
            payload = _load_json(profile_path, error_type="voice_profile_invalid")
            voice_id = voice_id or str(payload.get("voice_id") or payload.get("profile_id") or "")
            version = version if version is not None else payload.get("version")
    try:
        parsed_version = int(version) if version is not None else None
    except (TypeError, ValueError):
        parsed_version = None
    return voice_id, parsed_version


def _normalized_voice_tuning(tuning: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(tuning or {})
    allowed = {"speed", "pitch_shift_semitones", "expressiveness"}
    if set(value) - allowed:
        raise VoiceProfileError(
            "voice_profile_tuning_invalid",
            f"unsupported voice tuning fields: {sorted(set(value) - allowed)}",
        )
    if "speed" in value:
        value["speed"] = float(value["speed"])
        if not 0.85 <= value["speed"] <= 1.2:
            raise VoiceProfileError(
                "voice_profile_tuning_invalid", "voice speed must be between 0.85 and 1.2"
            )
    if "pitch_shift_semitones" in value:
        value["pitch_shift_semitones"] = float(value["pitch_shift_semitones"])
        if not -3.0 <= value["pitch_shift_semitones"] <= 3.0:
            raise VoiceProfileError(
                "voice_profile_tuning_invalid",
                "voice pitch shift must be between -3 and 3 semitones",
            )
    if "expressiveness" in value and value["expressiveness"] not in {
        "restrained",
        "natural",
        "lively",
        "dramatic",
    }:
        raise VoiceProfileError(
            "voice_profile_tuning_invalid",
            f"unsupported expressiveness: {value['expressiveness']}",
        )
    return value


def add_voice_profile(
    *,
    voice_id: str,
    display_name: str,
    reference_audio: str | Path,
    reference_transcript: str,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    consent: str,
    model_id: str = DEFAULT_MODEL_ID,
    tuning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    voice_id = _validate_voice_id(voice_id)
    if consent != "user_confirmed_self_recording":
        raise VoiceProfileError(
            "voice_profile_consent_required",
            "voice profile creation requires confirmed self-recording consent",
        )
    transcript = str(reference_transcript or "").strip()
    if not transcript:
        raise VoiceProfileError(
            "voice_profile_reference_invalid",
            "reference transcript is required",
        )
    normalized_tuning = _normalized_voice_tuning(tuning)
    source = Path(reference_audio).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise VoiceProfileError(
            "voice_profile_reference_invalid",
            f"reference audio is missing or empty: {source}",
        )
    registry = Path(registry_path).expanduser().resolve()
    payload = _mutable_registry(registry)
    runtime_settings: dict[str, Any] = {
        "engine": "Qwen3-TTS via MLX-Audio",
        "model_path": str(DEFAULT_MODEL_PATH),
        "asr_model_path": str(DEFAULT_ASR_MODEL_PATH),
        "aligner_model_path": str(DEFAULT_ALIGNER_MODEL_PATH),
        "runtime_path": str(DEFAULT_RUNTIME_PATH),
        "speed": 1.06,
        "temperature": 0.7,
        "top_p": 0.8,
        "prosody_temperature": 0.8,
        "prosody_top_p": 0.9,
        "prosody": {
            "segmentation": "sentence_voice_chunk_v1",
            "pause_after_segment_sec": 0.18,
            "speed_enforcement": "ffmpeg_atempo",
            "pitch_span_min_semitones": 2.5,
            "rms_span_min_db": 6.0,
        },
    }
    default_profile_id = str(payload.get("default_profile_id") or "").strip()
    default_entry = next(
        (
            entry
            for entry in payload["profiles"]
            if isinstance(entry, dict)
            and str(entry.get("profile_id") or "") == default_profile_id
        ),
        None,
    )
    if default_entry is not None:
        default_path = _resolved_path(
            str(default_entry.get("profile_path") or ""), relative_to=registry.parent
        )
        default_payload = _load_json(default_path, error_type="voice_profile_invalid")
        for key in runtime_settings:
            if key in default_payload:
                runtime_settings[key] = default_payload[key]
    existing_versions = [
        version
        for entry in payload["profiles"]
        if isinstance(entry, dict)
        for entry_voice_id, version in [_entry_identity(entry, registry)]
        if entry_voice_id == voice_id and version is not None
    ]
    if any(
        _entry_identity(entry, registry)[0] == voice_id
        and _entry_identity(entry, registry)[1] is None
        for entry in payload["profiles"]
        if isinstance(entry, dict)
    ):
        existing_versions.append(1)
    version = max(existing_versions, default=0) + 1
    profile_id = f"{voice_id}@v{version}"
    profile_dir = registry.parent / profile_id
    if profile_dir.exists():
        raise VoiceProfileError(
            "voice_profile_exists",
            f"voice profile path already exists: {profile_dir}",
        )
    profile_dir.mkdir(parents=True)
    suffix = source.suffix.lower() or ".wav"
    copied_reference = profile_dir / f"reference{suffix}"
    shutil.copy2(source, copied_reference)
    parent_profile_id = ""
    if existing_versions:
        prior_version = max(existing_versions)
        prior = next(
            (
                entry
                for entry in payload["profiles"]
                if isinstance(entry, dict)
                and _entry_identity(entry, registry) == (voice_id, prior_version)
            ),
            None,
        )
        parent_profile_id = str((prior or {}).get("profile_id") or "")
    profile_path = profile_dir / "profile.json"
    profile_payload: dict[str, Any] = {
        "schema": "story_video_local_voice_profile_v2",
        "voice_id": voice_id,
        "profile_id": profile_id,
        "version": version,
        "display_name": str(display_name or voice_id).strip(),
        "status": "locked_by_user",
        "provider": "local_qwen",
        "model_id": model_id,
        "reference_audio": str(copied_reference),
        "reference_transcript": transcript,
        "language": "zh-TW",
        "clone_mode": "full_icl",
        "inference_mode": "offline",
        "network_fallback": "forbidden",
        "consent": consent,
        "tuning": normalized_tuning,
        "created_at": _utc_now(),
        **runtime_settings,
    }
    if "speed" in profile_payload["tuning"]:
        profile_payload["speed"] = float(profile_payload["tuning"]["speed"])
    if parent_profile_id:
        profile_payload["parent_profile_id"] = parent_profile_id
    _write_json_atomic(profile_path, profile_payload)
    payload["profiles"].append(
        {
            "voice_id": voice_id,
            "profile_id": profile_id,
            "version": version,
            "profile_path": str(profile_path),
            "enabled": True,
            "lifecycle_status": "active",
        }
    )
    if not str(payload.get("default_profile_id") or "").strip():
        payload["default_profile_id"] = profile_id
    _write_json_atomic(registry, payload)
    result = _profile_assessment(profile_path, expected_profile_id=profile_id)
    result.update(
        {
            "voice_id": voice_id,
            "version": version,
            "lifecycle_status": "active",
            "enabled": True,
        }
    )
    return result


def tune_voice_profile(
    *,
    voice_id: str,
    tuning: dict[str, Any],
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    reference_audio: str | Path | None = None,
    reference_transcript: str | None = None,
) -> dict[str, Any]:
    voice_id = _validate_voice_id(voice_id)
    registry = Path(registry_path).expanduser().resolve()
    payload = _mutable_registry(registry)
    versions = [
        (version, entry)
        for entry in payload["profiles"]
        if isinstance(entry, dict)
        for entry_voice_id, version in [_entry_identity(entry, registry)]
        if entry_voice_id == voice_id and version is not None
    ]
    if not versions:
        raise VoiceProfileError(
            "voice_profile_not_found",
            f"voice {voice_id!r} is not registered",
        )
    _, latest_entry = max(versions, key=lambda row: row[0])
    latest_path = _resolved_path(
        str(latest_entry["profile_path"]), relative_to=registry.parent
    )
    latest = _load_json(latest_path, error_type="voice_profile_invalid")
    source = reference_audio or latest.get("reference_audio")
    transcript = reference_transcript or latest.get("reference_transcript")
    merged_tuning = dict(latest.get("tuning") or {})
    merged_tuning.update(dict(tuning or {}))
    return add_voice_profile(
        voice_id=voice_id,
        display_name=str(latest.get("display_name") or voice_id),
        reference_audio=str(source or ""),
        reference_transcript=str(transcript or ""),
        registry_path=registry,
        consent="user_confirmed_self_recording",
        model_id=str(latest.get("model_id") or DEFAULT_MODEL_ID),
        tuning=merged_tuning,
    )


def archive_voice_profile(
    *,
    voice_id: str,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
) -> dict[str, Any]:
    voice_id = _validate_voice_id(voice_id)
    registry = Path(registry_path).expanduser().resolve()
    payload = _mutable_registry(registry)
    archived: list[str] = []
    for entry in payload["profiles"]:
        if not isinstance(entry, dict):
            continue
        entry_voice_id, _ = _entry_identity(entry, registry)
        if entry_voice_id != voice_id:
            continue
        entry["voice_id"] = voice_id
        entry["enabled"] = False
        entry["lifecycle_status"] = "archived"
        archived.append(str(entry.get("profile_id") or ""))
    if not archived:
        raise VoiceProfileError(
            "voice_profile_not_found",
            f"voice {voice_id!r} is not registered",
        )
    if payload.get("default_profile_id") in archived:
        payload["default_profile_id"] = next(
            (
                str(entry.get("profile_id") or "")
                for entry in payload["profiles"]
                if isinstance(entry, dict) and entry.get("enabled") is not False
            ),
            "",
        )
    _write_json_atomic(registry, payload)
    return {"voice_id": voice_id, "archived_profile_ids": archived}


def _profile_references(projects_root: Path, profile_ids: set[str]) -> list[str]:
    if not projects_root.is_dir():
        return []
    references: list[str] = []
    for name in (VOICE_BINDING_NAME, "voice_cast_binding.json"):
        for path in projects_root.rglob(name):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            referenced_ids: set[str] = set()
            if isinstance(payload, dict):
                direct = str(payload.get("profile_id") or "").strip()
                if direct:
                    referenced_ids.add(direct)
                for row in payload.get("speakers") or []:
                    if isinstance(row, dict):
                        value = str(row.get("profile_id") or "").strip()
                        if value:
                            referenced_ids.add(value)
            if profile_ids & referenced_ids:
                references.append(str(path))
    return sorted(set(references))


def delete_voice_profile(
    *,
    voice_id: str,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    projects_root: str | Path = Path.home() / ".hermes" / "story_videos",
) -> dict[str, Any]:
    voice_id = _validate_voice_id(voice_id)
    registry = Path(registry_path).expanduser().resolve()
    payload = _mutable_registry(registry)
    targets = [
        entry
        for entry in payload["profiles"]
        if isinstance(entry, dict) and _entry_identity(entry, registry)[0] == voice_id
    ]
    if not targets:
        raise VoiceProfileError(
            "voice_profile_not_found",
            f"voice {voice_id!r} is not registered",
        )
    profile_ids = {str(entry.get("profile_id") or "") for entry in targets}
    references = _profile_references(
        Path(projects_root).expanduser().resolve(), profile_ids
    )
    if references:
        raise VoiceProfileError(
            "voice_profile_in_use",
            "voice profile is referenced by project bindings: " + ", ".join(references),
        )
    target_paths = [
        _resolved_path(str(entry["profile_path"]), relative_to=registry.parent)
        for entry in targets
    ]
    payload["profiles"] = [entry for entry in payload["profiles"] if entry not in targets]
    if payload.get("default_profile_id") in profile_ids:
        payload["default_profile_id"] = next(
            (
                str(entry.get("profile_id") or "")
                for entry in payload["profiles"]
                if isinstance(entry, dict) and entry.get("enabled") is not False
            ),
            "",
        )
    _write_json_atomic(registry, payload)
    for profile_path in target_paths:
        profile_dir = profile_path.parent
        if profile_dir.parent == registry.parent and profile_dir.is_dir():
            shutil.rmtree(profile_dir)
        else:
            profile_path.unlink(missing_ok=True)
    return {"voice_id": voice_id, "deleted_profile_ids": sorted(profile_ids)}


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
    profile = _selectable_profile(
        profile_id,
        registry_path=registry_path,
        active_profile_path=active_profile_path,
    )
    concrete_profile_id = str(profile["profile_id"])
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
        if current is not None and current.profile_id == concrete_profile_id:
            return current
        if _has_narration(project):
            raise VoiceProfileError(
                "voice_profile_revoice_required",
                "cannot change voice profile with existing narration; start an explicit revoice operation",
            )

    profile_path = Path(profile["profile_path"])
    payload = {
        "schema": VOICE_BINDING_SCHEMA,
        "voice_role": "narrator",
        "profile_id": concrete_profile_id,
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

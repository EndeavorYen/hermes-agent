from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .voice_presets import (
    DEFAULT_CUSTOM_VOICE_MODEL_PATH,
    DEFAULT_MLX_PYTHON,
    PRESET_VOICES,
)
from .voice_profiles import (
    DEFAULT_VOICE_REGISTRY,
    _profile_assessment,
    list_voice_profiles,
)


VOICE_CATALOG_SCHEMA = "story_video_voice_catalog_v1"


class VoiceCatalogError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _supported_presets(model: Path) -> tuple[set[str], str]:
    config = model / "config.json"
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return set(), f"cannot read Qwen CustomVoice model config: {exc}"
    speakers = payload.get("talker_config", {}).get("spk_id", {})
    if payload.get("tts_model_type") != "custom_voice" or not isinstance(
        speakers, dict
    ):
        return set(), "installed model is not a valid Qwen CustomVoice model"
    return {str(name).casefold() for name in speakers}, ""


def _profile_voice(profile: dict[str, Any]) -> dict[str, Any]:
    voice_id = str(profile.get("voice_id") or profile["profile_id"])
    return {
        "voice_id": voice_id,
        "display_name": str(profile.get("display_name") or profile["profile_id"]),
        "aliases": [str(profile["profile_id"]), voice_id],
        "version": profile.get("version"),
        "engine": "qwen_full_icl",
        "source_kind": "clone_profile",
        "language": str(profile.get("language") or "zh-TW"),
        "locale": str(profile.get("language") or "zh-TW"),
        "traits": {},
        "capabilities": {
            "preview": False,
            "single_narrator": True,
            "character_dubbing": True,
            "operator_tunable": True,
        },
        "availability": {
            "status": "ready" if profile.get("selectable") else "disabled",
            "reason": str(profile.get("reason") or ""),
        },
        "selectable": bool(profile.get("selectable")),
        "engine_binding": {
            "profile_id": str(profile["profile_id"]),
            "profile_path": str(profile["profile_path"]),
            "profile_sha256": str(profile["profile_sha256"]),
        },
    }


def _preset_voice(
    key: str,
    metadata: dict[str, Any],
    *,
    model: Path,
    runtime: Path,
    supported: set[str],
    model_reason: str,
) -> dict[str, Any]:
    reasons = []
    if key not in supported:
        reasons.append(
            model_reason
            or f"installed model does not support {metadata['speaker']}"
        )
    if not runtime.is_file():
        reasons.append(f"missing local Qwen runtime: {runtime}")
    selectable = not reasons
    config = model / "config.json"
    return {
        "voice_id": str(metadata["catalog_voice_id"]),
        "display_name": str(metadata["speaker"]),
        "aliases": [str(metadata["speaker"]), key],
        "engine": "qwen_custom_voice",
        "source_kind": "preset",
        "language": "zh",
        "locale": str(metadata["locale"]),
        "traits": dict(metadata["traits"]),
        "capabilities": {
            "preview": True,
            "single_narrator": True,
            "character_dubbing": True,
            "operator_tunable": False,
        },
        "availability": {
            "status": "ready" if selectable else "setup_required",
            "reason": "; ".join(reasons),
        },
        "selectable": selectable,
        "engine_binding": {
            "preset_speaker": str(metadata["speaker"]),
            "model_path": str(model),
            "model_config_path": str(config),
            "model_config_sha256": _sha256(config) if selectable else "",
            "runtime_path": str(runtime),
        },
    }


def list_voice_catalog(
    *,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    active_profile_path: str | Path | None = None,
    preset_model_path: str | Path = DEFAULT_CUSTOM_VOICE_MODEL_PATH,
    preset_runtime_path: str | Path = DEFAULT_MLX_PYTHON,
) -> dict[str, Any]:
    profile_catalog = list_voice_profiles(
        registry_path=registry_path,
        active_profile_path=active_profile_path,
    )
    voices = [_profile_voice(profile) for profile in profile_catalog["profiles"]]

    model = Path(preset_model_path).expanduser().resolve()
    runtime = Path(preset_runtime_path).expanduser().resolve()
    supported, model_reason = _supported_presets(model)
    voices.extend(
        _preset_voice(
            key,
            metadata,
            model=model,
            runtime=runtime,
            supported=supported,
            model_reason=model_reason,
        )
        for key, metadata in PRESET_VOICES.items()
        if metadata.get("character_dubbing") is True
    )

    snapshot = [
        {
            "voice_id": row["voice_id"],
            "engine": row["engine"],
            "selectable": row["selectable"],
            "engine_binding": row["engine_binding"],
        }
        for row in voices
    ]
    default_profile_id = str(profile_catalog.get("default_profile_id") or "")
    default_profile = next(
        (
            row
            for row in profile_catalog["profiles"]
            if str(row.get("profile_id") or "") == default_profile_id
        ),
        None,
    )
    return {
        **profile_catalog,
        "catalog_schema": VOICE_CATALOG_SCHEMA,
        "catalog_sha256": _canonical_sha256(snapshot),
        "default_voice_id": str(
            (default_profile or {}).get("voice_id") or default_profile_id
        ),
        "voices": voices,
        "voice_count": len(voices),
    }


def resolve_catalog_voice(selector: str, catalog: dict[str, Any]) -> dict[str, Any]:
    requested = str(selector or "").strip().casefold()
    matches = [
        row
        for row in catalog.get("voices") or []
        if requested == str(row.get("voice_id") or "").casefold()
        or requested in {str(alias).casefold() for alias in row.get("aliases") or []}
    ]
    if not matches:
        raise VoiceCatalogError(
            "voice_catalog_not_found",
            f"voice {selector!r} is not registered",
        )
    selectable = [row for row in matches if row.get("selectable")]
    if not selectable:
        row = matches[0]
        raise VoiceCatalogError(
            "voice_catalog_not_selectable",
            f"voice {selector!r} is not selectable: {row['availability']['reason']}",
        )
    row = max(selectable, key=lambda item: int(item.get("version") or 0))
    return dict(row)


def build_engine_binding(voice: dict[str, Any]) -> dict[str, Any]:
    binding = voice.get("engine_binding")
    if not isinstance(binding, dict):
        raise VoiceCatalogError(
            "voice_binding_invalid",
            f"voice {voice.get('voice_id')!r} has no engine binding",
        )
    return {**dict(binding), "engine": str(voice.get("engine") or "")}


def validate_engine_binding(binding: Any) -> None:
    if not isinstance(binding, dict):
        raise VoiceCatalogError(
            "voice_binding_invalid",
            "engine binding must be an object",
        )
    engine = str(binding.get("engine") or "")
    if engine == "qwen_full_icl":
        profile_path = Path(
            str(binding.get("profile_path") or "")
        ).expanduser().resolve()
        assessment = _profile_assessment(
            profile_path,
            expected_profile_id=str(binding.get("profile_id") or ""),
        )
        if not assessment.get("selectable"):
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                f"bound voice profile is invalid: {assessment.get('reason')}",
            )
        if assessment.get("profile_sha256") != str(
            binding.get("profile_sha256") or ""
        ):
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                f"bound voice profile hash mismatch: {profile_path}",
            )
        return
    if engine == "qwen_custom_voice":
        runtime = Path(str(binding.get("runtime_path") or "")).expanduser().resolve()
        config = Path(
            str(binding.get("model_config_path") or "")
        ).expanduser().resolve()
        if not runtime.is_file() or not config.is_file():
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                "bound Qwen CustomVoice setup is missing",
            )
        if _sha256(config) != str(binding.get("model_config_sha256") or ""):
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                f"bound model config hash mismatch: {config}",
            )
        supported, reason = _supported_presets(config.parent)
        speaker = str(binding.get("preset_speaker") or "").casefold()
        if reason or speaker not in supported:
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                reason
                or f"bound model does not support {binding.get('preset_speaker')}",
            )
        return
    raise VoiceCatalogError(
        "voice_binding_invalid",
        f"unsupported voice engine: {engine or '<missing>'}",
    )

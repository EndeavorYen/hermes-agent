from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tone_map import ToneMapError, build_tone_catalog, resolve_utterance_tone
from .voice_catalog import (
    VoiceCatalogError,
    build_engine_binding,
    list_voice_catalog,
    resolve_catalog_voice,
    validate_engine_binding,
)
from .voice_profiles import (
    DEFAULT_VOICE_REGISTRY,
    VoiceProfileError,
    _load_json,
    _profile_assessment,
    _resolved_path,
    _sha256,
    _write_json_atomic,
)


STORY_MODE_SCHEMA = "story_video_story_mode_v1"
CAST_BIBLE_SCHEMA = "story_video_cast_bible_v1"
DIALOGUE_LEDGER_SCHEMA_V1 = "story_video_dialogue_ledger_v1"
DIALOGUE_LEDGER_SCHEMA_V2 = "story_video_dialogue_ledger_v2"
DIALOGUE_LEDGER_SCHEMAS = {
    DIALOGUE_LEDGER_SCHEMA_V1,
    DIALOGUE_LEDGER_SCHEMA_V2,
}
DIALOGUE_LEDGER_SCHEMA = DIALOGUE_LEDGER_SCHEMA_V2
VOICE_CAST_BINDING_SCHEMA_V1 = "story_video_voice_cast_binding_v1"
VOICE_CAST_BINDING_SCHEMA_V2 = "story_video_voice_cast_binding_v2"
VOICE_CAST_BINDING_SCHEMAS = {
    VOICE_CAST_BINDING_SCHEMA_V1,
    VOICE_CAST_BINDING_SCHEMA_V2,
}
VOICE_CAST_BINDING_SCHEMA = VOICE_CAST_BINDING_SCHEMA_V1

STORY_MODE_NAME = "story_mode.json"
CAST_BIBLE_NAME = "cast_bible.json"
DIALOGUE_LEDGER_NAME = "dialogue_ledger.json"
VOICE_CAST_BINDING_NAME = "voice_cast_binding.json"

STORY_MODES = {"creative", "remake", "read_aloud"}
SPEAKER_ROLES = {"narrator", "lead", "supporting", "extra"}
PACES = {"slow", "measured", "natural", "quick"}
EXPRESSIVENESS = {"restrained", "natural", "lively", "dramatic"}

_LOW_ENERGY_TONES = {
    "general.warm",
    "general.sad",
    "adult.intimate",
    "adult.shy",
    "adult.receptive",
    "adult.afterglow",
}
_HIGH_ENERGY_TONES = {
    "general.joyful",
    "general.excited",
    "general.angry",
    "adult.commanding",
    "adult.intense",
}
_TONE_TRANSITION_CUES = (
    "突然",
    "忽然",
    "猛然",
    "頓時",
    "立刻",
    "轉而",
    "就在這時",
)


class DubbingContractError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class VoiceCastSelection:
    binding_path: Path
    binding_sha256: str
    story_mode: str
    speakers: tuple[dict[str, Any], ...]


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_speakers(speakers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not speakers:
        raise DubbingContractError(
            "dubbing_cast_invalid", "at least one speaker is required"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in speakers:
        if not isinstance(raw, dict):
            raise DubbingContractError(
                "dubbing_cast_invalid", "speaker records must be objects"
            )
        speaker_id = str(raw.get("speaker_id") or "").strip()
        voice_id = str(raw.get("voice_id") or "").strip()
        role = str(raw.get("role") or "supporting").strip()
        if not speaker_id or speaker_id in seen or not voice_id:
            raise DubbingContractError(
                "dubbing_cast_invalid",
                f"speaker_id must be unique and voice_id is required: {speaker_id!r}",
            )
        if role not in SPEAKER_ROLES:
            raise DubbingContractError(
                "dubbing_cast_invalid", f"unsupported speaker role: {role}"
            )
        variant = raw.get("variant") or {}
        if not isinstance(variant, dict):
            raise DubbingContractError(
                "voice_cast_variant_invalid", f"variant must be an object: {speaker_id}"
            )
        seen.add(speaker_id)
        row = {
            "speaker_id": speaker_id,
            "display_name": str(raw.get("display_name") or speaker_id).strip(),
            "role": role,
            "voice_id": voice_id,
        }
        if variant:
            row["variant"] = dict(variant)
        normalized.append(row)
    return normalized


def _validate_source_refs(
    utterance_id: str,
    refs: Any,
    source_text: str,
) -> list[dict[str, int]]:
    if not isinstance(refs, list) or not refs:
        raise DubbingContractError(
            "remake_source_reference_missing",
            f"remake utterance {utterance_id} requires source_refs",
        )
    normalized: list[dict[str, int]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise DubbingContractError(
                "remake_source_reference_invalid",
                f"source_refs must contain objects: {utterance_id}",
            )
        try:
            start = int(ref["start"])
            end = int(ref["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DubbingContractError(
                "remake_source_reference_invalid",
                f"source_refs require integer start/end: {utterance_id}",
            ) from exc
        if start < 0 or end <= start or end > len(source_text):
            raise DubbingContractError(
                "remake_source_reference_invalid",
                f"source_refs are outside source text: {utterance_id}",
            )
        normalized.append({"start": start, "end": end})
    return normalized


def _apply_tone_continuity(
    previous_tone: dict[str, Any] | None,
    resolved_tone: dict[str, Any],
    *,
    cue_text: str,
) -> dict[str, Any]:
    if (
        not previous_tone
        or resolved_tone.get("resolution") == "explicit"
        or previous_tone.get("tone_id") not in _LOW_ENERGY_TONES
        or resolved_tone.get("tone_id") not in _HIGH_ENERGY_TONES
        or any(cue in cue_text for cue in _TONE_TRANSITION_CUES)
    ):
        return resolved_tone
    intensity = resolved_tone.get("intensity")
    if not isinstance(intensity, int) or intensity <= 1:
        return resolved_tone
    adjusted = dict(resolved_tone)
    adjusted["intensity"] = intensity - 1
    adjusted["continuity_adjustment"] = (
        "reduced_unprompted_low_to_high_transition"
    )
    return adjusted


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_dialogue_ledger_contract(
    ledger: dict[str, Any],
    *,
    path: Path,
) -> None:
    schema = str(ledger.get("schema") or "")
    if schema not in DIALOGUE_LEDGER_SCHEMAS:
        raise DubbingContractError(
            "dubbing_utterance_invalid",
            f"dialogue ledger schema is unsupported or missing: {path}",
        )
    if schema == DIALOGUE_LEDGER_SCHEMA_V1:
        return
    if not isinstance(ledger.get("utterances"), list):
        raise DubbingContractError(
            "dubbing_utterance_invalid",
            f"dialogue ledger utterances are invalid: {path}",
        )
    catalog = ledger.get("tone_catalog")
    if not isinstance(catalog, dict):
        raise DubbingContractError(
            "dubbing_tone_catalog_invalid",
            f"dialogue ledger v2 tone catalog is missing: {path}",
        )
    catalog_sha = str(catalog.get("sha256") or "")
    tones = catalog.get("tones")
    modifiers = catalog.get("modifiers")
    if (
        catalog.get("schema") != "story_video_tone_catalog_v1"
        or len(catalog_sha) != 64
        or any(character not in "0123456789abcdef" for character in catalog_sha)
        or not isinstance(tones, dict)
        or not tones
        or not isinstance(modifiers, dict)
        or not modifiers
    ):
        raise DubbingContractError(
            "dubbing_tone_catalog_invalid",
            f"dialogue ledger v2 tone catalog shape is invalid: {path}",
        )
    canonical_catalog = {key: value for key, value in catalog.items() if key != "sha256"}
    if _canonical_json_sha256(canonical_catalog) != catalog_sha:
        raise DubbingContractError(
            "dubbing_tone_catalog_invalid",
            f"dialogue ledger v2 tone catalog hash mismatch: {path}",
        )


def _validate_utterances(
    *,
    mode: str,
    source_text: str,
    utterances: list[dict[str, Any]],
    speaker_ids: set[str],
    content_rating: str,
) -> list[dict[str, Any]]:
    if not utterances:
        raise DubbingContractError(
            "dubbing_utterance_invalid", "at least one utterance is required"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_cursor = 0
    previous_tone: dict[str, Any] | None = None
    for order, raw in enumerate(utterances, start=1):
        if not isinstance(raw, dict):
            raise DubbingContractError(
                "dubbing_utterance_invalid", "utterance records must be objects"
            )
        utterance_id = str(raw.get("utterance_id") or "").strip()
        speaker_id = str(raw.get("speaker_id") or "").strip()
        display_text = str(raw.get("display_text") or "")
        if not utterance_id or utterance_id in seen or not display_text:
            raise DubbingContractError(
                "dubbing_utterance_invalid",
                f"utterance_id must be unique and display_text is required: {utterance_id!r}",
            )
        if speaker_id not in speaker_ids:
            raise DubbingContractError(
                "dubbing_speaker_unresolved",
                f"utterance {utterance_id} references unknown speaker {speaker_id!r}",
            )
        scene_id = str(raw.get("scene_id") or "").strip()
        shot_id = str(raw.get("shot_id") or "").strip()
        if not scene_id or not shot_id:
            raise DubbingContractError(
                "dubbing_utterance_invalid",
                f"utterance {utterance_id} requires scene_id and shot_id",
            )
        row: dict[str, Any] = {
            "order": order,
            "utterance_id": utterance_id,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "speaker_id": speaker_id,
            "display_text": display_text,
        }
        emotion = str(raw.get("emotion") or "").strip()
        action = str(raw.get("action") or "").strip()
        pace = str(raw.get("pace") or "").strip()
        if emotion:
            row["emotion"] = emotion
        if action:
            row["action"] = action
        if pace:
            if pace not in PACES:
                raise DubbingContractError(
                    "dubbing_performance_invalid",
                    f"unsupported pace {pace!r}: {utterance_id}",
                )
            row["pace"] = pace
        try:
            resolved_tone = resolve_utterance_tone(
                emotion=emotion,
                action=action,
                pace=pace,
                tone_id=str(raw.get("tone_id") or ""),
                intensity=raw.get("tone_intensity"),
                modifiers=(
                    raw.get("tone_modifiers")
                    if "tone_modifiers" in raw
                    else None
                ),
                content_rating=content_rating,
            )
        except ToneMapError as exc:
            raise DubbingContractError(exc.error_type, str(exc)) from exc
        row["tone"] = _apply_tone_continuity(
            previous_tone,
            resolved_tone,
            cue_text=f"{action}\n{display_text}",
        )
        if mode == "read_aloud":
            try:
                start = int(raw["source_start"])
                end = int(raw["source_end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DubbingContractError(
                    "read_aloud_source_span_invalid",
                    f"read-aloud utterance requires integer source span: {utterance_id}",
                ) from exc
            if start != source_cursor:
                raise DubbingContractError(
                    "read_aloud_source_coverage_invalid",
                    f"read-aloud source has a gap or overlap at {utterance_id}",
                )
            if end <= start or end > len(source_text):
                raise DubbingContractError(
                    "read_aloud_source_span_invalid",
                    f"read-aloud source span is invalid: {utterance_id}",
                )
            if display_text != source_text[start:end]:
                raise DubbingContractError(
                    "read_aloud_text_mismatch",
                    f"read-aloud display text is not the exact source slice: {utterance_id}",
                )
            row.update({"source_start": start, "source_end": end})
            source_cursor = end
        elif mode == "remake":
            row["source_refs"] = _validate_source_refs(
                utterance_id, raw.get("source_refs"), source_text
            )
        seen.add(utterance_id)
        normalized.append(row)
        previous_tone = row["tone"]
    if mode == "read_aloud" and source_cursor != len(source_text):
        raise DubbingContractError(
            "read_aloud_source_coverage_invalid",
            "read-aloud source has a gap or overlap after the final utterance",
        )
    return normalized


def compile_dubbing_project(
    project_dir: str | Path,
    *,
    mode: str,
    source_text: str,
    speakers: list[dict[str, Any]],
    utterances: list[dict[str, Any]],
    content_rating: str = "general",
) -> dict[str, Any]:
    project = Path(project_dir).expanduser().resolve()
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in STORY_MODES:
        raise DubbingContractError(
            "story_mode_invalid", f"unsupported story mode: {mode!r}"
        )
    source = str(source_text or "")
    normalized_content_rating = str(content_rating or "general").strip().casefold()
    if normalized_content_rating not in {
        "family",
        "general",
        "mature",
        "adult_explicit",
    }:
        raise DubbingContractError(
            "content_rating_invalid",
            f"unsupported content rating: {content_rating!r}",
        )
    if normalized_mode in {"remake", "read_aloud"} and not source:
        raise DubbingContractError(
            "story_mode_source_required",
            f"{normalized_mode} mode requires source_text",
        )
    normalized_speakers = _validate_speakers(speakers)
    normalized_utterances = _validate_utterances(
        mode=normalized_mode,
        source_text=source,
        utterances=utterances,
        speaker_ids={row["speaker_id"] for row in normalized_speakers},
        content_rating=normalized_content_rating,
    )
    project.mkdir(parents=True, exist_ok=True)
    source_sha = _text_sha256(source) if source else ""
    mode_payload = {
        "schema": STORY_MODE_SCHEMA,
        "mode": normalized_mode,
        "source_text": source,
        "source_sha256": source_sha,
        "exact_text_required": normalized_mode == "read_aloud",
    }
    cast_payload = {
        "schema": CAST_BIBLE_SCHEMA,
        "speakers": normalized_speakers,
    }
    ledger_payload = {
        "schema": DIALOGUE_LEDGER_SCHEMA,
        "mode": normalized_mode,
        "content_rating": normalized_content_rating,
        "tone_catalog": build_tone_catalog(),
        "source_sha256": source_sha,
        "utterances": normalized_utterances,
    }
    planned = {
        STORY_MODE_NAME: mode_payload,
        CAST_BIBLE_NAME: cast_payload,
        DIALOGUE_LEDGER_NAME: ledger_payload,
    }
    if (project / VOICE_CAST_BINDING_NAME).is_file() and _has_narration(project):
        changed = []
        for name, expected_payload in planned.items():
            existing_path = project / name
            try:
                existing_payload = _load_json(
                    existing_path, error_type="dubbing_contract_invalid"
                )
            except VoiceProfileError:
                changed.append(name)
                continue
            if existing_payload != expected_payload:
                changed.append(name)
        if changed:
            raise DubbingContractError(
                "voice_cast_revoice_required",
                "cannot recompile locked dubbing contracts with existing narration; "
                "start an explicit revoice operation: " + ", ".join(changed),
            )
    _write_json_atomic(project / STORY_MODE_NAME, mode_payload)
    _write_json_atomic(project / CAST_BIBLE_NAME, cast_payload)
    _write_json_atomic(project / DIALOGUE_LEDGER_NAME, ledger_payload)
    return {
        "mode": normalized_mode,
        "source_sha256": source_sha,
        "exact_text_required": normalized_mode == "read_aloud",
        "speaker_count": len(normalized_speakers),
        "utterance_count": len(normalized_utterances),
        "story_mode_path": str(project / STORY_MODE_NAME),
        "cast_bible_path": str(project / CAST_BIBLE_NAME),
        "dialogue_ledger_path": str(project / DIALOGUE_LEDGER_NAME),
    }


def _validate_variant(speaker_id: str, variant: Any) -> dict[str, Any]:
    if variant in (None, {}):
        return {}
    if not isinstance(variant, dict):
        raise DubbingContractError(
            "voice_cast_variant_invalid", f"variant must be an object: {speaker_id}"
        )
    allowed = {"speed", "pitch_shift_semitones", "expressiveness"}
    if set(variant) - allowed:
        raise DubbingContractError(
            "voice_cast_variant_invalid",
            f"unsupported variant fields for {speaker_id}: {sorted(set(variant) - allowed)}",
        )
    result = dict(variant)
    if "speed" in result:
        speed = float(result["speed"])
        if not 0.85 <= speed <= 1.2:
            raise DubbingContractError(
                "voice_cast_variant_invalid",
                f"variant speed must be between 0.85 and 1.2: {speaker_id}",
            )
        result["speed"] = speed
    if "pitch_shift_semitones" in result:
        pitch = float(result["pitch_shift_semitones"])
        if not -3.0 <= pitch <= 3.0:
            raise DubbingContractError(
                "voice_cast_variant_invalid",
                f"variant pitch must be between -3 and 3: {speaker_id}",
            )
        result["pitch_shift_semitones"] = pitch
    if "expressiveness" in result and result["expressiveness"] not in EXPRESSIVENESS:
        raise DubbingContractError(
            "voice_cast_variant_invalid",
            f"unsupported expressiveness for {speaker_id}: {result['expressiveness']}",
        )
    return result


def _has_narration(project: Path) -> bool:
    if (project / "manifests" / "narration_manifest.json").is_file():
        return True
    audio = project / "audio" / "qwen"
    return audio.is_dir() and any(audio.glob("*.wav"))


def bind_project_voice_cast(
    project_dir: str | Path,
    *,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    voice_catalog: dict[str, Any] | None = None,
) -> VoiceCastSelection:
    project = Path(project_dir).expanduser().resolve()
    cast_path = project / CAST_BIBLE_NAME
    mode_path = project / STORY_MODE_NAME
    ledger_path = project / DIALOGUE_LEDGER_NAME
    for path in (cast_path, mode_path, ledger_path):
        if not path.is_file():
            raise DubbingContractError(
                "dubbing_contract_missing", f"required dubbing contract is missing: {path}"
            )
    ledger = _load_json(ledger_path, error_type="dubbing_utterance_invalid")
    _validate_dialogue_ledger_contract(ledger, path=ledger_path)
    binding_path = project / VOICE_CAST_BINDING_NAME
    if binding_path.is_file():
        try:
            current = resolve_project_voice_cast(project)
        except DubbingContractError:
            if _has_narration(project):
                raise DubbingContractError(
                    "voice_cast_revoice_required",
                    "cannot repair cast binding with existing narration; start an explicit revoice operation",
                ) from None
        else:
            return current
    catalog = voice_catalog
    if catalog is None:
        try:
            catalog = list_voice_catalog(registry_path=registry_path)
        except (VoiceCatalogError, VoiceProfileError) as exc:
            raise DubbingContractError(
                "voice_cast_profile_unresolved", str(exc)
            ) from exc
    cast = _load_json(cast_path, error_type="dubbing_cast_invalid")
    mode = _load_json(mode_path, error_type="story_mode_invalid")
    resolved: list[dict[str, Any]] = []
    for speaker in cast.get("speakers") or []:
        speaker_id = str(speaker.get("speaker_id") or "")
        variant = _validate_variant(speaker_id, speaker.get("variant"))
        try:
            voice = resolve_catalog_voice(
                str(speaker.get("voice_id") or ""),
                catalog,
            )
            engine_binding = build_engine_binding(voice)
        except VoiceCatalogError as exc:
            raise DubbingContractError(
                "voice_cast_profile_unresolved", str(exc)
            ) from exc
        row = {
            "speaker_id": speaker_id,
            "display_name": str(speaker.get("display_name") or speaker_id),
            "role": str(speaker.get("role") or "supporting"),
            "voice_id": str(voice["voice_id"]),
            "engine": str(voice["engine"]),
            "source_kind": str(voice["source_kind"]),
            "assignment_origin": "manual",
            "engine_binding": engine_binding,
            "variant": variant,
        }
        if voice["engine"] == "qwen_full_icl":
            row.update(
                {
                    "profile_id": str(engine_binding["profile_id"]),
                    "profile_path": str(engine_binding["profile_path"]),
                    "profile_sha256": str(engine_binding["profile_sha256"]),
                    "clone_mode": "full_icl",
                }
            )
        resolved.append(row)
    payload = {
        "schema": VOICE_CAST_BINDING_SCHEMA_V2,
        "status": "locked",
        "language_policy": "zh-TW",
        "catalog_sha256": str(catalog.get("catalog_sha256") or ""),
        "story_mode": str(mode.get("mode") or ""),
        "story_mode_path": str(mode_path),
        "story_mode_sha256": _sha256(mode_path),
        "cast_bible_path": str(cast_path),
        "cast_bible_sha256": _sha256(cast_path),
        "dialogue_ledger_path": str(ledger_path),
        "dialogue_ledger_sha256": _sha256(ledger_path),
        "speakers": resolved,
    }
    _write_json_atomic(binding_path, payload)
    return resolve_project_voice_cast(project)


def resolve_project_voice_cast(project_dir: str | Path) -> VoiceCastSelection:
    project = Path(project_dir).expanduser().resolve()
    binding_path = project / VOICE_CAST_BINDING_NAME
    binding = _load_json(binding_path, error_type="voice_cast_binding_invalid")
    if (
        binding.get("schema") not in VOICE_CAST_BINDING_SCHEMAS
        or binding.get("status") != "locked"
        or binding.get("language_policy") != "zh-TW"
    ):
        raise DubbingContractError(
            "voice_cast_binding_invalid", f"invalid voice cast binding: {binding_path}"
        )
    schema = str(binding["schema"])
    if schema == VOICE_CAST_BINDING_SCHEMA_V2 and not str(
        binding.get("catalog_sha256") or ""
    ):
        raise DubbingContractError(
            "voice_cast_binding_invalid",
            f"v2 voice cast binding has no catalog hash: {binding_path}",
        )
    for key, name in (
        ("story_mode_sha256", STORY_MODE_NAME),
        ("cast_bible_sha256", CAST_BIBLE_NAME),
        ("dialogue_ledger_sha256", DIALOGUE_LEDGER_NAME),
    ):
        path = project / name
        if not path.is_file() or _sha256(path) != str(binding.get(key) or ""):
            raise DubbingContractError(
                "voice_cast_binding_mismatch", f"bound dubbing contract hash mismatch: {path}"
            )
    ledger_path = project / DIALOGUE_LEDGER_NAME
    ledger = _load_json(ledger_path, error_type="dubbing_utterance_invalid")
    _validate_dialogue_ledger_contract(ledger, path=ledger_path)
    mode = _load_json(project / STORY_MODE_NAME, error_type="story_mode_invalid")
    if str(mode.get("mode") or "") != str(binding.get("story_mode") or ""):
        raise DubbingContractError(
            "voice_cast_binding_mismatch",
            f"bound story mode does not match story mode contract: {project / STORY_MODE_NAME}",
        )
    speakers = binding.get("speakers")
    if not isinstance(speakers, list) or not speakers:
        raise DubbingContractError(
            "voice_cast_binding_invalid", "voice cast binding has no speakers"
        )
    for row in speakers:
        if not isinstance(row, dict):
            raise DubbingContractError(
                "voice_cast_binding_invalid",
                "voice cast binding speaker rows must be objects",
            )
        if schema == VOICE_CAST_BINDING_SCHEMA_V1:
            profile_path = _resolved_path(
                str(row.get("profile_path") or ""),
                relative_to=binding_path.parent,
            )
            assessment = _profile_assessment(
                profile_path,
                expected_profile_id=str(row.get("profile_id") or ""),
            )
            if not assessment["selectable"]:
                raise DubbingContractError(
                    "voice_cast_binding_mismatch",
                    f"bound voice profile is invalid: {assessment['reason']}",
                )
            if assessment["profile_sha256"] != str(
                row.get("profile_sha256") or ""
            ):
                raise DubbingContractError(
                    "voice_cast_binding_mismatch",
                    f"bound voice profile hash mismatch: {profile_path}",
                )
        else:
            engine_binding = row.get("engine_binding")
            if (
                not isinstance(engine_binding, dict)
                or not str(row.get("voice_id") or "")
                or str(row.get("engine") or "")
                != str(engine_binding.get("engine") or "")
            ):
                raise DubbingContractError(
                    "voice_cast_binding_invalid",
                    "v2 voice cast speaker has inconsistent engine evidence",
                )
            try:
                validate_engine_binding(engine_binding)
            except VoiceCatalogError as exc:
                raise DubbingContractError(
                    "voice_cast_binding_mismatch", str(exc)
                ) from exc
        _validate_variant(str(row.get("speaker_id") or ""), row.get("variant"))
    return VoiceCastSelection(
        binding_path=binding_path,
        binding_sha256=_sha256(binding_path),
        story_mode=str(binding.get("story_mode") or ""),
        speakers=tuple(dict(row) for row in speakers),
    )


def inspect_dubbing_project(project_dir: str | Path) -> dict[str, Any]:
    project = Path(project_dir).expanduser().resolve()
    mode = _load_json(project / STORY_MODE_NAME, error_type="story_mode_invalid")
    cast = _load_json(project / CAST_BIBLE_NAME, error_type="dubbing_cast_invalid")
    ledger = _load_json(
        project / DIALOGUE_LEDGER_NAME, error_type="dubbing_utterance_invalid"
    )
    _validate_dialogue_ledger_contract(
        ledger,
        path=project / DIALOGUE_LEDGER_NAME,
    )
    payload: dict[str, Any] = {
        "mode": str(mode.get("mode") or ""),
        "source_sha256": str(mode.get("source_sha256") or ""),
        "exact_text_required": bool(mode.get("exact_text_required")),
        "speaker_count": len(cast.get("speakers") or []),
        "utterance_count": len(ledger.get("utterances") or []),
        "bound": False,
        "integrity": "NOT_BOUND",
    }
    binding_path = project / VOICE_CAST_BINDING_NAME
    if binding_path.is_file():
        selection = resolve_project_voice_cast(project)
        payload.update(
            {
                "bound": True,
                "integrity": "PASS",
                "binding_path": str(selection.binding_path),
                "binding_sha256": selection.binding_sha256,
            }
        )
    return payload

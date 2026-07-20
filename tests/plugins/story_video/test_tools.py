from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from plugins.story_video.accessible_explainer import (
    ACCESSIBLE_EXPLAINER_PROFILE_ID,
    ensure_explanation_profile,
)
from plugins.story_video.audit import ProviderAudit, ProviderAuditEvent
from plugins.story_video.dubbing import (
    DubbingContractError,
    bind_project_voice_cast,
    compile_dubbing_project,
)
from plugins.story_video.schemas import (
    STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA,
    STORY_VIDEO_CONTROL_SCHEMA,
    STORY_VIDEO_VOICE_MANAGER_SCHEMA,
)
from plugins.story_video.sequence_quality import write_sequence_quality_report
from plugins.story_video.shot_contract import shot_contract_hash
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call
from plugins.story_video.tone_map import build_tone_catalog
from plugins.story_video.tools import (
    _next_phase,
    _project_content_rating,
    story_video_audio_director,
    story_video_control,
    story_video_voice_manager,
    validate_phase,
)


def _active_context(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert call is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request="start",
    )
    ensure_explanation_profile(context.project_dir, context.original_request)
    return store, context


def _voice_registry(tmp_path, *profile_ids: str, default: str | None = None):
    root = tmp_path / "voice_profiles"
    root.mkdir(exist_ok=True)
    rows = []
    for profile_id in profile_ids:
        directory = root / profile_id
        directory.mkdir()
        reference = directory / "reference.wav"
        reference.write_bytes(b"clean reference")
        profile = directory / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "profile_id": profile_id,
                    "display_name": profile_id,
                    "status": "locked_by_user",
                    "provider": "local_qwen",
                    "model_id": "Qwen3-TTS-12Hz-1.7B-Base-8bit",
                    "reference_audio": str(reference),
                    "reference_transcript": "這是本人授權的參考錄音。",
                    "language": "zh-TW",
                    "clone_mode": "full_icl",
                    "inference_mode": "offline",
                    "network_fallback": "forbidden",
                    "consent": "user_confirmed_self_recording",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rows.append(
            {"profile_id": profile_id, "profile_path": str(profile), "enabled": True}
        )
    registry = root / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "story_video_voice_profile_registry_v1",
                "default_profile_id": default or profile_ids[0],
                "profiles": rows,
            }
        ),
        encoding="utf-8",
    )
    return registry


def _ready_voice_catalog(tmp_path) -> dict:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry = _voice_registry(
        tmp_path,
        "simon_clean_v2",
        default="simon_clean_v2",
    )
    model = tmp_path / "custom-voice-model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "tts_model_type": "custom_voice",
                "talker_config": {
                    "spk_id": {"vivian": 1, "serena": 2, "uncle_fu": 3}
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = tmp_path / "mlx-python"
    runtime.write_text("runtime", encoding="utf-8")
    return list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )


def _write_valid_v7_tone_voice_project(tmp_path):
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    catalog = _ready_voice_catalog(tmp_path)
    compile_dubbing_project(
        context.project_dir,
        mode="creative",
        source_text="",
        content_rating="general",
        speakers=[
            {
                "speaker_id": "narrator",
                "display_name": "旁白",
                "role": "narrator",
                "voice_id": "simon_clean_v2",
            },
            {
                "speaker_id": "xiaomei",
                "display_name": "小美",
                "role": "lead",
                "voice_id": "Vivian",
            },
        ],
        utterances=[
            {
                "utterance_id": "U001",
                "scene_id": "S01",
                "shot_id": "S01_SH01",
                "speaker_id": "narrator",
                "display_text": "故事開始。",
            },
            {
                "utterance_id": "U002",
                "scene_id": "S01",
                "shot_id": "S01_SH01",
                "speaker_id": "xiaomei",
                "display_text": "你好。",
                "emotion": "warmth",
                "action": "輕聲走近",
            },
        ],
    )
    selection = bind_project_voice_cast(
        context.project_dir,
        voice_catalog=catalog,
    )
    dialogue = context.project_dir / "dialogue_ledger.json"
    ledger = json.loads(dialogue.read_text(encoding="utf-8"))
    binding = selection.binding_path
    profiles = {
        str(row["speaker_id"]): row for row in selection.speakers
    }
    audio = context.project_dir / "audio" / "qwen" / "S01.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"tone-aware-cast-audio")
    pronunciation = context.project_dir / "qc" / "pronunciation_qc_report.json"
    pronunciation.parent.mkdir(parents=True)
    pronunciation.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v3",
                "run_id": context.run_id,
                "status": "PASS",
                "language": "zh-TW",
                "method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
                "checked_unit": "voice_chunk",
                "fluency_contract": "bounded_internal_silence_v1",
                "max_internal_silence_sec": 0.9,
                "applied_entries": [],
                "acoustic_evidence": [
                    {
                        "shot_id": chunk_id,
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "fluency_status": "PASS",
                        "longest_internal_silence_sec": 0.1,
                        "term_checks": [],
                    }
                    for chunk_id in ("U001__C01", "U002__C01")
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def chunk(
        *,
        utterance_id: str,
        speaker_id: str,
        display_text: str,
        start: float,
        tone: dict,
    ) -> dict:
        profile = profiles[speaker_id]
        engine = str(profile["engine"])
        tone_id = str(tone["tone_id"])
        adapter = ledger["tone_catalog"]["tones"][tone_id]["adapters"][engine]
        template_id = str(adapter.get("template_id") or "")
        instruct = str(adapter.get("instruct") or "")
        instruction_fragments = [
            str(
                ledger["tone_catalog"]["modifiers"][modifier_id]["adapters"][
                    engine
                ].get("instruction_fragment")
                or ""
            ).strip()
            for modifier_id in tone.get("modifiers") or []
            if str(
                ledger["tone_catalog"]["modifiers"][modifier_id]["adapters"][
                    engine
                ].get("instruction_fragment")
                or ""
            ).strip()
        ]
        if instruction_fragments:
            instruct = "；".join([instruct, *instruction_fragments])
        pause = float(adapter.get("pause_seconds") or 0.18)
        return {
            "voice_chunk_id": f"{utterance_id}__C01",
            "utterance_id": utterance_id,
            "speaker_id": speaker_id,
            "voice_id": str(profile["voice_id"]),
            "engine": engine,
            "profile_id": str(profile.get("profile_id") or ""),
            "profile_sha256": str(profile.get("profile_sha256") or ""),
            "speaker_routing_status": "PASS",
            "display_text": display_text,
            "spoken_text": display_text,
            "scene_start_sec": start,
            "scene_speech_end_sec": start + 1.0,
            "start_sec": start,
            "speech_end_sec": start + 1.0,
            "alignment_status": "PASS",
            "pronunciation_status": "PASS",
            "prosody_status": "PASS",
            "fluency_status": "PASS",
            "tone": tone,
            "tone_adapter": engine,
            "tone_instruction_template_id": template_id,
            "tone_application": {
                "adapter_status": (
                    "neutral_noop" if tone_id == "general.neutral" else "applied"
                ),
                "engine": engine,
                "instruction_template_id": template_id,
                "instruct": instruct,
                "pause_seconds": pause if tone_id != "general.neutral" else None,
                "applied_parameters": {
                    "speed": float(adapter.get("speed_multiplier") or 1.0),
                    "temperature_delta": float(adapter.get("temperature_delta") or 0.0),
                    "pitch_shift_semitones": 0,
                    "tone_pitch_shift_semitones": 0,
                    "expressiveness": str(adapter.get("expressiveness") or "natural"),
                },
            },
            "tone_applied_parameters": {
                "speed": float(adapter.get("speed_multiplier") or 1.0),
                "temperature_delta": float(adapter.get("temperature_delta") or 0.0),
                "pitch_shift_semitones": 0,
                "tone_pitch_shift_semitones": 0,
                "expressiveness": str(adapter.get("expressiveness") or "natural"),
            },
            "resolved_pause_after_sec": pause,
            "pause_after_sec": pause,
            "candidate_count": 1,
            "selected_candidate": 1,
            "candidate_rejections": [],
        }

    chunks = [
        chunk(
            utterance_id="U001",
            speaker_id="narrator",
            display_text="故事開始。",
            start=0.0,
            tone=ledger["utterances"][0]["tone"],
        ),
        chunk(
            utterance_id="U002",
            speaker_id="xiaomei",
            display_text="你好。",
            start=1.18,
            tone=ledger["utterances"][1]["tone"],
        ),
    ]
    tone_catalog = build_tone_catalog()
    manifest = {
        "schema": "story_video_narration_manifest_v7",
        "run_id": context.run_id,
        "provider": "local_qwen",
        "engine": "Qwen3-TTS via MLX-Audio",
        "language": "zh-TW",
        "voice_role": "cast",
        "voice": "multi_character",
        "rate": "per_speaker",
        "profile_status": "cast_bound",
        "voice_contract_status": "PASS",
        "model": "Qwen3-TTS-1.7B",
        "inference_mode": "offline",
        "network_fallback": "forbidden",
        "pronunciation_status": "PASS",
        "alignment_status": "PASS",
        "prosody_status": "PASS",
        "fluency_status": "PASS",
        "spoken_text_normalization": "bounded_ellipsis_v1",
        "voice_segmentation": "sentence_chunks_v1",
        "voice_chunk_count": 2,
        "story_mode": "creative",
        "speaker_routing_status": "PASS",
        "speaker_similarity_status": "NOT_MEASURED",
        "speaker_similarity_method": "routing_integrity_only",
        "voice_cast_binding": str(binding),
        "voice_cast_binding_sha256": hashlib.sha256(binding.read_bytes()).hexdigest(),
        "dialogue_ledger": str(dialogue),
        "dialogue_ledger_sha256": hashlib.sha256(dialogue.read_bytes()).hexdigest(),
        "speaker_profiles": selection.speakers,
        "content_rating": "general",
        "tone_catalog_schema": str(tone_catalog["schema"]),
        "tone_catalog_version": int(tone_catalog["version"]),
        "tone_catalog_sha256": str(tone_catalog["sha256"]),
        "tone_control_status": "PASS",
        "tone_evidence_status": "HEURISTIC_PASS",
        "outputs": [
            {
                "scene_id": "S01",
                "audio": str(audio),
                "duration_sec": 2.36,
                "display_text": "故事開始。你好。",
                "spoken_text": "故事開始。你好。",
                "pronunciation_status": "PASS",
                "segments": [
                    {
                        "shot_id": "S01_SH01",
                        "timeline_duration_sec": 2.36,
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "voice_chunks": chunks,
                    }
                ],
            }
        ],
    }
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return context, manifest_path, dialogue, binding


def test_story_video_control_schema_exposes_voice_profile_actions() -> None:
    action = STORY_VIDEO_CONTROL_SCHEMA["parameters"]["properties"]["action"]

    assert {"guide", "list_voices", "select_voice", "voice_status"}.issubset(
        action["enum"]
    )
    assert STORY_VIDEO_CONTROL_SCHEMA["parameters"]["properties"]["section"][
        "enum"
    ] == ["help", "status", "examples", "writing", "voices"]


def test_story_video_control_guides_without_active_project(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)

    payload = json.loads(
        story_video_control(
            {"action": "guide", "section": "status"},
            session_id="no-project",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["action"] == "guide"
    assert payload["section"] == "status"
    assert "沒有綁定故事影片" in payload["guide"]
    assert store.for_session("no-project") is None


def test_black_subtitle_planning_skips_image_phases(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    text = "故事影片：夜班故事｜1分｜全黑背景加字幕。"
    call = parse_operator_call(text)
    assert call is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request=text,
    )

    assert _next_phase(context) == "voice"


def test_story_video_control_guides_active_project_without_advancing(tmp_path) -> None:
    store, context = _active_context(tmp_path)

    payload = json.loads(
        story_video_control(
            {"action": "guide", "section": "status"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["phase"] == "planning"
    assert "恐龍起源" in payload["guide"]
    assert store.for_session("session-1").phase == context.phase


def test_story_video_control_recovers_context_from_verified_run_identity(
    tmp_path,
) -> None:
    store, context = _active_context(tmp_path)

    payload = json.loads(
        story_video_control(
            {
                "action": "status",
                "run_id": context.run_id,
                "project_dir": str(context.project_dir),
            },
            session_id="rotated-session-without-index",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["run_id"] == context.run_id
    assert store.for_session("rotated-session-without-index").run_id == context.run_id


def test_story_video_control_rejects_unverified_run_identity(tmp_path) -> None:
    store, context = _active_context(tmp_path)

    payload = json.loads(
        story_video_control(
            {
                "action": "status",
                "run_id": "wrong-run",
                "project_dir": str(context.project_dir),
            },
            session_id="rotated-session-without-index",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "story_video_context_missing"


def test_story_video_specialist_tool_schemas_are_narrow_and_complete() -> None:
    manager_actions = STORY_VIDEO_VOICE_MANAGER_SCHEMA["parameters"]["properties"][
        "action"
    ]["enum"]
    director_actions = STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA["parameters"]["properties"][
        "action"
    ]["enum"]

    assert manager_actions == [
        "list",
        "preview_preset",
        "add",
        "tune",
        "archive",
        "delete",
    ]
    assert STORY_VIDEO_VOICE_MANAGER_SCHEMA["parameters"]["properties"]["speakers"][
        "maxItems"
    ] == 3
    assert "CustomVoice preset previews" in STORY_VIDEO_VOICE_MANAGER_SCHEMA[
        "description"
    ]
    assert director_actions == [
        "compile",
        "bind_cast",
        "status",
        "start_production",
        "production_status",
        "retry_delivery",
    ]
    assert "catalog voice" in STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA["description"]
    assert STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA["parameters"]["properties"]["mode"][
        "enum"
    ] == ["creative", "remake", "read_aloud"]


def test_voice_manager_adds_tunes_and_archives_local_voice(tmp_path) -> None:
    registry = tmp_path / "voices" / "registry.json"
    source = tmp_path / "mom.wav"
    source.write_bytes(b"clean-mom-reference")

    added = json.loads(
        story_video_voice_manager(
            {
                "action": "add",
                "voice_id": "mom",
                "display_name": "Mom",
                "reference_audio": str(source),
                "reference_transcript": "這是媽媽本人授權的乾淨錄音。",
                "consent": "user_confirmed_self_recording",
            },
            voice_registry_path=registry,
        )
    )
    tuned = json.loads(
        story_video_voice_manager(
            {
                "action": "tune",
                "voice_id": "mom",
                "tuning": {"speed": 1.08, "expressiveness": "lively"},
            },
            voice_registry_path=registry,
        )
    )
    archived = json.loads(
        story_video_voice_manager(
            {"action": "archive", "voice_id": "mom"},
            voice_registry_path=registry,
        )
    )

    assert added["success"] is True
    assert added["profile_id"] == "mom@v1"
    assert tuned["profile_id"] == "mom@v2"
    assert archived["archived_profile_ids"] == ["mom@v1", "mom@v2"]


def test_voice_manager_list_returns_normalized_selectable_actors(tmp_path) -> None:
    catalog = {
        "schema": "story_video_voice_profile_registry_v2",
        "profiles": [],
        "catalog_schema": "story_video_voice_catalog_v1",
        "catalog_sha256": "catalog-hash",
        "voices": [
            {
                "voice_id": "qwen_custom_vivian",
                "display_name": "Vivian",
                "engine": "qwen_custom_voice",
                "source_kind": "preset",
                "selectable": True,
                "availability": {"status": "ready", "reason": ""},
            }
        ],
    }

    payload = json.loads(
        story_video_voice_manager(
            {"action": "list"},
            voice_catalog_builder=lambda **kwargs: catalog,
            voice_registry_path=tmp_path / "registry.json",
        )
    )

    assert payload["success"] is True
    assert payload["profiles"] == []
    assert payload["voices"][0]["voice_id"] == "qwen_custom_vivian"


def test_voice_manager_previews_named_custom_voice_presets(tmp_path) -> None:
    calls = []

    def previewer(*, speakers, sample_text):
        calls.append((speakers, sample_text))
        paths = [tmp_path / f"{speaker}.wav" for speaker in speakers]
        for path in paths:
            path.write_bytes(b"audio")
        return {
            "speakers": speakers,
            "sample_text": sample_text,
            "samples": [
                {"speaker": speaker, "path": str(path)}
                for speaker, path in zip(speakers, paths)
            ],
            "media": [f"MEDIA:{path}" for path in paths],
        }

    payload = json.loads(
        story_video_voice_manager(
            {
                "action": "preview_preset",
                "speakers": ["Vivian", "Serena", "Uncle_Fu"],
                "sample_text": "這是一段聲線試聽。",
            },
            preset_previewer=previewer,
        )
    )

    assert payload["success"] is True
    assert payload["action"] == "preview_preset"
    assert payload["media"] == [
        f"MEDIA:{tmp_path / 'Vivian.wav'}",
        f"MEDIA:{tmp_path / 'Serena.wav'}",
        f"MEDIA:{tmp_path / 'Uncle_Fu.wav'}",
    ]
    assert calls == [
        (["Vivian", "Serena", "Uncle_Fu"], "這是一段聲線試聽。")
    ]


def test_voice_manager_returns_structured_error_when_preview_names_are_missing() -> None:
    payload = json.loads(
        story_video_voice_manager(
            {"action": "preview_preset", "speakers": []},
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "voice_preset_speakers_required"


def test_audio_director_compiles_and_binds_active_story_project(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    registry = _voice_registry(tmp_path, "voice_a", "voice_b", default="voice_a")

    payload = json.loads(
        story_video_audio_director(
            {
                "action": "compile",
                "mode": "creative",
                "source_text": "",
                "speakers": [
                    {
                        "speaker_id": "narrator",
                        "display_name": "旁白",
                        "role": "narrator",
                        "voice_id": "voice_a",
                    },
                    {
                        "speaker_id": "hero",
                        "display_name": "主角",
                        "role": "lead",
                        "voice_id": "voice_b",
                    },
                ],
                "utterances": [
                    {
                        "utterance_id": "U001",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "narrator",
                        "display_text": "故事開始。",
                    },
                    {
                        "utterance_id": "U002",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "hero",
                        "display_text": "出發吧！",
                    },
                ],
            },
            session_id="session-1",
            store=store,
            voice_registry_path=registry,
        )
    )

    assert payload["success"] is True
    assert payload["mode"] == "creative"
    assert payload["speaker_count"] == 2
    assert payload["bound"] is True
    assert Path(payload["binding_path"]) == context.project_dir / "voice_cast_binding.json"

    assert "voice_id" in STORY_VIDEO_CONTROL_SCHEMA["parameters"]["properties"]


def test_audio_director_rejects_incomplete_adult_profile_as_general(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    registry = _voice_registry(tmp_path, "voice_a", default="voice_a")
    (context.project_dir / "content_profile.json").write_text(
        json.dumps(
            {
                "schema": "story_video_content_profile_v1",
                "rating": "adult_explicit",
                "activation_status": "active",
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        story_video_audio_director(
            {
                "action": "compile",
                "mode": "creative",
                "source_text": "",
                "speakers": [
                    {
                        "speaker_id": "lead",
                        "display_name": "主角",
                        "role": "lead",
                        "voice_id": "voice_a",
                    }
                ],
                "utterances": [
                    {
                        "utterance_id": "U001",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "lead",
                        "display_text": "再靠近一點。",
                        "tone_id": "adult.intimate",
                        "tone_intensity": 2,
                        "tone_modifiers": ["soft"],
                    }
                ],
            },
            session_id="session-1",
            store=store,
            voice_registry_path=registry,
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "tone_content_rating_invalid"
    assert not (context.project_dir / "voice_cast_binding.json").exists()


@pytest.mark.parametrize(
    "profile_update",
    [
        {"schema": "wrong"},
        {"activation_status": "inactive"},
        {"provider_capability_status": "unavailable"},
        {"minimum_viewer_age": -1},
        {"policy_profile_id": ""},
        {"writer_profile_id": ""},
        {"review_profile_id": ""},
    ],
)
def test_project_content_rating_falls_back_for_invalid_general_profile(
    tmp_path,
    profile_update,
) -> None:
    _store, context = _active_context(tmp_path)
    profile = {
        "schema": "story_video_content_profile_v1",
        "rating": "family",
        "activation_status": "active",
        "minimum_viewer_age": 5,
        "policy_profile_id": "family-safe-v1",
        "writer_profile_id": "family-writer-v1",
        "review_profile_id": "family-review-board-v1",
        "provider_capability_status": "available",
    }
    profile.update(profile_update)
    (context.project_dir / "content_profile.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    assert _project_content_rating(context) == "general"


def test_project_content_rating_accepts_valid_general_contract(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    (context.project_dir / "content_profile.json").write_text(
        json.dumps(
            {
                "schema": "story_video_content_profile_v1",
                "rating": "family",
                "activation_status": "active",
                "minimum_viewer_age": 5,
                "policy_profile_id": "family-safe-v1",
                "writer_profile_id": "family-writer-v1",
                "review_profile_id": "family-review-board-v1",
                "provider_capability_status": "available",
            }
        ),
        encoding="utf-8",
    )

    assert _project_content_rating(context) == "family"


def test_audio_director_starts_bound_production_with_canonical_context(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    calls = []

    def starter(active_context):
        calls.append(active_context)
        return {
            "success": True,
            "work_status": "running",
            "process_session_id": "proc-1",
        }

    payload = json.loads(
        story_video_audio_director(
            {"action": "start_production"},
            session_id="session-1",
            store=store,
            production_starter=starter,
        )
    )

    assert calls == [context]
    assert payload["success"] is True
    assert payload["run_id"] == context.run_id
    assert payload["process_session_id"] == "proc-1"


def test_audio_director_does_not_launch_production_during_planning(tmp_path) -> None:
    store, _context = _active_context(tmp_path)
    calls = []

    payload = json.loads(
        story_video_audio_director(
            {"action": "start_production"},
            session_id="session-1",
            store=store,
            production_starter=lambda context: calls.append(context),
        )
    )

    assert calls == []
    assert payload["success"] is False
    assert payload["error_type"] == "production_phase_invalid"


def test_audio_director_default_production_rejects_uncompiled_project(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    store.update(context, phase="voice")

    payload = json.loads(
        story_video_audio_director(
            {"action": "start_production"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] in {
        "story_mode_invalid",
        "dubbing_contract_incomplete",
    }


def test_audio_director_render_resume_does_not_require_dubbing_contract(
    tmp_path, monkeypatch
) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")

    def forbidden_inspection(_project_dir):
        raise DubbingContractError(
            "story_mode_invalid",
            "render resume must not inspect the completed voice contract",
        )

    monkeypatch.setattr(
        "plugins.story_video.tools.inspect_dubbing_project",
        forbidden_inspection,
    )
    monkeypatch.setattr(
        "plugins.story_video.production.start_production",
        lambda active_context: {
            "success": True,
            "work_status": "running",
            "process_session_id": "render-proc",
            "run_id": active_context.run_id,
        },
    )

    payload = json.loads(
        story_video_audio_director(
            {"action": "start_production"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["work_status"] == "running"
    assert payload["run_id"] == context.run_id


def test_audio_director_preserves_failed_production_status(tmp_path) -> None:
    store, _context = _active_context(tmp_path)

    payload = json.loads(
        story_video_audio_director(
            {"action": "production_status"},
            session_id="session-1",
            store=store,
            production_status_reader=lambda _context: {
                "success": False,
                "work_status": "failed",
                "error_type": "render_failed",
                "error": "renderer exited 1",
            },
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "render_failed"


def test_audio_director_binds_three_qwen_voice_actors(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    catalog = _ready_voice_catalog(tmp_path)
    catalog_calls = []

    def catalog_builder(**kwargs):
        catalog_calls.append(kwargs)
        return catalog

    payload = json.loads(
        story_video_audio_director(
            {
                "action": "compile",
                "mode": "creative",
                "source_text": "",
                "speakers": [
                    {
                        "speaker_id": "girl",
                        "display_name": "安安",
                        "role": "lead",
                        "voice_id": "Vivian",
                    },
                    {
                        "speaker_id": "mother",
                        "display_name": "媽媽",
                        "role": "supporting",
                        "voice_id": "Serena",
                    },
                    {
                        "speaker_id": "captain",
                        "display_name": "老船長",
                        "role": "supporting",
                        "voice_id": "Uncle_Fu",
                    },
                ],
                "utterances": [
                    {
                        "utterance_id": "U001",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "girl",
                        "display_text": "我們出發吧！",
                    },
                    {
                        "utterance_id": "U002",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "mother",
                        "display_text": "路上要小心。",
                    },
                    {
                        "utterance_id": "U003",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "captain",
                        "display_text": "風向變了。",
                    },
                ],
            },
            session_id="session-1",
            store=store,
            voice_catalog_builder=catalog_builder,
        )
    )

    assert catalog_calls == [{}]
    assert payload["success"] is True
    assert payload["bound"] is True
    binding = json.loads(
        (context.project_dir / "voice_cast_binding.json").read_text(encoding="utf-8")
    )
    assert binding["catalog_sha256"] == catalog["catalog_sha256"]
    rows = {row["speaker_id"]: row for row in binding["speakers"]}
    assert rows["girl"]["voice_id"] == "qwen_custom_vivian"
    assert rows["mother"]["voice_id"] == "qwen_custom_serena"
    assert rows["captain"]["voice_id"] == "qwen_custom_uncle_fu"
    assert (
        rows["girl"]["engine_binding"]["model_config_path"]
        == catalog["voices"][1]["engine_binding"]["model_config_path"]
    )


def test_story_video_control_lists_voices_without_active_project(tmp_path) -> None:
    registry = _voice_registry(tmp_path, "voice_a", "voice_b", default="voice_b")

    payload = json.loads(
        story_video_control(
            {"action": "list_voices"},
            session_id="no-project",
            store=StoryVideoStateStore(tmp_path / "state"),
            voice_registry_path=registry,
        )
    )

    assert payload["success"] is True
    assert payload["default_profile_id"] == "voice_b"
    assert [row["profile_id"] for row in payload["profiles"]] == [
        "voice_a",
        "voice_b",
    ]


def test_story_video_control_selects_and_reports_project_voice(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    registry = _voice_registry(tmp_path, "voice_a", "voice_b")

    selected = json.loads(
        story_video_control(
            {"action": "select_voice", "voice_id": "voice_b"},
            session_id="session-1",
            store=store,
            voice_registry_path=registry,
        )
    )
    status = json.loads(
        story_video_control(
            {"action": "voice_status"},
            session_id="session-1",
            store=store,
            voice_registry_path=registry,
        )
    )

    assert selected["success"] is True
    assert selected["profile_id"] == "voice_b"
    assert selected["clone_mode"] == "full_icl"
    assert status["bound"] is True
    assert status["integrity"] == "PASS"
    assert status["profile_id"] == "voice_b"
    assert (context.project_dir / "voice_profile_binding.json").is_file()


def test_story_video_control_requires_voice_id_for_selection(tmp_path) -> None:
    store, _context = _active_context(tmp_path)
    registry = _voice_registry(tmp_path, "voice_a")

    payload = json.loads(
        story_video_control(
            {"action": "select_voice"},
            session_id="session-1",
            store=store,
            voice_registry_path=registry,
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "voice_profile_id_required"


def _quality_shots(count: int = 40) -> list[dict]:
    scales = ("close_up", "medium", "wide", "macro", "medium", "insert", "medium", "establishing")
    shots = []
    for index in range(count):
        shot_id = f"S00_SH{index:02d}"
        shots.append(
            {
                "shot_id": shot_id,
                "narration_text": f"第 {index} 個旁白片段",
                "narrative_role": "evidence",
                "viewer_takeaway": "觀眾看懂一個具體證據",
                "subject": "可辨識的主要證據",
                "action": "主體執行與旁白相符的動作",
                "evidence_detail": "關鍵細節清楚可見",
                "shot_scale": scales[index % len(scales)],
                "camera_angle": "eye level",
                "focal_point": "primary evidence",
                "subtitle_safe_area": "bottom 20 percent clear",
                "acceptance_criteria": ["evidence is immediately readable"],
                "risk_class": "high" if index == 0 else "normal",
            }
        )
    return shots


def _write_planning_fixture(context, *, report_status: str = "PASS", shot_count: int = 40) -> dict:
    ensure_explanation_profile(context.project_dir, context.original_request)
    shots = _quality_shots(shot_count)
    ledger = {
        "schema": "story_video_scene_ledger_v2",
        "production_type": "science_explainer",
        "target_duration_sec": 300 if shot_count == 40 else 60,
        "visual_style": "photoreal professional science documentary",
        "scenes": [
            {
                "scene_id": "S00",
                "narrative_role": "evidence",
                "viewer_takeaway": "觀眾看懂一個具體證據",
                "shots": shots,
            }
        ],
    }
    (context.project_dir / "PROJECT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (context.project_dir / "script.md").write_text(
        "### S00\nfinal narration script", encoding="utf-8"
    )
    (context.project_dir / "storyboard.md").write_text("storyboard", encoding="utf-8")
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    (context.project_dir / "production_checklist.json").write_text(
        json.dumps({"quality_mode": "quality_first", "status": "planning"}),
        encoding="utf-8",
    )
    (context.project_dir / "script_quality_report.json").write_text(
        json.dumps(
            {
                "schema": "story_video_script_quality_v1",
                "quality_contract_version": 2,
                "status": report_status,
                "production_type": "science_explainer",
                "shot_count": shot_count,
                "checks": {
                    "visual_evidence": "PASS",
                    "narrative_roles": "PASS",
                    "claim_confidence": "PASS",
                },
            }
        ),
        encoding="utf-8",
    )
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    return ledger


_REVIEWER_IDS = (
    "language_editor",
    "fact_checker",
    "clarity_editor",
    "engagement_editor",
    "audience_safety_editor",
    "performance_editor",
)


def _write_v6_review_fixture(context, *, include_review_artifacts: bool = True) -> dict:
    ledger = _write_planning_fixture(context)
    shots = ledger["scenes"][0]["shots"][:15]
    roles = ("hook", "turn", "payoff", "close", "build", "reveal")
    engagement_roles = ("hook", "build", "reveal", "reaction", "payoff", "breathe")
    energies = ("curious", "tense", "awe", "kinetic", "curious", "calm")
    for index, shot in enumerate(shots):
        shot.update(
            {
                "narration_text": "先看見一個具體線索。再理解它代表的意義。",
                "narrative_role": roles[index % len(roles)],
                "engagement_role": engagement_roles[index % len(engagement_roles)],
                "attention_hook": "先看結果，再追問原因",
                "story_moment": "證據改變了觀眾原本的猜測",
                "action_consequence": "可見線索帶出下一個問題",
                "composition_energy": energies[index % len(energies)],
                "viewer_emotion": "curiosity",
                "engagement_criteria": ["the decisive evidence is readable"],
                "visual_truth_mode": "direct_evidence",
            }
        )
        if shot["engagement_role"] == "breathe":
            shot["calm_reason"] = "讓觀眾消化剛揭示的知識"
    opening = "恐龍最早是怎麼出現的？"
    payoff = "答案藏在化石、骨骼與年代的交叉證據裡。"
    ending = "每一塊化石，都可能讓起源故事再前進一步。"
    script = f"### S00\n{opening}{payoff}{ending}"
    (context.project_dir / "script.md").write_text(script, encoding="utf-8")
    ledger.update(
        {
            "quality_contract_version": 6,
            "target_duration_sec": 300,
            "audience_profile": {
                "age_band": "school_age",
                "minimum_age_years": 5,
                "knowledge_level": "newcomer",
                "attention_style": "curious_explorer",
                "safety_intensity": "gentle",
            },
            "engagement_profile": {
                "mode": "young_explorer",
                "energy": "high",
                "humor": "light",
                "sensationalism_forbidden": True,
            },
            "story_engine": {
                "audience_promise": "把陌生科學變成一場可以跟上的發現",
                "opening_question": opening,
                "dramatic_question": "哪些證據能排除看似合理的猜測？",
                "curiosity_gap": "最早期化石仍留下哪些空白？",
                "escalation": ["先看年代", "再比骨骼", "最後交叉驗證"],
                "knowledge_payoff": payoff,
                "ending_echo": ending,
                "humor_strategy": "用輕巧比喻舒緩資訊密度，不改寫事實",
            },
            "style_bible": {
                "style_id": "cinematic-science-v1",
                "anchor_shot_id": shots[0]["shot_id"],
                "medium": "camera-real cinematic factual reconstruction",
                "palette": "natural earth tones with selective vivid accents",
                "lighting": "dramatic motivated natural light",
                "lens_language": "layered depth with evidence-led close views",
                "texture": "tactile rock, bone, skin, and atmosphere",
                "atmosphere": "curious, urgent, and credible",
                "subject_treatment": "hero evidence remains dominant and factual",
                "forbidden_drift": ["flat museum catalog framing"],
            },
            "music_direction": {
                "schema": "story_video_music_direction_v1",
                "moods": ["discovery", "wonder", "mystery", "resolution"],
                "instruments": ["marimba", "bells", "warm pads"],
                "excluded_styles": ["aggressive drums", "trailer braam"],
                "energy_curve": {
                    "opening": "high",
                    "body": "balanced",
                    "payoff": "high",
                    "ending": "gentle",
                },
                "narration_priority": True,
                "min_cue_variants": 3,
            },
        }
    )
    ledger["scenes"][0]["shots"] = shots
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
    )
    script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()
    quality_report = {
        "schema": "story_video_script_quality_v1",
        "quality_contract_version": 6,
        "status": "PASS",
        "production_type": "science_explainer",
        "shot_count": len(shots),
        "final_script_sha256": script_sha,
        "checks": {
            "visual_evidence": "PASS",
            "narrative_roles": "PASS",
            "claim_confidence": "PASS",
            "audience_engagement": "PASS",
            "visual_truth": "PASS",
            "child_curiosity": "PASS",
            "dramatic_arc": "PASS",
            "read_aloud_liveliness": "PASS",
            "knowledge_integrity": "PASS",
            "visual_causality": "PASS",
            "style_consistency": "PASS",
            "language_fluency": "PASS",
            "factual_integrity": "PASS",
            "clarity_concision": "PASS",
            "engagement": "PASS",
            "audience_fit": "PASS",
            "read_aloud_performance": "PASS",
        },
    }
    (context.project_dir / "script_quality_report.json").write_text(
        json.dumps(quality_report), encoding="utf-8"
    )
    if include_review_artifacts:
        content_profile = {
            "schema": "story_video_content_profile_v1",
            "rating": "family",
            "activation_status": "active",
            "minimum_viewer_age": 5,
            "policy_profile_id": "family-safe-v1",
            "writer_profile_id": "taiwan-childrens-story-writing-v1",
            "review_profile_id": "family-review-board-v1",
            "provider_capability_status": "available",
            "explanation_profile_id": ACCESSIBLE_EXPLAINER_PROFILE_ID,
            "explanation_mode": "accessible",
            "supplemental_writer_profile_ids": [ACCESSIBLE_EXPLAINER_PROFILE_ID],
        }
        reviewers = [
            {
                "reviewer_id": reviewer_id,
                "status": "PASS",
                "score": 90,
                "findings": [],
                "evidence_source_ids": (
                    ["nhm-dinosaur-origins"] if reviewer_id == "fact_checker" else []
                ),
                "verified_claim_ids": (
                    ["C001"] if reviewer_id == "fact_checker" else []
                ),
                "claim_coverage_status": (
                    "PASS" if reviewer_id == "fact_checker" else ""
                ),
                "coverage_verified_segment_ids": (
                    ["S00"] if reviewer_id == "fact_checker" else []
                ),
            }
            for reviewer_id in _REVIEWER_IDS
        ]
        reviewers.append(
            {
                "reviewer_id": "newcomer_comprehension_editor",
                "status": "PASS",
                "score": 92,
                "findings": [],
            }
        )
        review_report = {
            "schema": "story_video_script_review_v1",
            "quality_contract_version": 6,
            "status": "PASS",
            "execution_mode": "structured_board",
            "revision_round_count": 1,
            "reviewers": reviewers,
            "adjudication": {
                "status": "PASS",
                "resolved_finding_ids": [],
                "unresolved_finding_ids": [],
            },
            "final_verification": {
                "status": "PASS",
                "final_script_sha256": script_sha,
            },
            "accessibility_metrics": {
                "schema": "story_video_accessibility_metrics_v1",
                "status": "PASS",
                "unexplained_jargon": [],
                "baby_talk_detected": False,
                "precision_loss_detected": False,
                "concept_bridges": [
                    {
                        "term": "交叉證據",
                        "segment_id": "S00",
                        "concrete_anchor": "化石、骨骼與年代被放在一起比對",
                        "plain_explanation": "不同線索互相支持，答案才更可靠",
                        "precision_boundary": "新證據仍可能修正目前的結論",
                    }
                ],
            },
        }
        (context.project_dir / "content_profile.json").write_text(
            json.dumps(content_profile), encoding="utf-8"
        )
        (context.project_dir / "script_review_report.json").write_text(
            json.dumps(review_report), encoding="utf-8"
        )
        (context.project_dir / "factual_evidence.json").write_text(
            json.dumps(
                {
                    "schema": "story_video_factual_evidence_v1",
                    "status": "PASS",
                    "sources": [
                        {
                            "source_id": "nhm-dinosaur-origins",
                            "title": "What were the first dinosaurs?",
                            "publisher": "Natural History Museum",
                            "url": "https://www.nhm.ac.uk/discover/what-were-the-first-dinosaurs.html",
                            "source_type": "official",
                            "accessed_at": "2026-07-19",
                        }
                    ],
                    "claims": [
                        {
                            "claim_id": "C001",
                            "segment_id": "S00",
                            "quote": payoff,
                            "importance": "central",
                            "confidence": "established",
                            "source_ids": ["nhm-dinosaur-origins"],
                            "verification_status": "verified",
                            "verification_note": "The source describes fossil, skeletal, and dating evidence.",
                        }
                    ],
                    "nonfactual_segments": [],
                }
            ),
            encoding="utf-8",
        )
    return ledger


def _write_candidate_manifest(context, shots: list[dict]) -> None:
    outputs = []
    for index, shot in enumerate(shots):
        shot_id = shot["shot_id"]
        image = context.project_dir / "images" / f"{shot_id}.png"
        prompt = context.project_dir / "prompts" / f"{shot_id}.txt"
        image.parent.mkdir(parents=True, exist_ok=True)
        prompt.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(f"selected-{shot_id}".encode())
        prompt.write_text(f"prompt for {shot_id}", encoding="utf-8")
        shot["selected_asset_path"] = str(image.relative_to(context.project_dir))
        outputs.append(
            {
                "shot_id": shot_id,
                "shot_scale": shot["shot_scale"],
                "selected": True,
                "status": "selected_current",
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
                "prompt_path": str(prompt.relative_to(context.project_dir)),
                "local_path": str(image.relative_to(context.project_dir)),
                "quality_score": 88,
                "hard_blockers": [],
                "vision_evidence": {"status": "PASS", "response_id": f"resp_{index}"},
            }
        )
    path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "story_video_shot_candidate_manifest_v1",
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
                "quality_threshold": 80,
                "outputs": outputs,
            }
        ),
        encoding="utf-8",
    )


def _write_render_fixture(
    context,
    *,
    hard_burned: bool = True,
    motion_policy: str = "stable center zoom 1.0 -> 1.025",
) -> None:
    output = context.project_dir / "renders" / "final.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"rendered video")
    manifest = {
        "cards": {
            "opening": {"status": "PASS", "duration_sec": 3.0},
            "ending": {"status": "PASS", "duration_sec": 4.0},
        },
        "timeline": {
            "motion_policy": motion_policy,
            "selected_shot_count": 8,
            "shot_density_status": "PASS",
        },
        "output": {
            "path": "renders/final.mp4",
            "subtitles": {"hard_burned": hard_burned},
        },
        "qc_report": "render_qc.json",
    }
    for path in (
        context.project_dir / "render_manifest.json",
        context.project_dir / "manifests" / "render_manifest.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
    (context.project_dir / "render_qc.json").write_text(
        json.dumps(
            {
                "visual_source_contract": {"provider_qc": "PASS"},
                "artifact_quality_evidence": {
                    "caption_visibility": {
                        "status": "PASS",
                        "hard_burned": hard_burned,
                    },
                    "motion": {"status": "PASS"},
                    "shot_density": {
                        "status": "PASS",
                        "selected_shot_count": 8,
                    },
                    "title_cards": {
                        "status": "PASS",
                        "opening": True,
                        "ending": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_planning_validation_blocks_with_exact_missing_artifacts(tmp_path) -> None:
    _store, context = _active_context(tmp_path)

    proof = validate_phase(context)

    assert proof.ok is False
    assert "storyboard.md" in proof.missing
    assert "scene_ledger.json" in proof.missing
    assert proof.marker == "STORY_VIDEO_PHASE_PROOF: planning BLOCKED"


def test_planning_validation_passes_and_advances_to_keyframes(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    _write_planning_fixture(context)

    proof = validate_phase(context)
    result = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-1",
            store=store,
        )
    )

    assert proof.ok is True
    assert proof.marker == "STORY_VIDEO_PHASE_PROOF: planning PASS"
    assert result["success"] is True
    assert result["proof"] == "STORY_VIDEO_PHASE_PROOF: planning PASS"
    assert store.for_session("session-1").phase == "keyframes"
    assert result["next_call"] == "繼續"


def test_planning_validation_fails_closed_without_explanation_profile(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "explanation_profile.json").unlink()

    proof = validate_phase(context)

    assert proof.ok is False
    assert "explanation_profile.json" in proof.missing


def test_planning_validation_fails_closed_for_non_object_explanation_profile(
    tmp_path,
) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "explanation_profile.json").write_text(
        "[]\n", encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "explanation_profile.json root is not an object" in proof.violations


def test_explicit_autopilot_authorization_advances_a_planning_only_hold(
    tmp_path,
) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call(
        "故事影片：泡泡為什麼是圓的｜30秒｜電影感。只規劃。"
    )
    assert start is not None
    context = store.create_or_load(
        source_key="source-planning-hold",
        session_id="session-planning",
        call=start,
        original_request="故事影片：泡泡為什麼是圓的｜30秒｜電影感。只規劃。",
    )
    _write_planning_fixture(context)

    held = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-planning",
            store=store,
        )
    )
    assert held["phase"] == "planning"
    assert held["status"] == "complete"

    authorize = parse_operator_call("全自動", has_active_project=True)
    assert authorize is not None
    resumed = store.create_or_load(
        source_key="source-planning-hold",
        session_id="session-production",
        call=authorize,
        original_request="全自動",
    )
    assert resumed.auto_mode is True
    assert resumed.status == "active"

    advanced = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-production",
            store=store,
        )
    )

    assert advanced["success"] is True
    assert advanced["phase"] == "keyframes"
    assert advanced["status"] == "active"
    assert store.for_session("session-production").phase == "keyframes"


def test_planning_validation_rejects_missing_or_failed_script_quality(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context, report_status="BLOCKED")

    blocked = validate_phase(context)
    (context.project_dir / "script_quality_report.json").unlink()
    missing = validate_phase(context)

    assert blocked.ok is False
    assert "script_quality_report.status=BLOCKED" in blocked.violations
    assert "script_quality_report.json" in missing.missing


def test_planning_validation_requires_v5_script_report_for_v5_ledger(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    ledger = _write_planning_fixture(context)
    ledger["quality_contract_version"] = 5
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert "script_quality_report.quality_contract_version<5" in proof.violations


def test_v6_review_board_requires_new_planning_artifacts(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context, include_review_artifacts=False)

    proof = validate_phase(context)

    assert proof.ok is False
    assert "content_profile.json" in proof.missing
    assert "script_review_report.json" in proof.missing


def test_v6_review_board_accepts_complete_review_bundle(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)

    proof = validate_phase(context)

    assert proof.ok is True


def test_v6_factual_review_requires_factual_evidence_artifact(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    (context.project_dir / "factual_evidence.json").unlink()

    proof = validate_phase(context)

    assert proof.ok is False
    assert "factual_evidence.json is missing" in proof.violations


def test_v6_factual_review_rejects_unbound_source_ids(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "factual_evidence.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["claims"][0]["source_ids"] = ["invented-source"]
    path.write_text(json.dumps(evidence), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert (
        "factual_evidence claim C001 references unknown source: invented-source"
        in proof.violations
    )


def test_v6_factual_review_handles_nonlist_reviewers_without_crashing(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "script_review_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["reviewers"] = None
    path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report reviewers are not a list" in proof.violations
    assert "script_review_report fact_checker is missing" in proof.violations


def test_v6_editorial_profile_requires_evidence_bound_metrics(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    profile_path = context.project_dir / "content_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["review_profile_id"] = "family-review-board-v2"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report editorial_metrics is missing" in proof.violations


def test_v6_editorial_profile_v3_requires_script_bound_narrative_dynamics(
    tmp_path,
) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    profile_path = context.project_dir / "content_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["review_profile_id"] = "story-video-review-board-v3"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report editorial_metrics is missing" in proof.violations
    assert "script_review_report narrative_dynamics is missing" in proof.violations


def test_v6_editorial_profile_accepts_complete_metrics(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    profile_path = context.project_dir / "content_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["review_profile_id"] = "family-review-board-v2"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    report_path = context.project_dir / "script_review_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["editorial_metrics"] = {
        "schema": "story_video_editorial_metrics_v1",
        "concrete_scene_evidence": [
            {
                "segment_id": "S00",
                "subject": "化石證據",
                "action": "線索被逐項比對",
                "sensory_detail": "骨骼與岩層清楚可見",
                "stakes_or_question": "哪些證據能排除猜測",
            }
        ],
        "abstract_only_segment_ids": [],
        "curiosity_loop_evidence": [
            {
                "loop_id": f"Q{index}",
                "opening_segment_id": "S00",
                "payoff_segment_id": "S00",
                "question": "一個具體問題",
                "payoff": "一個具體答案",
                "status": "resolved",
            }
            for index in range(1, 6)
        ],
        "delight_beat_evidence": [
            {"segment_id": "S00", "beat_type": "surprise", "text": "意外線索"},
            {"segment_id": "S00", "beat_type": "reveal", "text": "知識揭曉"},
        ],
        "emotional_turn_evidence": [
            {
                "segment_id": "S00",
                "from_state": before,
                "to_state": after,
                "cause": "新證據改變理解",
            }
            for before, after in (
                ("curiosity", "surprise"),
                ("surprise", "doubt"),
                ("doubt", "awe"),
            )
        ],
        "rhetorical_template_evidence": [],
        "reported_read_aloud_metrics": {
            "sentence_count": 3,
            "long_sentence_ratio": 0.0,
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is True


def test_v6_editorial_profile_requires_valid_music_direction(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    ledger = _write_v6_review_fixture(context)
    profile_path = context.project_dir / "content_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["review_profile_id"] = "family-review-board-v2"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    ledger["music_direction"]["narration_priority"] = False
    ledger["music_direction"]["min_cue_variants"] = 1
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert "music_direction narration_priority must be true" in proof.violations
    assert "music_direction min_cue_variants<3" in proof.violations


def test_v6_review_board_blocks_low_reviewer_score(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "script_review_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["reviewers"][0]["score"] = 84
    path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report reviewer language_editor score<85" in proof.violations


def test_v6_review_board_blocks_duplicate_and_missing_reviewers(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "script_review_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    performance_index = next(
        index
        for index, reviewer in enumerate(report["reviewers"])
        if reviewer["reviewer_id"] == "performance_editor"
    )
    report["reviewers"][performance_index] = dict(report["reviewers"][0])
    path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report duplicate reviewer: language_editor" in proof.violations
    assert "script_review_report missing reviewer: performance_editor" in proof.violations


def test_v6_review_board_blocks_unresolved_critical_finding(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "script_review_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["reviewers"][1]["findings"] = [
        {
            "finding_id": "F001",
            "severity": "critical",
            "location": "S00",
            "category": "factual_accuracy",
            "evidence": "The claim overstates the available fossil evidence.",
            "recommendation": "State the uncertainty explicitly.",
            "resolution_status": "unresolved",
        }
    ]
    report["adjudication"]["unresolved_finding_ids"] = ["F001"]
    path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report unresolved critical finding: F001" in proof.violations


def test_v6_review_board_requires_adjudication_for_every_finding(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "script_review_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["reviewers"][0]["findings"] = [
        {
            "finding_id": "LANG-001",
            "severity": "moderate",
            "location": "S00",
            "category": "fluency",
            "evidence": "The transition is grammatically valid but unnatural.",
            "recommendation": "Replace it with natural Taiwan usage.",
            "resolution_status": "resolved",
        }
    ]
    path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report adjudication omits finding: LANG-001" in proof.violations


def test_v6_review_board_binds_review_to_final_script_bytes(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    script_path = context.project_dir / "script.md"
    script_path.write_text(
        script_path.read_text(encoding="utf-8") + "\n未經審核的新句子。",
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report final_script_sha256 mismatch" in proof.violations
    assert "script_quality_report final_script_sha256 mismatch" in proof.violations


def test_v6_fact_checker_requires_sources_for_science_production(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "script_review_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["reviewers"][1]["evidence_source_ids"] = []
    path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report fact_checker evidence_source_ids are missing" in proof.violations


def test_v6_adult_explicit_profile_is_reserved_setup_required(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "content_profile.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile.update(
        {
            "rating": "adult_explicit",
            "activation_status": "active",
            "minimum_viewer_age": 18,
            "policy_profile_id": "adult-reserved-v1",
            "writer_profile_id": "adult-writer-reserved",
            "review_profile_id": "adult-review-reserved",
            "provider_capability_status": "available",
        }
    )
    path.write_text(json.dumps(profile), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "content_profile rating adult_explicit SETUP_REQUIRED" in proof.violations


def test_planning_validation_requires_the_final_script_artifact(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "script.md").unlink()

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script.md" in proof.missing


def test_planning_validation_requires_voice_compatible_script_headings(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "script.md").write_text(
        "### Shot 01\n三疊紀。", encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script.md requires ### S00-style narration headings" in proof.violations


def test_planning_validation_rejects_spoken_alias_leakage_into_script(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "script.md").write_text(
        "### S00\n恐龍最早出現在三碟紀。", encoding="utf-8"
    )
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [
                    {
                        "display": "三疊紀",
                        "spoken": "三碟紀",
                        "expected_pinyin": "san1 die2 ji4",
                        "source": "taiwan_mandarin_review",
                        "risk": "high",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script.md contains spoken alias for high-risk term: 三疊紀" in proof.violations


def test_planning_validation_requires_pronunciation_lexicon(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "pronunciation_lexicon.json").unlink()

    blocked = validate_phase(context)

    assert blocked.ok is False
    assert "pronunciation_lexicon.json" in blocked.missing

    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    passed = validate_phase(context)

    assert passed.ok is True


def test_planning_validation_rejects_unchanged_high_risk_pronunciation_alias(
    tmp_path,
) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    lexicon = {
        "schema": "story_video_pronunciation_lexicon_v1",
        "language": "zh-TW",
        "review_status": "PASS",
        "entries": [
            {
                "display": "三疊紀",
                "spoken": "三疊紀",
                "expected_pinyin": "san1 die2 ji4",
                "source": "taiwan_mandarin_review",
                "risk": "high",
            }
        ],
    }
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(lexicon, ensure_ascii=False), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert (
        "pronunciation_lexicon entry[0] high-risk spoken alias is unchanged"
        in proof.violations
    )


def test_planning_validation_accepts_corrected_high_risk_pronunciation_alias(
    tmp_path,
) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    lexicon = {
        "schema": "story_video_pronunciation_lexicon_v1",
        "language": "zh-TW",
        "review_status": "PASS",
        "entries": [
            {
                "display": "三疊紀",
                "spoken": "三碟紀",
                "expected_pinyin": "san1 die2 ji4",
                "source": "taiwan_mandarin_review",
                "risk": "high",
            }
        ],
    }
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(lexicon, ensure_ascii=False), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_planning_validation_rejects_shallow_scene_ledger(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    _write_planning_fixture(context)
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(
            {
                "production_type": "science_explainer",
                "target_duration_sec": 300,
                "scenes": [{"scene_id": "S00", "viewer_takeaway": "too shallow"}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "S00.shots" in proof.violations


def test_planning_validation_enforces_v3_engagement_fields(tmp_path) -> None:
    _store, context = _active_context(tmp_path)
    ledger = _write_planning_fixture(context)
    roles = ("hook", "build", "reveal", "reaction", "payoff", "breathe")
    energies = ("curious", "tense", "awe", "kinetic", "curious", "calm")
    ledger.update(
        {
            "quality_contract_version": 3,
            "audience_profile": {
                "age_band": "general",
                "knowledge_level": "newcomer",
                "attention_style": "curious_explorer",
                "safety_intensity": "standard",
            },
            "engagement_profile": {
                "mode": "discovery_documentary",
                "energy": "balanced",
                "humor": "none",
                "sensationalism_forbidden": True,
            },
        }
    )
    for index, shot in enumerate(ledger["scenes"][0]["shots"]):
        shot.update(
            {
                "engagement_role": roles[index % len(roles)],
                "attention_hook": "先看見結果，再追問原因",
                "story_moment": "主體完成一個可見動作",
                "action_consequence": "動作留下可辨識結果",
                "composition_energy": energies[index % len(energies)],
                "viewer_emotion": "curiosity",
                "engagement_criteria": ["the decisive instant is readable"],
                "visual_truth_mode": "direct_evidence",
            }
        )
        if shot["engagement_role"] == "breathe":
            shot["calm_reason"] = "讓觀眾消化剛揭示的內容"
    del ledger["scenes"][0]["shots"][0]["story_moment"]
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "S00_SH00.story_moment" in proof.violations


def test_control_status_returns_active_project_and_policy(tmp_path) -> None:
    store, context = _active_context(tmp_path)

    result = json.loads(
        story_video_control(
            {"action": "status"},
            session_id="session-1",
            store=store,
        )
    )

    assert result["success"] is True
    assert result["project_dir"] == str(context.project_dir)
    assert result["phase"] == "planning"
    assert result["provider_policy"]["image"] == ["openai", "openai-codex"]
    assert result["provider_policy"]["tts"] == ["local-qwen"]


def test_control_without_active_session_fails_closed(tmp_path) -> None:
    result = json.loads(
        story_video_control(
            {"action": "status"},
            session_id="missing",
            store=StoryVideoStateStore(tmp_path),
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "story_video_context_missing"


def test_blocked_validation_sets_repair_next_call(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    (context.project_dir / "PROJECT_CONTRACT.md").write_text(
        "contract", encoding="utf-8"
    )

    result = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-1",
            store=store,
        )
    )

    assert result["success"] is False
    assert result["next_call"].startswith("修正：")
    assert "script.md" in result["next_call"]
    assert store.for_session("session-1").repair_request


def test_keyframe_validation_requires_selected_openai_provenance(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="keyframes")
    ledger = _write_planning_fixture(context)
    shots = ledger["scenes"][0]["shots"][:3]
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "openai-codex",
                "outputs": [
                    {"shot_id": shot["shot_id"], "selected": True}
                    for shot in shots
                ],
            }
        ),
        encoding="utf-8",
    )

    blocked = validate_phase(context)
    _write_candidate_manifest(context, shots)
    passed = validate_phase(context)

    assert blocked.ok is False
    assert "selected keyframe missing OpenAI vision score evidence" in blocked.violations
    assert passed.ok is True


def test_story_video_control_synchronizes_candidate_manifest_phase(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"phase": "keyframes", "outputs": []}),
        encoding="utf-8",
    )

    story_video_control(
        {"action": "status"},
        session_id="session-1",
        store=store,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "batch"


def test_keyframe_validation_rejects_noncanonical_nested_candidate_manifest(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="keyframes")
    ledger = _write_planning_fixture(context)
    shot = ledger["scenes"][0]["shots"][0]
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "openai-codex",
                "judge_provider": "openai-codex",
                "shots": [
                    {
                        "shot_id": shot["shot_id"],
                        "candidates": [{"selected": True, "judge_score": 80}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert (
        "shot candidate manifest must contain canonical outputs[] from "
        "story_video_quality_control"
    ) in proof.violations


def test_keyframe_accepts_nonempty_openai_chat_completion_response_id(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="keyframes")
    ledger = _write_planning_fixture(context)
    shots = ledger["scenes"][0]["shots"][:3]
    _write_candidate_manifest(context, shots)
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for output in manifest["outputs"]:
        output["vision_evidence"]["response_id"] = "chatcmpl_openai_story_judge"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is True


def test_batch_validation_accepts_scene_ledger_selected_asset_path(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    _write_candidate_manifest(context, shots)
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_batch_editorial_v2_requires_current_sequence_quality_report(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    _write_candidate_manifest(context, shots)
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    (context.project_dir / "content_profile.json").write_text(
        json.dumps({"review_profile_id": "family-review-board-v2"}), encoding="utf-8"
    )

    missing = validate_phase(context)

    assert "manifests/sequence_quality_report.json" in missing.missing

    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    shots_by_id = {shot["shot_id"]: shot for shot in shots}
    for output in manifest["outputs"]:
        shot = shots_by_id[output["shot_id"]]
        image = context.project_dir / output["local_path"]
        output.update(
            {
                "artifact_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "shot_contract_hash": shot_contract_hash(shot),
                "quality_dimensions": {
                    "text_alignment": 90,
                    "evidence_specificity": 90,
                    "narrative_engagement": 90,
                    "story_moment_clarity": 90,
                    "cinematic_impact": 90,
                    "professional_quality": 90,
                    "style_consistency": 90,
                },
            }
        )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    write_sequence_quality_report(context.project_dir, ledger, manifest)

    passed = validate_phase(context)

    assert passed.ok is True


def test_batch_autopilot_promotes_legacy_scale_repeat_reason_and_transitions(
    tmp_path,
) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch", auto_mode=True)
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    for shot in shots[1:4]:
        shot["shot_scale"] = "medium"
    shots[3]["scale_repetition_reason"] = (
        "Keep equal visual weight while comparing three adjacent subjects."
    )
    _write_candidate_manifest(context, shots)
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    payload = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-1",
            store=store,
        )
    )

    assert payload["success"] is True
    assert payload["proof"] == "STORY_VIDEO_PHASE_PROOF: batch PASS"
    assert payload["phase"] == "voice"
    repaired = json.loads(
        (context.project_dir / "scene_ledger.json").read_text(encoding="utf-8")
    )
    assert repaired["scenes"][0]["shots"][3][
        "intentional_scale_repeat_reason"
    ] == shots[3]["scale_repetition_reason"]


def test_legacy_replan_composition_energy_normalization_is_bounded_and_audited(
    tmp_path,
) -> None:
    from plugins.story_video.sequence_quality import validate_sequence_quality_report
    from plugins.story_video.tools import _promote_legacy_replan_composition_energies

    _store, context = _active_context(tmp_path)
    context = _store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shot = ledger["scenes"][0]["shots"][3]
    shot.update(
        {
            "engagement_role": "reveal",
            "composition_energy": "果斷、緊迫但受控",
        }
    )
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    old_hash = shot_contract_hash(shot)
    row = {
        "shot_id": shot["shot_id"],
        "candidate_id": f"{shot['shot_id']}_C01",
        "selected": True,
        "status": "selected_current",
        "shot_contract_hash": old_hash,
    }
    manifest = {
        "outputs": [dict(row)],
        "attempt_history": [dict(row)],
        "contract_replans": [
            {
                "event": "shot_contract_replanned",
                "shot_id": shot["shot_id"],
                "new_shot_contract_hash": old_hash,
            }
        ],
    }
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    write_sequence_quality_report(context.project_dir, ledger, manifest)

    migrated = _promote_legacy_replan_composition_energies(context)

    assert migrated == (shot["shot_id"],)
    repaired_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    repaired_shot = repaired_ledger["scenes"][0]["shots"][3]
    assert repaired_shot["composition_energy"] == "tense"
    new_hash = shot_contract_hash(repaired_shot)
    assert new_hash != old_hash
    repaired_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert repaired_manifest["outputs"][0]["shot_contract_hash"] == new_hash
    assert repaired_manifest["attempt_history"][0]["shot_contract_hash"] == new_hash
    replan = repaired_manifest["contract_replans"][0]
    assert replan["new_shot_contract_hash"] == new_hash
    assert replan["legacy_generated_shot_contract_hash"] == old_hash
    event = repaired_manifest["contract_events"][-1]
    assert event["event"] == "legacy_composition_energy_normalized"
    assert event["old_composition_energy"] == "果斷、緊迫但受控"
    assert event["new_composition_energy"] == "tense"
    assert event["old_shot_contract_hash"] == old_hash
    assert event["new_shot_contract_hash"] == new_hash
    report = json.loads(
        (context.project_dir / "manifests" / "sequence_quality_report.json").read_text(
            encoding="utf-8"
        )
    )
    report_violations = validate_sequence_quality_report(
        context.project_dir,
        repaired_ledger,
        repaired_manifest,
        report,
    )
    assert "sequence_quality_report is stale or does not match current artifacts" not in (
        report_violations
    )
    assert _promote_legacy_replan_composition_energies(context) == ()


def test_legacy_replan_energy_normalizer_covers_observed_free_text_shapes() -> None:
    from plugins.story_video.tools import _canonical_legacy_composition_energy

    observed = {
        "precise_lock_in": "tense",
        "由左下向右上的單一強勁動線，能量集中在蜂鳥的振翅爬升": "kinetic",
        "視線由汗濕髮際沿臉部集中到嘴邊水杯，形成克制而明確的單一動作動線": "calm",
        "果斷、緊迫但受控": "tense",
    }

    assert {
        value: _canonical_legacy_composition_energy(value, engagement_role="reveal")
        for value in observed
    } == observed


def test_legacy_composition_energy_without_matching_replan_is_not_rewritten(
    tmp_path,
) -> None:
    from plugins.story_video.tools import _promote_legacy_replan_composition_energies

    _store, context = _active_context(tmp_path)
    ledger = _write_planning_fixture(context, shot_count=8)
    shot = ledger["scenes"][0]["shots"][3]
    shot["composition_energy"] = "user-authored custom energy"
    ledger_path = context.project_dir / "scene_ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    assert _promote_legacy_replan_composition_energies(context) == ()
    unchanged = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert unchanged["scenes"][0]["shots"][3]["composition_energy"] == (
        "user-authored custom energy"
    )


def test_batch_validation_rejects_selected_asset_from_superseded_shot_contract(
    tmp_path,
) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    _write_candidate_manifest(context, shots)
    shots[0]["shot_scale"] = "macro"
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert f"{shots[0]['shot_id']} selected candidate uses superseded shot contract" in (
        proof.violations
    )


def test_batch_validation_rejects_missing_and_duplicate_selected_shots(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="batch")
    ledger = _write_planning_fixture(context, shot_count=8)
    shots = ledger["scenes"][0]["shots"]
    _write_candidate_manifest(context, shots[:-1])
    duplicate = context.project_dir / "images" / f"{shots[0]['shot_id']}.png"
    shots[1]["selected_asset_path"] = str(duplicate.relative_to(context.project_dir))
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert f"{shots[-1]['shot_id']}.selected_asset" in proof.missing
    assert "duplicate selected asset files" in proof.violations


def test_voice_validation_rejects_local_macos_timing_draft(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    audio = context.project_dir / "audio" / "S00.aiff"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"local draft audio")
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "local",
                "engine": "macOS say",
                "voice": "Meijia",
                "rate": 60,
                "outputs": [{"scene_id": "S00", "audio": str(audio)}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "production narration provider is local, expected local-qwen" in proof.violations


def test_voice_validation_accepts_v4_and_verifies_v5_voice_binding(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"local qwen production audio")
    profile = context.project_dir / "voice_profiles" / "simon_primary.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps(
            {
                "profile_id": "simon_primary",
                "status": "locked_by_user",
                "provider": "local_qwen",
            }
        ),
        encoding="utf-8",
    )
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    pronunciation_path = context.project_dir / "qc" / "pronunciation_qc_report.json"
    pronunciation_path.parent.mkdir(parents=True)
    pronunciation_path.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v3",
                "run_id": context.run_id,
                "status": "PASS",
                "language": "zh-TW",
                "method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
                "checked_unit": "voice_chunk",
                "applied_entries": [
                    {
                        "display": "三疊紀",
                        "spoken": "三碟紀",
                        "expected_pinyin": "san1 die2 ji4",
                        "risk": "high",
                    }
                ],
                "acoustic_evidence": [
                    {
                        "shot_id": "S00_SH00",
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "term_checks": [
                            {
                                "display": "三疊紀",
                                "status": "PASS",
                                "method": "forced_alignment_isolated_term_asr",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "story_video_narration_manifest_v4",
                "provider": "local_qwen",
                "engine": "Qwen3-TTS via MLX-Audio",
                "language": "zh-TW",
                "voice_role": "narrator",
                "voice": "simon_primary",
                "rate": "1.06x",
                "profile_status": "locked_by_user",
                "voice_contract_status": "PASS",
                "voice_profile": str(profile),
                "model": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
                "inference_mode": "offline",
                "network_fallback": "forbidden",
                "pronunciation_status": "PASS",
                "alignment_status": "PASS",
                "prosody_status": "PASS",
                "voice_segmentation": "sentence_chunks_v1",
                "voice_chunk_count": 1,
                "outputs": [
                    {
                        "scene_id": "S00",
                        "audio": str(audio),
                        "display_text": "三疊紀。",
                        "spoken_text": "三碟紀。",
                        "pronunciation_status": "PASS",
                        "segments": [
                            {
                                "shot_id": "S00_SH00",
                                "timeline_duration_sec": 1.25,
                                "alignment_status": "PASS",
                                "pronunciation_status": "PASS",
                                "prosody_status": "PASS",
                                "voice_chunks": [
                                    {
                                        "voice_chunk_id": "S00_SH00__C01",
                                        "display_text": "三疊紀。",
                                        "start_sec": 0.0,
                                        "speech_end_sec": 1.07,
                                        "alignment_status": "PASS",
                                        "pronunciation_status": "PASS",
                                        "prosody_status": "PASS",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True

    binding = context.project_dir / "voice_profile_binding.json"
    binding.write_text(
        json.dumps(
            {
                "schema": "story_video_voice_profile_binding_v1",
                "voice_role": "narrator",
                "profile_id": "simon_primary",
                "profile_path": str(profile),
                "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
                "clone_mode": "full_icl",
                "language_policy": "zh-TW",
                "status": "locked",
            }
        ),
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "schema": "story_video_narration_manifest_v5",
            "voice_profile_id": "simon_primary",
            "voice_profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
            "voice_profile_binding": str(binding),
            "voice_profile_binding_sha256": hashlib.sha256(
                binding.read_bytes()
            ).hexdigest(),
            "clone_mode": "full_icl",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert validate_phase(context).ok is True

    external_binding = tmp_path / "external_voice_profile_binding.json"
    external_binding.write_bytes(binding.read_bytes())
    manifest["voice_profile_binding"] = str(external_binding)
    manifest["voice_profile_binding_sha256"] = hashlib.sha256(
        external_binding.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    external = validate_phase(context)
    assert external.ok is False
    assert "local Qwen voice profile binding is not project-local" in external.violations

    manifest["voice_profile_binding"] = str(binding)
    manifest["voice_profile_binding_sha256"] = hashlib.sha256(
        binding.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    profile.write_text('{"profile_id":"changed"}', encoding="utf-8")
    drifted = validate_phase(context)

    assert drifted.ok is False
    assert "local Qwen voice profile hash does not match project binding" in drifted.violations

    pronunciation_report = json.loads(pronunciation_path.read_text(encoding="utf-8"))
    pronunciation_report["method"] = "sentence_chunk_lexicon_plus_independent_asr"
    pronunciation_path.write_text(json.dumps(pronunciation_report), encoding="utf-8")
    legacy_method = validate_phase(context)

    assert legacy_method.ok is False
    assert (
        "local Qwen acoustic pronunciation QC lacks isolated term ASR"
        in legacy_method.violations
    )

    pronunciation_report["method"] = (
        "sentence_chunk_plus_forced_alignment_isolated_term_asr"
    )
    pronunciation_path.write_text(json.dumps(pronunciation_report), encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"][0]["segments"][0]["voice_chunks"][0][
        "pronunciation_status"
    ] = "FAIL"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    failed_chunk = validate_phase(context)

    assert failed_chunk.ok is False
    assert (
        "audio narration segment[0].segments[0].voice_chunks[0] pronunciation is not PASS"
        in failed_chunk.violations
    )

    manifest["outputs"][0]["segments"][0]["voice_chunks"][0][
        "pronunciation_status"
    ] = "PASS"
    manifest["outputs"][0]["segments"][0]["prosody_status"] = "FAIL"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    failed = validate_phase(context)

    assert failed.ok is False
    assert (
        "audio narration segment[0].segments[0] prosody is not PASS"
        in failed.violations
    )


def test_voice_validation_verifies_v6_multi_character_routing_and_hashes(
    tmp_path,
) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"multi-character-production-audio")
    profiles = []
    for profile_id in ("simon@v1", "hero@v1"):
        profile = context.project_dir / "voice_profiles" / profile_id / "profile.json"
        profile.parent.mkdir(parents=True)
        profile.write_text(
            json.dumps(
                {
                    "profile_id": profile_id,
                    "status": "locked_by_user",
                    "provider": "local_qwen",
                    "model_id": "Qwen3-TTS-1.7B-Base",
                    "reference_audio": str(profile.parent / "reference.wav"),
                    "reference_transcript": "本人授權參考錄音。",
                    "language": "zh-TW",
                    "clone_mode": "full_icl",
                    "inference_mode": "offline",
                    "network_fallback": "forbidden",
                    "consent": "user_confirmed_self_recording",
                }
            ),
            encoding="utf-8",
        )
        (profile.parent / "reference.wav").write_bytes(b"reference")
        profiles.append(profile)
    cast_bible = context.project_dir / "cast_bible.json"
    cast_bible.write_text('{"schema":"story_video_cast_bible_v1"}', encoding="utf-8")
    story_mode = context.project_dir / "story_mode.json"
    story_mode.write_text(
        '{"schema":"story_video_story_mode_v1","mode":"creative"}',
        encoding="utf-8",
    )
    dialogue = context.project_dir / "dialogue_ledger.json"
    dialogue.write_text(
        '{"schema":"story_video_dialogue_ledger_v1","mode":"creative"}',
        encoding="utf-8",
    )
    binding = context.project_dir / "voice_cast_binding.json"
    binding.write_text(
        json.dumps(
            {
                "schema": "story_video_voice_cast_binding_v1",
                "status": "locked",
                "language_policy": "zh-TW",
                "story_mode": "creative",
                "story_mode_path": str(story_mode),
                "story_mode_sha256": hashlib.sha256(story_mode.read_bytes()).hexdigest(),
                "cast_bible_path": str(cast_bible),
                "cast_bible_sha256": hashlib.sha256(cast_bible.read_bytes()).hexdigest(),
                "dialogue_ledger_path": str(dialogue),
                "dialogue_ledger_sha256": hashlib.sha256(dialogue.read_bytes()).hexdigest(),
                "speakers": [
                    {
                        "speaker_id": speaker_id,
                        "voice_id": profile.stem,
                        "profile_id": profile.parent.name,
                        "profile_path": str(profile),
                        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
                        "clone_mode": "full_icl",
                        "variant": {},
                    }
                    for speaker_id, profile in zip(("narrator", "hero"), profiles)
                ],
            }
        ),
        encoding="utf-8",
    )
    pronunciation = context.project_dir / "qc" / "pronunciation_qc_report.json"
    pronunciation.parent.mkdir(parents=True)
    pronunciation.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v3",
                "run_id": context.run_id,
                "status": "PASS",
                "language": "zh-TW",
                "method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
                "checked_unit": "voice_chunk",
                "fluency_contract": "bounded_internal_silence_v1",
                "max_internal_silence_sec": 0.9,
                "applied_entries": [],
                "acoustic_evidence": [
                    {
                        "shot_id": "U001__C01",
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "fluency_status": "PASS",
                        "longest_internal_silence_sec": 0.28,
                        "term_checks": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    chunk = {
        "voice_chunk_id": "U001__C01",
        "speaker_id": "narrator",
        "profile_id": "simon@v1",
        "profile_sha256": hashlib.sha256(profiles[0].read_bytes()).hexdigest(),
        "speaker_routing_status": "PASS",
        "display_text": "故事開始。",
        "spoken_text": "故事開始。",
        "start_sec": 0.0,
        "speech_end_sec": 1.0,
        "alignment_status": "PASS",
        "pronunciation_status": "PASS",
        "prosody_status": "PASS",
        "fluency_status": "PASS",
    }
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest = {
        "schema": "story_video_narration_manifest_v6",
        "run_id": context.run_id,
        "provider": "local_qwen",
        "engine": "Qwen3-TTS via MLX-Audio",
        "language": "zh-TW",
        "voice_role": "cast",
        "voice": "multi_character",
        "rate": "per_speaker",
        "profile_status": "cast_bound",
        "voice_contract_status": "PASS",
        "model": "Qwen3-TTS-1.7B-Base",
        "inference_mode": "offline",
        "network_fallback": "forbidden",
        "pronunciation_status": "PASS",
        "alignment_status": "PASS",
        "prosody_status": "PASS",
        "fluency_status": "PASS",
        "spoken_text_normalization": "bounded_ellipsis_v1",
        "voice_segmentation": "sentence_chunks_v1",
        "story_mode": "creative",
        "speaker_routing_status": "PASS",
        "speaker_similarity_status": "NOT_MEASURED",
        "speaker_similarity_method": "routing_integrity_only",
        "voice_cast_binding": str(binding),
        "voice_cast_binding_sha256": hashlib.sha256(binding.read_bytes()).hexdigest(),
        "dialogue_ledger": str(dialogue),
        "dialogue_ledger_sha256": hashlib.sha256(dialogue.read_bytes()).hexdigest(),
        "speaker_profiles": json.loads(binding.read_text(encoding="utf-8"))["speakers"],
        "outputs": [
            {
                "scene_id": "S00",
                "audio": str(audio),
                "display_text": "故事開始。",
                "spoken_text": "故事開始。",
                "pronunciation_status": "PASS",
                "segments": [
                    {
                        "shot_id": "S00_SH00",
                        "timeline_duration_sec": 1.18,
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "voice_chunks": [chunk],
                    }
                ],
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert validate_phase(context).ok is True

    pronunciation_payload = json.loads(pronunciation.read_text(encoding="utf-8"))
    pronunciation_payload["acoustic_evidence"][0][
        "longest_internal_silence_sec"
    ] = 2.38
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")
    too_slow = validate_phase(context)
    assert too_slow.ok is False
    assert (
        "local Qwen multi-character fluency evidence is not PASS"
        in too_slow.violations
    )
    pronunciation_payload["acoustic_evidence"][0][
        "longest_internal_silence_sec"
    ] = 0.28
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")

    pronunciation_payload["acoustic_evidence"][0]["shot_id"] = "STALE__C01"
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")
    stale_chunk = validate_phase(context)
    assert stale_chunk.ok is False
    assert (
        "local Qwen acoustic evidence voice chunk coverage mismatch"
        in stale_chunk.violations
    )
    pronunciation_payload["acoustic_evidence"][0]["shot_id"] = "U001__C01"
    pronunciation_payload["run_id"] = "stale-run"
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")
    stale_run = validate_phase(context)
    assert stale_run.ok is False
    assert (
        "local Qwen multi-character pronunciation QC run_id mismatch"
        in stale_run.violations
    )
    pronunciation_payload["run_id"] = context.run_id
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")

    for field in (
        "alignment_status",
        "pronunciation_status",
        "prosody_status",
    ):
        pronunciation_payload["acoustic_evidence"][0][field] = "FAIL"
        pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")
        failed_acoustic_status = validate_phase(context)
        assert failed_acoustic_status.ok is False
        assert (
            "local Qwen acoustic evidence statuses are not PASS"
            in failed_acoustic_status.violations
        )
        pronunciation_payload["acoustic_evidence"][0][field] = "PASS"
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")

    pronunciation_payload["acoustic_evidence"][0][
        "longest_internal_silence_sec"
    ] = "not-measured"
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")
    malformed = validate_phase(context)
    assert malformed.ok is False
    pronunciation_payload["acoustic_evidence"][0][
        "longest_internal_silence_sec"
    ] = 0.28
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")

    pronunciation_payload["acoustic_evidence"] = [False]
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")
    malformed_row = validate_phase(context)
    assert malformed_row.ok is False
    assert (
        "local Qwen multi-character fluency evidence is malformed"
        in malformed_row.violations
    )
    pronunciation_payload["acoustic_evidence"] = [
        {
            "shot_id": "U001__C01",
            "alignment_status": "PASS",
            "pronunciation_status": "PASS",
            "prosody_status": "PASS",
            "fluency_status": "PASS",
            "longest_internal_silence_sec": False,
            "term_checks": [],
        }
    ]
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")
    boolean_duration = validate_phase(context)
    assert boolean_duration.ok is False
    pronunciation_payload["acoustic_evidence"][0][
        "longest_internal_silence_sec"
    ] = 0.28
    pronunciation.write_text(json.dumps(pronunciation_payload), encoding="utf-8")

    manifest["outputs"][0]["segments"][0]["voice_chunks"][0][
        "spoken_text"
    ] = "那味道——繼續。"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    unbounded_dash = validate_phase(context)
    assert unbounded_dash.ok is False
    assert (
        "multi-character voice chunk contains unbounded spoken pause"
        in unbounded_dash.violations
    )
    manifest["outputs"][0]["segments"][0]["voice_chunks"][0][
        "spoken_text"
    ] = "故事開始。"

    manifest["outputs"][0]["segments"][0]["voice_chunks"][0][
        "profile_id"
    ] = "hero@v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    drifted = validate_phase(context)

    assert drifted.ok is False
    assert "multi-character voice chunk profile does not match cast binding" in drifted.violations


def test_voice_validation_accepts_v7_engine_aware_tone_contract(tmp_path) -> None:
    context, _manifest_path, _dialogue, _binding = (
        _write_valid_v7_tone_voice_project(tmp_path)
    )

    proof = validate_phase(context)

    assert proof.ok is True, proof


def test_voice_validation_accepts_v7_selective_retry_candidate_evidence(
    tmp_path,
) -> None:
    context, manifest_path, _dialogue, _binding = (
        _write_valid_v7_tone_voice_project(tmp_path)
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][1]
    chunk["candidate_count"] = 2
    chunk["selected_candidate"] = 2
    chunk["candidate_rejections"] = [
        {
            "candidate_id": 1,
            "reasons": [
                {
                    "gate": "pronunciation_status",
                    "status": "FAIL",
                    "metrics": {"asr_transcript": "錯誤"},
                }
            ],
        }
    ]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True, proof


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing_catalog_sha", "tone catalog identity"),
        ("mismatched_catalog_sha", "tone catalog hash mismatch"),
        ("tone_control_failed", "tone control status is not PASS"),
        ("tone_evidence_overclaimed", "tone evidence status is not HEURISTIC_PASS"),
        ("custom_instruction_missing", "CustomVoice tone instruction evidence"),
        ("custom_template_missing", "CustomVoice tone instruction evidence"),
        ("clone_instruction_present", "full-ICL tone instruction evidence"),
        ("speed_out_of_bounds", "tone speed is outside safe bounds"),
        ("temperature_out_of_bounds", "tone temperature delta is outside safe bounds"),
        ("pause_out_of_bounds", "tone pause is outside safe bounds"),
        ("tone_pitch_nonzero", "tone pitch shift must remain zero"),
        ("adult_tone_in_general", "adult tone requires adult_explicit"),
        ("display_label_in_spoken_text", "display-only role or action label"),
        ("candidate_selection_invalid", "tone candidate evidence is invalid"),
        ("engine_adapter_mismatch", "tone adapter does not match cast binding"),
        ("application_engine_mismatch", "tone adapter does not match cast binding"),
        ("v7_with_v1_ledger", "tone narration requires dialogue ledger v2"),
    ],
)
def test_voice_validation_rejects_invalid_v7_tone_evidence(
    tmp_path,
    case: str,
    expected: str,
) -> None:
    context, manifest_path, dialogue_path, binding_path = (
        _write_valid_v7_tone_voice_project(tmp_path)
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = manifest["outputs"][0]["segments"][0]["voice_chunks"]

    if case == "missing_catalog_sha":
        manifest.pop("tone_catalog_sha256")
    elif case == "mismatched_catalog_sha":
        manifest["tone_catalog_sha256"] = "0" * 64
    elif case == "tone_control_failed":
        manifest["tone_control_status"] = "FAIL"
    elif case == "tone_evidence_overclaimed":
        manifest["tone_evidence_status"] = "PASS"
    elif case == "custom_instruction_missing":
        chunks[1]["tone_application"]["instruct"] = ""
    elif case == "custom_template_missing":
        chunks[1]["tone_instruction_template_id"] = ""
    elif case == "clone_instruction_present":
        chunks[0]["tone_application"]["instruct"] = "不應送出的指令"
    elif case == "speed_out_of_bounds":
        chunks[1]["tone_applied_parameters"]["speed"] = 1.11
    elif case == "temperature_out_of_bounds":
        chunks[1]["tone_applied_parameters"]["temperature_delta"] = 0.11
    elif case == "pause_out_of_bounds":
        chunks[1]["resolved_pause_after_sec"] = 0.46
    elif case == "tone_pitch_nonzero":
        chunks[1]["tone_applied_parameters"]["tone_pitch_shift_semitones"] = 1
    elif case == "adult_tone_in_general":
        ledger = json.loads(dialogue_path.read_text(encoding="utf-8"))
        adult_tone = {
            "tone_id": "adult.intimate",
            "intensity": 2,
            "modifiers": [],
            "resolution": "explicit",
            "source": {"emotion": "neutral", "action": "", "pace": "natural"},
        }
        ledger["utterances"][1]["tone"] = adult_tone
        dialogue_path.write_text(
            json.dumps(ledger, ensure_ascii=False),
            encoding="utf-8",
        )
        chunks[1]["tone"] = adult_tone
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        binding["dialogue_ledger_sha256"] = hashlib.sha256(
            dialogue_path.read_bytes()
        ).hexdigest()
        binding_path.write_text(
            json.dumps(binding, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest["dialogue_ledger_sha256"] = binding[
            "dialogue_ledger_sha256"
        ]
        manifest["voice_cast_binding_sha256"] = hashlib.sha256(
            binding_path.read_bytes()
        ).hexdigest()
    elif case == "display_label_in_spoken_text":
        chunks[1]["spoken_text"] = "小美（輕聲走近）你好。"
    elif case == "candidate_selection_invalid":
        chunks[1]["candidate_count"] = 2
        chunks[1]["selected_candidate"] = 3
    elif case == "engine_adapter_mismatch":
        chunks[1]["tone_adapter"] = "qwen_full_icl"
    elif case == "application_engine_mismatch":
        chunks[1]["tone_application"]["engine"] = "qwen_full_icl"
    elif case == "v7_with_v1_ledger":
        ledger = json.loads(dialogue_path.read_text(encoding="utf-8"))
        ledger["schema"] = "story_video_dialogue_ledger_v1"
        dialogue_path.write_text(
            json.dumps(ledger, ensure_ascii=False),
            encoding="utf-8",
        )
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        binding["dialogue_ledger_sha256"] = hashlib.sha256(
            dialogue_path.read_bytes()
        ).hexdigest()
        binding_path.write_text(
            json.dumps(binding, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest["dialogue_ledger_sha256"] = binding[
            "dialogue_ledger_sha256"
        ]
        manifest["voice_cast_binding_sha256"] = hashlib.sha256(
            binding_path.read_bytes()
        ).hexdigest()
    else:  # pragma: no cover - parametrization is exhaustive
        raise AssertionError(case)

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert any(
        expected in message for message in (*proof.missing, *proof.violations)
    ), proof


def test_voice_validation_blocks_local_qwen_without_pronunciation_proof(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="voice")
    audio = context.project_dir / "audio" / "qwen" / "S00.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"local qwen production audio")
    profile = context.project_dir / "voice_profiles" / "simon_primary.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps(
            {
                "profile_id": "simon_primary",
                "status": "locked_by_user",
                "provider": "local_qwen",
            }
        ),
        encoding="utf-8",
    )
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "local_qwen",
                "engine": "Qwen3-TTS via MLX-Audio",
                "language": "zh-TW",
                "voice": "simon_primary",
                "rate": "1.06x",
                "profile_status": "locked_by_user",
                "voice_contract_status": "PASS",
                "voice_profile": str(profile),
                "model": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
                "inference_mode": "offline",
                "network_fallback": "forbidden",
                "outputs": [{"scene_id": "S00", "audio": str(audio)}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "qc/pronunciation_qc_report.json" in proof.missing


def test_voice_validation_accepts_locked_azure_narration_manifest(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(
        context,
        phase="voice",
        provider_policy={**context.provider_policy, "tts": ["azure"]},
    )
    audio = context.project_dir / "audio" / "azure" / "S00.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"azure production audio")
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "azure",
                "engine": "Azure AI Speech",
                "language": "zh-TW",
                "voice_role": "narrator",
                "voice": "zh-TW-HsiaoChenNeural",
                "rate": "+6%",
                "profile_status": "locked_by_user",
                "voice_contract_status": "PASS",
                "outputs": [{"scene_id": "S00", "audio": str(audio)}],
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_render_validation_requires_clean_provider_audit(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context)

    blocked = validate_phase(context)
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="planning",
            provider="openai-codex",
            model="gpt-5.5",
            status="ok",
        )
    )
    passed = validate_phase(context)

    assert blocked.ok is False
    assert "provider audit has no events" in blocked.violations
    assert passed.ok is True


def test_render_validation_blocks_soft_subtitles_and_static_motion(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(
        context,
        hard_burned=False,
        motion_policy="stable static hold",
    )
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-sol",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "primary render has no hard-burned subtitles" in proof.violations
    assert "primary render has no non-static motion policy" in proof.violations


def test_render_validation_recognizes_cinematic_focus_push_as_motion(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context, motion_policy="cinematic_focus_push")
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-sol",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert "primary render has no non-static motion policy" not in proof.violations


def test_render_validation_requires_shot_density_evidence(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context)
    manifest_path = context.project_dir / "render_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["timeline"].pop("selected_shot_count")
    manifest["timeline"].pop("shot_density_status")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    qc_path = context.project_dir / "render_qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    qc["artifact_quality_evidence"].pop("shot_density")
    qc_path.write_text(json.dumps(qc), encoding="utf-8")
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-terra",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "render manifest lacks selected-shot density evidence" in proof.violations
    assert "render QC lacks selected-shot density evidence" in proof.violations


def test_render_validation_allows_small_semantic_density_tolerance(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context, motion_policy="cinematic_focus_push")
    for relative in ("render_manifest.json", "manifests/render_manifest.json"):
        path = context.project_dir / relative
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["timeline"].update(
            {
                "shot_density_status": "BLOCKED",
                "selected_shots_per_minute": 4.0839,
                "preferred_shots_per_minute": {"minimum": 3.0, "maximum": 4.0},
            }
        )
        path.write_text(json.dumps(manifest), encoding="utf-8")
    qc_path = context.project_dir / "render_qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    qc["artifact_quality_evidence"]["shot_density"].update(
        {
            "status": "BLOCKED",
            "selected_shots_per_minute": 4.0839,
        }
    )
    qc_path.write_text(json.dumps(qc), encoding="utf-8")
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-sol",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert "render manifest lacks selected-shot density evidence" not in proof.violations
    assert "render QC lacks selected-shot density evidence" not in proof.violations


def test_render_validation_requires_opening_and_ending_cards(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    context = store.update(context, phase="render")
    _write_render_fixture(context)
    for relative in ("render_manifest.json", "manifests/render_manifest.json"):
        path = context.project_dir / relative
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["cards"].pop("ending")
        path.write_text(json.dumps(manifest), encoding="utf-8")
    qc_path = context.project_dir / "render_qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    qc["artifact_quality_evidence"]["title_cards"]["ending"] = False
    qc_path.write_text(json.dumps(qc), encoding="utf-8")
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="api",
            phase="render",
            provider="openai-codex",
            model="gpt-5.6-sol",
            status="ok",
        )
    )

    proof = validate_phase(context)

    assert proof.ok is False
    assert "render manifest lacks opening and ending cards" in proof.violations
    assert "render QC lacks opening and ending card evidence" in proof.violations

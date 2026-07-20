from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from plugins.story_video.dubbing import (
    DubbingContractError,
    bind_project_voice_cast,
    compile_dubbing_project,
    inspect_dubbing_project,
    resolve_project_voice_cast,
)
from plugins.story_video.voice_profiles import add_voice_profile
from plugins.story_video.schemas import STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA


def _add_voice(root: Path, voice_id: str, *, tuning=None) -> dict:
    source = root.parent / f"{voice_id}.wav"
    source.write_bytes(f"clean-{voice_id}".encode())
    return add_voice_profile(
        voice_id=voice_id,
        display_name=voice_id.title(),
        reference_audio=source,
        reference_transcript=f"這是{voice_id}本人授權的乾淨參考錄音。",
        registry_path=root / "registry.json",
        consent="user_confirmed_self_recording",
        tuning=tuning,
    )


def _speakers() -> list[dict]:
    return [
        {
            "speaker_id": "narrator",
            "display_name": "旁白",
            "role": "narrator",
            "voice_id": "simon",
        },
        {
            "speaker_id": "hero",
            "display_name": "小明",
            "role": "lead",
            "voice_id": "young_male",
            "variant": {"speed": 1.06, "expressiveness": "lively"},
        },
    ]


def _utterance(
    utterance_id: str,
    speaker_id: str,
    text: str,
    **extra,
) -> dict:
    return {
        "utterance_id": utterance_id,
        "scene_id": "S01",
        "shot_id": "S01_SH01",
        "speaker_id": speaker_id,
        "display_text": text,
        **extra,
    }


def _preset_cast_project(
    tmp_path,
    *,
    narrator_voice: str,
    hero_voice: str,
) -> tuple[Path, dict]:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry = tmp_path / "voices" / "registry.json"
    _add_voice(registry.parent, "simon_clean_v2")
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
    catalog = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )
    project = tmp_path / "story"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=[
            {
                "speaker_id": "narrator",
                "display_name": "旁白",
                "role": "narrator",
                "voice_id": narrator_voice,
            },
            {
                "speaker_id": "hero",
                "display_name": "主角",
                "role": "lead",
                "voice_id": hero_voice,
            },
        ],
        utterances=[
            _utterance("U001", "narrator", "故事開始。"),
            _utterance("U002", "hero", "出發吧！"),
        ],
    )
    return project, catalog


def test_creative_mode_compiles_three_project_contracts(tmp_path) -> None:
    project = tmp_path / "story"

    result = compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[
            _utterance("U001", "narrator", "森林裡傳來一聲巨響。", emotion="wonder"),
            _utterance(
                "U002",
                "hero",
                "那是什麼？",
                action="驚訝地看向森林深處",
                pace="quick",
            ),
        ],
    )

    assert result["mode"] == "creative"
    assert result["speaker_count"] == 2
    assert result["utterance_count"] == 2
    assert (project / "story_mode.json").is_file()
    assert (project / "cast_bible.json").is_file()
    ledger = json.loads((project / "dialogue_ledger.json").read_text(encoding="utf-8"))
    assert ledger["schema"] == "story_video_dialogue_ledger_v2"
    assert ledger["content_rating"] == "general"
    assert ledger["tone_catalog"]["schema"] == "story_video_tone_catalog_v1"
    assert ledger["tone_catalog"]["paces"]["natural"]["adapters"] == {
        "qwen_custom_voice": {},
        "qwen_full_icl": {},
    }
    assert [row["order"] for row in ledger["utterances"]] == [1, 2]
    assert ledger["utterances"][0]["pace"] == "natural"
    assert ledger["utterances"][0]["tone"]["source"]["pace"] == "natural"
    assert ledger["utterances"][1]["action"] == "驚訝地看向森林深處"
    assert ledger["utterances"][1]["display_text"] == "那是什麼？"


def test_compiler_resolves_per_utterance_tone_and_preserves_display_text(
    tmp_path,
) -> None:
    project = tmp_path / "story"

    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        content_rating="general",
        utterances=[
            _utterance(
                "U001",
                "hero",
                "你真的看見了嗎？",
                emotion="curious",
                action="猶豫地問",
            )
        ],
    )

    ledger = json.loads((project / "dialogue_ledger.json").read_text(encoding="utf-8"))
    row = ledger["utterances"][0]
    assert ledger["schema"] == "story_video_dialogue_ledger_v2"
    assert ledger["tone_catalog"]["schema"] == "story_video_tone_catalog_v1"
    assert row["tone"]["tone_id"] == "general.puzzled"
    assert row["tone"]["modifiers"] == ["hesitant"]
    assert row["display_text"] == "你真的看見了嗎？"
    assert "猶豫地問" not in row["display_text"]


def test_compiler_accepts_explicit_tone_fields_and_rejects_adult_tone_in_general(
    tmp_path,
) -> None:
    project = tmp_path / "adult-tone"

    with pytest.raises(DubbingContractError, match="requires adult_explicit") as error:
        compile_dubbing_project(
            project,
            mode="creative",
            source_text="",
            speakers=_speakers(),
            content_rating="general",
            utterances=[
                _utterance(
                    "U001",
                    "hero",
                    "靠近一點。",
                    tone_id="adult.intimate",
                    tone_intensity=2,
                    tone_modifiers=["soft"],
                )
            ],
        )

    assert error.value.error_type == "tone_content_rating_invalid"
    assert not (project / "voice_cast_binding.json").exists()
    assert not (project / "dialogue_ledger.json").exists()


def test_automatic_tone_continuity_downgrades_unprompted_low_to_high_jump(
    tmp_path,
) -> None:
    project = tmp_path / "continuity"

    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[
            _utterance("U001", "hero", "我真的很難過。", emotion="sadness"),
            _utterance("U002", "hero", "太好了！", emotion="joy"),
        ],
    )

    ledger = json.loads((project / "dialogue_ledger.json").read_text(encoding="utf-8"))
    assert ledger["utterances"][0]["tone"]["tone_id"] == "general.sad"
    assert ledger["utterances"][1]["tone"]["tone_id"] == "general.joyful"
    assert ledger["utterances"][1]["tone"]["intensity"] == 1
    assert ledger["utterances"][1]["tone"]["continuity_adjustment"] == (
        "reduced_unprompted_low_to_high_transition"
    )


def test_tone_continuity_never_changes_explicit_tone(tmp_path) -> None:
    project = tmp_path / "explicit-continuity"

    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[
            _utterance("U001", "hero", "我真的很難過。", emotion="sadness"),
            _utterance(
                "U002",
                "hero",
                "太好了！",
                tone_id="general.joyful",
                tone_intensity=3,
            ),
        ],
    )

    ledger = json.loads((project / "dialogue_ledger.json").read_text(encoding="utf-8"))
    tone = ledger["utterances"][1]["tone"]
    assert tone["resolution"] == "explicit"
    assert tone["intensity"] == 3
    assert "continuity_adjustment" not in tone


def test_tone_continuity_keeps_automatic_intensity_with_explicit_narrative_cue(
    tmp_path,
) -> None:
    project = tmp_path / "cued-continuity"

    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[
            _utterance("U001", "hero", "我真的很難過。", emotion="sadness"),
            _utterance(
                "U002",
                "hero",
                "太好了！",
                emotion="joy",
                action="突然收到期待已久的好消息",
            ),
        ],
    )

    ledger = json.loads((project / "dialogue_ledger.json").read_text(encoding="utf-8"))
    tone = ledger["utterances"][1]["tone"]
    assert tone["resolution"] == "mapped"
    assert tone["intensity"] == 2
    assert "continuity_adjustment" not in tone


def test_audio_director_schema_exposes_optional_tone_controls() -> None:
    utterance = STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA["parameters"]["properties"][
        "utterances"
    ]["items"]

    assert utterance["properties"]["tone_id"] == {"type": "string"}
    assert utterance["properties"]["tone_intensity"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 3,
    }
    assert utterance["properties"]["tone_modifiers"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert not {"tone_id", "tone_intensity", "tone_modifiers"}.intersection(
        utterance["required"]
    )


def test_audio_director_schema_exposes_optional_action() -> None:
    utterance = STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA["parameters"]["properties"][
        "utterances"
    ]["items"]

    assert utterance["properties"]["action"] == {"type": "string"}
    assert "action" not in utterance["required"]


def test_legacy_v1_ledger_remains_inspectable_and_bindable(tmp_path) -> None:
    voices = tmp_path / "voices"
    _add_voice(voices, "simon")
    _add_voice(voices, "young_male")
    project = tmp_path / "legacy-v1"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[_utterance("U001", "narrator", "故事開始。")],
    )
    ledger_path = project / "dialogue_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["schema"] = "story_video_dialogue_ledger_v1"
    ledger.pop("content_rating")
    ledger.pop("tone_catalog")
    for row in ledger["utterances"]:
        row.pop("tone")
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    status = inspect_dubbing_project(project)
    selection = bind_project_voice_cast(
        project,
        registry_path=voices / "registry.json",
    )

    assert status["utterance_count"] == 1
    assert selection.binding_path.is_file()


@pytest.mark.parametrize(
    "ledger_schema",
    ["story_video_dialogue_ledger_v999", None],
)
def test_inspect_and_bind_reject_unknown_or_missing_dialogue_ledger_schema(
    tmp_path,
    ledger_schema,
) -> None:
    project = tmp_path / "unknown-ledger"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[_utterance("U001", "narrator", "故事開始。")],
    )
    ledger_path = project / "dialogue_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger_schema is None:
        ledger.pop("schema")
    else:
        ledger["schema"] = ledger_schema
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    with pytest.raises(DubbingContractError, match="ledger schema"):
        inspect_dubbing_project(project)
    with pytest.raises(DubbingContractError, match="ledger schema"):
        bind_project_voice_cast(project)


def test_inspect_rejects_malformed_v2_tone_catalog(tmp_path) -> None:
    project = tmp_path / "malformed-v2"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[_utterance("U001", "narrator", "故事開始。")],
    )
    ledger_path = project / "dialogue_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["tone_catalog"].pop("tones")
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    with pytest.raises(DubbingContractError, match="tone catalog"):
        inspect_dubbing_project(project)


def test_read_aloud_requires_exact_ordered_gap_free_source_coverage(tmp_path) -> None:
    source = "第一句。\n第二句！"
    project = tmp_path / "story"

    compile_dubbing_project(
        project,
        mode="read_aloud",
        source_text=source,
        speakers=_speakers(),
        utterances=[
            _utterance(
                "U001", "narrator", "第一句。", source_start=0, source_end=4
            ),
            _utterance(
                "U002", "hero", "\n第二句！", source_start=4, source_end=len(source)
            ),
        ],
    )

    mode = json.loads((project / "story_mode.json").read_text(encoding="utf-8"))
    assert mode["source_text"] == source
    assert mode["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert mode["exact_text_required"] is True

    with pytest.raises(DubbingContractError, match="exact source slice") as rewritten:
        compile_dubbing_project(
            tmp_path / "rewritten",
            mode="read_aloud",
            source_text=source,
            speakers=_speakers(),
            utterances=[
                _utterance(
                    "U001", "narrator", "第一句！", source_start=0, source_end=4
                ),
                _utterance(
                    "U002", "hero", "\n第二句！", source_start=4, source_end=len(source)
                ),
            ],
        )
    assert rewritten.value.error_type == "read_aloud_text_mismatch"

    with pytest.raises(DubbingContractError, match="gap or overlap"):
        compile_dubbing_project(
            tmp_path / "gap",
            mode="read_aloud",
            source_text=source,
            speakers=_speakers(),
            utterances=[
                _utterance(
                    "U001", "narrator", "第一句。", source_start=0, source_end=4
                ),
                _utterance(
                    "U002", "hero", "第二句！", source_start=5, source_end=len(source)
                ),
            ],
        )


def test_remake_locks_source_and_requires_traceable_source_refs(tmp_path) -> None:
    source = "小明走進森林，看見一道藍光。"

    result = compile_dubbing_project(
        tmp_path / "story",
        mode="remake",
        source_text=source,
        speakers=_speakers(),
        utterances=[
            _utterance(
                "U001",
                "narrator",
                "小明才踏進森林，藍光就像閃電般竄了出來！",
                source_refs=[{"start": 0, "end": len(source)}],
            )
        ],
    )

    assert result["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert result["exact_text_required"] is False

    with pytest.raises(DubbingContractError, match="source_refs"):
        compile_dubbing_project(
            tmp_path / "untraceable",
            mode="remake",
            source_text=source,
            speakers=_speakers(),
            utterances=[_utterance("U001", "narrator", "完全重寫。")],
        )


def test_compiler_rejects_unknown_speaker_and_duplicate_utterance(tmp_path) -> None:
    with pytest.raises(DubbingContractError) as unknown:
        compile_dubbing_project(
            tmp_path / "unknown",
            mode="creative",
            source_text="",
            speakers=_speakers(),
            utterances=[_utterance("U001", "villain", "你找不到我！")],
        )
    assert unknown.value.error_type == "dubbing_speaker_unresolved"

    with pytest.raises(DubbingContractError) as duplicate:
        compile_dubbing_project(
            tmp_path / "duplicate",
            mode="creative",
            source_text="",
            speakers=_speakers(),
            utterances=[
                _utterance("U001", "narrator", "第一句。"),
                _utterance("U001", "hero", "第二句。"),
            ],
        )
    assert duplicate.value.error_type == "dubbing_utterance_invalid"


def test_cast_binding_resolves_latest_concrete_profiles_and_variants(tmp_path) -> None:
    voices = tmp_path / "voices"
    simon = _add_voice(voices, "simon")
    young = _add_voice(voices, "young_male")
    project = tmp_path / "story"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[
            _utterance("U001", "narrator", "故事開始。"),
            _utterance("U002", "hero", "出發吧！"),
        ],
    )

    selection = bind_project_voice_cast(
        project, registry_path=voices / "registry.json"
    )

    assert selection.binding_path == project / "voice_cast_binding.json"
    rows = {row["speaker_id"]: row for row in selection.speakers}
    assert rows["narrator"]["profile_id"] == simon["profile_id"]
    assert rows["hero"]["profile_id"] == young["profile_id"]
    assert rows["hero"]["variant"] == {
        "speed": 1.06,
        "expressiveness": "lively",
    }
    assert all(row["profile_sha256"] for row in rows.values())
    assert resolve_project_voice_cast(project).binding_sha256 == selection.binding_sha256
    status = inspect_dubbing_project(project)
    assert status["integrity"] == "PASS"
    assert status["speaker_count"] == 2


def test_cast_binding_accepts_qwen_preset_aliases(tmp_path) -> None:
    project, catalog = _preset_cast_project(
        tmp_path,
        narrator_voice="Vivian",
        hero_voice="Uncle_Fu",
    )

    selection = bind_project_voice_cast(project, voice_catalog=catalog)

    rows = {row["speaker_id"]: row for row in selection.speakers}
    assert rows["narrator"]["voice_id"] == "qwen_custom_vivian"
    assert rows["narrator"]["engine"] == "qwen_custom_voice"
    assert rows["narrator"]["engine_binding"]["preset_speaker"] == "Vivian"
    assert rows["hero"]["engine_binding"]["preset_speaker"] == "Uncle_Fu"
    binding = json.loads(selection.binding_path.read_text(encoding="utf-8"))
    assert binding["schema"] == "story_video_voice_cast_binding_v2"
    assert binding["catalog_sha256"] == catalog["catalog_sha256"]


def test_preset_binding_fails_closed_on_model_config_drift(tmp_path) -> None:
    project, catalog = _preset_cast_project(
        tmp_path,
        narrator_voice="Serena",
        hero_voice="Vivian",
    )
    selection = bind_project_voice_cast(project, voice_catalog=catalog)
    model_config = Path(
        selection.speakers[0]["engine_binding"]["model_config_path"]
    )
    payload = json.loads(model_config.read_text(encoding="utf-8"))
    payload["talker_config"]["spk_id"].pop("serena")
    model_config.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DubbingContractError) as error:
        resolve_project_voice_cast(project)

    assert error.value.error_type == "voice_cast_binding_mismatch"


def test_v1_clone_binding_remains_readable_after_v2_upgrade(tmp_path) -> None:
    voices = tmp_path / "voices"
    _add_voice(voices, "simon")
    _add_voice(voices, "young_male")
    project = tmp_path / "story"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[_utterance("U001", "narrator", "故事開始。")],
    )
    selection = bind_project_voice_cast(
        project,
        registry_path=voices / "registry.json",
    )
    payload = json.loads(selection.binding_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "story_video_voice_cast_binding_v2"
    payload["schema"] = "story_video_voice_cast_binding_v1"
    selection.binding_path.write_text(json.dumps(payload), encoding="utf-8")

    resolved = resolve_project_voice_cast(project)

    assert {row["profile_id"] for row in resolved.speakers} == {
        "simon@v1",
        "young_male@v1",
    }


def test_cast_binding_fails_closed_on_profile_hash_drift(tmp_path) -> None:
    voices = tmp_path / "voices"
    _add_voice(voices, "simon")
    young = _add_voice(voices, "young_male")
    project = tmp_path / "story"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[_utterance("U001", "hero", "出發吧！")],
    )
    bind_project_voice_cast(project, registry_path=voices / "registry.json")
    profile = Path(young["profile_path"])
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["tuning"] = {"speed": 9}
    profile.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DubbingContractError, match="hash mismatch") as error:
        resolve_project_voice_cast(project)

    assert error.value.error_type == "voice_cast_binding_mismatch"


def test_cast_binding_fails_closed_on_story_mode_hash_drift(tmp_path) -> None:
    voices = tmp_path / "voices"
    _add_voice(voices, "simon")
    _add_voice(voices, "young_male")
    project = tmp_path / "story"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[_utterance("U001", "narrator", "故事開始。")],
    )
    bind_project_voice_cast(project, registry_path=voices / "registry.json")
    mode_path = project / "story_mode.json"
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    mode["mode"] = "read_aloud"
    mode_path.write_text(json.dumps(mode), encoding="utf-8")

    with pytest.raises(DubbingContractError, match="hash mismatch") as error:
        resolve_project_voice_cast(project)

    assert error.value.error_type == "voice_cast_binding_mismatch"


def test_recompile_with_existing_narration_fails_before_mutating_contracts(
    tmp_path,
) -> None:
    voices = tmp_path / "voices"
    _add_voice(voices, "simon")
    _add_voice(voices, "young_male")
    project = tmp_path / "story"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[_utterance("U001", "narrator", "原本的故事。")],
    )
    bind_project_voice_cast(project, registry_path=voices / "registry.json")
    manifest = project / "manifests" / "narration_manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("{}", encoding="utf-8")
    before = {
        name: (project / name).read_bytes()
        for name in ("story_mode.json", "cast_bible.json", "dialogue_ledger.json")
    }

    with pytest.raises(DubbingContractError, match="revoice") as error:
        compile_dubbing_project(
            project,
            mode="creative",
            source_text="",
            speakers=_speakers(),
            utterances=[_utterance("U001", "narrator", "改寫後的故事。")],
        )

    assert error.value.error_type == "voice_cast_revoice_required"
    assert before == {
        name: (project / name).read_bytes()
        for name in ("story_mode.json", "cast_bible.json", "dialogue_ledger.json")
    }


def test_binding_rejects_invalid_variant_and_unregistered_voice(tmp_path) -> None:
    voices = tmp_path / "voices"
    _add_voice(voices, "simon")
    project = tmp_path / "story"
    speakers = _speakers()
    speakers[1]["voice_id"] = "missing"
    speakers[0]["variant"] = {"speed": 2.0}
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=speakers,
        utterances=[_utterance("U001", "hero", "出發吧！")],
    )

    with pytest.raises(DubbingContractError) as error:
        bind_project_voice_cast(project, registry_path=voices / "registry.json")

    assert error.value.error_type in {
        "voice_cast_variant_invalid",
        "voice_cast_profile_unresolved",
    }

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


def test_creative_mode_compiles_three_project_contracts(tmp_path) -> None:
    project = tmp_path / "story"

    result = compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=_speakers(),
        utterances=[
            _utterance("U001", "narrator", "森林裡傳來一聲巨響。", emotion="wonder"),
            _utterance("U002", "hero", "那是什麼？", pace="quick"),
        ],
    )

    assert result["mode"] == "creative"
    assert result["speaker_count"] == 2
    assert result["utterance_count"] == 2
    assert (project / "story_mode.json").is_file()
    assert (project / "cast_bible.json").is_file()
    ledger = json.loads((project / "dialogue_ledger.json").read_text(encoding="utf-8"))
    assert ledger["schema"] == "story_video_dialogue_ledger_v1"
    assert [row["order"] for row in ledger["utterances"]] == [1, 2]


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

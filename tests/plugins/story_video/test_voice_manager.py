from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.story_video.voice_profiles import (
    VoiceProfileError,
    add_voice_profile,
    archive_voice_profile,
    delete_voice_profile,
    list_voice_profiles,
    tune_voice_profile,
)


def _source_audio(tmp_path: Path, name: str = "source.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"clean-user-authorized-reference")
    return path


def test_add_voice_creates_first_immutable_version_and_registry(tmp_path) -> None:
    root = tmp_path / "voices"

    created = add_voice_profile(
        voice_id="mom",
        display_name="Mom",
        reference_audio=_source_audio(tmp_path),
        reference_transcript="這是媽媽乾淨而且本人授權的參考錄音。",
        registry_path=root / "registry.json",
        consent="user_confirmed_self_recording",
    )

    assert created["voice_id"] == "mom"
    assert created["profile_id"] == "mom@v1"
    assert created["version"] == 1
    assert created["selectable"] is True
    profile = json.loads(Path(created["profile_path"]).read_text(encoding="utf-8"))
    assert profile["voice_id"] == "mom"
    assert profile["version"] == 1
    assert Path(profile["reference_audio"]).read_bytes() == b"clean-user-authorized-reference"
    catalog = list_voice_profiles(registry_path=root / "registry.json")
    assert catalog["default_profile_id"] == "mom@v1"
    assert catalog["profiles"][0]["lifecycle_status"] == "active"


def test_tune_voice_creates_new_version_without_mutating_parent(tmp_path) -> None:
    registry = tmp_path / "voices" / "registry.json"
    first = add_voice_profile(
        voice_id="mom",
        display_name="Mom",
        reference_audio=_source_audio(tmp_path),
        reference_transcript="這是媽媽乾淨而且本人授權的參考錄音。",
        registry_path=registry,
        consent="user_confirmed_self_recording",
    )
    first_bytes = Path(first["profile_path"]).read_bytes()

    tuned = tune_voice_profile(
        voice_id="mom",
        registry_path=registry,
        tuning={"speed": 1.08, "expressiveness": "lively"},
    )

    assert tuned["profile_id"] == "mom@v2"
    assert tuned["version"] == 2
    assert tuned["parent_profile_id"] == "mom@v1"
    assert Path(first["profile_path"]).read_bytes() == first_bytes
    tuned_payload = json.loads(Path(tuned["profile_path"]).read_text(encoding="utf-8"))
    assert tuned_payload["tuning"] == {"speed": 1.08, "expressiveness": "lively"}
    catalog = list_voice_profiles(registry_path=registry)
    rows = {row["profile_id"]: row for row in catalog["profiles"]}
    assert rows["mom@v1"]["selectable"] is True
    assert rows["mom@v2"]["selectable"] is True


def test_archive_disables_new_selection_but_keeps_locked_profile_valid(tmp_path) -> None:
    registry = tmp_path / "voices" / "registry.json"
    created = add_voice_profile(
        voice_id="mom",
        display_name="Mom",
        reference_audio=_source_audio(tmp_path),
        reference_transcript="這是媽媽乾淨而且本人授權的參考錄音。",
        registry_path=registry,
        consent="user_confirmed_self_recording",
    )

    result = archive_voice_profile(voice_id="mom", registry_path=registry)

    assert result["archived_profile_ids"] == ["mom@v1"]
    row = list_voice_profiles(registry_path=registry)["profiles"][0]
    assert row["enabled"] is False
    assert row["lifecycle_status"] == "archived"
    assert Path(created["profile_path"]).is_file()


def test_delete_fails_closed_when_single_or_cast_binding_references_voice(tmp_path) -> None:
    registry = tmp_path / "voices" / "registry.json"
    created = add_voice_profile(
        voice_id="mom",
        display_name="Mom",
        reference_audio=_source_audio(tmp_path),
        reference_transcript="這是媽媽乾淨而且本人授權的參考錄音。",
        registry_path=registry,
        consent="user_confirmed_self_recording",
    )
    projects = tmp_path / "projects"
    project = projects / "story"
    project.mkdir(parents=True)
    (project / "voice_cast_binding.json").write_text(
        json.dumps(
            {
                "schema": "story_video_voice_cast_binding_v1",
                "speakers": [
                    {"speaker_id": "mother", "profile_id": created["profile_id"]}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(VoiceProfileError, match="referenced") as error:
        delete_voice_profile(
            voice_id="mom",
            registry_path=registry,
            projects_root=projects,
        )

    assert error.value.error_type == "voice_profile_in_use"
    assert Path(created["profile_path"]).is_file()


def test_delete_removes_unreferenced_voice_versions_and_repairs_default(tmp_path) -> None:
    registry = tmp_path / "voices" / "registry.json"
    mom = add_voice_profile(
        voice_id="mom",
        display_name="Mom",
        reference_audio=_source_audio(tmp_path, "mom.wav"),
        reference_transcript="這是媽媽乾淨而且本人授權的參考錄音。",
        registry_path=registry,
        consent="user_confirmed_self_recording",
    )
    narrator = add_voice_profile(
        voice_id="narrator",
        display_name="Narrator",
        reference_audio=_source_audio(tmp_path, "narrator.wav"),
        reference_transcript="這是旁白乾淨而且本人授權的參考錄音。",
        registry_path=registry,
        consent="user_confirmed_self_recording",
    )

    deleted = delete_voice_profile(
        voice_id="mom",
        registry_path=registry,
        projects_root=tmp_path / "empty-projects",
    )

    assert deleted["deleted_profile_ids"] == ["mom@v1"]
    assert not Path(mom["profile_path"]).exists()
    catalog = list_voice_profiles(registry_path=registry)
    assert [row["profile_id"] for row in catalog["profiles"]] == ["narrator@v1"]
    assert catalog["default_profile_id"] == narrator["profile_id"]


def test_delete_last_voice_leaves_valid_empty_registry_that_can_be_reused(tmp_path) -> None:
    registry = tmp_path / "voices" / "registry.json"
    created = add_voice_profile(
        voice_id="temporary",
        display_name="Temporary",
        reference_audio=_source_audio(tmp_path),
        reference_transcript="這是本人授權的乾淨參考錄音。",
        registry_path=registry,
        consent="user_confirmed_self_recording",
    )

    delete_voice_profile(
        voice_id="temporary",
        registry_path=registry,
        projects_root=tmp_path / "empty-projects",
    )

    catalog = list_voice_profiles(registry_path=registry)
    assert catalog["profiles"] == []
    assert catalog["default_profile_id"] == ""
    assert not Path(created["profile_path"]).exists()


def test_manager_rejects_unconfirmed_or_missing_reference_audio(tmp_path) -> None:
    registry = tmp_path / "voices" / "registry.json"

    with pytest.raises(VoiceProfileError) as consent_error:
        add_voice_profile(
            voice_id="mom",
            display_name="Mom",
            reference_audio=_source_audio(tmp_path),
            reference_transcript="參考錄音。",
            registry_path=registry,
            consent="",
        )
    assert consent_error.value.error_type == "voice_profile_consent_required"

    with pytest.raises(VoiceProfileError) as audio_error:
        add_voice_profile(
            voice_id="mom",
            display_name="Mom",
            reference_audio=tmp_path / "missing.wav",
            reference_transcript="參考錄音。",
            registry_path=registry,
            consent="user_confirmed_self_recording",
        )
    assert audio_error.value.error_type == "voice_profile_reference_invalid"

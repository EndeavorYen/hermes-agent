from __future__ import annotations

import json

import pytest

from plugins.story_video.voice_profiles import add_voice_profile


def _catalog_setup(tmp_path):
    voices = tmp_path / "voices"
    reference = tmp_path / "simon.wav"
    reference.write_bytes(b"authorized-simon-reference")
    add_voice_profile(
        voice_id="simon_clean_v2",
        display_name="Simon clean narrator v2",
        reference_audio=reference,
        reference_transcript="這是 Simon 本人授權的乾淨錄音。",
        consent="user_confirmed_self_recording",
        registry_path=voices / "registry.json",
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
    return voices / "registry.json", model, runtime


def test_catalog_merges_clone_and_three_approved_qwen_actors(tmp_path) -> None:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry, model, runtime = _catalog_setup(tmp_path)
    result = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )

    rows = {row["voice_id"]: row for row in result["voices"]}
    assert set(rows) == {
        "simon_clean_v2",
        "qwen_custom_vivian",
        "qwen_custom_serena",
        "qwen_custom_uncle_fu",
    }
    assert rows["simon_clean_v2"]["engine"] == "qwen_full_icl"
    assert rows["qwen_custom_vivian"]["engine"] == "qwen_custom_voice"
    assert rows["qwen_custom_vivian"]["capabilities"]["character_dubbing"] is True
    assert all(row["selectable"] is True for row in rows.values())
    assert result["default_voice_id"] == "simon_clean_v2"
    assert result["catalog_sha256"]


def test_catalog_keeps_missing_qwen_setup_visible_but_unselectable(tmp_path) -> None:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry, _, _ = _catalog_setup(tmp_path)
    result = list_voice_catalog(
        registry_path=registry,
        preset_model_path=tmp_path / "missing-model",
        preset_runtime_path=tmp_path / "missing-runtime",
    )

    presets = [row for row in result["voices"] if row["source_kind"] == "preset"]
    assert [row["display_name"] for row in presets] == [
        "Vivian",
        "Serena",
        "Uncle_Fu",
    ]
    assert all(row["selectable"] is False for row in presets)
    assert all(row["availability"]["status"] == "setup_required" for row in presets)


def test_catalog_alias_resolution_is_case_insensitive(tmp_path) -> None:
    from plugins.story_video.voice_catalog import (
        VoiceCatalogError,
        list_voice_catalog,
        resolve_catalog_voice,
    )

    registry, model, runtime = _catalog_setup(tmp_path)
    catalog = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )

    assert resolve_catalog_voice("Vivian", catalog)["voice_id"] == "qwen_custom_vivian"
    assert (
        resolve_catalog_voice("UNCLE_FU", catalog)["voice_id"]
        == "qwen_custom_uncle_fu"
    )
    with pytest.raises(VoiceCatalogError, match="not registered"):
        resolve_catalog_voice("missing_actor", catalog)


def test_catalog_resolves_latest_selectable_clone_version(tmp_path) -> None:
    from plugins.story_video.voice_catalog import (
        list_voice_catalog,
        resolve_catalog_voice,
    )

    registry, model, runtime = _catalog_setup(tmp_path)
    newer_reference = tmp_path / "simon-newer.wav"
    newer_reference.write_bytes(b"authorized-simon-newer-reference")
    newer = add_voice_profile(
        voice_id="simon_clean_v2",
        display_name="Simon clean narrator v2 tuned",
        reference_audio=newer_reference,
        reference_transcript="這是 Simon 本人授權的新版乾淨錄音。",
        consent="user_confirmed_self_recording",
        registry_path=registry,
    )
    catalog = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )

    selected = resolve_catalog_voice("simon_clean_v2", catalog)

    assert selected["engine_binding"]["profile_id"] == newer["profile_id"]


def test_engine_binding_validates_clone_and_preset_evidence(tmp_path) -> None:
    from plugins.story_video.voice_catalog import (
        build_engine_binding,
        list_voice_catalog,
        validate_engine_binding,
    )

    registry, model, runtime = _catalog_setup(tmp_path)
    catalog = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )
    rows = {row["voice_id"]: row for row in catalog["voices"]}

    for voice_id in ("simon_clean_v2", "qwen_custom_serena"):
        binding = build_engine_binding(rows[voice_id])
        assert binding["engine"] == rows[voice_id]["engine"]
        validate_engine_binding(binding)


def test_engine_binding_rejects_unknown_engine() -> None:
    from plugins.story_video.voice_catalog import (
        VoiceCatalogError,
        validate_engine_binding,
    )

    with pytest.raises(VoiceCatalogError, match="unsupported voice engine"):
        validate_engine_binding({"engine": "future_engine"})

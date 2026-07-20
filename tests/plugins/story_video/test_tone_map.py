from __future__ import annotations

import hashlib
import json

import pytest

from plugins.story_video.tone_map import (
    ToneMapError,
    build_tone_catalog,
    resolve_utterance_tone,
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_catalog_is_canonical_and_engine_aware() -> None:
    catalog = build_tone_catalog()
    unsigned = {key: value for key, value in catalog.items() if key != "sha256"}

    assert catalog["schema"] == "story_video_tone_catalog_v1"
    assert catalog["version"] == 1
    assert catalog["sha256"] == _canonical_sha256(unsigned)
    assert set(catalog["tones"]) == {
        "general.neutral",
        "general.warm",
        "general.joyful",
        "general.excited",
        "general.sad",
        "general.angry",
        "general.tense",
        "general.puzzled",
        "adult.flirtatious",
        "adult.intimate",
        "adult.desirous",
        "adult.breathless",
        "adult.shy",
        "adult.teasing",
        "adult.commanding",
        "adult.receptive",
        "adult.intense",
        "adult.afterglow",
    }
    assert list(catalog["modifiers"]) == [
        "whispered",
        "breathy",
        "trembling",
        "restrained",
        "urgent",
        "hesitant",
        "soft",
        "firm",
    ]
    assert catalog["safe_bounds"] == {
        "speed_multiplier": [0.9, 1.1],
        "temperature_delta": [-0.1, 0.1],
        "ordinary_pause_seconds": [0.08, 0.35],
        "ellipsis_pause_seconds_max": 0.45,
        "pitch_shift_semitones": 0,
    }
    modifier_ids = set(catalog["modifiers"])
    for tone_id, entry in catalog["tones"].items():
        assert entry["tone_id"] == tone_id
        assert set(entry["allowed_modifiers"]) <= modifier_ids
        assert set(entry["adapters"]) == {
            "qwen_custom_voice",
            "qwen_full_icl",
        }


def test_all_catalog_adapters_stay_within_safe_bounds() -> None:
    catalog = build_tone_catalog()
    bounds = catalog["safe_bounds"]

    for collection in (catalog["tones"], catalog["modifiers"]):
        for entry in collection.values():
            for adapter in entry["adapters"].values():
                if "speed_multiplier" in adapter:
                    assert bounds["speed_multiplier"][0] <= adapter[
                        "speed_multiplier"
                    ] <= bounds["speed_multiplier"][1]
                if "temperature_delta" in adapter:
                    assert bounds["temperature_delta"][0] <= adapter[
                        "temperature_delta"
                    ] <= bounds["temperature_delta"][1]
                if "pause_seconds" in adapter:
                    assert bounds["ordinary_pause_seconds"][0] <= adapter[
                        "pause_seconds"
                    ] <= bounds["ordinary_pause_seconds"][1]
                if "pitch_shift_semitones" in adapter:
                    assert (
                        adapter["pitch_shift_semitones"]
                        == bounds["pitch_shift_semitones"]
                    )


def test_neutral_adapters_are_empty_noops() -> None:
    catalog = build_tone_catalog()

    assert catalog["tones"]["general.neutral"]["adapters"] == {
        "qwen_custom_voice": {},
        "qwen_full_icl": {},
    }


def test_catalog_instructions_do_not_request_untranscribed_vocalizations() -> None:
    catalog = build_tone_catalog()
    instruction_texts = [
        adapter[field]
        for collection in (catalog["tones"], catalog["modifiers"])
        for entry in collection.values()
        for adapter in entry["adapters"].values()
        for field in ("instruct", "instruction_fragment")
        if field in adapter
    ]
    prohibited_vocalizations = (
        "喘息",
        "喘氣",
        "吸氣",
        "呼氣",
        "呻吟",
        "嘆氣",
        "嘆息",
        "笑聲",
    )

    assert instruction_texts
    assert all(
        word not in instruction
        for instruction in instruction_texts
        for word in prohibited_vocalizations
    )


def test_resolve_general_emotion_and_action_modifiers() -> None:
    tone = resolve_utterance_tone(
        emotion="curious",
        action="壓低聲音，猶豫地看向門口",
        pace="slow",
    )

    assert tone["tone_id"] == "general.puzzled"
    assert tone["modifiers"] == ["whispered", "hesitant"]
    assert tone["resolution"] == "mapped"


def test_explicit_adult_tone_requires_adult_rating() -> None:
    with pytest.raises(ToneMapError, match="requires adult_explicit"):
        resolve_utterance_tone(
            emotion="neutral",
            action="",
            pace="natural",
            tone_id="adult.intimate",
            content_rating="general",
        )


def test_adult_action_maps_without_injecting_vocalization() -> None:
    tone = resolve_utterance_tone(
        emotion="neutral",
        action="靠近耳邊，帶著壓抑的渴望輕聲說",
        pace="slow",
        content_rating="adult_explicit",
    )

    assert tone["tone_id"] == "adult.desirous"
    assert tone["modifiers"] == ["whispered", "restrained", "soft"]


def test_breathless_uses_only_phrase_and_bounded_pause_controls() -> None:
    catalog = build_tone_catalog()
    entry = catalog["tones"]["adult.breathless"]
    custom_voice = entry["adapters"]["qwen_custom_voice"]
    full_icl = entry["adapters"]["qwen_full_icl"]

    assert custom_voice["speed_multiplier"] == 1.0
    assert custom_voice["temperature_delta"] == 0.0
    assert full_icl["speed_multiplier"] == 1.0
    assert full_icl["temperature_delta"] == 0.0
    assert full_icl["expressiveness"] == "natural"
    for adapter in (custom_voice, full_icl):
        assert adapter["pause_seconds"] <= catalog["safe_bounds"][
            "ordinary_pause_seconds"
        ][1]
        assert adapter["pitch_shift_semitones"] == 0
    assert "較短語句" in custom_voice["instruct"]


@pytest.mark.parametrize(
    "action",
    ["接受邀請", "回應問題", "迫切需要幫助"],
)
def test_general_actions_do_not_map_to_adult_tones(action: str) -> None:
    tone = resolve_utterance_tone(
        emotion="neutral",
        action=action,
        pace="natural",
        content_rating="general",
    )

    assert tone["tone_id"] == "general.neutral"


@pytest.mark.parametrize(
    ("action", "expected_tone_id"),
    [
        ("在明確成人情境中接受對方", "adult.receptive"),
        ("在明確成人情境中回應對方", "adult.receptive"),
        ("在明確成人情境中迫切地要求對方", "adult.intense"),
    ],
)
def test_adult_rating_enables_adult_action_mapping(
    action: str,
    expected_tone_id: str,
) -> None:
    tone = resolve_utterance_tone(
        emotion="neutral",
        action=action,
        pace="natural",
        content_rating="adult_explicit",
    )

    assert tone["tone_id"] == expected_tone_id


def test_explicit_tone_preserves_requested_controls() -> None:
    tone = resolve_utterance_tone(
        emotion="neutral",
        action="",
        pace="natural",
        tone_id="general.tense",
        intensity=3,
        modifiers=["restrained", "firm"],
    )

    assert tone["tone_id"] == "general.tense"
    assert tone["intensity"] == 3
    assert tone["modifiers"] == ["restrained", "firm"]
    assert tone["resolution"] == "explicit"


@pytest.mark.parametrize("intensity", [0, 4, True])
def test_invalid_intensity_fails(intensity: object) -> None:
    with pytest.raises(ToneMapError) as exc_info:
        resolve_utterance_tone(
            emotion="neutral",
            action="",
            pace="natural",
            intensity=intensity,  # type: ignore[arg-type]
        )

    assert exc_info.value.error_type == "tone_intensity_invalid"


def test_invalid_or_incompatible_explicit_controls_fail() -> None:
    with pytest.raises(ToneMapError) as exc_info:
        resolve_utterance_tone(
            emotion="neutral",
            action="",
            pace="natural",
            tone_id="general.missing",
        )
    assert exc_info.value.error_type == "tone_id_invalid"

    with pytest.raises(ToneMapError) as exc_info:
        resolve_utterance_tone(
            emotion="sadness",
            action="",
            pace="slow",
            modifiers=["urgent"],
        )
    assert exc_info.value.error_type == "tone_modifier_incompatible"

    with pytest.raises(ToneMapError) as exc_info:
        resolve_utterance_tone(
            emotion="neutral",
            action="",
            pace="natural",
            modifiers=["invented"],
        )
    assert exc_info.value.error_type == "tone_modifier_invalid"


def test_unknown_automatic_emotion_falls_back_with_warning() -> None:
    tone = resolve_utterance_tone(
        emotion="mysterious_future_emotion",
        action="",
        pace="natural",
    )

    assert tone["tone_id"] == "general.neutral"
    assert tone["resolution"] == "fallback"
    assert "mysterious_future_emotion" in tone["warning"]

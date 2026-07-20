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
    assert len(catalog["tones"]) == 18
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
    assert "喘息" not in json.dumps(tone, ensure_ascii=False)


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

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import story_video_tone_pk as tone_pk


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expressive_annotation() -> dict:
    return {
        "tone_id": "general.puzzled",
        "intensity": 2,
        "pace": "quick",
        "modifiers": [],
    }


def sanitized_source_project(tmp_path: Path, *, utterance_count: int) -> Path:
    project = tmp_path / "sanitized-source"
    project.mkdir()
    story_mode = {
        "schema": "story_video_story_mode_v1",
        "mode": "creative",
        "source_text": "",
        "source_sha256": "",
        "exact_text_required": False,
    }
    _write_json(project / "story_mode.json", story_mode)
    _write_json(
        project / "cast_bible.json",
        {
            "schema": "story_video_cast_bible_v1",
            "speakers": [
                {
                    "speaker_id": "guide",
                    "display_name": "導覽員",
                    "role": "narrator",
                    "voice_id": "fixture_voice",
                }
            ],
        },
    )
    fixture_rows = [
        {
            "order": 1,
            "utterance_id": "U0001",
            "scene_id": "S01",
            "shot_id": "S01_SH01",
            "speaker_id": "guide",
            "action": "疑惑地查看地圖",
            "display_text": "這條路通往哪裡？",
            "pace": "natural",
            "tone": {
                "tone_id": "general.neutral",
                "intensity": 2,
                "modifiers": [],
                "resolution": "explicit",
                "source": {"emotion": "", "action": "", "pace": "natural"},
            },
        },
        {
            "order": 2,
            "utterance_id": "U0002",
            "scene_id": "S01",
            "shot_id": "S01_SH02",
            "speaker_id": "guide",
            "action": "急促地提醒同行者",
            "display_text": "前方天氣變化很快，請立刻回到安全的休息站，並確認所有裝備。",
            "pace": "natural",
            "tone": {
                "tone_id": "general.neutral",
                "intensity": 2,
                "modifiers": [],
                "resolution": "explicit",
                "source": {"emotion": "", "action": "", "pace": "natural"},
            },
        },
    ]
    ledger = {
        "schema": "story_video_dialogue_ledger_v2",
        "mode": "creative",
        "content_rating": "general",
        "source_sha256": "",
        "utterances": fixture_rows[:utterance_count],
    }
    _write_json(project / "dialogue_ledger.json", ledger)
    binding = {
        "schema": "story_video_voice_cast_binding_v2",
        "status": "locked",
        "language_policy": "zh-TW",
        "catalog_sha256": "f" * 64,
        "story_mode": "creative",
        "story_mode_path": str(project / "story_mode.json"),
        "story_mode_sha256": _sha256(project / "story_mode.json"),
        "cast_bible_path": str(project / "cast_bible.json"),
        "cast_bible_sha256": _sha256(project / "cast_bible.json"),
        "dialogue_ledger_path": str(project / "dialogue_ledger.json"),
        "dialogue_ledger_sha256": _sha256(project / "dialogue_ledger.json"),
        "speakers": [
            {
                "speaker_id": "guide",
                "display_name": "導覽員",
                "role": "narrator",
                "voice_id": "fixture_voice",
                "engine": "qwen_custom_voice",
                "source_kind": "preset",
                "assignment_origin": "manual",
                "engine_binding": {
                    "engine": "qwen_custom_voice",
                    "preset_speaker": "Fixture",
                },
                "variant": {},
            }
        ],
    }
    _write_json(project / "voice_cast_binding.json", binding)
    return project


def _annotations() -> dict[str, dict]:
    return {
        "U0001": expressive_annotation(),
        "U0002": {
            "tone_id": "adult.breathless",
            "intensity": 2,
            "pace": "quick",
            "modifiers": ["urgent"],
        },
    }


def test_stable_pair_seed_is_deterministic_bounded_and_chunk_specific() -> None:
    seed = tone_pk.stable_pair_seed("tone-pk-test", "U0001", 1)

    assert seed == tone_pk.stable_pair_seed("tone-pk-test", "U0001", 1)
    assert 0 <= seed <= 0x7FFFFFFF
    assert seed != tone_pk.stable_pair_seed("tone-pk-test", "U0001", 2)


def test_pair_plan_holds_seed_text_voice_and_chunks_constant(tmp_path: Path) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=2)

    plan = tone_pk.build_pair_plan(
        source_project=source,
        run_id="tone-pk-test",
        annotations=_annotations(),
        expected_utterance_count=2,
    )

    assert plan["schema"] == "story_video_tone_pk_plan_v1"
    assert [pair["pair_id"] for pair in plan["pairs"]] == ["PK-0001", "PK-0002"]
    for pair in plan["pairs"]:
        neutral = pair["neutral"]
        expressive = pair["expressive"]
        assert neutral["generation_seeds"] == expressive["generation_seeds"]
        assert neutral["spoken_text"] == expressive["spoken_text"]
        assert neutral["voice_id"] == expressive["voice_id"]
        assert neutral["canonical_voice_chunks"] == expressive["canonical_voice_chunks"]
        assert "疑惑地查看地圖" not in neutral["spoken_text"]
        assert "急促地提醒同行者" not in neutral["spoken_text"]
        assert "".join(neutral["canonical_voice_chunks"]) == neutral["spoken_text"]
        assert [row["generation_seed"] for row in neutral["voice_chunks"]] == neutral[
            "generation_seeds"
        ]
    assert max(map(len, plan["pairs"][1]["neutral"]["canonical_voice_chunks"])) <= 18


def test_pair_plan_rejects_hash_or_annotation_drift(tmp_path: Path) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=2)
    with pytest.raises(tone_pk.TonePkError, match="annotation IDs"):
        tone_pk.build_pair_plan(
            source_project=source,
            run_id="tone-pk-test",
            annotations={"U0001": expressive_annotation()},
            expected_utterance_count=2,
        )

    ledger_path = source / "dialogue_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["utterances"][0]["display_text"] = "被竄改的文字。"
    _write_json(ledger_path, ledger)
    with pytest.raises(tone_pk.TonePkError, match="dialogue ledger hash"):
        tone_pk.build_pair_plan(
            source_project=source,
            run_id="tone-pk-test",
            annotations=_annotations(),
            expected_utterance_count=2,
        )


def test_pair_plan_requires_explicit_run_local_tone_id(tmp_path: Path) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=2)
    annotations = _annotations()
    annotations["U0001"] = {
        "intensity": 2,
        "pace": "quick",
        "modifiers": [],
    }

    with pytest.raises(tone_pk.TonePkError, match="explicit non-neutral tone_id"):
        tone_pk.build_pair_plan(
            source_project=source,
            run_id="tone-pk-test",
            annotations=annotations,
            expected_utterance_count=2,
        )


def test_prepare_writes_local_variant_contracts_with_tone_only_difference(
    tmp_path: Path,
) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=2)
    annotations_path = tmp_path / "run-input" / "tone_annotations.json"
    _write_json(annotations_path, _annotations())
    output = tmp_path / "local-output"

    result = tone_pk.prepare_project(
        source_project=source,
        output_project=output,
        run_id="tone-pk-test",
        annotations_path=annotations_path,
        expected_utterance_count=2,
    )

    assert result["pair_count"] == 2
    required = [
        "manifests/tone_pk_plan.json",
        "annotations/tone_annotations.json",
        "variants/neutral/dialogue_ledger.json",
        "variants/neutral/voice_cast_binding.json",
        "variants/expressive/dialogue_ledger.json",
        "variants/expressive/voice_cast_binding.json",
    ]
    assert all((output / relative).is_file() for relative in required)
    neutral = json.loads(
        (output / "variants/neutral/dialogue_ledger.json").read_text(encoding="utf-8")
    )
    expressive = json.loads(
        (output / "variants/expressive/dialogue_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    assert neutral["schema"] == expressive["schema"] == "story_video_dialogue_ledger_v2"
    assert neutral["content_rating"] == expressive["content_rating"] == "adult_explicit"
    assert neutral["utterances"][0]["tone"]["tone_id"] == "general.neutral"
    assert expressive["utterances"][0]["tone"]["tone_id"] == "general.puzzled"
    for neutral_row, expressive_row in zip(
        neutral["utterances"], expressive["utterances"], strict=True
    ):
        neutral_tone = neutral_row.pop("tone")
        expressive_tone = expressive_row.pop("tone")
        assert neutral_row == expressive_row
        assert neutral_tone != expressive_tone
    copied_annotations = json.loads(
        (output / "annotations/tone_annotations.json").read_text(encoding="utf-8")
    )
    assert copied_annotations == _annotations()
    assert (output / "variants/neutral/story_mode.json").is_file()
    assert (output / "variants/expressive/cast_bible.json").is_file()

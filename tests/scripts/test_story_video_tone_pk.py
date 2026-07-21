from __future__ import annotations

import hashlib
import json
import copy
import re
from pathlib import Path

import pytest

from plugins.story_video.final_speech_worker import load_narration_contract
from scripts import story_video_tone_pk as tone_pk


def passing_pair_evidence(tmp_path: Path | None = None) -> dict:
    audio_root = tmp_path or Path("/sanitized")
    source_chunk_hashes = ["e" * 64]
    common = {
        "spoken_text": "同一句。",
        "spoken_text_normalization": "bounded_ellipsis_v1",
        "source_spoken_text_sha256": hashlib.sha256("同一句。".encode()).hexdigest(),
        "canonical_spoken_chunks": ["同一句。"],
        "canonical_spoken_text": "同一句。",
        "canonical_spoken_text_sha256": hashlib.sha256(
            "同一句。".encode()
        ).hexdigest(),
        "pronunciation_lexicon_sources": [],
        "pronunciation_lexicon_sha256s": [],
        "source_assembly_contract": tone_pk.SOURCE_ASSEMBLY_CONTRACT,
        "source_chunk_audio_sha256s": source_chunk_hashes,
        "source_assembly_fingerprint": tone_pk._source_assembly_fingerprint(
            source_chunk_hashes
        ),
        "source_voice_chunk_ids": ["U0007__C01"],
        "voice_id": "fixture_voice",
        "engine": "qwen_custom_voice",
        "model_id": "fixture_model",
        "profile_id": "fixture_profile",
        "profile_sha256": "a" * 64,
        "engine_binding": {"preset_speaker": "Fixture"},
        "canonical_voice_chunks": ["同一句。"],
        "generation_seeds": [123],
        "post_utterance_pause_seconds": 0.4,
        "duration_seconds": 1.2,
        "integrated_lufs": -18.1,
        "qc_status": "PASS",
    }
    neutral = {
        **common,
        "variant": "neutral",
        "take_id": "PK-0007__A",
        "adapter_status": "neutral_noop",
        "tone": {"tone_id": "general.neutral"},
        "normalized_audio_path": str(audio_root / "PK-0007__A.wav"),
        "normalized_audio_sha256": "b" * 64,
    }
    expressive = {
        **copy.deepcopy(common),
        "variant": "expressive",
        "take_id": "PK-0007__B",
        "adapter_status": "applied",
        "tone": {"tone_id": "general.puzzled"},
        "integrated_lufs": -17.8,
        "normalized_audio_path": str(audio_root / "PK-0007__B.wav"),
        "normalized_audio_sha256": "c" * 64,
    }
    for take in (neutral, expressive):
        source_audio = audio_root / f"{take['take_id']}__source.wav"
        take["source_audio_path"] = str(source_audio)
        take["source_audio_sha256"] = "d" * 64
        if tmp_path is not None:
            source_audio.write_bytes(f"source-{take['take_id']}".encode())
            normalized_audio = Path(take["normalized_audio_path"])
            normalized_audio.write_bytes(f"normalized-{take['take_id']}".encode())
            take["source_audio_sha256"] = _sha256(source_audio)
            take["normalized_audio_sha256"] = _sha256(normalized_audio)
    return {
        "pair_id": "PK-0007",
        "utterance_id": "U0007",
        "order": 7,
        "speaker_id": "guide",
        "speaker_name": "導覽員",
        "action": "疑惑地查看地圖",
        "display_text": "同一句。",
        "spoken_text": "同一句。",
        "neutral": neutral,
        "expressive": expressive,
    }


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


def sanitized_source_project(
    tmp_path: Path,
    *,
    utterance_count: int,
    first_text: str = "這條路通往哪裡？",
) -> Path:
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
            "display_text": first_text,
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


def prepared_pk_project(
    tmp_path: Path,
    *,
    utterance_count: int = 1,
    first_text: str = "這條路通往哪裡？",
) -> Path:
    source = sanitized_source_project(
        tmp_path,
        utterance_count=utterance_count,
        first_text=first_text,
    )
    annotations = {key: value for key, value in _annotations().items() if int(key[1:]) <= utterance_count}
    annotations_path = tmp_path / "annotations.json"
    _write_json(annotations_path, annotations)
    output = tmp_path / "pk-project"
    tone_pk.prepare_project(
        source_project=source,
        output_project=output,
        run_id="tone-pk-test",
        annotations_path=annotations_path,
        expected_utterance_count=utterance_count,
    )
    return output


def fake_generator_runner(
    calls: list[list[str]],
    *,
    candidate_count: int | dict[str, int] = 1,
    qc_pass: bool = True,
):
    def runner(command: list[str], **_kwargs):
        if command[0] == "ffmpeg":
            sources = [
                Path(command[index + 1])
                for index, value in enumerate(command[:-1])
                if value == "-i"
            ]
            Path(command[-1]).write_bytes(b"".join(path.read_bytes() for path in sources))
            return None
        calls.append(command)
        variant_project = next(
            Path(value)
            for value in command
            if "/variants/" in value and Path(value).is_dir()
        )
        variant = variant_project.name
        ledger = json.loads(
            (variant_project / "dialogue_ledger.json").read_text(encoding="utf-8")
        )
        binding = json.loads(
            (variant_project / "voice_cast_binding.json").read_text(encoding="utf-8")
        )
        speaker = binding["speakers"][0]
        prior_chunks: dict[str, dict[str, Any]] = {}
        prior_manifest_path = variant_project / "manifests" / "narration_manifest.json"
        if prior_manifest_path.is_file():
            prior_manifest = json.loads(prior_manifest_path.read_text(encoding="utf-8"))
            prior_chunks = {
                chunk["voice_chunk_id"]: chunk
                for chunk in tone_pk._flatten_voice_chunks(prior_manifest)
            }
        repair_ids = {
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--repair-shot"
        }
        known_repair_ids = {
            str(utterance.get("shot_id") or "")
            for utterance in ledger["utterances"]
        }
        unknown_repair_ids = repair_ids - known_repair_ids
        if unknown_repair_ids:
            raise tone_pk.subprocess.CalledProcessError(1, command)
        chunks = []
        requested_voice_chunk_ids = []
        for utterance in ledger["utterances"]:
            generated_candidate_count = (
                candidate_count[utterance["utterance_id"]]
                if isinstance(candidate_count, dict)
                else candidate_count
            )
            requested = not repair_ids or utterance["shot_id"] in repair_ids
            for index, text in enumerate(utterance["canonical_voice_chunks"], start=1):
                voice_chunk_id = f"{utterance['utterance_id']}__C{index:02d}"
                audio = (
                    variant_project
                    / "audio"
                    / "segments"
                    / f"{utterance['utterance_id']}__C{index:02d}.wav"
                )
                audio.parent.mkdir(parents=True, exist_ok=True)
                if requested:
                    audio.write_bytes(
                        f"{variant}-{utterance['utterance_id']}-{len(calls)}".encode()
                    )
                    requested_voice_chunk_ids.append(
                        voice_chunk_id
                    )
                prior = prior_chunks.get(voice_chunk_id, {})
                baseline_count = int(prior.get("candidate_count") or 0)
                new_candidate_count = generated_candidate_count if requested else 0
                cumulative_candidate_count = baseline_count + new_candidate_count
                lineage = {
                    "schema": "story_video_candidate_lineage_v1",
                    "generation_mode": "selective_repair" if repair_ids else "full",
                    "requested": requested,
                    "baseline_candidate_count": baseline_count,
                    "new_candidate_count": new_candidate_count,
                    "cumulative_candidate_count": cumulative_candidate_count,
                    "output_audio_sha256": _sha256(audio),
                }
                lineage["lineage_sha256"] = hashlib.sha256(
                    json.dumps(
                        lineage,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                tone = utterance["tone"]
                chunks.append(
                    {
                        "voice_chunk_id": voice_chunk_id,
                        "utterance_id": utterance["utterance_id"],
                        "speaker_id": utterance["speaker_id"],
                        "voice_id": speaker["voice_id"],
                        "engine": speaker["engine"],
                        "profile_id": speaker.get("profile_id", ""),
                        "profile_sha256": speaker.get("profile_sha256", ""),
                        "display_text": text,
                        "spoken_text": text,
                        "audio": str(audio),
                        "generation_seed": utterance["generation_seeds"][index - 1],
                        "speech_duration_sec": 0.4,
                        "resolved_pause_after_sec": 0.2,
                        "tone": tone,
                        "tone_application": {
                            "adapter_status": (
                                "neutral_noop" if variant == "neutral" else "applied"
                            )
                        },
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS" if qc_pass else "FAIL",
                        "prosody_status": "PASS",
                        "fluency_status": "PASS",
                        "qc_status": "PASS" if qc_pass else "FAIL",
                        "audio_sha256": _sha256(audio),
                        "candidate_count": cumulative_candidate_count,
                        "selected_candidate": cumulative_candidate_count,
                        "candidate_lineage": lineage,
                    }
                )
        manifest = {
            "schema": "story_video_narration_manifest_v7",
            "run_id": "tone-pk-test",
            "model": "fixture_model",
            "spoken_text_normalization": "bounded_ellipsis_v1",
            "pronunciation_qc_report": str(
                variant_project / "qc" / "pronunciation_qc_report.json"
            ),
            "voice_chunk_count": len(chunks),
            "candidate_lineage_schema": "story_video_candidate_lineage_v1",
            "requested_voice_chunk_ids": sorted(requested_voice_chunk_ids),
            "generation_mode": "selective_repair" if repair_ids else "full",
            "outputs": [
                {
                    "spoken_text": "".join(row["spoken_text"] for row in chunks),
                    "segments": [{"voice_chunks": chunks}],
                }
            ],
        }
        _write_json(
            variant_project / "qc" / "pronunciation_qc_report.json",
            {
                "schema": "story_video_pronunciation_qc_v3",
                "lexicon_sources": [],
            },
        )
        _write_json(variant_project / "manifests" / "narration_manifest.json", manifest)

        class Result:
            returncode = 0

        return Result()

    return runner


@pytest.mark.parametrize(
    ("source", "generator_expected"),
    [
        ("停……〉。", "停，〉。"),
        ("停……〉", "停，〉"),
        ("停—〉。", "停，〉。"),
        ("停—〉", "停，〉"),
    ],
)
def test_bounded_ellipsis_closing_marks_match_generator_contract(
    source: str,
    generator_expected: str,
) -> None:
    assert tone_pk._CLOSING_MARKS == "」』”’\"'】）》）]"
    assert tone_pk.normalize_synthesis_spoken_text(source) == generator_expected


def test_generate_rejects_missing_pronunciation_qc_report(tmp_path: Path) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    base_runner = fake_generator_runner([])

    def missing_report_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        if command[0] == "ffmpeg":
            return result
        variant_project = next(
            Path(value)
            for value in command
            if "/variants/" in value and Path(value).is_dir()
        )
        manifest_path = variant_project / "manifests" / "narration_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("pronunciation_qc_report")
        _write_json(manifest_path, manifest)
        return result

    with pytest.raises(tone_pk.TonePkError, match="pronunciation QC report"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=missing_report_runner,
        )


def _seed_existing_variant_manifests(
    project: Path,
    generator: Path,
    *,
    qc_pass: bool,
) -> None:
    fixture_runner = fake_generator_runner([], qc_pass=qc_pass)
    for variant in ("neutral", "expressive"):
        fixture_runner([str(generator), str(project / "variants" / variant)])


def _set_manifest_utterance_qc(
    project: Path,
    *,
    variant: str,
    utterance_id: str,
    passed: bool,
) -> None:
    path = project / "variants" / variant / "manifests" / "narration_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    status = "PASS" if passed else "FAIL"
    for output in manifest["outputs"]:
        for segment in output["segments"]:
            for chunk in segment["voice_chunks"]:
                if chunk["utterance_id"] != utterance_id:
                    continue
                chunk["pronunciation_status"] = status
                chunk["qc_status"] = status
    _write_json(path, manifest)


def _set_manifest_candidate_count(
    project: Path,
    *,
    variant: str,
    utterance_id: str,
    candidate_count: int,
) -> None:
    path = project / "variants" / variant / "manifests" / "narration_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for chunk in tone_pk._flatten_voice_chunks(manifest):
        if chunk["utterance_id"] != utterance_id:
            continue
        chunk["candidate_count"] = candidate_count
        chunk["selected_candidate"] = candidate_count
        lineage = chunk["candidate_lineage"]
        lineage.update(
            {
                "baseline_candidate_count": 0,
                "new_candidate_count": candidate_count,
                "cumulative_candidate_count": candidate_count,
            }
        )
        canonical = {key: value for key, value in lineage.items() if key != "lineage_sha256"}
        lineage["lineage_sha256"] = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    _write_json(path, manifest)


def test_generate_resume_ingests_existing_pass_manifests_without_runner(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    _seed_existing_variant_manifests(project, generator, qc_pass=True)

    result = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
    )

    assert result["status"] == "PASS"
    assert result["generated_take_count"] == 0
    assert result["ingested_existing_take_count"] == 2


def test_generate_resume_ingests_existing_fail_manifests_before_guidance(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    _seed_existing_variant_manifests(project, generator, qc_pass=False)

    with pytest.raises(tone_pk.TonePkError, match="use qc --repair-failed"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )

    status = tone_pk._status_command(type("Args", (), {"project": project})())
    assert status["ingested_source_take_count"] == 2
    assert status["source_qc_pass_take_count"] == 0
    assert status["candidate_evidence_take_count"] == 2


def test_generate_resume_rejects_existing_drift_before_runner(tmp_path: Path) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    _seed_existing_variant_manifests(project, generator, qc_pass=True)
    manifest_path = project / "variants" / "neutral/manifests/narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
    chunk["spoken_text"] = "未授權改字。"
    _write_json(manifest_path, manifest)

    with pytest.raises(tone_pk.TonePkError, match="changed spoken text"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )


def test_neutral_fail_preingest_persists_generator_for_direct_repair(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    fixture_runner = fake_generator_runner([], qc_pass=False)
    fixture_runner([str(generator), str(project / "variants" / "neutral")])

    with pytest.raises(tone_pk.TonePkError, match="use qc --repair-failed"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )

    checkpoint = json.loads(
        (project / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["generator_path"] == str(generator.resolve())
    repair_calls: list[list[str]] = []
    result = tone_pk.repair_failed_takes(
        project,
        max_candidates=3,
        runner=fake_generator_runner(repair_calls),
    )
    assert result["status"] == "PASS"
    assert any(str(generator.resolve()) in command for command in repair_calls)


def test_generate_resume_reconciles_manifest_fail_over_green_checkpoint(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    manifest_path = project / "variants" / "neutral/manifests/narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
    chunk["pronunciation_status"] = "FAIL"
    chunk["qc_status"] = "FAIL"
    _write_json(manifest_path, manifest)

    with pytest.raises(tone_pk.TonePkError, match="use qc --repair-failed"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )

    checkpoint = json.loads(
        (project / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["pairs"][0]["neutral"]["qc_status"] == "FAIL"


def test_generate_resume_backfills_old_checkpoint_canonical_evidence(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests" / "tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    canonical_fields = (
        "spoken_text_normalization",
        "source_spoken_text_sha256",
        "canonical_spoken_chunks",
        "canonical_spoken_text",
        "canonical_spoken_text_sha256",
        "pronunciation_lexicon_sources",
        "pronunciation_lexicon_sha256s",
    )
    for field in canonical_fields:
        state["pairs"][0]["neutral"].pop(field)
    _write_json(state_path, state)

    result = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
    )

    assert result["generated_take_count"] == 0
    refreshed = json.loads(state_path.read_text(encoding="utf-8"))
    assert all(field in refreshed["pairs"][0]["neutral"] for field in canonical_fields)


def test_generate_resume_rejects_changed_chunk_without_candidate_lineage(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    _seed_existing_variant_manifests(project, generator, qc_pass=False)
    with pytest.raises(tone_pk.TonePkError, match="use qc --repair-failed"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )
    state_path = project / "manifests" / "tone_pk_manifest.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    take_before = before["pairs"][0]["neutral"]
    old_source_hash = take_before["source_audio_sha256"]
    manifest_path = project / "variants" / "neutral/manifests/narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
    chunk_audio = Path(chunk["audio"])
    chunk_audio.write_bytes(b"replacement-verified-chunk")
    chunk["audio_sha256"] = _sha256(chunk_audio)
    for gate in (
        "alignment_status",
        "pronunciation_status",
        "prosody_status",
        "fluency_status",
        "qc_status",
    ):
        chunk[gate] = "PASS"
    _write_json(manifest_path, manifest)

    with pytest.raises(tone_pk.TonePkError, match="candidate lineage"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )

    after = json.loads(state_path.read_text(encoding="utf-8"))
    neutral = after["pairs"][0]["neutral"]
    assert neutral["qc_status"] == "FAIL"
    assert neutral["source_audio_sha256"] == old_source_hash


def test_generate_resume_rejects_post_synthesis_pre_manifest_crash(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    fixture_runner = fake_generator_runner([], qc_pass=False)
    fixture_runner([str(generator), str(project / "variants" / "neutral")])
    with pytest.raises(tone_pk.TonePkError, match="use qc --repair-failed"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )
    manifest_path = project / "variants" / "neutral/manifests/narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
    audio = Path(chunk["audio"])
    audio.write_bytes(audio.read_bytes() + b"-crash-window")

    with pytest.raises(tone_pk.TonePkError, match="audio hash"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )


def test_generate_accepts_exact_bounded_ellipsis_normalization_and_records_hashes(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, first_text="等等……真的嗎？")
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    base_runner = fake_generator_runner([])

    def bounded_ellipsis_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        if command[0] == "ffmpeg":
            return result
        variant_project = next(
            Path(value)
            for value in command
            if "/variants/" in value and Path(value).is_dir()
        )
        path = variant_project / "manifests" / "narration_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
        chunk["spoken_text"] = "等等，真的嗎？"
        manifest["outputs"][0]["spoken_text"] = chunk["spoken_text"]
        _write_json(path, manifest)
        return result

    result = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=bounded_ellipsis_runner,
    )

    assert result["generated_take_count"] == 2
    state = json.loads(
        (project / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    pair = state["pairs"][0]
    for variant in ("neutral", "expressive"):
        take = pair[variant]
        assert take["spoken_text_normalization"] == "bounded_ellipsis_v1"
        assert take["canonical_spoken_chunks"] == ["等等，真的嗎？"]
        assert take["canonical_spoken_text"] == "等等，真的嗎？"
        assert take["source_spoken_text_sha256"] == hashlib.sha256(
            "等等……真的嗎？".encode()
        ).hexdigest()
        assert take["canonical_spoken_text_sha256"] == hashlib.sha256(
            "等等，真的嗎？".encode()
        ).hexdigest()


def test_generate_rejects_lexical_drift_after_bounded_ellipsis_normalization(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, first_text="等等……真的嗎？")
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    base_runner = fake_generator_runner([])

    def lexical_drift_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        if command[0] == "ffmpeg":
            return result
        variant_project = next(
            Path(value)
            for value in command
            if "/variants/" in value and Path(value).is_dir()
        )
        path = variant_project / "manifests" / "narration_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
        chunk["spoken_text"] = "等等，不是嗎？"
        manifest["outputs"][0]["spoken_text"] = chunk["spoken_text"]
        _write_json(path, manifest)
        return result

    with pytest.raises(tone_pk.TonePkError, match="changed spoken text"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lexical_drift_runner,
        )


def test_generate_accepts_only_pronunciation_substitution_anchored_to_lexicon(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, first_text="甲詞請再說一次。")
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    base_runner = fake_generator_runner([])

    def pronunciation_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        if command[0] == "ffmpeg":
            return result
        variant_project = next(
            Path(value)
            for value in command
            if "/variants/" in value and Path(value).is_dir()
        )
        lexicon_path = variant_project / "pronunciation_lexicon.json"
        entry = {
            "display": "甲詞",
            "spoken": "乙詞",
            "expected_pinyin": "fixture",
            "source": "reviewed_fixture",
            "risk": "medium",
        }
        _write_json(
            lexicon_path,
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [entry],
            },
        )
        report_path = variant_project / "qc" / "pronunciation_qc_report.json"
        _write_json(
            report_path,
            {
                "schema": "story_video_pronunciation_qc_v3",
                "lexicon_sources": [str(lexicon_path)],
            },
        )
        manifest_path = variant_project / "manifests" / "narration_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
        chunk["spoken_text"] = "乙詞請再說一次。"
        chunk["pronunciation_entries"] = [entry]
        chunk["pronunciation_rules"] = [entry["display"]]
        manifest["outputs"][0]["spoken_text"] = chunk["spoken_text"]
        manifest["pronunciation_qc_report"] = str(report_path)
        _write_json(manifest_path, manifest)
        return result

    result = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=pronunciation_runner,
    )

    assert result["generated_take_count"] == 2
    state = json.loads(
        (project / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    for variant in ("neutral", "expressive"):
        take = state["pairs"][0][variant]
        assert take["canonical_spoken_chunks"] == ["乙詞請再說一次。"]
        assert len(take["pronunciation_lexicon_sha256s"]) == 1


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


def test_pair_plan_uses_explicit_empty_modifiers_without_action_inference(
    tmp_path: Path,
) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=2)
    annotations = _annotations()
    annotations["U0002"]["modifiers"] = []

    plan = tone_pk.build_pair_plan(
        source_project=source,
        run_id="tone-pk-test",
        annotations=annotations,
        expected_utterance_count=2,
    )

    assert plan["pairs"][1]["action"] == "急促地提醒同行者"
    assert plan["pairs"][1]["expressive"]["tone"]["modifiers"] == []


@pytest.mark.parametrize("modifier_value", ["missing", None])
def test_pair_plan_rejects_missing_or_null_run_local_modifiers(
    tmp_path: Path,
    modifier_value: object,
) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=2)
    annotations = _annotations()
    if modifier_value == "missing":
        annotations["U0002"].pop("modifiers")
    else:
        annotations["U0002"]["modifiers"] = modifier_value

    with pytest.raises(tone_pk.TonePkError, match="explicit modifiers list"):
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


def test_prepare_accepts_hash_locked_v1_source_and_upgrades_variant_ledgers(
    tmp_path: Path,
) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=2)
    ledger_path = source / "dialogue_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["schema"] = "story_video_dialogue_ledger_v1"
    _write_json(ledger_path, ledger)
    binding_path = source / "voice_cast_binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["dialogue_ledger_sha256"] = _sha256(ledger_path)
    _write_json(binding_path, binding)
    annotations_path = tmp_path / "tone_annotations.json"
    _write_json(annotations_path, _annotations())
    output = tmp_path / "local-output"

    result = tone_pk.prepare_project(
        source_project=source,
        output_project=output,
        run_id="tone-pk-v1-source",
        annotations_path=annotations_path,
        expected_utterance_count=2,
    )

    assert result["pair_count"] == 2
    plan = json.loads(
        (output / "manifests/tone_pk_plan.json").read_text(encoding="utf-8")
    )
    assert plan["source_binding"]["dialogue_ledger_sha256"] == _sha256(ledger_path)
    for variant in ("neutral", "expressive"):
        variant_ledger = json.loads(
            (output / f"variants/{variant}/dialogue_ledger.json").read_text(
                encoding="utf-8"
            )
        )
        assert variant_ledger["schema"] == "story_video_dialogue_ledger_v2"


def test_prepare_rejects_unknown_source_ledger_schema(tmp_path: Path) -> None:
    source = sanitized_source_project(tmp_path, utterance_count=1)
    ledger_path = source / "dialogue_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["schema"] = "story_video_dialogue_ledger_v99"
    _write_json(ledger_path, ledger)
    binding_path = source / "voice_cast_binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["dialogue_ledger_sha256"] = _sha256(ledger_path)
    _write_json(binding_path, binding)

    with pytest.raises(tone_pk.TonePkError, match="schema is unsupported"):
        tone_pk.build_pair_plan(
            source_project=source,
            run_id="tone-pk-unknown-source",
            annotations={"U0001": expressive_annotation()},
            expected_utterance_count=1,
        )


def _prepared_short_replan_source(tmp_path: Path) -> tuple[Path, dict]:
    project = prepared_pk_project(
        tmp_path,
        utterance_count=2,
        first_text="甲乙丙丁戊己庚辛壬癸，甲乙丙丁。",
    )
    generator = tmp_path / "generator.py"
    generator.write_text("# fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests" / "tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for pair in state["pairs"]:
        for variant in ("neutral", "expressive"):
            take = pair[variant]
            take["normalized_audio_path"] = take["source_audio_path"]
            take["normalized_audio_sha256"] = take["source_audio_sha256"]
            take["integrated_lufs"] = -18.0
    state["pairs"][0]["neutral"]["qc_status"] = "FAIL"
    tone_pk.write_checkpoint(
        project,
        state["pairs"],
        run_id=state["run_id"],
        metadata={"generator_path": state["generator_path"]},
    )
    return project, json.loads(state_path.read_text(encoding="utf-8"))


def test_short_replan_resets_only_failed_pair_and_reuses_green_evidence(
    tmp_path: Path,
) -> None:
    source, before = _prepared_short_replan_source(tmp_path)
    overrides = tone_pk.build_failed_short_chunk_overrides(source, max_chars=12)
    output = tmp_path / "short-v2"

    result = tone_pk.replan_failed_pairs_short(
        source_project=source,
        output_project=output,
        overrides=overrides,
        max_chars=12,
    )

    assert result == {
        "schema": "story_video_tone_pk_short_replan_result_v1",
        "status": "READY_FOR_GENERATION",
        "affected_pair_count": 1,
        "reused_pair_count": 1,
        "candidate_budget_start": 1,
        "candidate_budget_cap": 3,
        "output_project": str(output.resolve()),
    }
    plan = json.loads(
        (output / "manifests" / "tone_pk_plan.json").read_text(encoding="utf-8")
    )
    after = json.loads(
        (output / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    affected_plan = plan["pairs"][0]
    affected_state = after["pairs"][0]
    reused_state = after["pairs"][1]
    assert affected_plan["neutral"]["canonical_voice_chunks"] == affected_plan[
        "expressive"
    ]["canonical_voice_chunks"]
    assert affected_plan["neutral"]["generation_seeds"] == affected_plan[
        "expressive"
    ]["generation_seeds"]
    assert "candidate_count" not in affected_state["neutral"]
    assert "source_audio_path" not in affected_state["neutral"]
    assert "normalized_audio_path" not in affected_state["neutral"]
    assert "qc_status" not in affected_state["neutral"]
    assert reused_state == before["pairs"][1]
    assert all(
        len(chunk) <= 12
        for chunk in affected_plan["neutral"]["canonical_voice_chunks"]
    )
    assert "plan_revision" in plan
    assert plan["plan_revision"]["candidate_budget"] == {"start": 1, "cap": 3}
    archive = json.loads(
        (output / "archive" / "short_replan_v2" / "affected_pairs.json").read_text(
            encoding="utf-8"
        )
    )
    assert archive["pairs"] == [before["pairs"][0]]
    assert (
        output / "annotations" / "short_chunk_overrides.json"
    ).read_text(encoding="utf-8") == json.dumps(
        overrides, ensure_ascii=False, indent=2
    ) + "\n"


def test_short_replan_preserves_exact_ab_text_voice_tone_and_chunk_concat(
    tmp_path: Path,
) -> None:
    source, before = _prepared_short_replan_source(tmp_path)
    overrides = tone_pk.build_failed_short_chunk_overrides(source, max_chars=12)
    output = tmp_path / "short-v2"

    tone_pk.replan_failed_pairs_short(
        source_project=source,
        output_project=output,
        overrides=overrides,
        max_chars=12,
    )

    after = json.loads(
        (output / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    pair = after["pairs"][0]
    old_pair = before["pairs"][0]
    for field in ("spoken_text", "voice_id", "engine", "profile_id", "profile_sha256"):
        assert pair["neutral"][field] == old_pair["neutral"][field]
        assert pair["expressive"][field] == old_pair["expressive"][field]
    assert pair["neutral"]["tone"] == old_pair["neutral"]["tone"]
    assert pair["expressive"]["tone"] == old_pair["expressive"]["tone"]
    assert pair["neutral"]["canonical_voice_chunks"] == pair["expressive"][
        "canonical_voice_chunks"
    ]
    assert "".join(pair["neutral"]["canonical_voice_chunks"]) == pair["spoken_text"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload["pairs"].clear(), "override pair IDs"),
        (
            lambda payload: payload["pairs"]["PK-0001"].__setitem__(0, "錯誤"),
            "changed canonical text",
        ),
        (
            lambda payload: payload["pairs"]["PK-0001"].__setitem__(
                0, "甲" * 13
            ),
            "exceeds 12",
        ),
        (
            lambda payload: payload.__setitem__("source_manifest_sha256", "0" * 64),
            "manifest hash",
        ),
    ],
)
def test_short_replan_rejects_invalid_or_drifted_override(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    source, _before = _prepared_short_replan_source(tmp_path)
    overrides = tone_pk.build_failed_short_chunk_overrides(source, max_chars=12)
    mutate(overrides)

    with pytest.raises(tone_pk.TonePkError, match=message):
        tone_pk.replan_failed_pairs_short(
            source_project=source,
            output_project=tmp_path / "short-v2",
            overrides=overrides,
            max_chars=12,
        )


def _prepared_short_v2(tmp_path: Path) -> tuple[Path, dict]:
    source, before = _prepared_short_replan_source(tmp_path)
    output = tmp_path / "short-v2"
    tone_pk.replan_failed_pairs_short(
        source_project=source,
        output_project=output,
        overrides=tone_pk.build_failed_short_chunk_overrides(
            source,
            max_chars=12,
        ),
        max_chars=12,
    )
    return output, before


def test_short_replan_blocks_legacy_partial_generation_without_prior_manifest(
    tmp_path: Path,
) -> None:
    project, _before = _prepared_short_v2(tmp_path)
    generator = tmp_path / "generator.py"
    generator.write_text("# fixture\n", encoding="utf-8")

    with pytest.raises(tone_pk.TonePkError, match="fresh short-replan generation"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )


def test_fresh_short_replan_generation_filters_provider_scope_and_ingests_ab(
    tmp_path: Path,
) -> None:
    project, before = _prepared_short_v2(tmp_path)
    generator = tmp_path / "generator.py"
    generator.write_text("# fixture\n", encoding="utf-8")
    calls: list[list[str]] = []
    base_runner = fake_generator_runner(calls)
    provider_utterance_ids: list[set[str]] = []

    def scoped_runner(command: list[str], **kwargs):
        if command[0] == "ffmpeg":
            return base_runner(command, **kwargs)
        assert "--repair-shot" not in command
        assert command[-2:] == ["--max-acoustic-retries", "0"] or (
            "--max-acoustic-retries" in command
            and command[command.index("--max-acoustic-retries") + 1] == "0"
        )
        assert "--emit-failed-qc-manifest" in command
        scratch = next(
            Path(value)
            for value in command
            if "/scratch/short_replan_v2/variants/" in value
            and Path(value).is_dir()
        )
        ledger = json.loads(
            (scratch / "dialogue_ledger.json").read_text(encoding="utf-8")
        )
        provider_utterance_ids.append(
            {str(row["utterance_id"]) for row in ledger["utterances"]}
        )
        return base_runner(command, **kwargs)

    result = tone_pk.generate_fresh_replanned_takes(
        project,
        generator,
        runner=scoped_runner,
    )

    assert result["status"] == "PASS"
    assert result["generated_take_count"] == 2
    assert result["affected_pair_count"] == 1
    assert len(provider_utterance_ids) == 2
    assert provider_utterance_ids[0] == provider_utterance_ids[1]
    assert provider_utterance_ids[0] == {before["pairs"][0]["utterance_id"]}
    state = json.loads(
        (project / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["pairs"][1] == before["pairs"][1]
    for variant in ("neutral", "expressive"):
        take = state["pairs"][0][variant]
        assert take["candidate_count"] == 1
        assert take["selected_candidate"] == 1
        assert take["qc_status"] == "PASS"
        assert tone_pk._artifact_hash_matches(
            take["source_audio_path"],
            take["source_audio_sha256"],
        )
        scratch_manifest = (
            project
            / "scratch"
            / "short_replan_v2"
            / "variants"
            / variant
            / "manifests"
            / "narration_manifest.json"
        )
        assert scratch_manifest.is_file()


def test_fresh_short_replan_rejects_invalid_scratch_audio_hash(
    tmp_path: Path,
) -> None:
    project, before = _prepared_short_v2(tmp_path)
    generator = tmp_path / "generator.py"
    generator.write_text("# fixture\n", encoding="utf-8")
    base_runner = fake_generator_runner([])

    def corrupting_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        scratch = next(
            Path(value)
            for value in command
            if "/scratch/short_replan_v2/variants/" in value
            and Path(value).is_dir()
        )
        manifest = json.loads(
            (scratch / "manifests/narration_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        audio = Path(tone_pk._flatten_voice_chunks(manifest)[0]["audio"])
        audio.write_bytes(audio.read_bytes() + b"-corrupt")
        return result

    with pytest.raises(tone_pk.TonePkError, match="audio hash"):
        tone_pk.generate_fresh_replanned_takes(
            project,
            generator,
            runner=corrupting_runner,
        )

    state = json.loads(
        (project / "manifests" / "tone_pk_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["pairs"][1] == before["pairs"][1]
    assert "candidate_count" not in state["pairs"][0]["neutral"]


def test_fresh_short_replan_resumes_after_neutral_without_recalling_provider(
    tmp_path: Path,
) -> None:
    project, before = _prepared_short_v2(tmp_path)
    generator = tmp_path / "generator.py"
    generator.write_text("# fixture\n", encoding="utf-8")
    first_calls: list[list[str]] = []
    first_base = fake_generator_runner(first_calls)

    def fail_expressive(command: list[str], **kwargs):
        if command[0] != "ffmpeg" and "/variants/expressive" in command[2]:
            raise OSError("fixture expressive interruption")
        return first_base(command, **kwargs)

    with pytest.raises(tone_pk.TonePkError, match="expressive fresh"):
        tone_pk.generate_fresh_replanned_takes(
            project,
            generator,
            runner=fail_expressive,
        )

    interrupted = json.loads(
        (project / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    assert interrupted["pairs"][0]["neutral"]["candidate_count"] == 1
    assert "candidate_count" not in interrupted["pairs"][0]["expressive"]

    resumed_calls: list[list[str]] = []
    result = tone_pk.generate_fresh_replanned_takes(
        project,
        generator,
        runner=fake_generator_runner(resumed_calls),
    )

    assert result["status"] == "PASS"
    assert result["generated_take_count"] == 1
    assert len(resumed_calls) == 1
    assert "/variants/expressive" in resumed_calls[0][2]
    state = json.loads(
        (project / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    assert state["pairs"][1] == before["pairs"][1]


def test_fresh_short_replan_resume_rejects_corrupt_completed_neutral(
    tmp_path: Path,
) -> None:
    project, _before = _prepared_short_v2(tmp_path)
    generator = tmp_path / "generator.py"
    generator.write_text("# fixture\n", encoding="utf-8")
    first_base = fake_generator_runner([])

    def fail_expressive(command: list[str], **kwargs):
        if command[0] != "ffmpeg" and "/variants/expressive" in command[2]:
            raise OSError("fixture expressive interruption")
        return first_base(command, **kwargs)

    with pytest.raises(tone_pk.TonePkError, match="expressive fresh"):
        tone_pk.generate_fresh_replanned_takes(
            project,
            generator,
            runner=fail_expressive,
        )
    manifest_path = (
        project
        / "scratch/short_replan_v2/variants/neutral/manifests/narration_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audio = Path(tone_pk._flatten_voice_chunks(manifest)[0]["audio"])
    audio.write_bytes(audio.read_bytes() + b"-corrupt")

    with pytest.raises(tone_pk.TonePkError, match="audio hash"):
        tone_pk.generate_fresh_replanned_takes(
            project,
            generator,
            runner=lambda *_args, **_kwargs: pytest.fail("provider runner called"),
        )


@pytest.mark.parametrize("repair_passes", [True, False])
def test_short_replan_repair_uses_scratch_lineage_and_preserves_reused_pairs(
    tmp_path: Path,
    repair_passes: bool,
) -> None:
    project, before = _prepared_short_v2(tmp_path)
    generator = tmp_path / "generator.py"
    generator.write_text("# fixture\n", encoding="utf-8")
    fresh = tone_pk.generate_fresh_replanned_takes(
        project,
        generator,
        runner=fake_generator_runner([], qc_pass=False),
    )
    assert fresh["status"] == "FAIL"
    repair_calls: list[list[str]] = []
    repair_runner = fake_generator_runner(repair_calls, qc_pass=repair_passes)

    if repair_passes:
        result = tone_pk.repair_failed_takes(
            project,
            max_candidates=3,
            runner=repair_runner,
        )
        assert result["status"] == "PASS"
    else:
        with pytest.raises(tone_pk.TonePkError, match="failed takes remain"):
            tone_pk.repair_failed_takes(
                project,
                max_candidates=3,
                runner=repair_runner,
            )

    assert len(repair_calls) == 2
    for command in repair_calls:
        assert "/scratch/short_replan_v2/variants/" in command[2]
        assert "/short-v2/variants/" not in command[2]
        assert command.count("--repair-shot") == 1
        assert command[command.index("--max-acoustic-retries") + 1] == "1"
    state = json.loads(
        (project / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    assert state["pairs"][1] == before["pairs"][1]
    expected_status = "PASS" if repair_passes else "FAIL"
    for variant in ("neutral", "expressive"):
        take = state["pairs"][0][variant]
        assert take["candidate_count"] == 2
        assert take["selected_candidate"] == 2
        assert take["qc_status"] == expected_status


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda pair: pair["expressive"]["generation_seeds"].__setitem__(0, 124), "generation seed"),
        (lambda pair: pair["expressive"].__setitem__("spoken_text", "不同句。"), "spoken text"),
        (lambda pair: pair["expressive"].__setitem__("voice_id", "other"), "voice"),
        (lambda pair: pair["expressive"].__setitem__("integrated_lufs", -17.0), "loudness"),
    ],
)
def test_pair_qc_rejects_voice_seed_text_chunk_or_loudness_drift(
    mutation,
    message: str,
) -> None:
    pair = passing_pair_evidence()
    mutation(pair)

    with pytest.raises(tone_pk.TonePkError, match=message):
        tone_pk.validate_pair_evidence(pair)


def test_pair_qc_rejects_long_pause_or_invalid_tone_adapter() -> None:
    pair = passing_pair_evidence()
    pair["expressive"]["post_utterance_pause_seconds"] = 0.46
    with pytest.raises(tone_pk.TonePkError, match="pause"):
        tone_pk.validate_pair_evidence(pair)

    pair = passing_pair_evidence()
    pair["neutral"]["adapter_status"] = "applied"
    with pytest.raises(tone_pk.TonePkError, match="neutral adapter"):
        tone_pk.validate_pair_evidence(pair)


def test_pair_qc_accepts_distinct_paths_for_identical_pronunciation_lexicons(
    tmp_path: Path,
) -> None:
    pair = passing_pair_evidence(tmp_path)
    lexicon = {
        "schema": "story_video_pronunciation_lexicon_v1",
        "language": "zh-TW",
        "review_status": "PASS",
        "entries": [
            {
                "display": "甲詞",
                "spoken": "乙詞",
                "expected_pinyin": "fixture",
                "source": "reviewed_fixture",
                "risk": "medium",
            }
        ],
    }
    paths = [tmp_path / variant / "pronunciation_lexicon.json" for variant in ("a", "b")]
    for path in paths:
        _write_json(path, lexicon)
    lexicon_hash = _sha256(paths[0])
    pair["spoken_text"] = "甲詞。"
    for take, path in zip(
        (pair["neutral"], pair["expressive"]),
        paths,
        strict=True,
    ):
        take.update(
            {
                "spoken_text": "甲詞。",
                "source_spoken_text_sha256": hashlib.sha256(
                    "甲詞。".encode()
                ).hexdigest(),
                "canonical_voice_chunks": ["甲詞。"],
                "canonical_spoken_chunks": ["乙詞。"],
                "canonical_spoken_text": "乙詞。",
                "canonical_spoken_text_sha256": hashlib.sha256(
                    "乙詞。".encode()
                ).hexdigest(),
                "pronunciation_lexicon_sources": [str(path)],
                "pronunciation_lexicon_sha256s": [lexicon_hash],
            }
        )

    assert tone_pk.validate_pair_evidence(pair)["pair_id"] == pair["pair_id"]


def test_pair_qc_rejects_missing_source_assembly_fingerprint() -> None:
    pair = passing_pair_evidence()
    for variant in ("neutral", "expressive"):
        pair[variant].pop("source_assembly_fingerprint")

    with pytest.raises(tone_pk.TonePkError, match="source assembly evidence"):
        tone_pk.validate_pair_evidence(pair)


def _two_chunk_pair_evidence() -> dict:
    pair = passing_pair_evidence()
    pair["spoken_text"] = "同一句。"
    for take in (pair["neutral"], pair["expressive"]):
        take["canonical_voice_chunks"] = ["同一", "句。"]
        take["canonical_spoken_chunks"] = ["同一", "句。"]
        take["generation_seeds"] = [123, 456]
        take["source_voice_chunk_ids"] = ["U0007__C01", "U0007__C02"]
        hashes = ["e" * 64, "f" * 64]
        take["source_chunk_audio_sha256s"] = hashes
        take["source_assembly_fingerprint"] = tone_pk._source_assembly_fingerprint(
            hashes
        )
    return pair


def test_pair_qc_rejects_partial_source_chunk_hash_list_with_valid_fingerprint() -> None:
    pair = _two_chunk_pair_evidence()
    partial_hashes = ["e" * 64]
    pair["neutral"]["source_chunk_audio_sha256s"] = partial_hashes
    pair["neutral"]["source_assembly_fingerprint"] = (
        tone_pk._source_assembly_fingerprint(partial_hashes)
    )

    with pytest.raises(tone_pk.TonePkError, match="source assembly chunk evidence"):
        tone_pk.validate_pair_evidence(pair)


def test_pair_qc_rejects_duplicate_source_voice_chunk_ids() -> None:
    pair = _two_chunk_pair_evidence()
    pair["neutral"]["source_voice_chunk_ids"] = ["U0007__C01", "U0007__C01"]

    with pytest.raises(tone_pk.TonePkError, match="source assembly chunk evidence"):
        tone_pk.validate_pair_evidence(pair)


def test_resume_keeps_green_take_hashes_and_regenerates_only_failed_take(
    tmp_path: Path,
) -> None:
    pair = passing_pair_evidence(tmp_path)
    pair["neutral"]["qc_status"] = "PASS"
    green_hash = pair["neutral"]["source_audio_sha256"]
    pair["expressive"]["qc_status"] = "FAIL"
    pair["expressive"]["source_audio_sha256"] = "e" * 64
    state = {"pairs": [pair]}

    pending = tone_pk.pending_takes(state)

    assert [(row["pair_id"], row["variant"]) for row in pending] == [
        ("PK-0007", "expressive")
    ]
    assert pair["neutral"]["source_audio_sha256"] == green_hash


def test_resume_regenerates_green_take_when_audio_hash_no_longer_matches(
    tmp_path: Path,
) -> None:
    pair = passing_pair_evidence(tmp_path)
    Path(pair["neutral"]["normalized_audio_path"]).write_bytes(b"corrupted")

    pending = tone_pk.pending_takes({"pairs": [pair]})

    assert ("PK-0007", "neutral") in [
        (row["pair_id"], row["variant"]) for row in pending
    ]


def test_normalize_take_uses_fixed_loudness_contract(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"fixture")
    output = tmp_path / "normalized" / "take.wav"
    calls: list[list[str]] = []

    tone_pk.normalize_take(source, output, calls.append)

    assert calls == [[
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-af", "loudnorm=I=-18:LRA=7:TP=-2,aresample=48000",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(output),
    ]]
    assert output.parent.is_dir()


def test_probe_loudness_parses_final_ebur128_summary(tmp_path: Path) -> None:
    source = tmp_path / "normalized.wav"
    source.write_bytes(b"fixture")

    class Result:
        stderr = "I: -70.0 LUFS\nSummary:\n  I: -18.2 LUFS\n"

    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return Result()

    assert tone_pk.probe_loudness(source, runner) == -18.2
    assert "ebur128=peak=true" in calls[0]


def test_timeline_is_fixed_a_then_b_with_display_only_labels() -> None:
    timeline = tone_pk.build_pk_timeline([passing_pair_evidence()])

    assert [row["variant"] for row in timeline["takes"]] == [
        "neutral",
        "expressive",
    ]
    assert timeline["spoken_text"] == "同一句。同一句。"
    assert "無情緒" not in timeline["spoken_text"]
    assert "有情緒" not in timeline["spoken_text"]
    assert timeline["takes"][0]["subtitle_label"] == "A｜無情緒"
    assert timeline["takes"][1]["subtitle_label"].startswith("B｜有情緒")
    assert timeline["takes"][0]["start_seconds"] == 0.0
    assert timeline["takes"][1]["start_seconds"] == pytest.approx(1.55)
    assert timeline["duration_seconds"] == pytest.approx(2.75)


def test_write_checkpoint_builds_final_speech_compatible_manifest(
    tmp_path: Path,
) -> None:
    pair = passing_pair_evidence(tmp_path)

    result = tone_pk.write_checkpoint(tmp_path, [pair])

    manifest = json.loads(
        (tmp_path / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    narration = json.loads(
        (tmp_path / "manifests/narration_manifest.json").read_text(encoding="utf-8")
    )
    chunks = narration["outputs"][0]["segments"][0]["voice_chunks"]
    assert result["status"] == "PASS"
    assert manifest["schema"] == "story_video_tone_pk_manifest_v1"
    assert [row["voice_chunk_id"] for row in chunks] == [
        "PK-0007__A__001",
        "PK-0007__B__001",
    ]
    assert [row["spoken_text"] for row in chunks] == ["同一句。", "同一句。"]


def test_render_pk_video_builds_black_ass_h264_aac_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair = passing_pair_evidence(tmp_path)
    tone_pk.write_checkpoint(tmp_path, [pair])
    calls: list[list[str]] = []
    monkeypatch.setattr(tone_pk.subprocess, "run", lambda command, **_kwargs: calls.append(command))
    output = tmp_path / "video" / "tone_pk_full.mp4"

    result = tone_pk.render_pk_video(tmp_path, output, 1920, 1080)

    assert result["status"] == "PASS"
    assert result["visual_mode"] == "black_subtitle"
    command = calls[-1]
    assert command[:6] == ["ffmpeg", "-y", "-v", "error", "-f", "lavfi"]
    assert any(
        value.startswith("color=c=black:s=1920x1080:r=30:d=") for value in command
    )
    assert "libx264" in command
    assert "aac" in command
    ass_path = tmp_path / "manifests" / "tone_pk.ass"
    ass = ass_path.read_text(encoding="utf-8")
    assert "Alignment=5" not in ass
    assert r"A｜無情緒\N{\c&H" in ass
    assert r"B｜有情緒・疑惑\N{\c&H" in ass
    assert "導覽員 (疑惑地查看地圖)" in ass


def test_render_pk_video_rejects_stale_green_audio_hash(tmp_path: Path) -> None:
    pair = passing_pair_evidence(tmp_path)
    tone_pk.write_checkpoint(tmp_path, [pair])
    Path(pair["neutral"]["normalized_audio_path"]).write_bytes(b"corrupted")

    with pytest.raises(tone_pk.TonePkError, match="pending takes"):
        tone_pk.render_pk_video(
            tmp_path,
            tmp_path / "video" / "tone_pk_full.mp4",
            1920,
            1080,
        )


def test_cli_registers_status_qc_and_render_subcommands() -> None:
    parser = tone_pk._build_parser()

    status = parser.parse_args(["status", "--project", "/tmp/fixture"])
    qc = parser.parse_args(["qc", "--project", "/tmp/fixture"])
    render = parser.parse_args(
        [
            "render",
            "--project",
            "/tmp/fixture",
            "--output",
            "/tmp/fixture.mp4",
        ]
    )

    assert status.handler is tone_pk._status_command
    assert qc.handler is tone_pk._qc_command
    assert render.handler is tone_pk._render_command
    assert (render.width, render.height) == (1920, 1080)


def test_generate_resume_checkpoints_takes_and_skips_hash_green_audio(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    calls: list[list[str]] = []
    first = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner(calls),
    )
    state = json.loads(
        (project / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    source_hashes = {
        (pair["pair_id"], variant): pair[variant]["source_audio_sha256"]
        for pair in state["pairs"]
        for variant in ("neutral", "expressive")
    }

    second = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=lambda *_args, **_kwargs: pytest.fail("green takes regenerated"),
    )

    assert first["generated_take_count"] == 2
    assert len(calls) == 2
    assert all(
        command[command.index("--max-acoustic-retries") + 1] == "0"
        for command in calls
    )
    assert all("--emit-failed-qc-manifest" in command for command in calls)
    assert all(
        pair[variant]["candidate_count"] == 1
        for pair in state["pairs"]
        for variant in ("neutral", "expressive")
    )
    assert second["generated_take_count"] == 0
    assert second["skipped_green_take_count"] == 2
    resumed = json.loads(
        (project / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    assert {
        (pair["pair_id"], variant): pair[variant]["source_audio_sha256"]
        for pair in resumed["pairs"]
        for variant in ("neutral", "expressive")
    } == source_hashes


def test_generate_ingests_failed_candidate_for_bounded_controller_repair(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    calls: list[list[str]] = []

    result = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner(calls, qc_pass=False),
    )

    state = json.loads(
        (project / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "FAIL"
    assert result["generated_take_count"] == 2
    assert all("--emit-failed-qc-manifest" in command for command in calls)
    assert all(
        pair[variant]["candidate_count"] == 1
        and pair[variant]["selected_candidate"] == 1
        and pair[variant]["qc_status"] == "FAIL"
        and Path(pair[variant]["source_audio_path"]).is_file()
        and pair[variant]["source_audio_sha256"]
        for pair in state["pairs"]
        for variant in ("neutral", "expressive")
    )


def test_generate_rejects_candidate_when_generator_audio_hash_is_wrong(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    base_runner = fake_generator_runner([])

    def corrupt_hash_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        if command[0] != "ffmpeg":
            variant_project = next(
                Path(value)
                for value in command
                if "/variants/" in value and Path(value).is_dir()
            )
            path = variant_project / "manifests" / "narration_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            chunk = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
            chunk["audio_sha256"] = "0" * 64
            _write_json(path, manifest)
        return result

    with pytest.raises(tone_pk.TonePkError, match="candidate lineage"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=corrupt_hash_runner,
        )


def test_generate_resume_partial_variant_reassembles_existing_chunks_without_inference(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    green_provider = project / "variants/neutral/audio/segments/U0001__C01.wav"
    green_provider_hash = _sha256(green_provider)
    missing_take = state["pairs"][1]["neutral"]
    Path(missing_take["source_audio_path"]).unlink()
    missing_take.pop("source_audio_path")
    missing_take.pop("source_audio_sha256")
    _write_json(state_path, state)
    calls: list[list[str]] = []

    result = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner(calls),
    )

    assert result["generated_take_count"] == 0
    assert result["ingested_existing_take_count"] == 4
    assert calls == []
    refreshed = json.loads(state_path.read_text(encoding="utf-8"))
    assert Path(refreshed["pairs"][1]["neutral"]["source_audio_path"]).is_file()
    assert _sha256(green_provider) == green_provider_hash


def test_public_generate_resume_refuses_qc_failed_valid_source_with_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    failed = state["pairs"][0]["expressive"]
    failed["qc_status"] = "FAIL"
    _set_manifest_utterance_qc(
        project,
        variant="expressive",
        utterance_id="U0001",
        passed=False,
    )
    before = (failed["candidate_count"], failed["selected_candidate"])
    _write_json(state_path, state)
    ledger_hash = _sha256(state_path)
    monkeypatch.setattr(
        tone_pk.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("public resume retried QC failure"),
    )

    with pytest.raises(SystemExit):
        tone_pk.main(
            [
                "generate",
                "--project",
                str(project),
                "--generator",
                str(generator),
                "--resume",
            ]
        )

    error = capsys.readouterr().err
    assert "qc --repair-failed --max-candidates" in error
    assert _sha256(state_path) == ledger_hash
    unchanged = json.loads(state_path.read_text(encoding="utf-8"))
    take = unchanged["pairs"][0]["expressive"]
    assert (take["candidate_count"], take["selected_candidate"]) == before


def test_targeted_generate_counts_unselected_failed_take_separately(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for pair in state["pairs"]:
        pair["neutral"]["qc_status"] = "FAIL"
        _set_manifest_utterance_qc(
            project,
            variant="neutral",
            utterance_id=pair["utterance_id"],
            passed=False,
        )
    _write_json(state_path, state)

    result = tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
        candidate_budgets={("PK-0001", "neutral"): 1},
        target_takes={("PK-0001", "neutral")},
    )

    assert result["skipped_green_take_count"] == 2
    assert result["not_selected_take_count"] == 1


def test_repair_failed_takes_only_regenerates_failed_take(tmp_path: Path) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    setup_calls: list[list[str]] = []
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner(setup_calls),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    neutral_hash = state["pairs"][0]["neutral"]["source_audio_sha256"]
    state["pairs"][0]["expressive"]["qc_status"] = "FAIL"
    _set_manifest_utterance_qc(
        project,
        variant="expressive",
        utterance_id="U0001",
        passed=False,
    )
    _write_json(state_path, state)
    repair_calls: list[list[str]] = []

    result = tone_pk.repair_failed_takes(
        project,
        max_candidates=3,
        runner=fake_generator_runner(repair_calls),
    )

    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["repaired_take_count"] == 1
    assert len(repair_calls) == 1
    assert "--repair-shot" in repair_calls[0]
    assert "S01_SH01" in repair_calls[0]
    assert "U0001" not in repair_calls[0]
    assert repaired["pairs"][0]["neutral"]["source_audio_sha256"] == neutral_hash
    assert repaired["pairs"][0]["expressive"]["qc_status"] == "PASS"


@pytest.mark.parametrize("variant", ["neutral", "expressive"])
def test_generate_validates_each_variant_ledger_binding_before_runner(
    tmp_path: Path,
    variant: str,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    ledger_path = project / "variants" / variant / "dialogue_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["utterances"][0]["shot_id"] = "SHOT-TAMPERED"
    _write_json(ledger_path, ledger)

    with pytest.raises(tone_pk.TonePkError, match="ledger hash"):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("runner was invoked"),
        )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing", "missing an utterance or shot ID"),
        ("duplicate", "contains duplicate IDs"),
        ("unknown", "unknown=\\['U9999'\\]"),
    ],
)
def test_generate_repair_mapping_fails_closed_before_runner(
    tmp_path: Path,
    mutation: str,
    expected_error: str,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    variant = "expressive"
    variant_project = project / "variants" / variant
    ledger_path = variant_project / "dialogue_ledger.json"
    binding_path = variant_project / "voice_cast_binding.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        ledger["utterances"][0].pop("shot_id")
    elif mutation == "duplicate":
        ledger["utterances"][1]["shot_id"] = ledger["utterances"][0]["shot_id"]
    else:
        ledger["utterances"][1]["utterance_id"] = "U9999"
    _write_json(ledger_path, ledger)
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["dialogue_ledger_sha256"] = _sha256(ledger_path)
    _write_json(binding_path, binding)

    with pytest.raises(tone_pk.TonePkError, match=expected_error):
        tone_pk.generate_takes(
            project,
            generator,
            resume=True,
            runner=lambda *_args, **_kwargs: pytest.fail("runner was invoked"),
        )


def test_repair_candidate_budget_is_cumulative_and_never_exceeds_cap(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pairs"][0]["expressive"]["qc_status"] = "FAIL"
    _set_manifest_utterance_qc(
        project,
        variant="expressive",
        utterance_id="U0001",
        passed=False,
    )
    _write_json(state_path, state)
    calls: list[list[str]] = []

    tone_pk.repair_failed_takes(
        project,
        max_candidates=3,
        runner=fake_generator_runner(calls, candidate_count=2),
    )

    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    take = repaired["pairs"][0]["expressive"]
    assert take["candidate_count"] == 3
    assert take["selected_candidate"] == 3
    retries_index = calls[0].index("--max-acoustic-retries") + 1
    assert calls[0][retries_index] == "1"
    take["qc_status"] = "FAIL"
    _set_manifest_utterance_qc(
        project,
        variant="expressive",
        utterance_id="U0001",
        passed=False,
    )
    _write_json(state_path, repaired)
    with pytest.raises(tone_pk.TonePkError, match="candidate budget exhausted"):
        tone_pk.repair_failed_takes(
            project,
            max_candidates=3,
            runner=lambda *_args, **_kwargs: pytest.fail("cap exceeded"),
        )


def test_selective_candidate_lineage_counts_only_new_delta(tmp_path: Path) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pairs"][0]["expressive"]["qc_status"] = "FAIL"
    _set_manifest_utterance_qc(
        project,
        variant="expressive",
        utterance_id="U0001",
        passed=False,
    )
    _write_json(state_path, state)

    tone_pk.repair_failed_takes(
        project,
        max_candidates=3,
        runner=fake_generator_runner([], candidate_count=1),
    )

    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert repaired["pairs"][0]["expressive"]["candidate_count"] == 2


def test_selective_candidate_lineage_allows_canonical_partial_chunk_repair(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(
        tmp_path,
        first_text="這是一段足以切成兩個固定語音區塊的測試句子，後半段必須保持原始音訊與候選證據完全不變。",
    )
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    take = state["pairs"][0]["neutral"]
    assert len(take["canonical_voice_chunks"]) == 2
    take["qc_status"] = "FAIL"
    _set_manifest_utterance_qc(
        project,
        variant="neutral",
        utterance_id="U0001",
        passed=False,
    )
    _write_json(state_path, state)
    manifest_path = project / "variants/neutral/manifests/narration_manifest.json"
    prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prior_chunks = list(tone_pk._flatten_voice_chunks(prior_manifest))
    untouched = prior_chunks[1]
    untouched_bytes = Path(untouched["audio"]).read_bytes()
    base_runner = fake_generator_runner([], candidate_count=1)

    def partial_chunk_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        if command[0] == "ffmpeg":
            return result
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunks = list(tone_pk._flatten_voice_chunks(manifest))
        repaired, unaffected = chunks
        Path(unaffected["audio"]).write_bytes(untouched_bytes)
        for field in (
            "audio_sha256",
            "candidate_count",
            "selected_candidate",
            "candidate_rejections",
            "alignment_status",
            "pronunciation_status",
            "prosody_status",
            "fluency_status",
            "qc_status",
        ):
            if field in untouched:
                unaffected[field] = copy.deepcopy(untouched[field])
            else:
                unaffected.pop(field, None)
        lineage = {
            "schema": tone_pk.CANDIDATE_LINEAGE_SCHEMA,
            "generation_mode": "selective_repair",
            "requested": False,
            "baseline_candidate_count": 1,
            "new_candidate_count": 0,
            "cumulative_candidate_count": 1,
            "output_audio_sha256": unaffected["audio_sha256"],
        }
        lineage["lineage_sha256"] = tone_pk._canonical_json_sha256(lineage)
        unaffected["candidate_lineage"] = lineage
        manifest["requested_voice_chunk_ids"] = [repaired["voice_chunk_id"]]
        _write_json(manifest_path, manifest)
        return result

    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=partial_chunk_runner,
        candidate_budgets={("PK-0001", "neutral"): 1},
        target_takes={("PK-0001", "neutral")},
    )

    repaired_state = json.loads(state_path.read_text(encoding="utf-8"))
    repaired_take = repaired_state["pairs"][0]["neutral"]
    assert repaired_take["candidate_count"] == 2
    assert repaired_take["source_chunk_audio_sha256s"][1] == untouched["audio_sha256"]


def test_repair_reconciles_interrupted_manifest_before_group_planning(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for pair in state["pairs"]:
        pair["neutral"]["qc_status"] = "FAIL"
        _set_manifest_utterance_qc(
            project,
            variant="neutral",
            utterance_id=pair["utterance_id"],
            passed=False,
        )
    _write_json(state_path, state)
    fake_generator_runner([], candidate_count=1)(
        [
            str(generator),
            str(project / "variants" / "neutral"),
            "--repair-shot",
            "S01_SH01",
        ]
    )
    repair_calls: list[list[str]] = []

    tone_pk.repair_failed_takes(
        project,
        max_candidates=3,
        runner=fake_generator_runner(repair_calls, candidate_count=1),
    )

    neutral_calls = [
        command for command in repair_calls if "/variants/neutral" in " ".join(command)
    ]
    assert len(neutral_calls) == 1
    assert "S01_SH02" in neutral_calls[0]
    assert "S01_SH01" not in neutral_calls[0]


def test_repair_groups_same_variant_and_remaining_budget_in_one_invocation(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for pair in state["pairs"]:
        pair["neutral"]["qc_status"] = "FAIL"
        _set_manifest_utterance_qc(
            project,
            variant="neutral",
            utterance_id=pair["utterance_id"],
            passed=False,
        )
    _write_json(state_path, state)
    calls: list[list[str]] = []

    result = tone_pk.repair_failed_takes(
        project,
        max_candidates=3,
        runner=fake_generator_runner(calls),
    )

    neutral_calls = [
        command for command in calls if "/variants/neutral" in " ".join(command)
    ]
    assert len(neutral_calls) == 1
    assert [
        neutral_calls[0][index + 1]
        for index, value in enumerate(neutral_calls[0][:-1])
        if value == "--repair-shot"
    ] == ["S01_SH01", "S01_SH02"]
    assert result["attempts"] == 1
    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert [pair["neutral"]["candidate_count"] for pair in repaired["pairs"]] == [
        2,
        2,
    ]


def test_repair_dispatches_heterogeneous_take_budgets_independently(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    first = state["pairs"][0]["neutral"]
    second = state["pairs"][1]["neutral"]
    first.update({"qc_status": "FAIL", "candidate_count": 2, "selected_candidate": 2})
    second.update({"qc_status": "FAIL", "candidate_count": 1, "selected_candidate": 1})
    for row in first["candidate_evidence"]:
        row.update({"candidate_count": 2, "selected_candidate": 2})
    _set_manifest_candidate_count(
        project,
        variant="neutral",
        utterance_id="U0001",
        candidate_count=2,
    )
    _set_manifest_utterance_qc(
        project,
        variant="neutral",
        utterance_id="U0001",
        passed=False,
    )
    _set_manifest_utterance_qc(
        project,
        variant="neutral",
        utterance_id="U0002",
        passed=False,
    )
    _write_json(state_path, state)
    calls: list[list[str]] = []
    base_runner = fake_generator_runner(
        calls,
        candidate_count={"U0001": 1, "U0002": 2},
    )

    def targeted_runner(command: list[str], **kwargs):
        return base_runner(command, **kwargs)

    tone_pk.repair_failed_takes(
        project,
        max_candidates=3,
        runner=targeted_runner,
    )

    neutral_calls = [command for command in calls if "/variants/neutral" in " ".join(command)]
    assert len(neutral_calls) == 2
    by_shot = {
        command[command.index("--repair-shot") + 1]: command[
            command.index("--max-acoustic-retries") + 1
        ]
        for command in neutral_calls
    }
    assert by_shot == {"S01_SH01": "0", "S01_SH02": "1"}
    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert repaired["pairs"][0]["neutral"]["candidate_count"] == 3
    assert repaired["pairs"][1]["neutral"]["candidate_count"] == 3


def test_grouped_repair_accounts_for_passing_and_failing_takes_independently(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for pair in state["pairs"]:
        pair["neutral"]["qc_status"] = "FAIL"
        _set_manifest_utterance_qc(
            project,
            variant="neutral",
            utterance_id=pair["utterance_id"],
            passed=False,
        )
    _write_json(state_path, state)
    calls: list[list[str]] = []
    base_runner = fake_generator_runner(calls, candidate_count=2)

    def one_fails_runner(command: list[str], **kwargs):
        result = base_runner(command, **kwargs)
        if command[0] == "ffmpeg":
            return result
        manifest_path = (
            project
            / "variants"
            / "neutral"
            / "manifests"
            / "narration_manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for chunk in tone_pk._flatten_voice_chunks(manifest):
            if chunk["utterance_id"] == "U0002":
                chunk["pronunciation_status"] = "FAIL"
                chunk["qc_status"] = "FAIL"
        _write_json(manifest_path, manifest)
        return result

    with pytest.raises(tone_pk.TonePkError, match="failed takes remain"):
        tone_pk.repair_failed_takes(
            project,
            max_candidates=3,
            runner=one_fails_runner,
        )

    neutral_calls = [
        command for command in calls if "/variants/neutral" in " ".join(command)
    ]
    assert len(neutral_calls) == 1
    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert repaired["pairs"][0]["neutral"]["qc_status"] == "PASS"
    assert repaired["pairs"][1]["neutral"]["qc_status"] == "FAIL"
    assert [pair["neutral"]["candidate_count"] for pair in repaired["pairs"]] == [
        3,
        3,
    ]


def test_exhausted_failed_take_does_not_block_other_group_and_cap_stays_three(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path, utterance_count=2)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    first = state["pairs"][0]["neutral"]
    second = state["pairs"][1]["neutral"]
    first.update({"qc_status": "FAIL", "candidate_count": 3, "selected_candidate": 3})
    second.update({"qc_status": "FAIL", "candidate_count": 2, "selected_candidate": 2})
    for row in first["candidate_evidence"]:
        row.update({"candidate_count": 3, "selected_candidate": 3})
    for row in second["candidate_evidence"]:
        row.update({"candidate_count": 2, "selected_candidate": 2})
    _set_manifest_candidate_count(
        project,
        variant="neutral",
        utterance_id="U0001",
        candidate_count=3,
    )
    _set_manifest_candidate_count(
        project,
        variant="neutral",
        utterance_id="U0002",
        candidate_count=2,
    )
    for utterance_id in ("U0001", "U0002"):
        _set_manifest_utterance_qc(
            project,
            variant="neutral",
            utterance_id=utterance_id,
            passed=False,
        )
    _write_json(state_path, state)
    calls: list[list[str]] = []

    with pytest.raises(tone_pk.TonePkError, match="candidate budget exhausted"):
        tone_pk.repair_failed_takes(
            project,
            max_candidates=3,
            runner=fake_generator_runner(calls),
        )

    neutral_calls = [
        command for command in calls if "/variants/neutral" in " ".join(command)
    ]
    assert len(neutral_calls) == 1
    assert neutral_calls[0].count("--repair-shot") == 1
    assert "S01_SH02" in neutral_calls[0]
    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert repaired["pairs"][0]["neutral"]["candidate_count"] == 3
    assert repaired["pairs"][1]["neutral"]["candidate_count"] == 3


def test_repair_pre_inference_error_does_not_fabricate_candidate_evidence(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    state_path = project / "manifests/tone_pk_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    take = state["pairs"][0]["expressive"]
    take["qc_status"] = "FAIL"
    _set_manifest_utterance_qc(
        project,
        variant="expressive",
        utterance_id="U0001",
        passed=False,
    )
    before = (take["candidate_count"], take["selected_candidate"])
    _write_json(state_path, state)

    def launch_failure(*_args, **_kwargs):
        raise OSError("sanitized launch failure")

    with pytest.raises(tone_pk.TonePkError, match="generation failed"):
        tone_pk.repair_failed_takes(
            project,
            max_candidates=3,
            runner=launch_failure,
        )

    unchanged = json.loads(state_path.read_text(encoding="utf-8"))
    repaired_take = unchanged["pairs"][0]["expressive"]
    assert (repaired_take["candidate_count"], repaired_take["selected_candidate"]) == before


def test_normalize_project_updates_evidence_and_checkpoint_per_take(
    tmp_path: Path,
) -> None:
    project = prepared_pk_project(tmp_path)
    generator = tmp_path / "fake_generator.py"
    generator.write_text("# sanitized fixture\n", encoding="utf-8")
    tone_pk.generate_takes(
        project,
        generator,
        resume=True,
        runner=fake_generator_runner([]),
    )
    normalized: list[Path] = []

    def normalizer(source: Path, output: Path, _runner, *, target_lufs: float):
        assert target_lufs == -18.0
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source.read_bytes() + b"-normalized")
        normalized.append(output)

    result = tone_pk.normalize_project(
        project,
        target_lufs=-18.0,
        max_pair_delta_lufs=0.5,
        normalizer=normalizer,
        loudness_probe=lambda _path: -18.0,
        runner=lambda _command: None,
    )

    state = json.loads(
        (project / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "PASS"
    assert len(normalized) == 2
    assert state["status"] == "PASS"
    assert all(
        pair[variant]["integrated_lufs"] == -18.0
        and Path(pair[variant]["normalized_audio_path"]).is_file()
        for pair in state["pairs"]
        for variant in ("neutral", "expressive")
    )


@pytest.mark.parametrize("drift", ["seed", "loudness"])
def test_checkpoint_status_and_narration_fail_closed_on_pair_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    pair = passing_pair_evidence(tmp_path)
    if drift == "seed":
        pair["expressive"]["generation_seeds"][0] += 1
    else:
        pair["expressive"]["integrated_lufs"] = -17.0

    result = tone_pk.write_checkpoint(tmp_path, [pair], run_id="tone-pk-test")
    state = json.loads(
        (tmp_path / "manifests/tone_pk_manifest.json").read_text(encoding="utf-8")
    )
    narration = json.loads(
        (tmp_path / "manifests/narration_manifest.json").read_text(encoding="utf-8")
    )

    assert result["status"] != "PASS"
    assert state["status"] != "PASS"
    assert narration["status"] != "PASS"
    status_args = tone_pk._build_parser().parse_args(
        ["status", "--project", str(tmp_path)]
    )
    assert status_args.handler(status_args)["status"] != "PASS"


def test_checkpoint_narration_contract_loads_with_real_final_speech_loader(
    tmp_path: Path,
) -> None:
    pair = passing_pair_evidence(tmp_path)
    tone_pk.write_checkpoint(tmp_path, [pair], run_id="tone-pk-test")

    contract = load_narration_contract(tmp_path)

    assert contract["run_id"] == "tone-pk-test"
    assert contract["voice_chunk_count"] == 2
    assert contract["voice_chunk_ids"] == ["PK-0007__A__001", "PK-0007__B__001"]
    assert contract["expected_transcript"] == "同一句。同一句。"


def test_timeline_assigns_stable_distinct_role_colors(tmp_path: Path) -> None:
    first = passing_pair_evidence()
    first["pair_id"] = "PK-0001"
    first["neutral"]["take_id"] = "PK-0001__A"
    first["expressive"]["take_id"] = "PK-0001__B"
    second = copy.deepcopy(first)
    second["pair_id"] = "PK-0002"
    second["speaker_id"] = "traveler"
    second["speaker_name"] = "旅人"
    third = copy.deepcopy(first)
    third["pair_id"] = "PK-0003"

    timeline = tone_pk.build_pk_timeline([first, second, third])
    colors = [take["role_color"] for take in timeline["takes"] if take["variant"] == "neutral"]

    assert colors[0] == colors[2]
    assert colors[0] != colors[1]
    ass_path = tmp_path / "tone-pk-role-colors.ass"
    tone_pk._write_ass(ass_path, timeline, 1920, 1080)
    ass = ass_path.read_text(encoding="utf-8")
    role_tags = re.findall(r"\\c(&H[0-9A-F]{8}&)", ass)
    assert role_tags[0] == role_tags[1] == role_tags[4] == role_tags[5]
    assert role_tags[0] != role_tags[2]


def test_cli_registers_generation_repair_and_normalization_flags() -> None:
    parser = tone_pk._build_parser()

    generate = parser.parse_args(
        ["generate", "--project", "/tmp/p", "--generator", "/tmp/g.py", "--resume"]
    )
    qc = parser.parse_args(
        ["qc", "--project", "/tmp/p", "--repair-failed", "--max-candidates", "3"]
    )
    normalize = parser.parse_args(
        [
            "normalize", "--project", "/tmp/p", "--target-lufs", "-18",
            "--max-pair-delta-lufs", "0.5",
        ]
    )

    assert generate.resume is True
    assert qc.repair_failed is True and qc.max_candidates == 3
    assert normalize.target_lufs == -18.0
    assert normalize.max_pair_delta_lufs == 0.5

from __future__ import annotations

import hashlib
import json
import math
import wave
from array import array

import pytest

from plugins.story_video.state import StoryVideoStateStore, parse_operator_call


def _context(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    text = "故事影片：夜班故事｜1分｜故事圖片加字幕。"
    call = parse_operator_call(text)
    assert call is not None
    return store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request=text,
    )


def _write_loud_tone(path) -> None:
    sample_rate = 16_000
    samples = array(
        "h",
        (
            int(12_000 * math.sin(2 * math.pi * 220 * index / sample_rate))
            for index in range(sample_rate)
        ),
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())


def test_final_speech_worker_rejects_loud_tone_with_valid_source_report(tmp_path) -> None:
    from plugins.story_video.final_speech_worker import evaluate_final_speech

    video = tmp_path / "final.mp4"
    video.write_bytes(b"loud-tone-video")

    result = evaluate_final_speech(
        video=video,
        run_id="run-1",
        expected_text="小美你好",
        audio_extractor=lambda _video, audio: _write_loud_tone(audio),
        transcriber=lambda _audio: "",
    )

    assert result["status"] == "FAIL"
    assert result["asr_transcript"] == ""
    assert result["transcript_similarity"] == 0.0


def test_final_speech_worker_compares_transcript_phonetically(tmp_path) -> None:
    from plugins.story_video.final_speech_worker import evaluate_final_speech

    video = tmp_path / "final.mp4"
    video.write_bytes(b"speech-video")
    aliases = {
        "你們兩個，怎麼突然這麼客氣？": "ni3men5liang3ge4zen3me5tu1ran2zhe4me5ke4qi4",
        "你们两个怎么突然这么客气？": "ni3men5liang3ge4zen3me5tu1ran2zhe4me5ke4qi4",
    }

    result = evaluate_final_speech(
        video=video,
        run_id="run-1",
        expected_text="你們兩個，怎麼突然這麼客氣？",
        audio_extractor=lambda _video, audio: _write_loud_tone(audio),
        transcriber=lambda _audio: "你们两个怎么突然这么客气？",
        comparison_normalizer=aliases.__getitem__,
    )

    assert result["status"] == "PASS"
    assert result["transcript_similarity"] == 1.0


def test_final_speech_report_is_bound_to_run_and_exact_video_hash(tmp_path) -> None:
    from plugins.story_video.delivery_speech import validate_final_speech_report

    context = _context(tmp_path)
    video = context.project_dir / "video" / "final.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"speech-video")
    manifest = context.project_dir / "manifests" / "narration_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "voice_chunk_count": 2,
                "outputs": [
                    {
                        "spoken_text": "小美你好",
                        "segments": [
                            {
                                "voice_chunks": [
                                    {
                                        "voice_chunk_id": "U01__C01",
                                        "spoken_text": "小美",
                                    },
                                    {
                                        "voice_chunk_id": "U01__C02",
                                        "spoken_text": "你好",
                                    },
                                ]
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema": "story_video_final_speech_qc_v1",
        "run_id": context.run_id,
        "status": "PASS",
        "method": "final_mp4_demux_qwen_asr_v1",
        "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "narration_manifest_sha256": hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest(),
        "voice_chunk_count": 2,
        "voice_chunk_ids": ["U01__C01", "U01__C02"],
        "asr_transcript": "小美你好",
        "expected_transcript": "小美你好",
        "transcript_similarity": 0.98,
    }

    assert validate_final_speech_report(context, video, report).ok is True
    assert validate_final_speech_report(
        context, video, {**report, "run_id": "another-run"}
    ).ok is False
    assert validate_final_speech_report(
        context, video, {**report, "video_sha256": "0" * 64}
    ).ok is False
    assert validate_final_speech_report(
        context, video, {**report, "narration_manifest_sha256": "0" * 64}
    ).ok is False
    assert validate_final_speech_report(
        context, video, {**report, "voice_chunk_count": 1}
    ).ok is False
    assert validate_final_speech_report(
        context,
        video,
        {**report, "voice_chunk_ids": ["U01__C02", "U01__C01"]},
    ).ok is False
    assert validate_final_speech_report(
        context, video, {**report, "expected_transcript": "別的台詞"}
    ).ok is False
    assert validate_final_speech_report(
        context, video, {**report, "transcript_similarity": float("inf")}
    ).ok is False
    assert validate_final_speech_report(
        context, video, {**report, "transcript_similarity": 0.72}
    ).ok is True
    assert validate_final_speech_report(
        context, video, {**report, "transcript_similarity": 0.7199}
    ).ok is False

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["run_id"] = "foreign-run"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    assert validate_final_speech_report(context, video, report).ok is False


@pytest.mark.parametrize(
    ("chunk_ids", "declared_count"),
    [(["", "U01__C02"], 2), (["U01__C01", "U01__C01"], 2), (["U01__C01", "U01__C02"], 3)],
)
def test_final_speech_report_rejects_invalid_manifest_chunk_contract(
    tmp_path, chunk_ids, declared_count
) -> None:
    from plugins.story_video.delivery_speech import validate_final_speech_report

    context = _context(tmp_path)
    video = context.project_dir / "video" / "final.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"speech-video")
    manifest = context.project_dir / "manifests" / "narration_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "voice_chunk_count": declared_count,
                "outputs": [
                    {
                        "spoken_text": "小美你好",
                        "segments": [
                            {
                                "voice_chunks": [
                                    {"voice_chunk_id": chunk_ids[0], "spoken_text": "小美"},
                                    {"voice_chunk_id": chunk_ids[1], "spoken_text": "你好"},
                                ]
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema": "story_video_final_speech_qc_v1",
        "run_id": context.run_id,
        "status": "PASS",
        "method": "final_mp4_demux_qwen_asr_v1",
        "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "narration_manifest_sha256": hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest(),
        "voice_chunk_count": declared_count,
        "voice_chunk_ids": chunk_ids,
        "expected_transcript": "小美你好",
        "asr_transcript": "小美你好",
        "transcript_similarity": 1.0,
    }

    assert validate_final_speech_report(context, video, report).ok is False

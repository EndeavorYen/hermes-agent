from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import shutil
import wave
from array import array
from pathlib import Path

import pytest
from PIL import Image

from plugins.story_video.audit import ProviderAudit, ProviderAuditEvent
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call


def _black_context(tmp_path):
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
    return store, context


def _write_narration(context) -> None:
    audio = context.project_dir / "audio" / "S01.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"wave-audio")
    manifest = context.project_dir / "manifests" / "narration_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": "story_video_narration_manifest_v6",
                "run_id": context.run_id,
                "provider": "local_qwen",
                "voice": "multi_character",
                "speaker_routing_status": "PASS",
                "voice_chunk_count": 2,
                "outputs": [
                    {
                        "scene_id": "S01",
                        "audio": str(audio),
                        "duration_sec": 3.2,
                        "display_text": "故事開始。出發吧！",
                        "segments": [
                            {
                                "shot_id": "S01_SH01",
                                "display_text": "故事開始。出發吧！",
                                "timeline_duration_sec": 3.2,
                                "voice_chunks": [
                                    {
                                        "voice_chunk_id": "S01_SH01__C01",
                                        "display_text": "故事開始。",
                                        "speaker_id": "narrator",
                                        "voice_id": "simon_clean_v2",
                                        "emotion": "warmth",
                                        "scene_start_sec": 0.0,
                                        "scene_speech_end_sec": 1.4,
                                    },
                                    {
                                        "voice_chunk_id": "S01_SH01__C02",
                                        "display_text": "出發吧！",
                                        "speaker_id": "xiaomei",
                                        "voice_id": "qwen_custom_vivian",
                                        "emotion": "joy",
                                        "scene_start_sec": 1.6,
                                        "scene_speech_end_sec": 3.0,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (context.project_dir / "voice_cast_binding.json").write_text(
        json.dumps(
            {
                "schema": "story_video_voice_cast_binding_v2",
                "status": "locked",
                "speakers": [
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
                        "voice_id": "qwen_custom_vivian",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _module():
    return importlib.import_module("plugins.story_video.render_modes")


def _write_real_pcm_wav(path: Path, duration_sec: float = 3.2) -> None:
    sample_rate = 16_000
    samples = array(
        "h",
        (
            int(1_200 * math.sin(2 * math.pi * 220 * index / sample_rate))
            for index in range(int(sample_rate * duration_sec))
        ),
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())


def test_render_modes_module_exists() -> None:
    assert importlib.util.find_spec("plugins.story_video.render_modes") is not None


@pytest.mark.skipif(
    not shutil.which("ffmpeg")
    or not shutil.which("ffprobe")
    or not (
        Path.home()
        / ".hermes/skills/creative/story-video-production-pipeline/scripts/render_story_video.py"
    ).is_file(),
    reason="local story-video renderer with ffmpeg is required",
)
def test_real_black_subtitle_renderer_rejects_tone_without_speech_evidence(
    tmp_path,
) -> None:
    from plugins.story_video.production_runner import _default_renderer

    _store, context = _black_context(tmp_path)
    _write_narration(context)
    _write_real_pcm_wav(context.project_dir / "audio" / "S01.wav")
    _module().prepare_black_subtitle_render(context)

    payload = _default_renderer(context)

    assert payload["success"] is False
    final = Path(payload["video"])
    assert final.is_file()
    assert final.suffix == ".mp4"
    qc = json.loads(Path(payload["qc_report"]).read_text(encoding="utf-8"))
    assert qc["output"]["container_status"] == "PASS"
    assert qc["output"]["audio_status"] == "FAIL"
    assert qc["output"]["speech_content_status"] == "FAIL"
    assert qc["output"]["black_background_status"] == "PASS"


def test_black_render_input_uses_project_local_black_frame_and_voice_cues(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)

    payload = _module().prepare_black_subtitle_render(context)

    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    assert payload["visual_mode"] == "black_subtitle"
    assert render_input["visual_mode"] == "black_subtitle"
    assert render_input["motion_policy"] == "static_hold"
    assert "opening_card" not in render_input
    assert "ending_card" not in render_input
    shot = render_input["scenes"][0]["shots"][0]
    assert shot["subtitle_timing_source"] == "measured_voice_chunks"
    assert shot["subtitle_position"] == "center"
    assert render_input["subtitle"]["font_size"] == 72
    assert render_input["subtitle"]["max_chars_per_line"] == 24
    assert render_input["subtitle"]["max_lines"] == 3
    assert render_input["subtitle"]["position"] == "center"
    assert render_input["subtitle"]["center_y_ratio"] == 0.55
    assert [cue["text"] for cue in shot["subtitle_cues"]] == [
        "故事開始。",
        "出發吧！",
    ]
    assert [cue["visual_text"] for cue in shot["subtitle_cues"]] == [
        "故事開始。",
        "小美（開心）\n「出發吧！」",
    ]
    assert [cue["emotion"] for cue in shot["subtitle_cues"]] == [
        "warmth",
        "joy",
    ]
    assert shot["narration"] == "故事開始。出發吧！"
    assert render_input["scenes"][0]["narration"] == "故事開始。出發吧！"
    assert [cue["speaker_id"] for cue in shot["subtitle_cues"]] == [
        "narrator",
        "xiaomei",
    ]
    assert [cue["color"] for cue in shot["subtitle_cues"]] == [
        "#FFFFFF",
        "#7FDBFF",
    ]
    image_path = context.project_dir / shot["image"]
    assert image_path.is_relative_to(context.project_dir)
    with Image.open(image_path) as image:
        assert image.size == (1920, 1080)
        assert image.getpixel((10, 10)) == (0, 0, 0)
    assert not (context.project_dir / "manifests/shot_candidate_manifest.json").exists()


def test_black_render_accepts_v7_and_preserves_selected_audio(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = "story_video_narration_manifest_v7"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    _module().prepare_black_subtitle_render(context)

    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    assert render_input["scenes"][0]["audio"] == "audio/S01.wav"


def test_black_render_rejects_unknown_narration_schema(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = "story_video_narration_manifest_v99"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported narration manifest schema"):
        _module().prepare_black_subtitle_render(context)


def test_black_subtitle_prefers_action_without_changing_spoken_text(
    tmp_path,
) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    character = manifest["outputs"][0]["segments"][0]["voice_chunks"][1]
    character["action"] = "走到小王面前"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    _module().prepare_black_subtitle_render(context)

    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    cue = render_input["scenes"][0]["shots"][0]["subtitle_cues"][1]
    assert cue["visual_text"] == "小美（走到小王面前）\n「出發吧！」"
    assert cue["text"] == "出發吧！"
    assert cue["action"] == "走到小王面前"


def test_black_subtitle_localizes_non_chinese_direction_with_emotion(
    tmp_path,
) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    character = manifest["outputs"][0]["segments"][0]["voice_chunks"][1]
    character["action"] = "breathy and broken delivery"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    _module().prepare_black_subtitle_render(context)

    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    cue = render_input["scenes"][0]["shots"][0]["subtitle_cues"][1]
    assert cue["visual_text"] == "小美（開心）\n「出發吧！」"
    assert cue["action"] == "breathy and broken delivery"


def test_black_subtitle_bounds_mixed_language_action_and_unknown_emotion() -> None:
    module = _module()

    mixed = module._visual_subtitle_text(
        "你好。",
        speaker_id="xiaomei",
        display_name="小美",
        emotion="tension",
        action="very long breathy delivery 然後 slowly walks forward",
        is_narrator=False,
    )
    unknown = module._visual_subtitle_text(
        "你好。",
        speaker_id="xiaomei",
        display_name="小美",
        emotion="uncertain_custom_emotion",
        action="",
        is_narrator=False,
    )

    assert mixed == "小美（緊張）\n「你好。」"
    assert unknown == "小美（自然）\n「你好。」"


def test_black_subtitle_uses_cast_role_for_nonstandard_narrator_id(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    narrator = manifest["outputs"][0]["segments"][0]["voice_chunks"][0]
    narrator["speaker_id"] = "voiceover"
    narrator["action"] = "翻開故事書"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    binding_path = context.project_dir / "voice_cast_binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["speakers"][0]["speaker_id"] = "voiceover"
    binding_path.write_text(json.dumps(binding, ensure_ascii=False), encoding="utf-8")

    _module().prepare_black_subtitle_render(context)

    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    cues = render_input["scenes"][0]["shots"][0]["subtitle_cues"]
    assert cues[0]["visual_text"] == "故事開始。"
    assert cues[0]["color"] == "#FFFFFF"
    assert cues[1]["color"] == "#7FDBFF"


def test_black_frames_for_multiple_scenes_have_identical_content(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest_path = context.project_dir / "manifests" / "narration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    second = json.loads(json.dumps(manifest["outputs"][0]))
    second["scene_id"] = "S02"
    second_audio = context.project_dir / "audio" / "S02.wav"
    second_audio.write_bytes(b"wave-audio-2")
    second["audio"] = str(second_audio)
    manifest["outputs"].append(second)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    _module().prepare_black_subtitle_render(context)

    render_input = json.loads(
        (context.project_dir / "render_input.json").read_text(encoding="utf-8")
    )
    frames = [
        context.project_dir / scene["shots"][0]["image"]
        for scene in render_input["scenes"]
    ]
    assert len(set(frames)) == 2
    assert len({hashlib.sha256(path.read_bytes()).hexdigest() for path in frames}) == 1


def test_black_render_proof_accepts_zero_image_events_and_rejects_image_event(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    subtitle_qc = context.project_dir / "qc" / "subtitle_qc_report.json"
    subtitle_qc.parent.mkdir(parents=True)
    subtitle_qc.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (context.project_dir / "render_manifest.json").write_text(
        json.dumps(
            {
                "visual_mode": "black_subtitle",
                "output": {
                    "path": "video/final.mp4",
                    "subtitles": {"hard_burned": True, "coverage_status": "PASS"},
                        "container_status": "PASS",
                        "audio_status": "PASS",
                        "source_speech_evidence_status": "PASS",
                        "speech_content_status": "PASS",
                        "duration_match_status": "PASS",
                    "black_background_status": "PASS",
                },
                "qc_report": "render_qc.json",
            }
        ),
        encoding="utf-8",
    )
    (context.project_dir / "render_qc.json").write_text(
        json.dumps({"status": "PASS", "visual_mode": "black_subtitle"}),
        encoding="utf-8",
    )

    passed = _module().validate_black_subtitle_render(context)
    ProviderAudit(context).append_event(
        ProviderAuditEvent(
            kind="image",
            phase="render",
            provider="openai-codex",
            model="gpt-image",
            status="ok",
        )
    )
    blocked = _module().validate_black_subtitle_render(context)

    assert passed.ok is True
    assert blocked.ok is False
    assert "black_subtitle run invoked an image provider" in blocked.violations


def test_generic_phase_validator_uses_black_mode_proof(tmp_path) -> None:
    from plugins.story_video.tools import validate_phase

    store, context = _black_context(tmp_path)
    context = store.update(context, phase="render")
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    (context.project_dir / "render_manifest.json").write_text(
        json.dumps(
            {
                "visual_mode": "black_subtitle",
                "output": {
                    "path": "video/final.mp4",
                    "subtitles": {"hard_burned": True, "coverage_status": "PASS"},
                        "container_status": "PASS",
                        "audio_status": "PASS",
                        "source_speech_evidence_status": "PASS",
                        "speech_content_status": "PASS",
                        "duration_match_status": "PASS",
                    "black_background_status": "PASS",
                },
                "qc_report": "qc/black_subtitle_render_qc.json",
            }
        ),
        encoding="utf-8",
    )

    proof = validate_phase(context)

    assert proof.ok is True


def test_finalize_black_render_writes_mode_specific_proof(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    subtitle_qc = context.project_dir / "qc" / "subtitle_qc_report.json"
    subtitle_qc.parent.mkdir(parents=True)
    subtitle_qc.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    payload = _module().finalize_black_subtitle_render(
        context,
        {
            "video": str(final),
            "duration_sec": 3.2,
            "subtitle_qc_report": str(subtitle_qc),
        },
        media_probe=lambda _path, _duration: {
            "container_status": "PASS",
            "audio_status": "PASS",
            "duration_match_status": "PASS",
            "black_background_status": "PASS",
            "duration_sec": 3.2,
        },
        speech_evidence_probe=lambda _context: {
            "source_speech_evidence_status": "PASS",
            "speech_qc_method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
            "asr_verified_chunk_count": 2,
            "minimum_transcript_similarity": 0.94,
        },
        final_speech_probe=lambda _context, _video: {
            "success": True,
            "qc_report": "qc/final_speech_qc_report.json",
            "video_sha256": "a" * 64,
        },
    )

    manifest = json.loads(
        (context.project_dir / "render_manifest.json").read_text(encoding="utf-8")
    )
    assert payload["success"] is True
    assert manifest["visual_mode"] == "black_subtitle"
    assert manifest["output"]["path"] == "video/final.mp4"
    assert manifest["output"]["black_background_status"] == "PASS"
    assert manifest["output"]["source_speech_evidence_status"] == "PASS"
    assert manifest["output"]["speech_content_status"] == "PASS"
    assert _module().validate_black_subtitle_render(context).ok is True


def test_finalize_black_render_rejects_missing_qwen_asr_speech_evidence(
    tmp_path,
) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    subtitle_qc = context.project_dir / "qc" / "subtitle_qc_report.json"
    subtitle_qc.parent.mkdir(parents=True, exist_ok=True)
    subtitle_qc.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    payload = _module().finalize_black_subtitle_render(
        context,
        {
            "video": str(final),
            "duration_sec": 3.2,
            "subtitle_qc_report": str(subtitle_qc),
        },
        media_probe=lambda _path, _duration: {
            "container_status": "PASS",
            "audio_status": "PASS",
            "duration_match_status": "PASS",
            "black_background_status": "PASS",
            "duration_sec": 3.2,
        },
    )

    qc = json.loads(Path(payload["qc_report"]).read_text(encoding="utf-8"))
    assert payload["success"] is False
    assert qc["status"] == "FAIL"
    assert qc["output"]["speech_content_status"] == "FAIL"
    assert _module().validate_black_subtitle_render(context).ok is False


def test_finalize_black_render_rejects_loud_audio_when_final_asr_finds_no_speech(
    tmp_path,
) -> None:
    _store, context = _black_context(tmp_path)
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"loud-tone-video")
    subtitle_qc = context.project_dir / "qc" / "subtitle_qc_report.json"
    subtitle_qc.parent.mkdir(parents=True)
    subtitle_qc.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    payload = _module().finalize_black_subtitle_render(
        context,
        {
            "video": str(final),
            "duration_sec": 3.2,
            "subtitle_qc_report": str(subtitle_qc),
        },
        media_probe=lambda _path, _duration: {
            "container_status": "PASS",
            "audio_status": "PASS",
            "duration_match_status": "PASS",
            "black_background_status": "PASS",
            "duration_sec": 3.2,
        },
        speech_evidence_probe=lambda _context: {
            "source_speech_evidence_status": "PASS",
            "asr_verified_chunk_count": 2,
        },
        final_speech_probe=lambda _context, _video: {
            "success": False,
            "error": "final MP4 ASR transcript is empty",
        },
    )

    qc = json.loads(Path(payload["qc_report"]).read_text(encoding="utf-8"))
    assert payload["success"] is False
    assert qc["output"]["audio_status"] == "PASS"
    assert qc["output"]["source_speech_evidence_status"] == "PASS"
    assert qc["output"]["speech_content_status"] == "FAIL"


def test_finalize_black_render_fails_closed_for_malformed_final_speech_result(
    tmp_path,
) -> None:
    _store, context = _black_context(tmp_path)
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    subtitle_qc = context.project_dir / "qc" / "subtitle_qc_report.json"
    subtitle_qc.parent.mkdir(parents=True)
    subtitle_qc.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    payload = _module().finalize_black_subtitle_render(
        context,
        {
            "video": str(final),
            "duration_sec": 3.2,
            "subtitle_qc_report": str(subtitle_qc),
        },
        media_probe=lambda _path, _duration: {
            "container_status": "PASS",
            "audio_status": "PASS",
            "duration_match_status": "PASS",
            "black_background_status": "PASS",
            "duration_sec": 3.2,
        },
        speech_evidence_probe=lambda _context: {
            "source_speech_evidence_status": "PASS"
        },
        final_speech_probe=lambda _context, _video: None,
    )

    assert payload["success"] is False


def test_black_media_probe_requires_mp4_video_audio_duration_and_black_top_frame(
    tmp_path,
) -> None:
    final = tmp_path / "final.mp4"
    final.write_bytes(b"video")

    payload = _module().probe_black_subtitle_media(
        final,
        3.2,
        metadata_probe=lambda _path: {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration_sec": 3.21,
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        audio_loudness_probe=lambda _path: {
            "mean_volume_db": -26.9,
            "max_volume_db": -7.7,
        },
        top_frame_luminance_probe=lambda _path: 0.0,
    )

    assert payload == {
        "container_status": "PASS",
        "audio_status": "PASS",
        "audio_mean_volume_db": -26.9,
        "audio_max_volume_db": -7.7,
        "duration_match_status": "PASS",
        "black_background_status": "PASS",
        "duration_sec": 3.21,
        "top_frame_max_luminance": 0.0,
    }


def test_black_media_probe_rejects_quiet_audio_track(tmp_path) -> None:
    final = tmp_path / "final.mp4"
    final.write_bytes(b"video")

    payload = _module().probe_black_subtitle_media(
        final,
        3.2,
        metadata_probe=lambda _path: {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration_sec": 3.2,
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        audio_loudness_probe=lambda _path: {
            "mean_volume_db": -52.0,
            "max_volume_db": -41.0,
        },
        top_frame_luminance_probe=lambda _path: 0.0,
    )

    assert payload["audio_status"] == "FAIL"
    assert payload["audio_mean_volume_db"] == -52.0
    assert payload["audio_max_volume_db"] == -41.0


def test_qwen_speech_evidence_requires_nonempty_asr_transcript(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    report = context.project_dir / "qc" / "pronunciation_qc_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v3",
                "status": "PASS",
                "method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
                "checked_unit": "voice_chunk",
                "acoustic_evidence": [
                    {
                        "voice_chunk_id": "U01__C01",
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "asr_transcript": "",
                        "transcript_similarity": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _module().probe_narration_speech_evidence(context)

    assert payload["source_speech_evidence_status"] == "FAIL"
    assert payload["asr_verified_chunk_count"] == 0


def test_qwen_speech_evidence_fails_closed_for_malformed_similarity(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["voice_chunk_count"] = 1
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    report = context.project_dir / "qc" / "pronunciation_qc_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v3",
                "status": "PASS",
                "method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
                "checked_unit": "voice_chunk",
                "acoustic_evidence": [
                    {
                        "voice_chunk_id": "U01__C01",
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "asr_transcript": "你好",
                        "transcript_similarity": "not-a-number",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _module().probe_narration_speech_evidence(context)

    assert payload["source_speech_evidence_status"] == "FAIL"
    assert payload["asr_verified_chunk_count"] == 0


@pytest.mark.parametrize("bad_count", [True, 1.5, float("inf")])
def test_qwen_speech_evidence_rejects_non_exact_integer_chunk_count(
    tmp_path, bad_count
) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    manifest = context.project_dir / "manifests" / "narration_manifest.json"
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["voice_chunk_count"] = bad_count
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    payload = _module().probe_narration_speech_evidence(context)

    assert payload["source_speech_evidence_status"] == "FAIL"


def test_qwen_speech_evidence_rejects_mismatched_run_and_chunk_ids(tmp_path) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    report = context.project_dir / "qc" / "pronunciation_qc_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v3",
                "run_id": "another-run",
                "status": "PASS",
                "method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
                "checked_unit": "voice_chunk",
                "acoustic_evidence": [
                    {
                        "voice_chunk_id": chunk_id,
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "asr_transcript": "真實語音",
                        "transcript_similarity": 0.99,
                    }
                    for chunk_id in ("S01_SH01__C01", "wrong-chunk")
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _module().probe_narration_speech_evidence(context)

    assert payload["source_speech_evidence_status"] == "FAIL"


@pytest.mark.parametrize(
    "bad_similarity", [True, False, 1.01, -0.01, float("inf")]
)
def test_qwen_speech_evidence_rejects_invalid_similarity(
    tmp_path, bad_similarity
) -> None:
    _store, context = _black_context(tmp_path)
    _write_narration(context)
    report = context.project_dir / "qc" / "pronunciation_qc_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_qc_v3",
                "run_id": context.run_id,
                "status": "PASS",
                "method": "sentence_chunk_plus_forced_alignment_isolated_term_asr",
                "checked_unit": "voice_chunk",
                "acoustic_evidence": [
                    {
                        "voice_chunk_id": chunk_id,
                        "alignment_status": "PASS",
                        "pronunciation_status": "PASS",
                        "prosody_status": "PASS",
                        "asr_transcript": "真實語音",
                        "transcript_similarity": bad_similarity,
                    }
                    for chunk_id in ("S01_SH01__C01", "S01_SH01__C02")
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _module().probe_narration_speech_evidence(context)

    assert payload["source_speech_evidence_status"] == "FAIL"


def test_black_media_probe_rejects_nonfinite_loudness(tmp_path) -> None:
    final = tmp_path / "final.mp4"
    final.write_bytes(b"video")

    payload = _module().probe_black_subtitle_media(
        final,
        3.2,
        metadata_probe=lambda _path: {
            "format_name": "mp4",
            "duration_sec": 3.2,
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        audio_loudness_probe=lambda _path: {
            "mean_volume_db": float("inf"),
            "max_volume_db": float("inf"),
        },
        top_frame_luminance_probe=lambda _path: 0.0,
    )

    assert payload["audio_status"] == "FAIL"


def test_audio_loudness_probe_fails_closed_when_ffmpeg_is_missing(
    tmp_path, monkeypatch
) -> None:
    final = tmp_path / "final.mp4"
    final.write_bytes(b"video")
    monkeypatch.setattr(
        _module().subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing ffmpeg")),
    )

    assert _module()._ffmpeg_audio_loudness(final) == {
        "mean_volume_db": None,
        "max_volume_db": None,
    }

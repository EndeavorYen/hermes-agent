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
                                        "display_text": "故事開始。",
                                        "speaker_id": "narrator",
                                        "voice_id": "simon_clean_v2",
                                        "scene_start_sec": 0.0,
                                        "scene_speech_end_sec": 1.4,
                                    },
                                    {
                                        "display_text": "出發吧！",
                                        "speaker_id": "xiaomei",
                                        "voice_id": "qwen_custom_vivian",
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
def test_real_black_subtitle_renderer_produces_valid_mp4(tmp_path) -> None:
    from plugins.story_video.production_runner import _default_renderer

    _store, context = _black_context(tmp_path)
    _write_narration(context)
    _write_real_pcm_wav(context.project_dir / "audio" / "S01.wav")
    _module().prepare_black_subtitle_render(context)

    payload = _default_renderer(context)

    assert payload["success"] is True
    final = Path(payload["video"])
    assert final.is_file()
    assert final.suffix == ".mp4"
    qc = json.loads(Path(payload["qc_report"]).read_text(encoding="utf-8"))
    assert qc["output"]["container_status"] == "PASS"
    assert qc["output"]["audio_status"] == "PASS"
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
    assert render_input["subtitle"]["max_chars_per_line"] == 22
    assert render_input["subtitle"]["position"] == "center"
    assert render_input["subtitle"]["center_y_ratio"] == 0.55
    assert [cue["text"] for cue in shot["subtitle_cues"]] == [
        "故事開始。",
        "出發吧！",
    ]
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
    )

    manifest = json.loads(
        (context.project_dir / "render_manifest.json").read_text(encoding="utf-8")
    )
    assert payload["success"] is True
    assert manifest["visual_mode"] == "black_subtitle"
    assert manifest["output"]["path"] == "video/final.mp4"
    assert manifest["output"]["black_background_status"] == "PASS"
    assert _module().validate_black_subtitle_render(context).ok is True


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
        top_frame_luminance_probe=lambda _path: 0.0,
    )

    assert payload == {
        "container_status": "PASS",
        "audio_status": "PASS",
        "duration_match_status": "PASS",
        "black_background_status": "PASS",
        "duration_sec": 3.21,
        "top_frame_max_luminance": 0.0,
    }

from __future__ import annotations

import json
import io
import math
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from .state import StoryVideoRunContext


BLACK_SUBTITLE_NARRATOR_COLOR = "#FFFFFF"
BLACK_SUBTITLE_ROLE_PALETTE = (
    "#7FDBFF",
    "#FF9ECD",
    "#FFD166",
    "#B8F2A2",
    "#CDB4FF",
)
BLACK_SUBTITLE_EMOTION_LABELS = {
    "wonder": "驚奇",
    "curious": "疑惑",
    "joy": "開心",
    "sadness": "難過",
    "fear": "害怕",
    "tension": "緊張",
    "surprise": "驚訝",
    "humor": "幽默",
    "warmth": "溫暖",
}
BLACK_SUBTITLE_MIN_MEAN_VOLUME_DB = -45.0
BLACK_SUBTITLE_MIN_PEAK_VOLUME_DB = -24.0
QWEN_SPEECH_QC_METHOD = "sentence_chunk_plus_forced_alignment_isolated_term_asr"
SUPPORTED_NARRATION_MANIFEST_SCHEMAS = {
    "story_video_narration_manifest_v4",
    "story_video_narration_manifest_v5",
    "story_video_narration_manifest_v6",
    "story_video_narration_manifest_v7",
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"missing or invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _project_file(context: StoryVideoRunContext, value: Any, *, label: str) -> tuple[Path, str]:
    project = context.project_dir.expanduser().resolve()
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = project / path
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(project)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"{label} must be inside the active project") from exc
    if not resolved.is_file() or resolved.stat().st_size <= 1:
        raise ValueError(f"missing {label}: {resolved}")
    return resolved, str(relative)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "scene"


def _speaker_key(chunk: dict[str, Any]) -> str:
    return str(
        chunk.get("speaker_id")
        or chunk.get("speaker")
        or chunk.get("voice_id")
        or "narrator"
    ).strip()


def _speaker_cast_metadata(
    context: StoryVideoRunContext,
) -> dict[str, dict[str, str]]:
    path = context.project_dir / "voice_cast_binding.json"
    if not path.is_file():
        return {}
    payload = _load_json(path)
    speakers = payload.get("speakers")
    if not isinstance(speakers, list):
        return {}
    return {
        str(row.get("speaker_id") or "").strip(): {
            "display_name": str(
                row.get("display_name") or row.get("speaker_id") or ""
            ).strip(),
            "role": str(row.get("role") or "").strip().casefold(),
        }
        for row in speakers
        if isinstance(row, dict) and str(row.get("speaker_id") or "").strip()
    }


def _visual_subtitle_text(
    text: str,
    *,
    speaker_id: str,
    display_name: str,
    emotion: str,
    action: str,
    is_narrator: bool,
) -> str:
    if is_narrator or speaker_id.casefold() in {"narrator", "旁白"}:
        return text
    emotion_label = BLACK_SUBTITLE_EMOTION_LABELS.get(emotion, "")
    localized_action = (
        action
        if re.search(r"[\u3400-\u9fff]", action)
        and not re.search(r"[A-Za-z]", action)
        and len(action) <= 16
        else ""
    )
    direction = localized_action or emotion_label or "自然"
    suffix = f"（{direction}）" if direction else ""
    return f"{display_name or speaker_id}{suffix}\n「{text}」"


def _black_subtitle_role_colors(
    outputs: list[dict[str, Any]], narrator_ids: set[str]
) -> dict[str, str]:
    speakers: list[str] = []
    for output in outputs:
        for segment in output.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            for chunk in segment.get("voice_chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                speaker = _speaker_key(chunk)
                if speaker and speaker not in speakers:
                    speakers.append(speaker)
    colors: dict[str, str] = {}
    palette_index = 0
    for speaker in speakers or ["narrator"]:
        if speaker in narrator_ids or speaker.casefold() in {"narrator", "旁白"}:
            colors[speaker] = BLACK_SUBTITLE_NARRATOR_COLOR
            continue
        colors[speaker] = BLACK_SUBTITLE_ROLE_PALETTE[
            palette_index % len(BLACK_SUBTITLE_ROLE_PALETTE)
        ]
        palette_index += 1
    return colors


def _subtitle_cues(
    output: dict[str, Any],
    role_colors: dict[str, str],
    speaker_cast_metadata: dict[str, dict[str, str]],
) -> tuple[str, list[dict[str, Any]]]:
    cues: list[dict[str, Any]] = []
    for segment in output.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for chunk in segment.get("voice_chunks") or []:
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("display_text") or "")
            start = float(chunk.get("scene_start_sec") or 0.0)
            end = float(chunk.get("scene_speech_end_sec") or 0.0)
            if not text or end <= start:
                raise ValueError("voice chunk requires display text and measured timing")
            speaker_id = _speaker_key(chunk)
            speaker = speaker_cast_metadata.get(speaker_id, {})
            emotion = str(chunk.get("emotion") or "").strip()
            action = str(chunk.get("action") or "").strip()
            cues.append(
                {
                    "text": text,
                    "visual_text": _visual_subtitle_text(
                        text,
                        speaker_id=speaker_id,
                        display_name=speaker.get("display_name", speaker_id),
                        emotion=emotion,
                        action=action,
                        is_narrator=speaker.get("role") == "narrator",
                    ),
                    "start_sec": round(start, 4),
                    "end_sec": round(end, 4),
                    "sentence_count": 1,
                    "speaker_id": speaker_id,
                    "voice_id": str(chunk.get("voice_id") or "").strip(),
                    "emotion": emotion,
                    "action": action,
                    "color": role_colors.get(
                        speaker_id, BLACK_SUBTITLE_NARRATOR_COLOR
                    ),
                }
            )
    display_text = "".join(str(cue["text"]) for cue in cues)
    expected = str(output.get("display_text") or "")
    if not cues:
        duration = float(output.get("duration_sec") or 0.0)
        if not expected or duration <= 0:
            raise ValueError("narration output requires measured subtitle evidence")
        display_text = expected
        cues = [
            {
                "text": expected,
                "visual_text": expected,
                "start_sec": 0.0,
                "end_sec": round(duration, 4),
                "sentence_count": 1,
                "speaker_id": "narrator",
                "voice_id": str(output.get("voice_id") or "").strip(),
                "emotion": "",
                "action": "",
                "color": BLACK_SUBTITLE_NARRATOR_COLOR,
            }
        ]
    if "".join(display_text.split()) != "".join(expected.split()):
        raise ValueError("voice chunks do not preserve narration display text")
    return display_text, cues


def prepare_black_subtitle_render(context: StoryVideoRunContext) -> dict[str, Any]:
    if context.visual_mode != "black_subtitle":
        raise ValueError("black subtitle render requires visual_mode=black_subtitle")
    manifest = _load_json(
        context.project_dir / "manifests" / "narration_manifest.json"
    )
    narration_schema = str(manifest.get("schema") or "")
    if narration_schema and narration_schema not in SUPPORTED_NARRATION_MANIFEST_SCHEMAS:
        raise ValueError(f"unsupported narration manifest schema: {narration_schema}")
    if manifest.get("run_id") not in {None, "", context.run_id}:
        raise ValueError("narration manifest belongs to another run")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("narration manifest has no outputs")

    normalized_outputs = [output for output in outputs if isinstance(output, dict)]
    speaker_cast_metadata = _speaker_cast_metadata(context)
    narrator_ids = {
        speaker_id
        for speaker_id, metadata in speaker_cast_metadata.items()
        if metadata.get("role") == "narrator"
    }
    role_colors = _black_subtitle_role_colors(normalized_outputs, narrator_ids)
    scenes: list[dict[str, Any]] = []
    assets = context.project_dir / "assets" / "black"
    assets.mkdir(parents=True, exist_ok=True)
    for index, output in enumerate(outputs, start=1):
        if not isinstance(output, dict):
            raise ValueError(f"narration output[{index - 1}] must be an object")
        scene_id = str(output.get("scene_id") or f"S{index:02d}").strip()
        _audio_path, audio_relative = _project_file(
            context,
            output.get("audio"),
            label=f"audio for {scene_id}",
        )
        display_text, cues = _subtitle_cues(
            output,
            role_colors,
            speaker_cast_metadata,
        )
        duration = float(output.get("duration_sec") or 0.0)
        if duration <= 0 or cues[-1]["end_sec"] > duration + 0.25:
            raise ValueError(f"invalid narration duration for {scene_id}")
        image_path = assets / f"{index:03d}-{_safe_id(scene_id)}.png"
        Image.new("RGB", (1920, 1080), (0, 0, 0)).save(image_path, "PNG")
        image_relative = str(image_path.relative_to(context.project_dir))
        scenes.append(
            {
                "scene_id": scene_id,
                "selected": True,
                "audio": audio_relative,
                "narration": display_text,
                "shots": [
                    {
                        "shot_id": f"{scene_id}_BLACK",
                        "selected": True,
                        "image": image_relative,
                        "narration": display_text,
                        "timeline_duration_sec": duration,
                        "speech_end_sec": cues[-1]["end_sec"],
                        "subtitle_position": "center",
                        "subtitle_timing_source": "measured_voice_chunks",
                        "subtitle_cues": cues,
                    }
                ],
            }
        )

    render_input = {
        "schema": "story_video_render_input_v2",
        "visual_mode": "black_subtitle",
        "project_title": context.topic,
        "title": context.topic,
        "resolution": {"width": 1920, "height": 1080},
        "fps": 30,
        "post_speech_hold_sec": 0.18,
        "max_post_speech_hold_sec": 0.6,
        "motion_policy": "static_hold",
        "zoom_max": 1.0,
        "subtitle": {
            "font_size": 72,
            "max_lines": 3,
            "max_chars_per_line": 24,
            "preferred_sentences_per_cue": 1,
            "max_sentences_per_cue": 2,
            "min_cue_duration_sec": 0.35,
            "hide_outside_speech": True,
            "position": "center",
            "center_y_ratio": 0.55,
            "role_colors": role_colors,
            "production_stage": "post_composite",
            "qc_mode": "fast_post_composite",
        },
        "scenes": scenes,
        "output": "video/final.mp4",
    }
    path = context.project_dir / "render_input.json"
    _write_json_atomic(path, render_input)
    return {
        "success": True,
        "visual_mode": "black_subtitle",
        "render_input": str(path),
        "scene_count": len(scenes),
        "selected_shot_count": len(scenes),
    }


def _ffprobe_metadata(path: Path) -> dict[str, Any]:
    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration:stream=codec_type,codec_name",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {}
    if process.returncode != 0:
        return {}
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return {}
    streams = payload.get("streams") or []
    video = next(
        (row for row in streams if row.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (row for row in streams if row.get("codec_type") == "audio"),
        {},
    )
    format_payload = payload.get("format") or {}
    try:
        duration = float(format_payload.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "format_name": str(format_payload.get("format_name") or ""),
        "duration_sec": duration,
        "video_codec": str(video.get("codec_name") or ""),
        "audio_codec": str(audio.get("codec_name") or ""),
    }


def _top_frame_max_luminance(path: Path) -> float:
    try:
        process = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                "0.5",
                "-i",
                str(path),
                "-vf",
                "crop=iw:floor(ih*0.25):0:0",
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-",
            ],
            capture_output=True,
            check=False,
        )
    except OSError:
        return 255.0
    if process.returncode != 0 or not process.stdout:
        return 255.0
    with Image.open(io.BytesIO(process.stdout)) as image:
        _minimum, maximum = image.convert("L").getextrema()
    return float(maximum)


def _ffmpeg_audio_loudness(path: Path) -> dict[str, float | None]:
    try:
        process = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {"mean_volume_db": None, "max_volume_db": None}
    output = process.stderr or ""

    def value(label: str) -> float | None:
        match = re.search(rf"{label}:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dB", output)
        if match is None or match.group(1) == "-inf":
            return None
        return float(match.group(1))

    return {
        "mean_volume_db": value("mean_volume"),
        "max_volume_db": value("max_volume"),
    }


def probe_narration_speech_evidence(
    context: StoryVideoRunContext,
) -> dict[str, Any]:
    try:
        manifest = _load_json(
            context.project_dir / "manifests" / "narration_manifest.json"
        )
        report = _load_json(
            context.project_dir / "qc" / "pronunciation_qc_report.json"
        )
    except ValueError:
        manifest = {}
        report = {}
    expected_count_raw = manifest.get("voice_chunk_count")
    expected_count = expected_count_raw if type(expected_count_raw) is int else 0
    chunks_by_id = {
        str(chunk.get("voice_chunk_id") or "").strip(): chunk
        for output in manifest.get("outputs") or []
        if isinstance(output, dict)
        for segment in output.get("segments") or []
        if isinstance(segment, dict)
        for chunk in segment.get("voice_chunks") or []
        if isinstance(chunk, dict)
        and str(chunk.get("voice_chunk_id") or "").strip()
    }
    expected_ids = list(chunks_by_id)
    display_pause_only_re = re.compile(
        r"(?:(?:\.{3,}|…{2,}|⋯{2,}|—{1,2})\s*)+"
    )
    pause_ids = {
        chunk_id
        for chunk_id, chunk in chunks_by_id.items()
        if chunk.get("display_pause_only") is True
        and not str(chunk.get("spoken_text") or "").strip()
        and bool(
            (display_text := str(chunk.get("display_text") or "").strip())
            and display_pause_only_re.fullmatch(display_text)
        )
    }
    evidence = report.get("acoustic_evidence")
    rows = evidence if isinstance(evidence, list) else []
    verified: list[dict[str, Any]] = []
    verified_pauses: list[dict[str, Any]] = []
    similarities: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        chunk_id = str(row.get("voice_chunk_id") or "").strip()
        transcript_similarity_raw = row.get("transcript_similarity")
        transcript_similarity = (
            float(transcript_similarity_raw)
            if type(transcript_similarity_raw) in {int, float}
            and math.isfinite(float(transcript_similarity_raw))
            and 0.0 <= float(transcript_similarity_raw) <= 1.0
            else None
        )
        token_similarity_raw = row.get("token_similarity")
        token_similarity = (
            float(token_similarity_raw)
            if type(token_similarity_raw) in {int, float}
            and math.isfinite(float(token_similarity_raw))
            and 0.0 <= float(token_similarity_raw) <= 1.0
            else None
        )
        if transcript_similarity is None or (
            "token_similarity" in row and token_similarity is None
        ):
            continue
        gates_pass = all(
            str(row.get(gate) or "").upper() == "PASS"
            for gate in (
                "alignment_status",
                "pronunciation_status",
                "prosody_status",
            )
        )
        if chunk_id in pause_ids:
            if (
                gates_pass
                and not str(row.get("asr_transcript") or "").strip()
                and transcript_similarity == 1.0
                and str(row.get("prosody_measurement_status") or "").upper()
                == "NOT_APPLICABLE"
            ):
                verified_pauses.append(row)
            continue
        chunk = chunks_by_id.get(chunk_id, {})
        spoken_text = str(chunk.get("spoken_text") or "")
        speech_duration = chunk.get("speech_duration_sec")
        short_interjection_fallback = bool(
            transcript_similarity == 0.0
            and token_similarity is not None
            and token_similarity >= 0.94
            and type(speech_duration) in {int, float}
            and math.isfinite(float(speech_duration))
            and 0.0 < float(speech_duration) <= 0.75
            and 0 < sum(char.isalnum() for char in spoken_text) <= 2
            and str(row.get("prosody_measurement_status") or "").upper()
            == "NOT_MEASURED_SHORT_CLIP"
        )
        similarity = (
            token_similarity if short_interjection_fallback else transcript_similarity
        )
        if (
            not chunk_id
            or not str(row.get("asr_transcript") or "").strip()
            or not gates_pass
            or similarity <= 0.0
        ):
            continue
        verified.append(row)
        similarities.append(similarity)
    valid_contract = (
        str(manifest.get("provider") or "").replace("_", "-").casefold()
        == "local-qwen"
        and report.get("schema") == "story_video_pronunciation_qc_v3"
        and str(report.get("status") or "").upper() == "PASS"
        and report.get("method") == QWEN_SPEECH_QC_METHOD
        and report.get("checked_unit") == "voice_chunk"
        and str(manifest.get("run_id") or "") == context.run_id
        and str(report.get("run_id") or "") == context.run_id
        and expected_count > 0
        and expected_count == len(expected_ids)
        and len(set(expected_ids)) == expected_count
        and len(rows) == expected_count
        and len(verified) == expected_count - len(pause_ids)
        and len(verified_pauses) == len(pause_ids)
        and {str(row["voice_chunk_id"]) for row in verified}
        == set(expected_ids) - pause_ids
        and {str(row["voice_chunk_id"]) for row in verified_pauses} == pause_ids
    )
    return {
        "source_speech_evidence_status": "PASS" if valid_contract else "FAIL",
        "speech_qc_method": str(report.get("method") or ""),
        "asr_verified_chunk_count": len(verified),
        "display_pause_chunk_count": len(verified_pauses),
        "minimum_transcript_similarity": (
            round(min(similarities), 4) if similarities else 0.0
        ),
    }


def probe_black_subtitle_media(
    path: str | Path,
    expected_duration_sec: float,
    *,
    metadata_probe: Any = _ffprobe_metadata,
    audio_loudness_probe: Any = _ffmpeg_audio_loudness,
    top_frame_luminance_probe: Any = _top_frame_max_luminance,
) -> dict[str, Any]:
    video = Path(path).expanduser().resolve()
    metadata = metadata_probe(video)
    duration = float(metadata.get("duration_sec") or 0.0)
    expected = float(expected_duration_sec or 0.0)
    tolerance = max(0.25, expected * 0.02)
    luminance = float(top_frame_luminance_probe(video))
    loudness = audio_loudness_probe(video)
    mean_volume = loudness.get("mean_volume_db")
    max_volume = loudness.get("max_volume_db")
    audible = (
        isinstance(mean_volume, (int, float))
        and isinstance(max_volume, (int, float))
        and not isinstance(mean_volume, bool)
        and not isinstance(max_volume, bool)
        and math.isfinite(float(mean_volume))
        and math.isfinite(float(max_volume))
        and float(mean_volume) >= BLACK_SUBTITLE_MIN_MEAN_VOLUME_DB
        and float(max_volume) >= BLACK_SUBTITLE_MIN_PEAK_VOLUME_DB
    )
    return {
        "container_status": (
            "PASS"
            if video.suffix.casefold() == ".mp4"
            and "mp4" in str(metadata.get("format_name") or "").casefold()
            and str(metadata.get("video_codec") or "").casefold() == "h264"
            else "FAIL"
        ),
        "audio_status": (
            "PASS"
            if str(metadata.get("audio_codec") or "").strip() and audible
            else "FAIL"
        ),
        "audio_mean_volume_db": (
            round(float(mean_volume), 4) if mean_volume is not None else None
        ),
        "audio_max_volume_db": (
            round(float(max_volume), 4) if max_volume is not None else None
        ),
        "duration_match_status": (
            "PASS"
            if duration > 0 and expected > 0 and abs(duration - expected) <= tolerance
            else "FAIL"
        ),
        "black_background_status": "PASS" if luminance <= 8.0 else "FAIL",
        "duration_sec": round(duration, 4),
        "top_frame_max_luminance": round(luminance, 4),
    }


def finalize_black_subtitle_render(
    context: StoryVideoRunContext,
    renderer_result: dict[str, Any],
    *,
    media_probe: Any = probe_black_subtitle_media,
    speech_evidence_probe: Any = probe_narration_speech_evidence,
    final_speech_probe: Any = None,
) -> dict[str, Any]:
    selected, selected_relative = _project_file(
        context,
        renderer_result.get("video"),
        label="rendered MP4",
    )
    expected_duration = float(renderer_result.get("duration_sec") or 0.0)
    media = media_probe(selected, expected_duration)
    source_speech = speech_evidence_probe(context)
    if final_speech_probe is None:
        from .delivery_speech import verify_final_video_speech

        final_speech_probe = verify_final_video_speech
    final_speech = final_speech_probe(context, selected)
    if not isinstance(final_speech, dict):
        final_speech = {"success": False}
    subtitle_qc_path = Path(str(renderer_result.get("subtitle_qc_report") or ""))
    if not subtitle_qc_path.is_absolute():
        subtitle_qc_path = context.project_dir / subtitle_qc_path
    try:
        subtitle_qc = _load_json(subtitle_qc_path)
    except ValueError:
        subtitle_qc = {}
    subtitle_status = str(subtitle_qc.get("status") or "").upper()
    output = {
        "path": selected_relative,
        "subtitles": {
            "hard_burned": subtitle_status == "PASS",
            "coverage_status": subtitle_status or "FAIL",
        },
        **media,
        **source_speech,
        "speech_content_status": (
            "PASS" if final_speech.get("success") is True else "FAIL"
        ),
        "final_speech_qc_report": str(final_speech.get("qc_report") or ""),
        "final_speech_video_sha256": str(
            final_speech.get("video_sha256") or ""
        ),
    }
    proof_passes = (
        subtitle_status == "PASS"
        and all(
            str(output.get(field) or "").upper() == "PASS"
            for field in (
                "container_status",
                "audio_status",
                "source_speech_evidence_status",
                "speech_content_status",
                "duration_match_status",
                "black_background_status",
            )
        )
    )
    qc_path = context.project_dir / "qc" / "black_subtitle_render_qc.json"
    qc = {
        "schema": "story_video_black_subtitle_render_qc_v1",
        "run_id": context.run_id,
        "visual_mode": "black_subtitle",
        "status": "PASS" if proof_passes else "FAIL",
        "output": output,
    }
    _write_json_atomic(qc_path, qc)
    manifest = {
        "schema": "story_video_render_manifest_v2",
        "run_id": context.run_id,
        "visual_mode": "black_subtitle",
        "output": output,
        "qc_report": str(qc_path.relative_to(context.project_dir)),
    }
    _write_json_atomic(context.project_dir / "render_manifest.json", manifest)
    return {
        "success": proof_passes,
        "video": str(selected),
        "selected_mp4": str(selected),
        "qc_report": str(qc_path),
        "duration_sec": media.get("duration_sec"),
    }


def validate_black_subtitle_render(context: StoryVideoRunContext):
    from .tools import PhaseProof

    missing: list[str] = []
    violations: list[str] = []
    try:
        manifest = _load_json(context.project_dir / "render_manifest.json")
    except ValueError:
        manifest = {}
        missing.append("render_manifest.json")
    output = manifest.get("output") if isinstance(manifest, dict) else None
    if not isinstance(output, dict):
        missing.append("primary render output metadata")
    else:
        raw_path = str(output.get("path") or "")
        try:
            _project_file(context, raw_path, label="primary render")
        except ValueError:
            missing.append(raw_path or "primary render output path")
        subtitles = output.get("subtitles") or {}
        if not (
            subtitles.get("hard_burned") is True
            and str(subtitles.get("coverage_status") or "").upper() == "PASS"
        ):
            violations.append("black_subtitle render lacks complete hard-burned subtitles")
        for field in (
            "container_status",
            "audio_status",
            "source_speech_evidence_status",
            "speech_content_status",
            "duration_match_status",
            "black_background_status",
        ):
            if str(output.get(field) or "").upper() != "PASS":
                violations.append(f"black_subtitle {field} is not PASS")
    audit_path = context.project_dir / "manifests" / "provider_audit.json"
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        audit = {"events": []}
    for event in audit.get("events") or []:
        if not isinstance(event, dict):
            continue
        if (
            str(event.get("kind") or "").casefold() == "image"
            and str(event.get("status") or "").casefold() != "blocked"
        ):
            violations.append("black_subtitle run invoked an image provider")
            break
    return PhaseProof(
        phase="render",
        ok=not missing and not violations,
        missing=tuple(missing),
        violations=tuple(violations),
    )

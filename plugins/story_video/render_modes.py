from __future__ import annotations

import json
import io
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


def _black_subtitle_role_colors(outputs: list[dict[str, Any]]) -> dict[str, str]:
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
        if speaker.casefold() in {"narrator", "旁白"}:
            colors[speaker] = BLACK_SUBTITLE_NARRATOR_COLOR
            continue
        colors[speaker] = BLACK_SUBTITLE_ROLE_PALETTE[
            palette_index % len(BLACK_SUBTITLE_ROLE_PALETTE)
        ]
        palette_index += 1
    return colors


def _subtitle_cues(
    output: dict[str, Any], role_colors: dict[str, str]
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
            cues.append(
                {
                    "text": text,
                    "start_sec": round(start, 4),
                    "end_sec": round(end, 4),
                    "sentence_count": 1,
                    "speaker_id": speaker_id,
                    "voice_id": str(chunk.get("voice_id") or "").strip(),
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
                "start_sec": 0.0,
                "end_sec": round(duration, 4),
                "sentence_count": 1,
                "speaker_id": "narrator",
                "voice_id": str(output.get("voice_id") or "").strip(),
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
    if manifest.get("run_id") not in {None, "", context.run_id}:
        raise ValueError("narration manifest belongs to another run")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("narration manifest has no outputs")

    normalized_outputs = [output for output in outputs if isinstance(output, dict)]
    role_colors = _black_subtitle_role_colors(normalized_outputs)
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
        display_text, cues = _subtitle_cues(output, role_colors)
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
            "max_lines": 2,
            "max_chars_per_line": 22,
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
    if process.returncode != 0 or not process.stdout:
        return 255.0
    with Image.open(io.BytesIO(process.stdout)) as image:
        _minimum, maximum = image.convert("L").getextrema()
    return float(maximum)


def probe_black_subtitle_media(
    path: str | Path,
    expected_duration_sec: float,
    *,
    metadata_probe: Any = _ffprobe_metadata,
    top_frame_luminance_probe: Any = _top_frame_max_luminance,
) -> dict[str, Any]:
    video = Path(path).expanduser().resolve()
    metadata = metadata_probe(video)
    duration = float(metadata.get("duration_sec") or 0.0)
    expected = float(expected_duration_sec or 0.0)
    tolerance = max(0.25, expected * 0.02)
    luminance = float(top_frame_luminance_probe(video))
    return {
        "container_status": (
            "PASS"
            if video.suffix.casefold() == ".mp4"
            and "mp4" in str(metadata.get("format_name") or "").casefold()
            and str(metadata.get("video_codec") or "").casefold() == "h264"
            else "FAIL"
        ),
        "audio_status": (
            "PASS" if str(metadata.get("audio_codec") or "").strip() else "FAIL"
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
) -> dict[str, Any]:
    selected, selected_relative = _project_file(
        context,
        renderer_result.get("video"),
        label="rendered MP4",
    )
    expected_duration = float(renderer_result.get("duration_sec") or 0.0)
    media = media_probe(selected, expected_duration)
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
    }
    proof_passes = (
        subtitle_status == "PASS"
        and all(
            str(media.get(field) or "").upper() == "PASS"
            for field in (
                "container_status",
                "audio_status",
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

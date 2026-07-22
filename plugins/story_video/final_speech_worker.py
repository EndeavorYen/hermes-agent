"""Run final-artifact ASR against the rendered story-video MP4."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable


FINAL_SPEECH_QC_SCHEMA = "story_video_final_speech_qc_v1"
FINAL_SPEECH_QC_METHOD = "final_mp4_demux_qwen_asr_v1"
FINAL_SPEECH_MIN_SIMILARITY = 0.72
DEFAULT_ASR_MODEL = Path.home() / ".hermes/models/Qwen3-ASR-0.6B-8bit"
_DISPLAY_PAUSE_ONLY_RE = re.compile(
    r"(?:(?:\.{3,}|…{2,}|⋯{2,}|—{1,2})\s*)+"
)


def _is_display_pause_only(text: str) -> bool:
    source = str(text or "").strip()
    return bool(source and _DISPLAY_PAUSE_ONLY_RE.fullmatch(source))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_transcript(text: str) -> str:
    return "".join(re.findall(r"[\w\u3400-\u9fff]", str(text).casefold()))


def _comparison_transcript(text: str) -> str:
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        return _normalized_transcript(text)
    return "|".join(
        lazy_pinyin(
            str(text),
            style=Style.TONE3,
            neutral_tone_with_five=True,
            errors=lambda value: list(value),
        )
    )


def _default_audio_extractor(video: Path, audio: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        check=True,
        capture_output=True,
    )


def _default_transcriber(audio: Path) -> str:
    model_file = DEFAULT_ASR_MODEL / "model.safetensors"
    if not model_file.is_file():
        raise RuntimeError(f"final speech ASR model is missing: {DEFAULT_ASR_MODEL}")
    from mlx_audio.stt import load

    model = load(str(DEFAULT_ASR_MODEL))
    return str(model.generate(str(audio), language="Chinese").text).strip()


def evaluate_final_speech(
    *,
    video: Path,
    run_id: str,
    expected_text: str,
    audio_extractor: Callable[[Path, Path], None] = _default_audio_extractor,
    transcriber: Callable[[Path], str] = _default_transcriber,
    comparison_normalizer: Callable[[str], str] = _comparison_transcript,
) -> dict[str, Any]:
    expected = comparison_normalizer(expected_text)
    observed_text = ""
    error = ""
    with tempfile.TemporaryDirectory(prefix="story-video-final-speech-") as raw_tmp:
        audio = Path(raw_tmp) / "final.wav"
        try:
            audio_extractor(video, audio)
            observed_text = str(transcriber(audio) or "").strip()
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            error = str(exc)
    observed = comparison_normalizer(observed_text)
    similarity = (
        SequenceMatcher(None, expected, observed, autojunk=False).ratio()
        if expected and observed
        else 0.0
    )
    passed = bool(
        not error
        and expected
        and observed
        and math.isfinite(similarity)
        and similarity >= FINAL_SPEECH_MIN_SIMILARITY
    )
    return {
        "schema": FINAL_SPEECH_QC_SCHEMA,
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "method": FINAL_SPEECH_QC_METHOD,
        "video_sha256": _sha256(video),
        "expected_transcript": expected_text,
        "asr_transcript": observed_text,
        "transcript_similarity": round(similarity, 4),
        "minimum_similarity": FINAL_SPEECH_MIN_SIMILARITY,
        "error": error,
    }


def _expected_text(project_dir: Path) -> str:
    return str(load_narration_contract(project_dir)["expected_transcript"])


def load_narration_contract(project_dir: Path) -> dict[str, Any]:
    manifest_path = project_dir / "manifests" / "narration_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("narration manifest must be an object")
    run_id = str(payload.get("run_id") or "").strip()
    count = payload.get("voice_chunk_count")
    outputs = payload.get("outputs")
    if not run_id:
        raise ValueError("narration manifest lacks run_id")
    if type(count) is not int or count <= 0:
        raise ValueError("narration manifest voice_chunk_count must be a positive integer")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("narration manifest has no outputs")
    chunk_ids: list[str] = []
    chunk_texts: list[str] = []
    output_texts: list[str] = []
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("narration output must be an object")
        output_texts.append(str(output.get("spoken_text") or ""))
        segments = output.get("segments")
        if not isinstance(segments, list):
            raise ValueError("narration output lacks segments")
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError("narration segment must be an object")
            chunks = segment.get("voice_chunks")
            if not isinstance(chunks, list):
                raise ValueError("narration segment lacks voice chunks")
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    raise ValueError("narration voice chunk must be an object")
                chunk_id = str(chunk.get("voice_chunk_id") or "").strip()
                spoken_text = str(chunk.get("spoken_text") or "").strip()
                display_pause_only = chunk.get("display_pause_only") is True
                if not chunk_id or (not spoken_text and not display_pause_only):
                    raise ValueError("narration voice chunk lacks id or spoken text")
                if display_pause_only and (
                    spoken_text
                    or not _is_display_pause_only(
                        str(chunk.get("display_text") or "")
                    )
                ):
                    raise ValueError("narration display-only pause is not canonical")
                chunk_ids.append(chunk_id)
                if spoken_text:
                    chunk_texts.append(spoken_text)
    if len(chunk_ids) != count or len(set(chunk_ids)) != count:
        raise ValueError("narration voice chunk ids/count are inconsistent")
    expected = "".join(chunk_texts)
    if _normalized_transcript("".join(output_texts)) != _normalized_transcript(expected):
        raise ValueError("narration output and voice chunk transcripts differ")
    return {
        "run_id": run_id,
        "voice_chunk_count": count,
        "voice_chunk_ids": chunk_ids,
        "expected_transcript": expected,
        "narration_manifest_sha256": _sha256(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    project = Path(args.project_dir).expanduser().resolve()
    video = Path(args.video).expanduser().resolve()
    try:
        video.relative_to(project)
        contract = load_narration_contract(project)
        if contract["run_id"] != args.run_id:
            raise ValueError("narration manifest belongs to another run")
        result = evaluate_final_speech(
            video=video,
            run_id=args.run_id,
            expected_text=str(contract["expected_transcript"]),
        )
        result.update(
            {
                "narration_manifest_sha256": contract[
                    "narration_manifest_sha256"
                ],
                "voice_chunk_count": contract["voice_chunk_count"],
                "voice_chunk_ids": contract["voice_chunk_ids"],
            }
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema": FINAL_SPEECH_QC_SCHEMA,
            "run_id": args.run_id,
            "status": "FAIL",
            "method": FINAL_SPEECH_QC_METHOD,
            "video_sha256": _sha256(video) if video.is_file() else "",
            "narration_manifest_sha256": "",
            "voice_chunk_count": 0,
            "voice_chunk_ids": [],
            "expected_transcript": "",
            "asr_transcript": "",
            "transcript_similarity": 0.0,
            "error": str(exc),
        }
    report = project / "qc" / "final_speech_qc_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    temporary = report.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report)
    print(json.dumps({**result, "qc_report": str(report)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

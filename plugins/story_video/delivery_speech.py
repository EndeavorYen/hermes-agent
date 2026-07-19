"""Fail-closed final-MP4 speech verification for every story-video mode."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .final_speech_worker import (
    FINAL_SPEECH_MIN_SIMILARITY,
    FINAL_SPEECH_QC_METHOD,
    FINAL_SPEECH_QC_SCHEMA,
    load_narration_contract,
)
from .state import StoryVideoRunContext


DEFAULT_MLX_PYTHON = Path.home() / ".hermes/.venvs/mlx-audio/bin/python"
FINAL_SPEECH_QC_RELATIVE = Path("qc/final_speech_qc_report.json")


@dataclass(frozen=True)
class FinalSpeechProof:
    ok: bool
    violations: tuple[str, ...] = ()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_final_speech_report(
    context: StoryVideoRunContext,
    video: Path,
    report: dict[str, Any],
) -> FinalSpeechProof:
    violations: list[str] = []
    if report.get("schema") != FINAL_SPEECH_QC_SCHEMA:
        violations.append("final speech QC schema is stale")
    if str(report.get("run_id") or "") != context.run_id:
        violations.append("final speech QC belongs to another run")
    if str(report.get("status") or "").upper() != "PASS":
        violations.append("final speech QC is not PASS")
    if report.get("method") != FINAL_SPEECH_QC_METHOD:
        violations.append("final speech QC method is not final-artifact ASR")
    try:
        actual_hash = _sha256(video)
    except OSError:
        actual_hash = ""
    if not actual_hash or str(report.get("video_sha256") or "") != actual_hash:
        violations.append("final speech QC is not bound to the selected MP4")
    try:
        contract = load_narration_contract(context.project_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        contract = None
        violations.append(f"current narration contract is invalid: {exc}")
    if contract is not None:
        if contract["run_id"] != context.run_id:
            violations.append("narration manifest belongs to another run")
        if (
            str(report.get("narration_manifest_sha256") or "")
            != contract["narration_manifest_sha256"]
        ):
            violations.append("final speech QC is not bound to the narration manifest")
        if type(report.get("voice_chunk_count")) is not int or (
            report.get("voice_chunk_count") != contract["voice_chunk_count"]
        ):
            violations.append("final speech QC voice chunk count does not match")
        if report.get("voice_chunk_ids") != contract["voice_chunk_ids"]:
            violations.append("final speech QC ordered voice chunk ids do not match")
        if str(report.get("expected_transcript") or "") != contract[
            "expected_transcript"
        ]:
            violations.append("final speech QC expected transcript does not match")
    similarity_raw = report.get("transcript_similarity")
    similarity = (
        float(similarity_raw)
        if type(similarity_raw) in {int, float}
        else float("nan")
    )
    if not math.isfinite(similarity) or similarity < FINAL_SPEECH_MIN_SIMILARITY:
        violations.append("final MP4 ASR similarity is below threshold")
    if not str(report.get("expected_transcript") or "").strip():
        violations.append("final speech QC lacks expected transcript")
    if not str(report.get("asr_transcript") or "").strip():
        violations.append("final MP4 ASR transcript is empty")
    return FinalSpeechProof(ok=not violations, violations=tuple(violations))


def load_current_final_speech_report(
    context: StoryVideoRunContext,
    video: Path,
) -> tuple[dict[str, Any], FinalSpeechProof]:
    path = context.project_dir / FINAL_SPEECH_QC_RELATIVE
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {}
    if not isinstance(report, dict):
        report = {}
    return report, validate_final_speech_report(context, video, report)


def verify_final_video_speech(
    context: StoryVideoRunContext,
    video: Path,
    *,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    report, proof = load_current_final_speech_report(context, video)
    if proof.ok:
        return {
            "success": True,
            "qc_report": str(context.project_dir / FINAL_SPEECH_QC_RELATIVE),
            "video_sha256": str(report["video_sha256"]),
            "cached": True,
        }
    if not DEFAULT_MLX_PYTHON.is_file():
        return {
            "success": False,
            "error": f"final speech ASR runtime is missing: {DEFAULT_MLX_PYTHON}",
        }
    worker = Path(__file__).with_name("final_speech_worker.py")
    try:
        process = runner(
            [
                str(DEFAULT_MLX_PYTHON),
                str(worker),
                "--project-dir",
                str(context.project_dir),
                "--video",
                str(video),
                "--run-id",
                context.run_id,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": str(exc)}
    report, proof = load_current_final_speech_report(context, video)
    if process.returncode != 0 or not proof.ok:
        detail = "; ".join(proof.violations) or process.stderr or process.stdout
        return {"success": False, "error": str(detail)[-2000:]}
    return {
        "success": True,
        "qc_report": str(context.project_dir / FINAL_SPEECH_QC_RELATIVE),
        "video_sha256": str(report["video_sha256"]),
        "cached": False,
    }

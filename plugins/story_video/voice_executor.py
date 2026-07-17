from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .voice_profiles import (
    VoiceProfileError,
    VoiceProfileSelection,
    resolve_project_voice_profile,
)


DEFAULT_PYTHON = Path.home() / ".hermes" / ".venvs" / "mlx-audio" / "bin" / "python"
DEFAULT_SCRIPT = (
    Path.home()
    / ".hermes"
    / "skills"
    / "creative"
    / "story-video-production-pipeline"
    / "scripts"
    / "generate_qwen_story_narration.py"
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    stopped: bool = False


@dataclass(frozen=True)
class VoiceRunSummary:
    work_status: str
    attempts: int = 0
    transient_retries: int = 0
    already_complete: bool = False
    error_type: str = ""
    error: str = ""
    missing: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()
    profile_id: str = ""
    voice_profile: str = ""
    profile_sha256: str = ""
    binding_path: str = ""
    binding_sha256: str = ""
    clone_mode: str = ""


def _run_cancellable(
    command: list[str],
    cancel_check: Callable[[], bool],
) -> CommandResult:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    while process.poll() is None:
        if cancel_check():
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            return CommandResult(
                returncode=process.returncode or -15,
                stdout=stdout,
                stderr=stderr,
                stopped=True,
            )
        time.sleep(0.25)
    stdout, stderr = process.communicate()
    return CommandResult(
        returncode=int(process.returncode or 0),
        stdout=stdout,
        stderr=stderr,
    )


def _transient_mlx_abort(result: CommandResult) -> bool:
    detail = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode in {-6, 134} or any(
        marker in detail for marker in ("abort trap: 6", "sigabrt", "signal 6")
    )


class StoryVideoVoiceExecutor:
    def __init__(
        self,
        *,
        phase_validator: Callable[[Any], Any],
        command_runner: Callable[
            [list[str], Callable[[], bool]], CommandResult
        ] = _run_cancellable,
        voice_profile_resolver: Callable[
            [Path], VoiceProfileSelection
        ] = resolve_project_voice_profile,
        python_path: str | Path = DEFAULT_PYTHON,
        script_path: str | Path = DEFAULT_SCRIPT,
    ) -> None:
        self.phase_validator = phase_validator
        self.command_runner = command_runner
        self.voice_profile_resolver = voice_profile_resolver
        # Preserve venv launchers: resolving their symlink bypasses site-packages.
        self.python_path = Path(python_path).expanduser().absolute()
        self.script_path = Path(script_path).expanduser().resolve()

    def run(
        self,
        context: Any,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> VoiceRunSummary:
        cancelled = cancel_check or (lambda: False)
        proof = self.phase_validator(context)
        if proof.ok:
            return VoiceRunSummary(
                work_status="complete",
                already_complete=True,
            )
        if cancelled():
            return VoiceRunSummary(work_status="stopped")
        missing_runtime = [
            str(path)
            for path in (self.python_path, self.script_path)
            if not path.is_file()
        ]
        if missing_runtime:
            return VoiceRunSummary(
                work_status="setup_required",
                error_type="voice_runtime_missing",
                error="Missing local Qwen voice runtime: " + ", ".join(missing_runtime),
                missing=tuple(missing_runtime),
            )

        project_dir = Path(context.project_dir).resolve()
        try:
            selection = self.voice_profile_resolver(project_dir)
        except VoiceProfileError as exc:
            return VoiceRunSummary(
                work_status="setup_required",
                error_type=exc.error_type,
                error=str(exc),
            )
        except (OSError, ValueError) as exc:
            return VoiceRunSummary(
                work_status="setup_required",
                error_type="voice_profile_invalid",
                error=str(exc),
            )

        evidence = {
            "profile_id": selection.profile_id,
            "voice_profile": str(selection.profile_path),
            "profile_sha256": selection.profile_sha256,
            "binding_path": str(selection.binding_path),
            "binding_sha256": selection.binding_sha256,
            "clone_mode": selection.clone_mode,
        }

        command = [
            str(self.python_path),
            str(self.script_path),
            str(project_dir),
            "--voice-profile",
            str(selection.profile_path),
            "--voice-binding",
            str(selection.binding_path),
        ]
        transient_retries = 0
        for attempt in (1, 2):
            result = self.command_runner(command, cancelled)
            if result.stopped or cancelled():
                return VoiceRunSummary(
                    work_status="stopped",
                    attempts=attempt,
                    transient_retries=transient_retries,
                    **evidence,
                )
            if result.returncode == 0:
                proof = self.phase_validator(context)
                if proof.ok:
                    return VoiceRunSummary(
                        work_status="complete",
                        attempts=attempt,
                        transient_retries=transient_retries,
                        **evidence,
                    )
                return VoiceRunSummary(
                    work_status="human_review_required",
                    attempts=attempt,
                    transient_retries=transient_retries,
                    error_type="voice_qc_failed",
                    error="Narration command completed but voice phase proof failed.",
                    missing=tuple(proof.missing),
                    violations=tuple(proof.violations),
                    **evidence,
                )
            if attempt == 1 and _transient_mlx_abort(result):
                transient_retries += 1
                continue
            detail = (result.stderr or result.stdout or "voice generation failed").strip()
            qc_failed = "qc failed" in detail.lower()
            return VoiceRunSummary(
                work_status=(
                    "human_review_required" if qc_failed else "setup_required"
                ),
                attempts=attempt,
                transient_retries=transient_retries,
                error_type=(
                    "voice_qc_failed" if qc_failed else "voice_generation_failed"
                ),
                error=detail[-2000:],
                missing=tuple(proof.missing),
                violations=tuple(proof.violations),
                **evidence,
            )
        raise AssertionError("bounded voice retry loop exhausted unexpectedly")

from __future__ import annotations

from types import SimpleNamespace

from plugins.story_video.voice_executor import (
    CommandResult,
    StoryVideoVoiceExecutor,
    _run_cancellable,
)


def _context(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return SimpleNamespace(project_dir=project, run_id="run-1")


def _proof(*, ok: bool, missing: tuple[str, ...] = ()):
    return SimpleNamespace(ok=ok, missing=missing, violations=())


def _selection(tmp_path):
    return SimpleNamespace(
        profile_id="voice_b",
        profile_path=tmp_path / "voices" / "voice_b" / "profile.json",
        profile_sha256="profile-sha",
        binding_path=tmp_path / "project" / "voice_profile_binding.json",
        binding_sha256="binding-sha",
        clone_mode="full_icl",
    )


def test_voice_executor_is_idempotent_when_current_manifest_passes(tmp_path) -> None:
    context = _context(tmp_path)
    calls: list[list[str]] = []
    executor = StoryVideoVoiceExecutor(
        command_runner=lambda command, _cancel: calls.append(command),
        phase_validator=lambda _context: _proof(ok=True),
        python_path=tmp_path / "python",
        script_path=tmp_path / "generate.py",
    )

    summary = executor.run(context)

    assert summary.work_status == "complete"
    assert summary.already_complete is True
    assert summary.attempts == 0
    assert calls == []


def test_voice_executor_preserves_virtualenv_python_symlink(tmp_path) -> None:
    base_python = tmp_path / "base-python"
    base_python.write_text("runtime", encoding="utf-8")
    venv_python = tmp_path / "venv-python"
    venv_python.symlink_to(base_python)

    executor = StoryVideoVoiceExecutor(
        command_runner=lambda _command, _cancel: CommandResult(returncode=0),
        phase_validator=lambda _context: _proof(ok=True),
        python_path=venv_python,
        script_path=tmp_path / "generate.py",
    )

    assert executor.python_path == venv_python
    assert executor.python_path != base_python.resolve()


def test_voice_executor_retries_one_transient_mlx_abort_then_passes(tmp_path) -> None:
    context = _context(tmp_path)
    python = tmp_path / "python"
    script = tmp_path / "generate.py"
    python.write_text("runtime", encoding="utf-8")
    script.write_text("script", encoding="utf-8")
    passed = False
    calls: list[list[str]] = []

    def run(command, _cancel):
        nonlocal passed
        calls.append(command)
        if len(calls) == 1:
            return CommandResult(returncode=-6, stderr="Abort trap: 6")
        passed = True
        return CommandResult(returncode=0, stdout='{"success": true}')

    executor = StoryVideoVoiceExecutor(
        command_runner=run,
        phase_validator=lambda _context: _proof(ok=passed),
        voice_profile_resolver=lambda _project: _selection(tmp_path),
        python_path=python,
        script_path=script,
    )

    summary = executor.run(context)

    assert summary.work_status == "complete"
    assert summary.attempts == 2
    assert summary.transient_retries == 1
    assert summary.profile_id == "voice_b"
    assert summary.clone_mode == "full_icl"
    assert calls[0][-4:] == [
        "--voice-profile",
        str(tmp_path / "voices" / "voice_b" / "profile.json"),
        "--voice-binding",
        str(tmp_path / "project" / "voice_profile_binding.json"),
    ]
    assert calls[0] == calls[1]


def test_voice_executor_fails_closed_when_profile_binding_is_invalid(tmp_path) -> None:
    from plugins.story_video.voice_profiles import VoiceProfileError

    context = _context(tmp_path)
    python = tmp_path / "python"
    script = tmp_path / "generate.py"
    python.write_text("runtime", encoding="utf-8")
    script.write_text("script", encoding="utf-8")
    calls: list[list[str]] = []

    def fail_resolution(_project):
        raise VoiceProfileError(
            "voice_profile_binding_mismatch",
            "bound voice profile hash mismatch",
        )

    executor = StoryVideoVoiceExecutor(
        command_runner=lambda command, _cancel: calls.append(command),
        phase_validator=lambda _context: _proof(ok=False),
        voice_profile_resolver=fail_resolution,
        python_path=python,
        script_path=script,
    )

    summary = executor.run(context)

    assert summary.work_status == "setup_required"
    assert summary.error_type == "voice_profile_binding_mismatch"
    assert calls == []


def test_voice_executor_returns_bounded_qc_failure_without_rerunning(tmp_path) -> None:
    context = _context(tmp_path)
    python = tmp_path / "python"
    script = tmp_path / "generate.py"
    python.write_text("runtime", encoding="utf-8")
    script.write_text("script", encoding="utf-8")
    calls = 0

    def run(_command, _cancel):
        nonlocal calls
        calls += 1
        return CommandResult(
            returncode=1,
            stderr="acoustic narration QC failed for segments: S03_SH02",
        )

    executor = StoryVideoVoiceExecutor(
        command_runner=run,
        phase_validator=lambda _context: _proof(
            ok=False,
            missing=("audio narration segment[S03_SH02]",),
        ),
        voice_profile_resolver=lambda _project: _selection(tmp_path),
        python_path=python,
        script_path=script,
    )

    summary = executor.run(context)

    assert summary.work_status == "human_review_required"
    assert summary.error_type == "voice_qc_failed"
    assert summary.attempts == 1
    assert calls == 1


def test_voice_executor_honors_stop_before_dispatch(tmp_path) -> None:
    context = _context(tmp_path)
    calls = 0

    def run(_command, _cancel):
        nonlocal calls
        calls += 1
        return CommandResult(returncode=0)

    executor = StoryVideoVoiceExecutor(
        command_runner=run,
        phase_validator=lambda _context: _proof(ok=False),
        python_path=tmp_path / "python",
        script_path=tmp_path / "generate.py",
    )

    summary = executor.run(context, cancel_check=lambda: True)

    assert summary.work_status == "stopped"
    assert summary.attempts == 0
    assert calls == 0


def test_voice_process_is_terminated_when_stop_arrives_during_synthesis(
    monkeypatch,
) -> None:
    from plugins.story_video import voice_executor

    class Process:
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def communicate(self, timeout=None):
            return "", "stopped"

    process = Process()
    monkeypatch.setattr(voice_executor.subprocess, "Popen", lambda *_a, **_k: process)

    result = _run_cancellable(["voice-runtime"], lambda: True)

    assert result.stopped is True
    assert process.terminated is True
    assert result.returncode == -15

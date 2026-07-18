from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def _model_dir(tmp_path):
    model = tmp_path / "custom-voice-model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "tts_model_type": "custom_voice",
                "talker_config": {
                    "spk_id": {
                        "vivian": 1,
                        "serena": 2,
                        "uncle_fu": 3,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return model


def test_preview_custom_voice_presets_runs_one_batch_and_returns_media(tmp_path) -> None:
    from plugins.story_video.voice_presets import preview_custom_voice_presets

    model = _model_dir(tmp_path)
    python = tmp_path / "python"
    script = tmp_path / "preview.py"
    python.write_text("launcher", encoding="utf-8")
    script.write_text("script", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output_dir = command[command.index("--output-dir") + 1]
        speakers = [
            command[index + 1]
            for index, item in enumerate(command)
            if item == "--speaker"
        ]
        for speaker in speakers:
            path = Path(output_dir) / f"{speaker}.wav"
            path.write_bytes(b"wave-data")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    result = preview_custom_voice_presets(
        speakers=["vivian", "Serena", "UNCLE_FU"],
        sample_text="這是一段聲線試聽。",
        model_path=model,
        python_path=python,
        script_path=script,
        output_root=tmp_path / "previews",
        command_runner=runner,
    )

    assert result["speakers"] == ["Vivian", "Serena", "Uncle_Fu"]
    assert result["sample_text"] == "這是一段聲線試聽。"
    assert [sample["speaker"] for sample in result["samples"]] == result["speakers"]
    assert result["media"] == [
        f"MEDIA:{sample['path']}" for sample in result["samples"]
    ]
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 360


@pytest.mark.parametrize(
    ("speakers", "error_type"),
    [
        ([], "voice_preset_speakers_required"),
        (["Vivian", "Serena", "Uncle_Fu", "Ryan"], "voice_preset_limit_exceeded"),
        (["Missing"], "voice_preset_unsupported"),
    ],
)
def test_preview_custom_voice_presets_rejects_invalid_requests(
    tmp_path, speakers, error_type
) -> None:
    from plugins.story_video.voice_presets import VoicePresetError
    from plugins.story_video.voice_presets import preview_custom_voice_presets

    with pytest.raises(VoicePresetError) as exc_info:
        preview_custom_voice_presets(
            speakers=speakers,
            model_path=_model_dir(tmp_path),
            python_path=tmp_path / "python",
            script_path=tmp_path / "preview.py",
            output_root=tmp_path / "previews",
        )

    assert exc_info.value.error_type == error_type


def test_preview_custom_voice_presets_reports_missing_runtime(tmp_path) -> None:
    from plugins.story_video.voice_presets import VoicePresetError
    from plugins.story_video.voice_presets import preview_custom_voice_presets

    with pytest.raises(VoicePresetError) as exc_info:
        preview_custom_voice_presets(
            speakers=["Vivian"],
            model_path=_model_dir(tmp_path),
            python_path=tmp_path / "missing-python",
            script_path=tmp_path / "missing-script.py",
            output_root=tmp_path / "previews",
        )

    assert exc_info.value.error_type == "voice_preset_runtime_missing"


@pytest.mark.parametrize(
    ("runner", "error_type"),
    [
        (
            lambda _command, **_kwargs: SimpleNamespace(
                returncode=1, stdout="", stderr="generation failed"
            ),
            "voice_preset_preview_failed",
        ),
        (
            lambda command, **_kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(command, 360)
            ),
            "voice_preset_preview_timeout",
        ),
        (
            lambda _command, **_kwargs: SimpleNamespace(
                returncode=0, stdout="ok", stderr=""
            ),
            "voice_preset_preview_missing",
        ),
    ],
)
def test_preview_custom_voice_presets_reports_generation_failures(
    tmp_path, runner, error_type
) -> None:
    from plugins.story_video.voice_presets import VoicePresetError
    from plugins.story_video.voice_presets import preview_custom_voice_presets

    python = tmp_path / "python"
    script = tmp_path / "preview.py"
    python.write_text("launcher", encoding="utf-8")
    script.write_text("script", encoding="utf-8")

    with pytest.raises(VoicePresetError) as exc_info:
        preview_custom_voice_presets(
            speakers=["Vivian"],
            model_path=_model_dir(tmp_path),
            python_path=python,
            script_path=script,
            output_root=tmp_path / "previews",
            command_runner=runner,
        )

    assert exc_info.value.error_type == error_type
    assert not list((tmp_path / "previews").glob("qwen-custom-voice-*"))


def test_preview_custom_voice_presets_retains_only_bounded_successes(tmp_path) -> None:
    from plugins.story_video.voice_presets import MAX_RETAINED_PREVIEW_RUNS
    from plugins.story_video.voice_presets import preview_custom_voice_presets

    model = _model_dir(tmp_path)
    python = tmp_path / "python"
    script = tmp_path / "preview.py"
    python.write_text("launcher", encoding="utf-8")
    script.write_text("script", encoding="utf-8")
    root = tmp_path / "previews"
    root.mkdir()
    for index in range(MAX_RETAINED_PREVIEW_RUNS + 3):
        directory = root / f"qwen-custom-voice-old-{index:02d}"
        directory.mkdir()
        os.utime(directory, (index + 1, index + 1))

    def runner(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "Vivian.wav").write_bytes(b"wave-data")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    result = preview_custom_voice_presets(
        speakers=["Vivian"],
        model_path=model,
        python_path=python,
        script_path=script,
        output_root=root,
        command_runner=runner,
    )

    retained = list(root.glob("qwen-custom-voice-*"))
    assert len(retained) == MAX_RETAINED_PREVIEW_RUNS
    assert Path(result["samples"][0]["path"]).parent in retained

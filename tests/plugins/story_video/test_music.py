from __future__ import annotations

import json
import shutil
import subprocess
import wave
from types import SimpleNamespace

import pytest

from plugins.story_video.music import (
    compile_music_bed,
    plan_music_cues,
    validate_music_direction,
)
from plugins.story_video.visual_judge import _select_background_music


def _library(source_path: str, *, section_count: int = 4) -> dict:
    section_specs = (
        ("curious_open", 0.0, 1.0, ["hook", "curious", "discovery"]),
        ("mystery_turn", 1.0, 2.0, ["turn", "tense", "mystery"]),
        ("wonder_reveal", 2.0, 3.0, ["reveal", "awe", "wonder"]),
        ("warm_close", 3.0, 4.0, ["close", "calm", "resolution"]),
    )
    return {
        "schema": "story_video_music_library_v2",
        "tracks": [
            {
                "track_id": "local-story-suite-v2",
                "path": source_path,
                "enabled": True,
                "rights": {
                    "status": "approved",
                    "license": "locally_synthesized",
                    "provenance": "local test fixture",
                },
                "production_types": ["science_explainer", "*"],
                "audience_modes": ["young_explorer", "general"],
                "moods": ["discovery", "wonder", "mystery", "resolution"],
                "energy": ["gentle", "balanced", "high"],
                "instruments": ["marimba", "pads", "bells"],
                "excluded_styles": ["trailer_braam", "aggressive_drums"],
                "volume_db": -22.0,
                "sections": [
                    {
                        "cue_id": cue_id,
                        "start_sec": start,
                        "end_sec": end,
                        "tags": tags,
                    }
                    for cue_id, start, end, tags in section_specs[:section_count]
                ],
            }
        ],
    }


def _ledger() -> dict:
    return {
        "production_type": "science_explainer",
        "target_duration_sec": 12,
        "engagement_profile": {"mode": "young_explorer", "energy": "high"},
        "music_direction": {
            "schema": "story_video_music_direction_v1",
            "moods": ["discovery", "wonder"],
            "instruments": ["marimba", "bells"],
            "excluded_styles": ["aggressive drums"],
            "energy_curve": {
                "opening": "high",
                "body": "balanced",
                "payoff": "high",
                "ending": "gentle",
            },
            "narration_priority": True,
            "min_cue_variants": 3,
        },
        "scenes": [
            {"scene_id": "S00", "narrative_role": "hook"},
            {"scene_id": "S01", "narrative_role": "turn"},
            {"scene_id": "S02", "narrative_role": "reveal"},
            {"scene_id": "S03", "narrative_role": "close"},
        ],
    }


def test_music_direction_requires_a_narration_first_energy_curve() -> None:
    direction = _ledger()["music_direction"]

    assert validate_music_direction(direction) == ()

    direction["narration_priority"] = False
    direction["energy_curve"].pop("ending")

    violations = validate_music_direction(direction)

    assert "music_direction narration_priority must be true" in violations
    assert "music_direction energy_curve.ending is invalid" in violations


def test_music_plan_uses_three_or_more_rights_approved_cues() -> None:
    durations = [
        {"scene_id": f"S0{index}", "duration_sec": 3.0}
        for index in range(4)
    ]

    plan = plan_music_cues(_ledger(), _library("/tmp/source.wav"), durations)

    assert plan["status"] == "SELECTED"
    assert plan["rights_status"] == "approved"
    assert len({cue["cue_id"] for cue in plan["cues"]}) >= 3
    assert plan["total_duration_sec"] == 12.0
    assert plan["excluded_styles"] == ["aggressive_drums"]


def test_music_plan_rejects_library_with_too_few_variants() -> None:
    plan = plan_music_cues(
        _ledger(),
        _library("/tmp/source.wav", section_count=2),
        [{"scene_id": "S00", "duration_sec": 12.0}],
    )

    assert plan["status"] == "INSUFFICIENT_VARIANTS"
    assert plan["cues"] == []


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)
def test_music_bed_compiler_creates_exact_project_local_timeline(tmp_path) -> None:
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\0\0\0\0" * (48000 * 4))
    ledger = _ledger()
    ledger["target_duration_sec"] = 2.4
    durations = [
        {"scene_id": "S00", "duration_sec": 0.8},
        {"scene_id": "S01", "duration_sec": 0.8},
        {"scene_id": "S02", "duration_sec": 0.8},
    ]
    plan = plan_music_cues(ledger, _library(str(source)), durations)

    compiled = compile_music_bed(tmp_path / "project", plan)
    cached = compile_music_bed(tmp_path / "project", plan)

    output = tmp_path / "project" / compiled["path"]
    assert compiled["status"] == "PASS"
    assert output.is_file()
    duration = float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output),
            ],
            text=True,
        ).strip()
    )
    assert duration == pytest.approx(2.4, abs=0.05)
    assert compiled["cue_count"] == 3
    assert compiled["cache_hit"] is False
    assert cached["cache_hit"] is True
    assert cached["sha256"] == compiled["sha256"]


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)
def test_render_music_selection_compiles_v2_cue_plan(tmp_path, monkeypatch) -> None:
    hermes_home = tmp_path / "hermes"
    source = hermes_home / "music" / "story-suite.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\0\0\0\0" * (48000 * 4))
    library = _library(str(source))
    (hermes_home / "story_video_music_library.json").write_text(
        json.dumps(library), encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    project = tmp_path / "project"
    project.mkdir()
    context = SimpleNamespace(project_dir=project, topic="測試故事")
    ledger = _ledger()
    scenes = [
        {
            "scene_id": f"S0{index}",
            "shots": [{"timeline_duration_sec": 0.5}],
        }
        for index in range(4)
    ]

    music, status = _select_background_music(context, ledger, scenes)

    assert status == "SELECTED_CUED"
    assert music is not None
    assert music["track_id"] == "local-story-suite-v2-cued"
    assert (project / music["path"]).is_file()
    assert (project / "manifests" / "music_cue_plan.json").is_file()

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from plugins.story_video.voice_profiles import (
    VoiceProfileError,
    bind_project_voice_profile,
    inspect_project_voice_profile,
    list_voice_profiles,
    resolve_project_voice_profile,
)


def _write_profile(
    root: Path,
    profile_id: str,
    *,
    status: str = "locked_by_user",
    clone_mode: str = "full_icl",
) -> Path:
    directory = root / profile_id
    directory.mkdir(parents=True)
    reference = directory / "reference.wav"
    reference.write_bytes(f"reference-{profile_id}".encode())
    profile = directory / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema": "story_video_local_voice_profile_v1",
                "profile_id": profile_id,
                "display_name": profile_id.replace("_", " ").title(),
                "status": status,
                "provider": "local_qwen",
                "model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
                "reference_audio": str(reference),
                "reference_transcript": "這是一段本人授權的乾淨參考錄音。",
                "language": "zh-TW",
                "clone_mode": clone_mode,
                "inference_mode": "offline",
                "network_fallback": "forbidden",
                "consent": "user_confirmed_self_recording",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return profile


def _write_registry(root: Path, *, default: str, profiles: list[tuple[str, Path, bool]]) -> Path:
    registry = root / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "story_video_voice_profile_registry_v1",
                "default_profile_id": default,
                "profiles": [
                    {
                        "profile_id": profile_id,
                        "profile_path": str(path),
                        "enabled": enabled,
                    }
                    for profile_id, path, enabled in profiles
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry


def test_registry_lists_multiple_selectable_full_clone_profiles(tmp_path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    first = _write_profile(root, "voice_a")
    second = _write_profile(root, "voice_b")
    registry = _write_registry(
        root,
        default="voice_a",
        profiles=[("voice_a", first, True), ("voice_b", second, True)],
    )

    catalog = list_voice_profiles(registry_path=registry)

    assert catalog["default_profile_id"] == "voice_a"
    assert [row["profile_id"] for row in catalog["profiles"]] == [
        "voice_a",
        "voice_b",
    ]
    assert all(row["selectable"] is True for row in catalog["profiles"])
    assert all(row["clone_mode"] == "full_icl" for row in catalog["profiles"])


def test_registry_keeps_rejected_or_disabled_profiles_unselectable(tmp_path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    approved = _write_profile(root, "approved")
    rejected = _write_profile(root, "rejected", status="rejected_by_user")
    disabled = _write_profile(root, "disabled")
    registry = _write_registry(
        root,
        default="approved",
        profiles=[
            ("approved", approved, True),
            ("rejected", rejected, True),
            ("disabled", disabled, False),
        ],
    )

    catalog = list_voice_profiles(registry_path=registry)
    rows = {row["profile_id"]: row for row in catalog["profiles"]}

    assert rows["approved"]["selectable"] is True
    assert rows["rejected"]["selectable"] is False
    assert rows["disabled"]["selectable"] is False
    with pytest.raises(VoiceProfileError, match="not selectable"):
        bind_project_voice_profile(
            tmp_path / "project",
            profile_id="rejected",
            registry_path=registry,
        )


def test_resolver_supports_legacy_active_narrator_pointer(tmp_path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    profile = _write_profile(root, "legacy_voice")
    active = root / "active_narrator.json"
    active.write_text(
        json.dumps(
            {
                "schema": "story_video_active_narrator_v1",
                "profile_id": "legacy_voice",
                "profile_path": str(profile),
                "status": "locked_by_user",
            }
        ),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()

    selection = resolve_project_voice_profile(
        project,
        registry_path=root / "missing-registry.json",
        active_profile_path=active,
    )

    assert selection.profile_id == "legacy_voice"
    assert selection.profile_path == profile.resolve()
    assert selection.binding_path == project / "voice_profile_binding.json"
    assert selection.clone_mode == "full_icl"


def test_project_binding_is_stable_when_registry_default_changes(tmp_path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    first = _write_profile(root, "voice_a")
    second = _write_profile(root, "voice_b")
    registry = _write_registry(
        root,
        default="voice_a",
        profiles=[("voice_a", first, True), ("voice_b", second, True)],
    )
    project = tmp_path / "project"
    project.mkdir()

    initial = resolve_project_voice_profile(project, registry_path=registry)
    _write_registry(
        root,
        default="voice_b",
        profiles=[("voice_a", first, True), ("voice_b", second, True)],
    )
    resolved = resolve_project_voice_profile(project, registry_path=registry)

    assert initial.profile_id == "voice_a"
    assert resolved.profile_id == "voice_a"
    assert resolved.binding_sha256 == initial.binding_sha256


def test_bound_profile_hash_drift_fails_closed(tmp_path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    profile = _write_profile(root, "voice_a")
    registry = _write_registry(
        root,
        default="voice_a",
        profiles=[("voice_a", profile, True)],
    )
    project = tmp_path / "project"
    project.mkdir()
    resolve_project_voice_profile(project, registry_path=registry)
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["speed"] = 1.2
    profile.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(VoiceProfileError, match="hash mismatch") as error:
        resolve_project_voice_profile(project, registry_path=registry)

    assert error.value.error_type == "voice_profile_binding_mismatch"


def test_explicit_reselection_refreshes_drifted_binding_before_narration(
    tmp_path,
) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    profile = _write_profile(root, "voice_a")
    registry = _write_registry(
        root,
        default="voice_a",
        profiles=[("voice_a", profile, True)],
    )
    project = tmp_path / "project"
    project.mkdir()
    original = bind_project_voice_profile(
        project, profile_id="voice_a", registry_path=registry
    )
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["speed"] = 1.2
    profile.write_text(json.dumps(payload), encoding="utf-8")

    refreshed = bind_project_voice_profile(
        project, profile_id="voice_a", registry_path=registry
    )

    assert refreshed.profile_sha256 != original.profile_sha256
    assert refreshed.profile_sha256 == hashlib.sha256(profile.read_bytes()).hexdigest()


def test_voice_can_be_reselected_before_but_not_after_narration(tmp_path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    first = _write_profile(root, "voice_a")
    second = _write_profile(root, "voice_b")
    registry = _write_registry(
        root,
        default="voice_a",
        profiles=[("voice_a", first, True), ("voice_b", second, True)],
    )
    project = tmp_path / "project"
    project.mkdir()
    bind_project_voice_profile(project, profile_id="voice_a", registry_path=registry)

    rebound = bind_project_voice_profile(
        project, profile_id="voice_b", registry_path=registry
    )

    assert rebound.profile_id == "voice_b"
    manifest = project / "manifests" / "narration_manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(VoiceProfileError, match="existing narration"):
        bind_project_voice_profile(
            project, profile_id="voice_a", registry_path=registry
        )


def test_binding_status_reports_integrity_without_mutating_project(tmp_path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    profile = _write_profile(root, "voice_a")
    registry = _write_registry(
        root,
        default="voice_a",
        profiles=[("voice_a", profile, True)],
    )
    project = tmp_path / "project"
    project.mkdir()

    unbound = inspect_project_voice_profile(project, registry_path=registry)
    assert unbound["bound"] is False
    assert unbound["resolved_profile_id"] == "voice_a"
    assert not (project / "voice_profile_binding.json").exists()

    selection = bind_project_voice_profile(
        project, profile_id="voice_a", registry_path=registry
    )
    bound = inspect_project_voice_profile(project, registry_path=registry)
    assert bound["bound"] is True
    assert bound["integrity"] == "PASS"
    assert bound["profile_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest()
    assert bound["binding_sha256"] == selection.binding_sha256

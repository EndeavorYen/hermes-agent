# Story Video Voice Catalog And Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-neutral voice catalog that lists `simon_clean_v2`, `Vivian`, `Serena`, and `Uncle_Fu` as truthful choices and can lock any of the three Qwen presets to story characters.

**Architecture:** A new `voice_catalog.py` module normalizes the existing clone registry and supported Qwen CustomVoice presets into one catalog while preserving provider-specific engine evidence. Voice-manager listing and operator guidance consume that catalog. Multi-character binding moves to a backward-compatible v2 contract whose speaker rows carry either full-ICL profile evidence or Qwen preset model evidence.

**Tech Stack:** Python 3.11, pytest, existing Hermes story-video plugin tools, local Qwen3-TTS CustomVoice model metadata, JSON contracts, SHA-256 integrity checks.

## Global Constraints

- Development stays on `feat/story-video/voice-catalog-casting`; never edit `local/main` or `runtime/current` directly.
- Use strict red-green-refactor TDD for every production-code change.
- Keep `~/.hermes/story_video_voice_profiles/registry.json` authoritative for full-ICL clone lifecycle and consent.
- Do not write Qwen presets into the clone registry or invent reference-audio and consent fields for presets.
- Keep `profiles` in voice-manager list responses for existing callers; add `voices` as the preferred selection surface.
- `simon_clean_v2` remains the default narrator.
- Only `Vivian`, `Serena`, and `Uncle_Fu` become Qwen character-dubbing choices in this phase.
- A missing model, runtime, or preset remains visible with `availability.status="setup_required"` and `selectable=false`.
- New bindings use schema `story_video_voice_cast_binding_v2`; existing v1 full-ICL bindings remain readable.
- No generated media, model files, private prompts, provider logs, or operator preference traces may be committed.
- Phase 2 automatic casting and Phase 3 multi-engine synthesis are separate implementation plans.
- After every task, stop before starting the next task and record a checkpoint answering: `目標有偏移嗎？`, `有 over-design 嗎？`, `目前證據是什麼？`, and `下一個最小步驟是什麼？`. Remove or defer work that does not directly advance this Phase 1 goal.

## File Structure

- Create `plugins/story_video/voice_catalog.py`: normalized catalog construction, alias resolution, catalog hashing, engine-binding creation, and locked-engine validation.
- Modify `plugins/story_video/voice_presets.py`: add structured casting metadata and an explicit character-dubbing capability to the three approved presets.
- Modify `plugins/story_video/tools.py`: return normalized voices from `story_video_voice_manager(action="list")` and pass an injected catalog into cast binding tests.
- Modify `plugins/story_video/guide.py`: format normalized voices while retaining the legacy profile fallback.
- Modify `plugins/story_video/schemas.py`: describe the unified list and preset character-dubbing capability without changing required arguments.
- Modify `plugins/story_video/dubbing.py`: resolve catalog aliases, write v2 engine bindings, and validate both v1 and v2 bindings.
- Create `tests/plugins/story_video/test_voice_catalog.py`: focused catalog and engine-evidence tests.
- Modify `tests/plugins/story_video/test_tools.py`: voice-manager and audio-director tool-surface tests.
- Modify `tests/plugins/story_video/test_dubbing.py`: preset character binding, alias, drift, and v1 compatibility tests.
- Modify `tests/plugins/story_video/test_guide.py`: operator-visible catalog formatting tests.

---

### Task 1: Build The Provider-Neutral Voice Catalog

**Files:**
- Create: `plugins/story_video/voice_catalog.py`
- Modify: `plugins/story_video/voice_presets.py`
- Create: `tests/plugins/story_video/test_voice_catalog.py`

**Interfaces:**
- Consumes: `list_voice_profiles()`, `PRESET_VOICES`, `DEFAULT_CUSTOM_VOICE_MODEL_PATH`, and `DEFAULT_MLX_PYTHON`.
- Produces: `list_voice_catalog(...) -> dict[str, Any]`, `resolve_catalog_voice(selector, catalog) -> dict[str, Any]`, `build_engine_binding(voice) -> dict[str, Any]`, and `validate_engine_binding(binding) -> None`.

- [ ] **Step 1: Write the failing catalog tests**

Create `tests/plugins/story_video/test_voice_catalog.py` with real temporary clone and Qwen setup fixtures:

```python
from __future__ import annotations

import json

import pytest

from plugins.story_video.voice_profiles import add_voice_profile
from plugins.story_video.voice_catalog import VoiceCatalogError


def _catalog_setup(tmp_path):
    voices = tmp_path / "voices"
    reference = tmp_path / "simon.wav"
    reference.write_bytes(b"authorized-simon-reference")
    add_voice_profile(
        voice_id="simon_clean_v2",
        display_name="Simon clean narrator v2",
        reference_audio=reference,
        reference_transcript="這是 Simon 本人授權的乾淨錄音。",
        consent="user_confirmed_self_recording",
        registry_path=voices / "registry.json",
    )
    model = tmp_path / "custom-voice-model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "tts_model_type": "custom_voice",
                "talker_config": {
                    "spk_id": {"vivian": 1, "serena": 2, "uncle_fu": 3}
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = tmp_path / "mlx-python"
    runtime.write_text("runtime", encoding="utf-8")
    return voices / "registry.json", model, runtime


def test_catalog_merges_clone_and_three_approved_qwen_actors(tmp_path) -> None:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry, model, runtime = _catalog_setup(tmp_path)
    result = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )

    rows = {row["voice_id"]: row for row in result["voices"]}
    assert set(rows) == {
        "simon_clean_v2",
        "qwen_custom_vivian",
        "qwen_custom_serena",
        "qwen_custom_uncle_fu",
    }
    assert rows["simon_clean_v2"]["engine"] == "qwen_full_icl"
    assert rows["qwen_custom_vivian"]["engine"] == "qwen_custom_voice"
    assert rows["qwen_custom_vivian"]["capabilities"]["character_dubbing"] is True
    assert all(row["selectable"] is True for row in rows.values())
    assert result["default_voice_id"] == "simon_clean_v2"
    assert result["catalog_sha256"]


def test_catalog_keeps_missing_qwen_setup_visible_but_unselectable(tmp_path) -> None:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry, _, _ = _catalog_setup(tmp_path)
    result = list_voice_catalog(
        registry_path=registry,
        preset_model_path=tmp_path / "missing-model",
        preset_runtime_path=tmp_path / "missing-runtime",
    )

    presets = [row for row in result["voices"] if row["source_kind"] == "preset"]
    assert [row["display_name"] for row in presets] == [
        "Vivian",
        "Serena",
        "Uncle_Fu",
    ]
    assert all(row["selectable"] is False for row in presets)
    assert all(row["availability"]["status"] == "setup_required" for row in presets)


def test_catalog_alias_resolution_is_case_insensitive(tmp_path) -> None:
    from plugins.story_video.voice_catalog import (
        list_voice_catalog,
        resolve_catalog_voice,
    )

    registry, model, runtime = _catalog_setup(tmp_path)
    catalog = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )

    assert resolve_catalog_voice("Vivian", catalog)["voice_id"] == "qwen_custom_vivian"
    assert resolve_catalog_voice("UNCLE_FU", catalog)["voice_id"] == "qwen_custom_uncle_fu"
    with pytest.raises(VoiceCatalogError, match="not registered"):
        resolve_catalog_voice("missing_actor", catalog)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_voice_catalog.py
```

Expected: collection fails with `ModuleNotFoundError: No module named 'plugins.story_video.voice_catalog'`.

- [ ] **Step 3: Add structured preset metadata**

Change `PRESET_VOICES` to accept `Any` values and add these exact fields to the three approved records:

```python
PRESET_VOICES: dict[str, dict[str, Any]] = {
    "vivian": {
        "speaker": "Vivian",
        "gender_style": "女，明亮年輕",
        "native_language": "中文",
        "catalog_voice_id": "qwen_custom_vivian",
        "locale": "zh-CN",
        "traits": {
            "gender_presentation": "female",
            "age_impression": "young",
            "styles": ["bright", "clear"],
        },
        "character_dubbing": True,
    },
    "serena": {
        "speaker": "Serena",
        "gender_style": "女，溫暖柔和",
        "native_language": "中文",
        "catalog_voice_id": "qwen_custom_serena",
        "locale": "zh-CN",
        "traits": {
            "gender_presentation": "female",
            "age_impression": "adult",
            "styles": ["warm", "soft"],
        },
        "character_dubbing": True,
    },
    "uncle_fu": {
        "speaker": "Uncle_Fu",
        "gender_style": "男，低沉成熟",
        "native_language": "中文",
        "catalog_voice_id": "qwen_custom_uncle_fu",
        "locale": "zh-CN",
        "traits": {
            "gender_presentation": "male",
            "age_impression": "older",
            "styles": ["deep", "mature"],
        },
        "character_dubbing": True,
    },
```

Keep the existing fields on every other preset and set their `character_dubbing` value to `False` in this phase.

- [ ] **Step 4: Implement the minimal catalog module**

Create `plugins/story_video/voice_catalog.py` with these concrete boundaries:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .voice_presets import (
    DEFAULT_CUSTOM_VOICE_MODEL_PATH,
    DEFAULT_MLX_PYTHON,
    PRESET_VOICES,
)
from .voice_profiles import (
    DEFAULT_VOICE_REGISTRY,
    _profile_assessment,
    list_voice_profiles,
)

VOICE_CATALOG_SCHEMA = "story_video_voice_catalog_v1"


class VoiceCatalogError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _supported_presets(model: Path) -> tuple[set[str], str]:
    config = model / "config.json"
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return set(), f"cannot read Qwen CustomVoice model config: {exc}"
    speakers = payload.get("talker_config", {}).get("spk_id", {})
    if payload.get("tts_model_type") != "custom_voice" or not isinstance(speakers, dict):
        return set(), "installed model is not a valid Qwen CustomVoice model"
    return {str(name).casefold() for name in speakers}, ""


def list_voice_catalog(
    *,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    active_profile_path: str | Path | None = None,
    preset_model_path: str | Path = DEFAULT_CUSTOM_VOICE_MODEL_PATH,
    preset_runtime_path: str | Path = DEFAULT_MLX_PYTHON,
) -> dict[str, Any]:
    profile_catalog = list_voice_profiles(
        registry_path=registry_path,
        active_profile_path=active_profile_path,
    )
    voices = []
    for profile in profile_catalog["profiles"]:
        voices.append(
            {
                "voice_id": str(profile.get("voice_id") or profile["profile_id"]),
                "display_name": str(profile.get("display_name") or profile["profile_id"]),
                "aliases": [str(profile["profile_id"]), str(profile.get("voice_id") or "")],
                "engine": "qwen_full_icl",
                "source_kind": "clone_profile",
                "language": str(profile.get("language") or "zh-TW"),
                "locale": str(profile.get("language") or "zh-TW"),
                "traits": {},
                "capabilities": {
                    "preview": False,
                    "single_narrator": True,
                    "character_dubbing": True,
                    "operator_tunable": True,
                },
                "availability": {
                    "status": "ready" if profile.get("selectable") else "disabled",
                    "reason": str(profile.get("reason") or ""),
                },
                "selectable": bool(profile.get("selectable")),
                "engine_binding": {
                    "profile_id": str(profile["profile_id"]),
                    "profile_path": str(profile["profile_path"]),
                    "profile_sha256": str(profile["profile_sha256"]),
                },
            }
        )

    model = Path(preset_model_path).expanduser().resolve()
    runtime = Path(preset_runtime_path).expanduser().absolute()
    supported, model_reason = _supported_presets(model)
    for key, metadata in PRESET_VOICES.items():
        if metadata.get("character_dubbing") is not True:
            continue
        reasons = []
        if key not in supported:
            reasons.append(model_reason or f"installed model does not support {metadata['speaker']}")
        if not runtime.is_file():
            reasons.append(f"missing local Qwen runtime: {runtime}")
        selectable = not reasons
        config = model / "config.json"
        voices.append(
            {
                "voice_id": str(metadata["catalog_voice_id"]),
                "display_name": str(metadata["speaker"]),
                "aliases": [str(metadata["speaker"]), key],
                "engine": "qwen_custom_voice",
                "source_kind": "preset",
                "language": "zh",
                "locale": str(metadata["locale"]),
                "traits": dict(metadata["traits"]),
                "capabilities": {
                    "preview": True,
                    "single_narrator": True,
                    "character_dubbing": True,
                    "operator_tunable": False,
                },
                "availability": {
                    "status": "ready" if selectable else "setup_required",
                    "reason": "; ".join(reasons),
                },
                "selectable": selectable,
                "engine_binding": {
                    "preset_speaker": str(metadata["speaker"]),
                    "model_path": str(model),
                    "model_config_path": str(config),
                    "model_config_sha256": _sha256(config) if selectable else "",
                    "runtime_path": str(runtime),
                },
            }
        )
    snapshot = [
        {
            "voice_id": row["voice_id"],
            "engine": row["engine"],
            "selectable": row["selectable"],
            "engine_binding": row["engine_binding"],
        }
        for row in voices
    ]
    default_profile_id = str(profile_catalog.get("default_profile_id") or "")
    default_profile = next(
        (
            row
            for row in profile_catalog["profiles"]
            if str(row.get("profile_id") or "") == default_profile_id
        ),
        None,
    )
    return {
        **profile_catalog,
        "catalog_schema": VOICE_CATALOG_SCHEMA,
        "catalog_sha256": _canonical_sha256(snapshot),
        "default_voice_id": str(
            (default_profile or {}).get("voice_id") or default_profile_id
        ),
        "voices": voices,
        "voice_count": len(voices),
    }


def resolve_catalog_voice(selector: str, catalog: dict[str, Any]) -> dict[str, Any]:
    requested = str(selector or "").strip().casefold()
    matches = [
        row
        for row in catalog.get("voices") or []
        if requested == str(row.get("voice_id") or "").casefold()
        or requested in {str(alias).casefold() for alias in row.get("aliases") or []}
    ]
    if not matches:
        raise VoiceCatalogError(
            "voice_catalog_not_found", f"voice {selector!r} is not registered"
        )
    row = matches[0]
    if not row.get("selectable"):
        raise VoiceCatalogError(
            "voice_catalog_not_selectable",
            f"voice {selector!r} is not selectable: {row['availability']['reason']}",
        )
    return dict(row)
```

Add these exact engine-evidence helpers; keep validation limited to the two
engines that Phase 1 can actually bind:

```python
def build_engine_binding(voice: dict[str, Any]) -> dict[str, Any]:
    binding = voice.get("engine_binding")
    if not isinstance(binding, dict):
        raise VoiceCatalogError(
            "voice_binding_invalid",
            f"voice {voice.get('voice_id')!r} has no engine binding",
        )
    return {**dict(binding), "engine": str(voice.get("engine") or "")}


def validate_engine_binding(binding: Any) -> None:
    if not isinstance(binding, dict):
        raise VoiceCatalogError("voice_binding_invalid", "engine binding must be an object")
    engine = str(binding.get("engine") or "")
    if engine == "qwen_full_icl":
        profile_path = Path(str(binding.get("profile_path") or "")).expanduser().resolve()
        assessment = _profile_assessment(
            profile_path,
            expected_profile_id=str(binding.get("profile_id") or ""),
        )
        if not assessment.get("selectable"):
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                f"bound voice profile is invalid: {assessment.get('reason')}",
            )
        if assessment.get("profile_sha256") != str(binding.get("profile_sha256") or ""):
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                f"bound voice profile hash mismatch: {profile_path}",
            )
        return
    if engine == "qwen_custom_voice":
        runtime = Path(str(binding.get("runtime_path") or "")).expanduser().resolve()
        config = Path(str(binding.get("model_config_path") or "")).expanduser().resolve()
        if not runtime.is_file() or not config.is_file():
            raise VoiceCatalogError(
                "voice_binding_mismatch", "bound Qwen CustomVoice setup is missing"
            )
        if _sha256(config) != str(binding.get("model_config_sha256") or ""):
            raise VoiceCatalogError(
                "voice_binding_mismatch", f"bound model config hash mismatch: {config}"
            )
        supported, reason = _supported_presets(config.parent)
        speaker = str(binding.get("preset_speaker") or "").casefold()
        if reason or speaker not in supported:
            raise VoiceCatalogError(
                "voice_binding_mismatch",
                reason or f"bound model does not support {binding.get('preset_speaker')}",
            )
        return
    raise VoiceCatalogError(
        "voice_binding_invalid", f"unsupported voice engine: {engine or '<missing>'}"
    )
```

- [ ] **Step 5: Run catalog tests and the existing preset/profile suites**

Run:

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_voice_catalog.py tests/plugins/story_video/test_voice_presets.py tests/plugins/story_video/test_voice_profiles.py
```

Expected: all tests pass with zero collection errors and zero failures.

- [ ] **Step 6: Commit Task 1**

```bash
rtk git add plugins/story_video/voice_catalog.py plugins/story_video/voice_presets.py tests/plugins/story_video/test_voice_catalog.py
rtk git commit -m "feat(story-video): add normalized voice catalog"
```

- [ ] **Step 7: Goal-drift and over-design checkpoint**

Record a concise self-review in the active task commentary. It must confirm that
Task 1 only normalized existing clone and approved preset sources, did not add
automatic casting or synthesis, and cite the fresh catalog test output. If the
task added another provider abstraction, persistent preference store, or generic
scoring engine, remove it before continuing.

---

### Task 2: Expose The Catalog Through Listing And Operator Guidance

**Files:**
- Modify: `plugins/story_video/tools.py:1304-1385`
- Modify: `plugins/story_video/guide.py:172-190`
- Modify: `plugins/story_video/schemas.py:45-130`
- Modify: `tests/plugins/story_video/test_tools.py`
- Modify: `tests/plugins/story_video/test_guide.py`

**Interfaces:**
- Consumes: `list_voice_catalog(...) -> dict[str, Any]` from Task 1.
- Produces: `story_video_voice_manager(action="list")` responses with both `profiles` and `voices`, plus a human-readable guide based on normalized catalog records.

- [ ] **Step 1: Write failing tool and guide tests**

Add this tool test using an injected builder so it does not depend on the
machine-local model:

```python
def test_voice_manager_list_returns_normalized_selectable_actors(tmp_path) -> None:
    catalog = {
        "schema": "story_video_voice_profile_registry_v2",
        "profiles": [],
        "catalog_schema": "story_video_voice_catalog_v1",
        "catalog_sha256": "catalog-hash",
        "voices": [
            {
                "voice_id": "qwen_custom_vivian",
                "display_name": "Vivian",
                "engine": "qwen_custom_voice",
                "source_kind": "preset",
                "selectable": True,
                "availability": {"status": "ready", "reason": ""},
            }
        ],
    }

    payload = json.loads(
        story_video_voice_manager(
            {"action": "list"},
            voice_catalog_builder=lambda **kwargs: catalog,
            voice_registry_path=tmp_path / "registry.json",
        )
    )

    assert payload["success"] is True
    assert payload["profiles"] == []
    assert payload["voices"][0]["voice_id"] == "qwen_custom_vivian"
```

Add this guide test:

```python
def test_voice_guide_formats_clone_and_preset_catalog_rows() -> None:
    text = format_story_video_guide(
        None,
        "voices",
        voices={
            "default_voice_id": "simon_clean_v2",
            "voices": [
                {
                    "voice_id": "simon_clean_v2",
                    "display_name": "Simon clean narrator v2",
                    "engine": "qwen_full_icl",
                    "selectable": True,
                },
                {
                    "voice_id": "qwen_custom_vivian",
                    "display_name": "Vivian",
                    "engine": "qwen_custom_voice",
                    "selectable": True,
                },
            ],
        },
    )

    assert "simon_clean_v2" in text
    assert "Vivian" in text
    assert "Qwen CustomVoice" in text
```

- [ ] **Step 2: Run the two tests and verify RED**

Run the exact new test node IDs. Expected failures:

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_tools.py::test_voice_manager_list_returns_normalized_selectable_actors tests/plugins/story_video/test_guide.py::test_voice_guide_formats_clone_and_preset_catalog_rows
```

Expected: the manager rejects `voice_catalog_builder` behavior by returning the
old profile-only payload, and the guide omits Vivian.

- [ ] **Step 3: Route list through the catalog builder**

Modify the manager signature and list branch:

```python
def story_video_voice_manager(
    args: dict[str, Any],
    *,
    voice_registry_path: str | Path | None = None,
    voice_projects_root: str | Path | None = None,
    preset_previewer: Any = None,
    voice_catalog_builder: Any = None,
    **_: Any,
) -> str:
    action = str(args.get("action") or "list").strip().lower()
    registry_kwargs: dict[str, Any] = {}
    if voice_registry_path is not None:
        registry_kwargs["registry_path"] = voice_registry_path
    try:
        if action == "list":
            builder = voice_catalog_builder
            if builder is None:
                from .voice_catalog import list_voice_catalog

                builder = list_voice_catalog
            payload = builder(**registry_kwargs)
```

Do not change add, tune, archive, delete, or preview dispatch.

- [ ] **Step 4: Format normalized voices with a legacy fallback**

Replace `_format_voices()` row selection with:

```python
def _format_voices(voices: dict[str, Any] | None) -> str:
    payload = voices if isinstance(voices, dict) else {}
    catalog_rows = payload.get("voices")
    if isinstance(catalog_rows, list):
        enabled = [
            row
            for row in catalog_rows
            if isinstance(row, dict) and row.get("selectable") is not False
        ]
        default_voice = str(
            payload.get("default_voice_id")
            or payload.get("default_profile_id")
            or ""
        )
        lines = ["故事影片聲線"]
        for row in enabled:
            voice_id = str(row.get("voice_id") or "").strip()
            display_name = str(row.get("display_name") or voice_id).strip()
            engine = str(row.get("engine") or "")
            engine_label = (
                "Qwen CustomVoice" if engine == "qwen_custom_voice" else "完整聲線克隆"
            )
            marker = "（預設）" if voice_id == default_voice else ""
            lines.append(f"- `{voice_id}`：{display_name}｜{engine_label}{marker}")
        if enabled:
            lines.append("角色分配範例：`旁白用 simon_clean_v2，安安用 Vivian。`")
            return "\n".join(lines)
    profiles = payload.get("profiles")
    rows = profiles if isinstance(profiles, list) else []
    enabled = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("enabled") is not False
        and row.get("selectable") is not False
    ]
    if not enabled:
        return "故事影片聲線\n目前沒有可用聲線。使用 `新增故事影片聲線` 加入錄音。"
    default_profile = str(payload.get("default_profile_id") or "")
    lines = ["故事影片聲線"]
    for row in enabled:
        voice_id = str(row.get("voice_id") or row.get("profile_id") or "").strip()
        profile_id = str(row.get("profile_id") or "").strip()
        display_name = str(row.get("display_name") or voice_id).strip()
        marker = "（預設）" if profile_id == default_profile else ""
        lines.append(f"- `{voice_id}`：{display_name}，目前版本 `{profile_id}`{marker}")
    return "\n".join(lines)
```

Update the schema description to state that list returns clone profiles and
selectable CustomVoice actors. Do not add a new action or required parameter.

- [ ] **Step 5: Run focused listing tests**

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_guide.py tests/plugins/story_video/test_hooks.py
```

Expected: all tests pass; existing clone listing and fast-route tests remain green.

- [ ] **Step 6: Commit Task 2**

```bash
rtk git add plugins/story_video/tools.py plugins/story_video/guide.py plugins/story_video/schemas.py tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_guide.py
rtk git commit -m "feat(story-video): list selectable voice actors"
```

- [ ] **Step 7: Goal-drift and over-design checkpoint**

Record whether the public list truthfully distinguishes clone and preset actors,
whether compatibility fields remain intact, and the focused test evidence. Do
not proceed if listing code begins implementing cast scoring or media generation.

---

### Task 3: Bind Qwen Preset Actors With Locked Engine Evidence

**Files:**
- Modify: `plugins/story_video/dubbing.py:15-520`
- Modify: `tests/plugins/story_video/test_dubbing.py`

**Interfaces:**
- Consumes: `list_voice_catalog`, `resolve_catalog_voice`, `build_engine_binding`, and `validate_engine_binding` from Task 1.
- Produces: `bind_project_voice_cast(..., voice_catalog=None) -> VoiceCastSelection` and backward-compatible `resolve_project_voice_cast()` for v1 and v2 bindings.

- [ ] **Step 1: Write failing preset binding and drift tests**

Add this helper using the existing `_utterance()` fixture plus the real catalog
builder from Task 1, then add the assertions below:

```python
def _preset_cast_project(
    tmp_path,
    *,
    narrator_voice: str,
    hero_voice: str,
) -> tuple[Path, dict]:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry = tmp_path / "voices" / "registry.json"
    _add_voice(registry.parent, "simon_clean_v2")
    model = tmp_path / "custom-voice-model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "tts_model_type": "custom_voice",
                "talker_config": {
                    "spk_id": {"vivian": 1, "serena": 2, "uncle_fu": 3}
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = tmp_path / "mlx-python"
    runtime.write_text("runtime", encoding="utf-8")
    catalog = list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )
    project = tmp_path / "story"
    compile_dubbing_project(
        project,
        mode="creative",
        source_text="",
        speakers=[
            {
                "speaker_id": "narrator",
                "display_name": "旁白",
                "role": "narrator",
                "voice_id": narrator_voice,
            },
            {
                "speaker_id": "hero",
                "display_name": "主角",
                "role": "lead",
                "voice_id": hero_voice,
            },
        ],
        utterances=[
            _utterance("U001", "narrator", "故事開始。"),
            _utterance("U002", "hero", "出發吧！"),
        ],
    )
    return project, catalog
```

```python
def test_cast_binding_accepts_qwen_preset_aliases(tmp_path) -> None:
    project, catalog = _preset_cast_project(
        tmp_path,
        narrator_voice="Vivian",
        hero_voice="Uncle_Fu",
    )

    selection = bind_project_voice_cast(project, voice_catalog=catalog)

    rows = {row["speaker_id"]: row for row in selection.speakers}
    assert rows["narrator"]["voice_id"] == "qwen_custom_vivian"
    assert rows["narrator"]["engine"] == "qwen_custom_voice"
    assert rows["narrator"]["engine_binding"]["preset_speaker"] == "Vivian"
    assert rows["hero"]["engine_binding"]["preset_speaker"] == "Uncle_Fu"
    binding = json.loads(selection.binding_path.read_text(encoding="utf-8"))
    assert binding["schema"] == "story_video_voice_cast_binding_v2"
    assert binding["catalog_sha256"] == catalog["catalog_sha256"]


def test_preset_binding_fails_closed_on_model_config_drift(tmp_path) -> None:
    project, catalog = _preset_cast_project(
        tmp_path,
        narrator_voice="Serena",
        hero_voice="Vivian",
    )
    selection = bind_project_voice_cast(project, voice_catalog=catalog)
    model_config = Path(
        selection.speakers[0]["engine_binding"]["model_config_path"]
    )
    payload = json.loads(model_config.read_text(encoding="utf-8"))
    payload["talker_config"]["spk_id"].pop("serena")
    model_config.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DubbingContractError) as error:
        resolve_project_voice_cast(project)

    assert error.value.error_type == "voice_cast_binding_mismatch"
```

Keep `test_cast_binding_resolves_latest_concrete_profiles_and_variants` and the
existing v1 fixture tests unchanged as compatibility proof.

- [ ] **Step 2: Run the new tests and verify RED**

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_dubbing.py::test_cast_binding_accepts_qwen_preset_aliases tests/plugins/story_video/test_dubbing.py::test_preset_binding_fails_closed_on_model_config_drift
```

Expected: `TypeError` because `bind_project_voice_cast()` does not accept
`voice_catalog`, or `voice_cast_profile_unresolved` because presets are not clone
profiles.

- [ ] **Step 3: Add the v2 binding schema and catalog selection**

Add constants and imports:

```python
from .voice_catalog import (
    VoiceCatalogError,
    build_engine_binding,
    list_voice_catalog,
    resolve_catalog_voice,
    validate_engine_binding,
)

VOICE_CAST_BINDING_SCHEMA_V1 = "story_video_voice_cast_binding_v1"
VOICE_CAST_BINDING_SCHEMA_V2 = "story_video_voice_cast_binding_v2"
VOICE_CAST_BINDING_SCHEMAS = {
    VOICE_CAST_BINDING_SCHEMA_V1,
    VOICE_CAST_BINDING_SCHEMA_V2,
}
VOICE_CAST_BINDING_SCHEMA = VOICE_CAST_BINDING_SCHEMA_V1
```

Change binding construction to this provider-neutral shape:

```python
def bind_project_voice_cast(
    project_dir: str | Path,
    *,
    registry_path: str | Path = DEFAULT_VOICE_REGISTRY,
    voice_catalog: dict[str, Any] | None = None,
) -> VoiceCastSelection:
    project = Path(project_dir).expanduser().resolve()
    catalog = voice_catalog
    if catalog is None:
        try:
            catalog = list_voice_catalog(registry_path=registry_path)
        except (VoiceCatalogError, VoiceProfileError) as exc:
            raise DubbingContractError("voice_cast_profile_unresolved", str(exc)) from exc
```

Inside the speaker loop, replace `_select_profile()` with:

```python
        try:
            voice = resolve_catalog_voice(str(speaker.get("voice_id") or ""), catalog)
            engine_binding = build_engine_binding(voice)
        except VoiceCatalogError as exc:
            raise DubbingContractError("voice_cast_profile_unresolved", str(exc)) from exc
        resolved.append(
            {
                "speaker_id": speaker_id,
                "display_name": str(speaker.get("display_name") or speaker_id),
                "role": str(speaker.get("role") or "supporting"),
                "voice_id": str(voice["voice_id"]),
                "engine": str(voice["engine"]),
                "source_kind": str(voice["source_kind"]),
                "assignment_origin": "manual",
                "engine_binding": engine_binding,
                "variant": variant,
            }
        )
```

For `qwen_full_icl` only, also copy `profile_id`, `profile_path`,
`profile_sha256`, and `clone_mode="full_icl"` from `engine_binding` onto the
speaker row. Those fields preserve the existing `VoiceCastSelection.speakers`
shape for clone callers; never synthesize them for preset rows.

Write new bindings with `schema=VOICE_CAST_BINDING_SCHEMA_V2` and
`catalog_sha256=str(catalog["catalog_sha256"])`. Do not remove the contract file
hashes or story-mode fields.

- [ ] **Step 4: Validate v1 and v2 without weakening old checks**

In `resolve_project_voice_cast()`:

```python
    schema = str(binding.get("schema") or "")
    if (
        schema not in VOICE_CAST_BINDING_SCHEMAS
        or binding.get("status") != "locked"
        or binding.get("language_policy") != "zh-TW"
    ):
        raise DubbingContractError(
            "voice_cast_binding_invalid", f"invalid voice cast binding: {binding_path}"
        )
```

For every speaker row, keep the current `_profile_assessment()` logic when
`schema == VOICE_CAST_BINDING_SCHEMA_V1`. For v2, call
`validate_engine_binding(row["engine_binding"])` and convert every
`VoiceCatalogError` to:

```python
raise DubbingContractError("voice_cast_binding_mismatch", str(exc)) from exc
```

Always retain `_validate_variant()` after engine validation.

Add an explicit compatibility test by creating a clone-only v2 binding,
rewriting only its `schema` to `story_video_voice_cast_binding_v1` (the clone
speaker rows retain the legacy fields above), and asserting
`resolve_project_voice_cast()` succeeds. This is the proof that an existing v1
file remains readable; do not rely on the new v2 clone tests as a proxy.

- [ ] **Step 5: Run the complete dubbing and voice-catalog suites**

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_dubbing.py tests/plugins/story_video/test_voice_catalog.py tests/plugins/story_video/test_voice_profiles.py
```

Expected: all preset and full-ICL binding tests pass; existing v1 bindings remain readable.

- [ ] **Step 6: Commit Task 3**

```bash
rtk git add plugins/story_video/dubbing.py tests/plugins/story_video/test_dubbing.py
rtk git commit -m "feat(story-video): bind preset voice actors"
```

- [ ] **Step 7: Goal-drift and over-design checkpoint**

Confirm that v2 adds only provider-neutral locked evidence, v1 remains readable,
and no automatic character analysis or audio synthesis entered the binder. Cite
the preset drift and full-ICL regression results before starting Task 4.

---

### Task 4: Prove The User-Facing Tool Path And Regression Boundary

**Files:**
- Modify: `plugins/story_video/tools.py:1388-1470`
- Modify: `plugins/story_video/schemas.py:130-230`
- Modify: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Consumes: v2 catalog binding from Task 3.
- Produces: `story_video_audio_director(action="bind_cast")` support for preset actors through the same public tool used by multi-character projects.

- [ ] **Step 1: Write the failing audio-director integration test**

Add an injectable `voice_catalog_builder` at the tool boundary and test the real
compile-and-immediately-bind behavior. Reuse `_active_context()` and add a
`_ready_voice_catalog()` helper with the same temporary CustomVoice config and
runtime pattern used by `test_voice_catalog.py`:

```python
def _ready_voice_catalog(tmp_path) -> dict:
    from plugins.story_video.voice_catalog import list_voice_catalog

    registry = _voice_registry(
        tmp_path,
        "simon_clean_v2",
        default="simon_clean_v2",
    )
    model = tmp_path / "custom-voice-model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "tts_model_type": "custom_voice",
                "talker_config": {
                    "spk_id": {"vivian": 1, "serena": 2, "uncle_fu": 3}
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = tmp_path / "mlx-python"
    runtime.write_text("runtime", encoding="utf-8")
    return list_voice_catalog(
        registry_path=registry,
        preset_model_path=model,
        preset_runtime_path=runtime,
    )


def test_audio_director_binds_three_qwen_voice_actors(tmp_path) -> None:
    store, context = _active_context(tmp_path)
    catalog = _ready_voice_catalog(tmp_path)
    payload = json.loads(
        story_video_audio_director(
            {
                "action": "compile",
                "mode": "creative",
                "source_text": "",
                "speakers": [
                    {
                        "speaker_id": "girl",
                        "display_name": "安安",
                        "role": "lead",
                        "voice_id": "Vivian",
                    },
                    {
                        "speaker_id": "mother",
                        "display_name": "媽媽",
                        "role": "supporting",
                        "voice_id": "Serena",
                    },
                    {
                        "speaker_id": "captain",
                        "display_name": "老船長",
                        "role": "supporting",
                        "voice_id": "Uncle_Fu",
                    },
                ],
                "utterances": [
                    {
                        "utterance_id": "U001",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "girl",
                        "display_text": "我們出發吧！",
                    },
                    {
                        "utterance_id": "U002",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "mother",
                        "display_text": "路上要小心。",
                    },
                    {
                        "utterance_id": "U003",
                        "scene_id": "S01",
                        "shot_id": "S01_SH01",
                        "speaker_id": "captain",
                        "display_text": "風向變了。",
                    },
                ],
            },
            session_id="session-1",
            store=store,
            voice_catalog_builder=lambda **kwargs: catalog,
        )
    )
    assert payload["success"] is True
    assert payload["bound"] is True
    binding = json.loads(
        (context.project_dir / "voice_cast_binding.json").read_text(encoding="utf-8")
    )
    rows = {row["speaker_id"]: row for row in binding["speakers"]}
    assert rows["girl"]["voice_id"] == "qwen_custom_vivian"
    assert rows["mother"]["voice_id"] == "qwen_custom_serena"
    assert rows["captain"]["voice_id"] == "qwen_custom_uncle_fu"
```

Use the existing store and utterance fixture patterns in `test_tools.py`; do not
create a second fake state implementation.

- [ ] **Step 2: Run the integration test and verify RED**

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_tools.py::test_audio_director_binds_three_qwen_voice_actors
```

Expected: `TypeError` for the new injection or a structured unresolved-profile error.

- [ ] **Step 3: Pass the normalized catalog into the binder**

Extend the director signature with `voice_catalog_builder: Any = None`. Build
the injected catalog once before dispatch, then pass it in both the `compile`
and `bind_cast` branches:

```python
        catalog_kwargs: dict[str, Any] = {}
        if voice_registry_path is not None:
            catalog_kwargs["registry_path"] = voice_registry_path
        catalog = (
            voice_catalog_builder(**catalog_kwargs)
            if voice_catalog_builder is not None
            else None
        )
        selection = bind_project_voice_cast(
            context.project_dir,
            registry_path=(
                voice_registry_path
                if voice_registry_path is not None
                else DEFAULT_VOICE_REGISTRY
            ),
            voice_catalog=catalog,
        )
```

Update the audio-director schema description from “one concrete local voice
profile” to “one concrete catalog voice with locked engine evidence.” Keep the
existing speaker `voice_id` requirement in Phase 1; automatic assignment belongs
to Phase 2.

- [ ] **Step 4: Run all focused story-video voice tests**

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/plugins/story_video/test_voice_catalog.py tests/plugins/story_video/test_voice_presets.py tests/plugins/story_video/test_voice_profiles.py tests/plugins/story_video/test_dubbing.py tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_guide.py tests/plugins/story_video/test_hooks.py
```

Expected: all tests pass with zero failures.

- [ ] **Step 5: Run lint and diff hygiene**

```bash
rtk /Users/simon/.hermes/hermes-agent/venv/bin/ruff check plugins/story_video/voice_catalog.py plugins/story_video/voice_presets.py plugins/story_video/dubbing.py plugins/story_video/tools.py plugins/story_video/guide.py plugins/story_video/schemas.py tests/plugins/story_video/test_voice_catalog.py tests/plugins/story_video/test_dubbing.py tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_guide.py
rtk git diff --check local/main...HEAD
```

Expected: `All checks passed!` and no diff-check output.

- [ ] **Step 6: Run the local operator smoke**

Invoke the actual manager function from this worktree with the machine-local
registry, model, and runtime. This proves the operator tool path without
deploying or mutating `runtime/current`:

```bash
rtk env PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -c 'import json; from plugins.story_video.tools import story_video_voice_manager; payload=json.loads(story_video_voice_manager({"action":"list"})); print(json.dumps({"success":payload["success"],"voices":[{"voice_id":row["voice_id"],"engine":row["engine"],"selectable":row["selectable"]} for row in payload["voices"]]}, ensure_ascii=False, indent=2))'
```

Expected: the response contains `simon_clean_v2`, `Vivian`, `Serena`, and
`Uncle_Fu`; it must not claim that the presets are full-ICL clones or Taiwan-accent voices.

- [ ] **Step 7: Commit Task 4**

```bash
rtk git add plugins/story_video/tools.py plugins/story_video/schemas.py tests/plugins/story_video/test_tools.py
rtk git commit -m "feat(story-video): expose preset cast binding"
```

- [ ] **Step 8: Request review before publish or deployment**

Run:

```bash
rtk git status --short --branch
rtk git log --oneline local/main..HEAD
rtk git diff --stat local/main...HEAD
```

Expected: a clean topic worktree, four scoped commits after the design/plan
commits, and no unrelated files. Apply the repository's reviewer gate before
opening a fork-local PR. Deployment remains a separate explicitly authorized
cutover after PR CI is green.

- [ ] **Step 9: Final goal-drift and over-design checkpoint**

Compare the diff against the approved Phase 1 requirements. Confirm the four
voices are listed and bindable, failures are truthful, v1 compatibility is
preserved, and Phase 2/3 code was not pulled forward. List any remaining gap as
an explicit follow-up rather than hiding it behind a completion claim.

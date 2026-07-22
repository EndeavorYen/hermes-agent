# Story Video Multi-Voice Clone Profiles Design

**Date:** 2026-07-17

## Goal

Allow story-video projects to select one of multiple Qwen3-TTS Base voice-clone
profiles while keeping the shared zh-TW text normalization, pronunciation, and
acoustic QC pipeline independent from speaker identity.

Phase one supports one locked narrator per project. Multi-character casting is
intentionally deferred.

## Product Contract

- Operators select a narrator by stable `voice_id`; they do not pass reference
  paths or model flags in normal use.
- A project binds the selected profile before synthesis and records its SHA-256.
- Once bound, changing the global default cannot silently change that project's
  narrator.
- A changed or missing bound profile fails closed before synthesis.
- Production uses Qwen3-TTS Base full voice clone conditioning with both
  `ref_audio` and `ref_text`.
- `x_vector_only` is not a production fallback.
- All profiles share the same zh-TW pronunciation lexicon, text normalization,
  chunking, ASR/alignment checks, and prosody gates.
- Existing installations that only have `active_narrator.json` continue to work.
- Rejected, disabled, unapproved, online, or non-Base profiles cannot be selected.

## Runtime Data

### Registry

`~/.hermes/story_video_voice_profiles/registry.json` is the operator-owned list
of selectable profiles:

```json
{
  "schema": "story_video_voice_profile_registry_v1",
  "default_profile_id": "simon_clean_v2",
  "profiles": [
    {
      "profile_id": "simon_clean_v2",
      "profile_path": "~/.hermes/story_video_voice_profiles/simon_clean_v2/profile.json",
      "enabled": true
    }
  ]
}
```

The profile itself remains the authority for consent, local-only provider
policy, model, reference recording, reference transcript, and synthesis tuning.

### Project Binding

`<project>/voice_profile_binding.json` freezes the narrator choice:

```json
{
  "schema": "story_video_voice_profile_binding_v1",
  "voice_role": "narrator",
  "profile_id": "simon_clean_v2",
  "profile_path": "/absolute/profile.json",
  "profile_sha256": "...",
  "clone_mode": "full_icl",
  "language_policy": "zh-TW",
  "status": "locked"
}
```

The binding is created atomically. Existing bindings are verified on every
voice run. Selecting another voice deliberately replaces the binding before any
narration exists; once voice artifacts exist, changing the narrator requires a
forced revoice operation so mixed voices cannot appear accidentally.

## Resolution Order

1. A valid project binding.
2. The registry default.
3. Legacy `active_narrator.json` for backward compatibility.

The executor always passes the resolved profile explicitly to the narration
generator with `--voice-profile`; the generator must never infer a different
profile after project binding.

## Operator Interface

Extend `story_video_control` with:

- `action=list_voices`: list enabled selectable profiles and mark the current
  project/default narrator.
- `action=select_voice`, `voice_id=<id>`: create or replace the current project's
  binding when it is safe to do so.
- `action=voice_status`: show the current binding and integrity state.

The normal natural-language surface can translate requests such as `列出旁白聲線`
or `這部影片使用 simon_clean_v2` into these deterministic actions.

## Evidence

The narration manifest records `voice_profile_id`, profile hash, binding path,
binding hash, and `clone_mode=full_icl`. Voice phase validation verifies these
values against the current project binding. This makes provider/profile drift a
proof failure instead of an invisible change.

## Failure Handling

- Missing registry/profile/reference/model: `setup_required`.
- Invalid consent/status/provider/clone mode: fail before dispatch.
- Bound profile hash mismatch: `voice_profile_binding_mismatch`; no synthesis.
- Unknown or disabled `voice_id`: deterministic selection error.
- Existing narration plus narrator change: fail closed and require explicit
  revoice/cleanup rather than producing a mixed-voice project.

## Verification

- Unit tests cover registry fallback, profile eligibility, selection, binding
  immutability, hash mismatch, and explicit executor CLI arguments.
- Existing story-video suites prove backward compatibility.
- Local narration-generator tests prove manifest evidence and full Base clone
  parameters remain present.
- A deployed smoke lists the real registry, binds a temporary project, and
  verifies the runtime executor dispatches the selected profile explicitly.

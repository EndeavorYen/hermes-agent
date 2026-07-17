# Story Video Multi-Voice Clone Profiles Implementation Plan

**Goal:** Add selectable, project-locked Qwen Base voice-clone profiles without
coupling speaker identity to the shared zh-TW language/QC pipeline.

**Architecture:** A pure profile registry and project-binding module resolves a
stable profile. Story-video control exposes list/select/status actions. The
native voice executor passes the binding's exact profile path to the existing
Qwen generator, and both generator and voice phase proof persist/verify binding
evidence.

**Stack:** Python, pytest, Hermes plugin hooks/tools, Qwen3-TTS MLX local runtime.

## Task 1: Registry And Binding Core

- Add focused failing tests for legacy fallback, registry default, disabled and
  rejected profiles, atomic project binding, idempotent resolution, and hash
  mismatch.
- Implement `plugins/story_video/voice_profiles.py` with pure validation and
  filesystem-bound registry/binding operations.
- Run the focused tests until green.

## Task 2: Operator Controls

- Add failing schema/tool tests for `list_voices`, `select_voice`, and
  `voice_status` plus required `voice_id` validation.
- Extend `story_video_control` and its schema.
- Ensure narrator changes fail closed after narration exists unless an explicit
  revoice path is used.

## Task 3: Executor And Proof Evidence

- Add failing executor tests that require `--voice-profile` with the bound path
  and expose profile metadata in the summary.
- Resolve/bind before synthesis; classify profile errors as setup-required and
  never dispatch on integrity failure.
- Extend narration manifest and voice proof tests for profile/binding hashes and
  `clone_mode=full_icl`.

## Task 4: Skill And Runtime Registry

- Update the local narration generator tests first, then add binding evidence to
  the manifest while retaining explicit full ICL clone inputs.
- Update the story-video production skill with the simple voice selection
  contract and one-narrator-per-project rule.
- Create a registry containing only the approved `simon_clean_v2`; keep the
  rejected legacy recording unselectable.

## Task 5: Verification And Deployment

- Run focused tests, the complete story-video suite, formatting/static checks,
  and the broader relevant repository suite.
- Run a local live smoke against the real approved profile and a temporary
  project; verify list, bind, integrity, and explicit executor dispatch.
- Push the topic branch, open a PR to `local/main`, wait for CI, squash merge,
  fast-forward `local/main` and `runtime/current` to the same SHA, restart the
  gateway, and repeat the smoke against deployed code.

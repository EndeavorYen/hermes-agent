# Story Video Multi-Character Dubbing Implementation Plan

**Goal:** Add versioned local voice management and three-mode multi-character
dubbing without regressing the existing one-narrator story-video workflow.

**Architecture:** Add a voice lifecycle layer beside the current profile resolver,
a deterministic audio-director contract compiler, a hash-locked cast resolver, and
an executor branch that passes the cast contract to the local Qwen generator. Keep
language normalization shared and keep all private voice media outside git.

**Tech Stack:** Python, pytest, Hermes plugin tools/hooks, local MLX-Audio Qwen3-TTS.

---

## Task 1: Voice lifecycle

**Files:**
- Modify: `plugins/story_video/voice_profiles.py`
- Create: `tests/plugins/story_video/test_voice_manager.py`

1. Write failing tests for add, immutable tune, archive, reference-safe delete,
   default/version resolution, and legacy profiles.
2. Add registry v2-compatible metadata while preserving registry v1 reads.
3. Implement atomic lifecycle mutations and project-reference scanning.
4. Run the focused profile and manager tests.

## Task 2: Audio director contracts

**Files:**
- Create: `plugins/story_video/dubbing.py`
- Create: `tests/plugins/story_video/test_dubbing.py`

1. Write failing tests for creative, remake, and exact read-aloud compilation.
2. Implement strict schemas, controlled enums, source hashing, and exact span
   validation.
3. Implement deterministic cast-to-profile binding and hash validation.
4. Prove unresolved speakers and changed source/profile data fail closed.

## Task 3: Narrow tools and model routing

**Files:**
- Modify: `plugins/story_video/schemas.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `plugins/story_video/__init__.py`
- Modify: `plugins/story_video/plugin.yaml`
- Modify: `plugins/story_video/hooks.py`
- Modify: `agent/transports/hermes_tools_mcp_server.py`
- Modify: related tests

1. Write failing schema, registration, MCP exposure, and natural-routing tests.
2. Add `story_video_voice_manager` and `story_video_audio_director` tools.
3. Keep legacy voice actions operational.
4. Update hook instructions so short natural requests route automatically.

## Task 4: Multi-voice execution

**Files:**
- Modify: `plugins/story_video/voice_executor.py`
- Modify: `tests/plugins/story_video/test_voice_executor.py`

1. Write failing tests for cast-binding dispatch and single-voice compatibility.
2. Resolve the cast contract when present and pass `--voice-cast-binding` plus
   `--dialogue-ledger` to the local generator.
3. Include cast evidence in executor summaries and preserve cancellation/retries.

## Task 5: Local Qwen generator and skills

**Files:**
- Modify: local production generator and its tests
- Create: local `story-video-voice-manager` skill
- Create: local `story-video-audio-director` skill
- Modify: local production-pipeline skill

1. Add fixture tests for multi-profile loading, utterance routing, manifest v6,
   and fail-closed binding validation.
2. Load Qwen once and switch full-ICL reference inputs per utterance.
3. Reuse display/spoken compilation and acoustic QC for every utterance.
4. Document only orchestration rules in the pipeline skill; keep specialist rules
   in the two new skills.

## Task 6: Verification and deployment

1. Run focused tests, story-video suite, and relevant MCP/plugin suites.
2. Run a real Metal smoke using the approved profile plus a declared performance
   variant to prove multi-speaker routing without claiming a second identity.
3. Review privacy and git diff, open a PR to `local/main`, and wait for CI.
4. Merge, advance protected `runtime/current`, restart the gateway, and run a
   deployed tool/schema smoke.


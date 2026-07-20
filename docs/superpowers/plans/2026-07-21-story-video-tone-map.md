# Story Video Engine-Aware Tone Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each story-video utterance's emotion, action, and pace resolve to a bounded general or adult tone that actually controls Qwen CustomVoice or full-ICL synthesis without weakening pronunciation, routing, or final-video QC.

**Architecture:** Add one pure, versioned tone catalog to `plugins/story_video`, resolve tones while compiling the hash-locked dialogue ledger, and carry the full catalog plus resolved per-utterance controls into the installed local Qwen executor. The executor remains provider-specific: it sends stable `instruct` templates only to CustomVoice, applies conservative speed/sampling/pause controls to full-ICL clone, emits a v7 narration manifest, and leaves neutral legacy calls unchanged.

**Tech Stack:** Python 3.11, pytest, dataclasses/JSON contracts, Qwen3-TTS 1.7B Base and CustomVoice through MLX-Audio, Qwen ASR/forced alignment, ffmpeg/ffprobe, Hermes story-video state and production runner.

## Global Constraints

- Use TDD for every behavior change: focused test must fail for the missing behavior before production code is edited.
- General tone IDs are `neutral`, `warm`, `joyful`, `excited`, `sad`, `angry`, `tense`, and `puzzled` under the `general.*` namespace.
- Adult tone IDs are `flirtatious`, `intimate`, `desirous`, `breathless`, `shy`, `teasing`, `commanding`, `receptive`, `intense`, and `afterglow` under `adult.*`.
- Adult tones are accepted only when `content_profile.rating=adult_explicit`; the existing local user-source passthrough remains active and must not regress to `SETUP_REQUIRED`.
- CustomVoice may receive only catalog-owned stable Traditional Chinese `instruct` templates. Full-ICL clone must continue to receive exact `ref_audio` and `ref_text` and must never receive an emotion instruction.
- Tone speed is clamped to `0.90..1.10`, tone temperature delta to `-0.10..+0.10`, pause to `0.08..0.45` seconds, and tone pitch shift remains `0`.
- Actions, role names, and tone labels remain display-only. TTS and pronunciation QC consume only `spoken_text`.
- Tone control never injects untranscribed breathing, gasps, laughs, or other vocalizations.
- Existing v1 dialogue ledgers and v4-v6 narration manifests remain readable. Newly compiled tone-aware projects use dialogue-ledger v2 and narration-manifest v7.
- Generated audio, adult source text, provider output, and live-smoke artifacts stay local and uncommitted.

---

### Task 1: Add the pure tone catalog and resolver

**Files:**
- Create: `plugins/story_video/tone_map.py`
- Create: `tests/plugins/story_video/test_tone_map.py`

**Interfaces:**
- Produces: `build_tone_catalog() -> dict[str, Any]`
- Produces: `resolve_utterance_tone(*, emotion: str, action: str, pace: str, tone_id: str = "", intensity: int | None = None, modifiers: list[str] | None = None, content_rating: str = "general") -> dict[str, Any]`
- Produces: `ToneMapError(error_type: str, message: str)`
- Consumed by: Task 2 dialogue compilation and Task 3 executor catalog validation.

- [ ] **Step 1: Write failing catalog and resolution tests**

```python
def test_resolve_general_emotion_and_action_modifiers():
    tone = resolve_utterance_tone(
        emotion="curious",
        action="壓低聲音，猶豫地看向門口",
        pace="slow",
    )
    assert tone["tone_id"] == "general.puzzled"
    assert tone["modifiers"] == ["whispered", "hesitant"]
    assert tone["resolution"] == "mapped"


def test_explicit_adult_tone_requires_adult_rating():
    with pytest.raises(ToneMapError, match="requires adult_explicit"):
        resolve_utterance_tone(
            emotion="neutral", action="", pace="natural",
            tone_id="adult.intimate", content_rating="general",
        )


def test_adult_action_maps_without_injecting_vocalization():
    tone = resolve_utterance_tone(
        emotion="neutral", action="靠近耳邊，帶著壓抑的渴望輕聲說",
        pace="slow", content_rating="adult_explicit",
    )
    assert tone["tone_id"] == "adult.desirous"
    assert tone["modifiers"] == ["whispered", "restrained", "soft"]
    assert "喘息" not in json.dumps(tone, ensure_ascii=False)
```

- [ ] **Step 2: Run RED**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/plugins/story_video/test_tone_map.py -q
```

Expected: collection fails because `plugins.story_video.tone_map` does not exist.

- [ ] **Step 3: Implement the catalog and resolver**

Create a canonical catalog with schema `story_video_tone_catalog_v1`, version
`1`, all 18 tone entries, the eight approved modifiers, per-engine adapter
data, allowed modifier sets, safe bounds, and a SHA-256 computed from canonical
JSON without the `sha256` field. Map existing emotions deterministically:

```python
EMOTION_TO_TONE = {
    "neutral": "general.neutral",
    "wonder": "general.excited",
    "curious": "general.puzzled",
    "joy": "general.joyful",
    "sadness": "general.sad",
    "fear": "general.tense",
    "tension": "general.tense",
    "surprise": "general.excited",
    "humor": "general.joyful",
    "warmth": "general.warm",
}
```

Use ordered Traditional Chinese keyword tables for action-to-tone and
action-to-modifier mapping. Explicit invalid IDs, intensities outside `1..3`,
incompatible modifiers, and adult tones outside `adult_explicit` raise
`ToneMapError`. Unknown non-explicit emotion falls back to neutral with a
warning in the resolved object.

- [ ] **Step 4: Run GREEN and refactor only after green**

Run the Task 1 test file and require all tests to pass with no warnings.

- [ ] **Step 5: Commit Task 1**

```bash
git add plugins/story_video/tone_map.py tests/plugins/story_video/test_tone_map.py
git commit -m "feat(story-video): add controlled tone catalog"
```

---

### Task 2: Compile resolved tones into dialogue-ledger v2

**Files:**
- Modify: `plugins/story_video/dubbing.py`
- Modify: `plugins/story_video/source_passthrough.py`
- Modify: `plugins/story_video/schemas.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `tests/plugins/story_video/test_dubbing.py`
- Modify: `tests/plugins/story_video/test_source_passthrough.py`
- Modify: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Consumes: `build_tone_catalog()` and `resolve_utterance_tone()` from Task 1.
- Produces: `story_video_dialogue_ledger_v2` with `content_rating`, full `tone_catalog`, and one resolved `tone` object per utterance.
- Produces: `compile_dubbing_project(..., content_rating: str = "general")`.
- Consumed by: Task 3 local executor and existing cast-binding hash locks.

- [ ] **Step 1: Write failing compile and passthrough tests**

Add tests proving:

```python
result = compile_dubbing_project(
    project, mode="creative", source_text="", speakers=speakers,
    content_rating="general",
    utterances=[{**utterance, "emotion": "curious", "action": "猶豫地問"}],
)
ledger = json.loads((project / "dialogue_ledger.json").read_text())
assert ledger["schema"] == "story_video_dialogue_ledger_v2"
assert ledger["tone_catalog"]["schema"] == "story_video_tone_catalog_v1"
assert ledger["utterances"][0]["tone"]["tone_id"] == "general.puzzled"


prepared = prepare_local_adult_passthrough(adult_context)
ledger = json.loads((adult_context.project_dir / "dialogue_ledger.json").read_text())
assert ledger["content_rating"] == "adult_explicit"
assert ledger["utterances"][1]["tone"]["tone_id"].startswith("adult.")
assert validate_phase(adult_context, "planning").ok is True
```

Also assert explicit `tone_id`, `tone_intensity`, and `tone_modifiers` are
accepted by the audio-director schema, invalid adult use fails before binding,
and no action text is copied into `display_text` or later spoken fields.

- [ ] **Step 2: Run RED**

Run the three focused test files. Expected failures: compile has no
`content_rating`, ledger remains v1, and utterances have no resolved tone.

- [ ] **Step 3: Implement minimal compilation changes**

- Add v1/v2 ledger constants while keeping v1 inspection compatibility.
- Replace the old fixed emotion allowlist check with tone resolution.
- Preserve original `emotion`, `action`, and `pace`, then add `tone`.
- Store the complete canonical catalog and content rating at ledger top level.
- Add optional schema fields `tone_id`, `tone_intensity`, and
  `tone_modifiers`; keep them optional for natural-language operation.
- In `story_video_audio_director`, derive the rating from project-local
  `content_profile.json` when present and valid; otherwise use `general`.
- In adult source passthrough, call compile with
  `content_rating="adult_explicit"`. Keep the existing exact content-profile
  object unchanged so planning validation remains green.
- Parse only deterministic stage-direction keywords; do not invoke an LLM or
  rewrite the supplied adult source.

- [ ] **Step 4: Run focused tests and existing dubbing/source suites**

Require all focused files to pass. Run `git diff --check`.

- [ ] **Step 5: Commit Task 2**

```bash
git add plugins/story_video/dubbing.py plugins/story_video/source_passthrough.py \
  plugins/story_video/schemas.py plugins/story_video/tools.py \
  tests/plugins/story_video/test_dubbing.py \
  tests/plugins/story_video/test_source_passthrough.py \
  tests/plugins/story_video/test_tools.py
git commit -m "feat(story-video): compile per-utterance tones"
```

---

### Task 3: Apply tones in the installed local Qwen executor

**Files:**
- Modify local runtime: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/generate_qwen_story_narration.py`
- Modify local tests: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py`

**Interfaces:**
- Consumes: dialogue-ledger v2 and its embedded tone catalog from Task 2.
- Produces: per-chunk `tone`, `tone_adapter`, instruction template ID, applied parameters, and pause evidence.
- Produces: `story_video_narration_manifest_v7` for tone-aware cast runs.
- Preserves: v1 ledgers still synthesize through the neutral no-op path and v4-v6 manifest compatibility.

- [ ] **Step 1: Write failing executor tests**

Add tests proving:

```python
units = module.load_dialogue_segments(
    ledger_v2, story_mode="creative", speaker_profiles=profiles,
)[1]["S00"][0]["utterances"]
assert units[0]["tone"]["tone_id"] == "general.puzzled"

module.synthesize_qwen_cast_segments(
    segments=[custom_voice_tone_segment, clone_tone_segment],
    offline=True, model_loader=fake_loader, audio_writer=fake_writer,
    postprocessor=fake_postprocessor, cache_clearer=lambda: None,
)
assert custom_calls[0]["instruct"] == "帶著疑惑與些許猶豫，自然地問"
assert "instruct" not in clone_calls[0]
assert clone_calls[0]["ref_audio"] == clone_profile["reference_audio"]
assert clone_calls[0]["ref_text"] == clone_profile["reference_transcript"]
```

Add tests for neutral strict no-op, adult.breathless not injecting text, speed
and temperature bounds, per-chunk pause `<=0.45`, v1 ledger compatibility,
catalog hash mismatch failure, and v7 manifest evidence.

- [ ] **Step 2: Run RED**

Run:

```bash
/Users/simon/.hermes/.venvs/mlx-audio/bin/python -m unittest \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py
```

If the file requires pytest fixtures, use the repository Python with the local
script directory on `PYTHONPATH`:

```bash
PYTHONPATH=/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts \
  /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py -q
```

Expected failures: v2 ledger is unsupported, CustomVoice call has no
`instruct`, and manifest has no tone contract.

- [ ] **Step 3: Implement generic catalog-driven adaptation**

- Accept ledger schemas v1 and v2. For v2, recompute and validate the embedded
  catalog SHA before reading any utterance.
- Validate resolved tone IDs, intensity, modifiers, adapter values, and hard
  bounds from the embedded catalog.
- Merge tone adapter values over the speaker's locked variant without mutating
  the binding. Clamp final speed and temperature delta to approved bounds;
  keep tone pitch shift at zero.
- Pass catalog `instruct` only in the `qwen_custom_voice` branch. Keep the
  full-ICL call signature limited to text, language, `ref_audio`, `ref_text`,
  and sampling controls.
- Use each chunk's resolved pause for timeline math and `assemble_scene_audio`
  instead of a single global pause. Keep ellipsis normalization and cap all
  resolved pauses at `0.45` seconds.
- Record `candidate_count=1` for the initial candidate and increment it on the
  existing selective acoustic repair loop. Do not add a second unconditional
  generation framework; the spec permits a second candidate only when useful.
- Emit manifest v7 only for ledger v2 cast runs. Add top-level catalog and
  tone-control evidence and keep per-chunk evidence in `outputs`.

- [ ] **Step 4: Run the full local generator test file**

Require all tests to pass, including existing pronunciation, repair,
full-ICL, CustomVoice, and timeline tests.

- [ ] **Step 5: Record the local runtime patch evidence**

Record before/after SHA-256 of the generator and test files in the implementation
checkpoint. These files are local runtime state and must not be staged in the
Hermes repo commit.

---

### Task 4: Validate v7 manifests and expose tone help

**Files:**
- Modify: `plugins/story_video/tools.py`
- Modify: `plugins/story_video/render_modes.py`
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/guide.py`
- Modify: `docs/story-video-operator-guide.md`
- Modify: `tests/plugins/story_video/test_tools.py`
- Modify: `tests/plugins/story_video/test_render_modes.py`
- Modify: `tests/plugins/story_video/test_visual_judge.py`
- Modify: `tests/plugins/story_video/test_guide.py`

**Interfaces:**
- Consumes: narration-manifest v7 from Task 3.
- Produces: fail-closed voice proof for catalog hash, tone-control status,
  engine adapter separation, bounded applied controls, and dialogue-ledger hash.
- Produces: `/story-video help` and examples that explain optional general and adult tone concepts without requiring internal syntax.

- [ ] **Step 1: Write failing validation and help tests**

Create a valid v7 fixture and mutate each required field to prove failures for:

- missing or mismatched tone catalog SHA;
- `tone_control_status` other than `PASS`;
- CustomVoice non-neutral chunk without instruction evidence;
- full-ICL chunk containing instruction evidence;
- speed, temperature delta, pause, or pitch outside bounds;
- `adult.*` tone with non-adult ledger rating;
- action or role label appearing in `spoken_text`.

Update help tests to require `溫暖／開心／疑惑`, adult examples such as
`親密／挑逗／害羞`, the statement that actions are visible but not spoken,
and the statement that tone never silently adds breathing or other sounds.

- [ ] **Step 2: Run RED**

Run the four focused repo test files. Expected failures: v7 is unsupported and
help contains no tone guidance.

- [ ] **Step 3: Implement v7 validation and compatibility**

- Add v7 to schema allowlists in voice, render, and visual-judge consumers.
- Require the full tone contract only for v7; preserve v4-v6 behavior.
- Validate every voice chunk against the project-local dialogue ledger and its
  catalog SHA. Do not infer success from metadata alone: use
  `tone_control_status=PASS` for applied controls and retain
  `tone_evidence_status=HEURISTIC_PASS` as a bounded claim.
- Add a compact tone section to help and operator docs. Keep operator IDs
  optional and do not expose private paths or source text.

- [ ] **Step 4: Run focused and wider story-video suites**

Run all `tests/plugins/story_video` tests and `git diff --check`. Fix only
tone-related regressions; park unrelated findings.

- [ ] **Step 5: Commit Task 4**

```bash
git add plugins/story_video/tools.py plugins/story_video/render_modes.py \
  plugins/story_video/visual_judge.py plugins/story_video/guide.py \
  docs/story-video-operator-guide.md tests/plugins/story_video
git commit -m "feat(story-video): validate and document tone delivery"
```

---

### Task 5: Prove, review, integrate, and deploy the user-visible path

**Files:**
- Modify only when proof exposes a regression: files already listed in Tasks 1-4.
- Create local uncommitted smoke project under `/Users/simon/.hermes/story_videos/`.

**Interfaces:**
- Consumes: committed repo changes plus the installed local executor patch.
- Produces: focused/wider test evidence, independent code review, one current
  local audio/video smoke, merged `local/main`, exact `runtime/current` parity,
  gateway restart, and live help/status evidence.

- [ ] **Step 1: Run fresh verification**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/plugins/story_video -q
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m ruff check \
  plugins/story_video tests/plugins/story_video
git diff --check
```

Run the full local generator test file again. Record exact pass counts and
exit codes.

- [ ] **Step 2: Run one local tone-aware production smoke**

Build a private black-subtitle fixture with at least:

- one CustomVoice neutral line and one non-neutral tone line;
- one full-ICL neutral line and one bounded emotional line;
- one adult-explicit tone resolved from a user-supplied stage direction;
- repeated ellipsis proving no excessive silent gap.

Run compile, bind, local Qwen generation, pronunciation/alignment/prosody QC,
black-subtitle render, and final MP4 speech QC. Require a playable MP4, v7
manifest, correct speaker routing, all pronunciation gates PASS, all pauses
`<=0.45`, CustomVoice instruction evidence, and no clone instruction evidence.

- [ ] **Step 3: Request independent code review**

Review the full diff from base `5d4f21a7a` through feature HEAD against the
approved spec and this plan. Fix every Critical or Important finding with a
new failing test first, then rerun focused and wider verification.

- [ ] **Step 4: Publish through the governed local integration path**

Push the named branch to `origin`, open a fork-local PR targeting
`local/main`, wait for required CI, merge after review, then fast-forward the
root `local/main` checkout from `origin/local/main`. Do not push to upstream.

- [ ] **Step 5: Deploy exact accepted SHA and verify runtime**

Fast-forward `runtime/current` to the exact accepted `local/main` SHA, restart
the launchd-managed gateway, and verify branch/SHA parity plus a live
`/story-video help` and tone-aware production status call. Push the exact
runtime pointer only through the documented protected-branch cutover.

- [ ] **Step 6: Complete the durable goal**

Re-read every approved requirement, confirm current evidence for each one,
perform the final deep-fix checkpoint, then mark the durable goal complete.

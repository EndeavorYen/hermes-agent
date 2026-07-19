# Story Video Role And Emotion Subtitles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add visible character and emotion labels to black-background story-video subtitles without allowing those labels into TTS or voice QC.

**Architecture:** The repository render adapter keeps measured cue `text` as raw dialogue and adds optional `visual_text` composed from the cast binding and emotion. The existing shared Pillow renderer parses and draws `visual_text`, while narration-preservation checks continue to compare only raw `text`.

**Tech Stack:** Python 3.11, pytest, Pillow, ffmpeg/ffprobe, Hermes story-video plugin and shared renderer.

## Global Constraints

- Only `black_subtitle` mode changes.
- `text`, scene `narration`, TTS input, and voice QC input remain exact raw dialogue.
- `visual_text` is optional, render-only, and contains the exact raw dialogue.
- Narrator subtitles remain undecorated.
- No new dependency or generalized subtitle framework.

---

### Task 1: Repository render-input contract and help

**Files:**
- Modify: `tests/plugins/story_video/test_render_modes.py`
- Modify: `plugins/story_video/render_modes.py`
- Modify: `tests/plugins/story_video/test_guide.py`
- Modify: `plugins/story_video/guide.py`

**Interfaces:**
- Consumes: project-local `voice_cast_binding.json` and narration `voice_chunks`.
- Produces: measured cues with raw `text`, render-only `visual_text`, `emotion`, and existing timing/color fields.

- [ ] **Step 1: Write the failing adapter and help tests**

```python
assert character_cue["text"] == "出發吧！"
assert character_cue["visual_text"] == "小美（開心）\n「出發吧！」"
assert shot["narration"] == "故事開始。出發吧！"
assert narrator_cue["visual_text"] == narrator_cue["text"]
assert "角色與情緒標籤只顯示在字幕，不會念出來" in help_text
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `/Users/simon/.hermes/hermes-agent/.venv/bin/python -m pytest -q tests/plugins/story_video/test_render_modes.py tests/plugins/story_video/test_guide.py`

Expected: failures because cues have no `visual_text`/emotion and help lacks the copy.

- [ ] **Step 3: Implement the minimal adapter behavior**

```python
EMOTION_LABELS = {
    "wonder": "驚奇",
    "curious": "疑惑",
    "joy": "開心",
    "sadness": "難過",
    "fear": "害怕",
    "tension": "緊張",
    "surprise": "驚訝",
    "humor": "幽默",
    "warmth": "溫暖",
}

def _visual_subtitle_text(text, speaker_id, display_name, emotion):
    if speaker_id.casefold() in {"narrator", "旁白"}:
        return text
    suffix = f"（{EMOTION_LABELS[emotion]}）" if emotion in EMOTION_LABELS else ""
    return f"{display_name}{suffix}\n「{text}」"
```

Read display names from the optional project-local cast binding, preserve raw
`text` and scene narration, set `max_lines` to `3`, and add the approved help
sentence.

- [ ] **Step 4: Re-run the focused tests and confirm GREEN**

Run: `/Users/simon/.hermes/hermes-agent/.venv/bin/python -m pytest -q tests/plugins/story_video/test_render_modes.py tests/plugins/story_video/test_guide.py`

Expected: all selected tests pass.

### Task 2: Shared renderer visual-text support

**Files:**
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_render_story_video.py`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/render_story_video.py`

**Interfaces:**
- Consumes: optional cue `visual_text`; raw `text` remains required.
- Produces: `SubtitleCue.visual_text`; overlay and visual layout QC use it, narration coverage uses `SubtitleCue.text`.

- [ ] **Step 1: Write failing renderer tests**

```python
cue = render_input.scenes[0].shots[0].subtitle_cues[0]
assert cue.text == "出發吧！"
assert cue.visual_text == "小美（開心）\n「出發吧！」"
assert module._wrap_cjk(cue.visual_text, 22, 3)[0] == "小美（開心）"
```

Also assert that a `visual_text` which omits raw `text` is rejected.

- [ ] **Step 2: Run the renderer tests and confirm RED**

Run: `/Users/simon/.hermes/hermes-agent/.venv/bin/python -m pytest -q scripts/test_render_story_video.py`

Expected: failure because `SubtitleCue` has no `visual_text` and forced line breaks are collapsed.

- [ ] **Step 3: Implement the minimal renderer support**

```python
class SubtitleCue(NamedTuple):
    text: str
    start_sec: float
    end_sec: float
    sentence_count: int
    speaker_id: str = ""
    color: str = "#FFFFFF"
    visual_text: str = ""
```

Parse `visual_text` with fallback to `text`, require raw text containment, keep
forced newline boundaries in `_wrap_cjk`, and use `cue.visual_text or cue.text`
only in overlay/layout-QC calls.

- [ ] **Step 4: Re-run renderer tests and confirm GREEN**

Run: `/Users/simon/.hermes/hermes-agent/.venv/bin/python -m pytest -q scripts/test_render_story_video.py`

Expected: all renderer tests pass.

### Task 3: Regression, artifact proof, integration, and deployment

**Files:**
- Verify repository diff and generated local media only; do not commit generated artifacts.

**Interfaces:**
- Consumes: existing QC-passed multi-role project audio and manifests.
- Produces: a new black-background MP4 proof, merged integration SHA, and identical runtime SHA.

- [ ] **Step 1: Run focused and wider verification**

Run repository story-video tests, shared renderer tests, Ruff on changed Python
files, and `git diff --check`. Expected: zero failures/errors.

- [ ] **Step 2: Render a real artifact without regenerating audio**

Prepare a fresh local proof project from the existing QC-passed narration,
render it through the updated adapter and renderer, and verify MP4 H.264/AAC,
duration, black background, hard-subtitle coverage, unchanged audio hash, and
captured frames showing the expected labels/colors.

- [ ] **Step 3: Review, commit, push, and merge**

Commit only repository source/tests/docs, push the exact topic branch, open a
fork-local PR to `local/main`, require green CI, merge, and fast-forward the
local `local/main` checkout from `origin/local/main`.

- [ ] **Step 4: Deploy and prove runtime truth**

Fast-forward `runtime/current` to the identical `local/main` SHA, verify the
editable install and gateway import/PID, run a small runtime render-input smoke,
push the exact runtime pointer through the documented unlock/relock gate, and
read back branch protection.

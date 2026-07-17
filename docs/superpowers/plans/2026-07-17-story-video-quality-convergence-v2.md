# Story Video Quality Convergence v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make new story-video runs converge on engaging reviewed text, semantically distinct image sequences, distinct opening/ending art, and an auditable mixed music plan without increasing normal image candidate count.

**Architecture:** Add three focused plugin modules: deterministic editorial metrics, sequence-level artifact validation, and music planning/bed compilation. Existing v5/v6 and renderer contracts remain readable; new runs opt into `family-review-board-v2`, sequence rescue is bounded to one extra attempt per failed shot, and the existing renderer receives a project-local compiled music bed through its current background-music interface.

**Tech Stack:** Python 3.11+, pytest, Pillow, ffmpeg/ffprobe, JSON manifests, SHA-256, Hermes story-video plugin tools/hooks, OpenAI Codex image generation and vision QC.

## Global Constraints

- One precise image candidate per shot remains the default.
- Sequence rescue adds at most one candidate per defective shot and runs at most three shots in parallel.
- Story-video image generation and vision QC remain `openai-codex`; xAI/Grok remain forbidden.
- Existing v5, `family-review-board-v1`, and single-bed renderer artifacts remain compatible.
- New media, prompts, provider responses, user recordings, and runtime QC stay local and are not committed.
- Final-quality mode requires at least three compatible music cue variants with approved rights and provenance.

---

### Task 1: Deterministic Editorial Profile v2

**Files:**
- Create: `plugins/story_video/editorial_quality.py`
- Modify: `plugins/story_video/review_board.py`
- Modify: `plugins/story_video/tools.py`
- Test: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Consumes: `script.md`, `content_profile.json`, and `script_review_report.json`.
- Produces: `compute_read_aloud_metrics(script_text: str) -> dict[str, Any]` and `validate_editorial_profile_v2(project_dir: Path, content_profile: dict[str, Any], report: dict[str, Any]) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing tests for long-sentence ratio, missing evidence segment IDs, abstract-only segments, unresolved curiosity loops, insufficient delight beats, insufficient emotional turns, and repeated rhetorical templates.**

```python
def test_family_review_board_v2_blocks_weak_editorial_metrics(tmp_path):
    context = _write_v6_review_fixture(tmp_path, review_profile_id="family-review-board-v2")
    report = json.loads((context.project_dir / "script_review_report.json").read_text())
    report["editorial_metrics"] = {"concrete_scene_ratio": 0.5}
    (context.project_dir / "script_review_report.json").write_text(json.dumps(report))
    proof = validate_phase(context)
    assert "editorial_metrics.concrete_scene_ratio<0.80" in proof.violations
```

- [ ] **Step 2: Run the focused tests and confirm they fail because profile-v2 metrics are not validated.**

Run: `python3 -m pytest -q tests/plugins/story_video/test_tools.py -k 'editorial_profile_v2'`

Expected: FAIL with missing profile-v2 violations.

- [ ] **Step 3: Implement script segmentation, Traditional Chinese sentence measurement, repeated-template detection, evidence-ID validation, and profile-v2 thresholds in `editorial_quality.py`; call it only when `review_profile_id == "family-review-board-v2"`.**

```python
LONG_SENTENCE_CHARS = 46
MAX_LONG_SENTENCE_RATIO = 0.25

def compute_read_aloud_metrics(script_text: str) -> dict[str, Any]:
    segments = parse_script_segments(script_text)
    sentences = split_zh_sentences(segments)
    long_sentences = [row for row in sentences if row.char_count > LONG_SENTENCE_CHARS]
    return {
        "segment_ids": [row.segment_id for row in segments],
        "sentence_count": len(sentences),
        "long_sentence_ratio": len(long_sentences) / max(1, len(sentences)),
        "long_sentence_ids": [row.evidence_id for row in long_sentences],
    }
```

- [ ] **Step 4: Re-run focused tests, then all review-board and planning tests.**

Run: `python3 -m pytest -q tests/plugins/story_video/test_tools.py -k 'v6_review_board or editorial_profile_v2'`

Expected: PASS.

- [ ] **Step 5: Commit the independently testable editorial validator.**

```bash
git add plugins/story_video/editorial_quality.py plugins/story_video/review_board.py plugins/story_video/tools.py tests/plugins/story_video/test_tools.py
git commit -m "feat(story-video): enforce editorial profile v2"
```

### Task 2: Route New Family Scripts Through Profile v2

**Files:**
- Modify: `plugins/story_video/hooks.py`
- Modify: `tests/plugins/story_video/test_hooks.py`
- Modify local runtime skill after merge: `/Users/simon/.hermes/skills/creative/story-video-script-review-board/SKILL.md`
- Modify local runtime skill after merge: `/Users/simon/.hermes/skills/creative/taiwan-childrens-story-writing/SKILL.md`

**Interfaces:**
- Consumes: new-project planning context and the existing six reviewer IDs.
- Produces: planning instructions that require `review_profile_id=family-review-board-v2`, findings-only reviewers, and a complete `editorial_metrics` record.

- [ ] **Step 1: Add failing hook tests asserting the new profile ID, exact thresholds, evidence segment IDs, and two-round bound appear in family planning context while general and reserved profiles retain their routing policy.**
- [ ] **Step 2: Run `python3 -m pytest -q tests/plugins/story_video/test_hooks.py -k 'review_board or editorial'` and confirm failure.**
- [ ] **Step 3: Update planning instructions without merging the writer and reviewer skills; keep child writing conditional on family/child content.**
- [ ] **Step 4: Re-run hook tests and commit.**

```bash
git add plugins/story_video/hooks.py tests/plugins/story_video/test_hooks.py
git commit -m "feat(story-video): route family scripts through editorial v2"
```

### Task 3: Sequence-Level Artifact Quality

**Files:**
- Create: `plugins/story_video/sequence_quality.py`
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/tools.py`
- Test: `tests/plugins/story_video/test_visual_judge.py`
- Test: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Consumes: `scene_ledger.json`, `manifests/shot_candidate_manifest.json`, selected image files, and current shot contracts.
- Produces: `evaluate_selected_sequence(context: StoryVideoRunContext, ledger: dict[str, Any], manifest: dict[str, Any]) -> SequenceQualityReport` and `qc/sequence_quality_report.json`.

- [ ] **Step 1: Add failing fixtures for duplicate SHA-256 images, copied quality scores, stale artifact hashes, stale shot-contract hashes, inherited evidence, `final_qc_review_required`, and unresolved continuity fallback.**

```python
report = evaluate_selected_sequence(context, ledger, manifest)
assert report.status == "FAIL"
assert report.repair_shot_ids == ("S07", "S12")
assert "duplicate_artifact_sha256" in report.violations["S07"]
```

- [ ] **Step 2: Run `python3 -m pytest -q tests/plugins/story_video/test_visual_judge.py -k sequence_quality` and confirm failure.**
- [ ] **Step 3: Implement path containment, SHA-256 uniqueness, assessment provenance binding, shot-contract binding, score threshold checks, and stable report serialization.**
- [ ] **Step 4: Make `_prepare_render()` write the report and refuse render input when status is FAIL; make render phase validation require the report and exact selected-shot counts.**
- [ ] **Step 5: Re-run sequence tests plus render validation tests and commit.**

```bash
git add plugins/story_video/sequence_quality.py plugins/story_video/visual_judge.py plugins/story_video/tools.py tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video/test_tools.py
git commit -m "feat(story-video): gate render on sequence quality"
```

### Task 4: Bounded Sequence Rescue

**Files:**
- Modify: `plugins/story_video/batch_policy.py`
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/hooks.py`
- Test: `tests/plugins/story_video/test_visual_judge.py`
- Test: `tests/plugins/story_video/test_hooks.py`

**Interfaces:**
- Consumes: `SequenceQualityReport.repair_shot_ids` and per-shot attempt history.
- Produces: one `sequence_rescue` reservation per defective shot, a maximum three-shot generation wave, and one stable terminal review state after rescue exhaustion.

- [ ] **Step 1: Write failing tests proving only defective shots enter rescue, each gets one rescue attempt, normal shot budgets do not reset, and repeated sequence failure returns an identical review signature without another generation request.**
- [ ] **Step 2: Run the focused rescue tests and confirm failure.**
- [ ] **Step 3: Add `reserve_sequence_rescue(shot_id: str) -> bool`, persist rescue attempt evidence, and compile a defect-specific prompt while preserving the factual shot contract.**
- [ ] **Step 4: Update auto-continuation routing so a sequence-repair result continues batch once and a repeated exhausted signature stops cleanly at review-required.**
- [ ] **Step 5: Re-run visual-judge, hooks, and batch-policy tests and commit.**

```bash
git add plugins/story_video/batch_policy.py plugins/story_video/visual_judge.py plugins/story_video/hooks.py tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video/test_hooks.py
git commit -m "feat(story-video): add bounded sequence rescue"
```

### Task 5: Distinct Opening and Ending Art

**Files:**
- Modify: `plugins/story_video/release_art.py`
- Modify: `plugins/story_video/visual_judge.py`
- Test: `tests/plugins/story_video/test_release_art.py`
- Test: `tests/plugins/story_video/test_visual_judge.py`

**Interfaces:**
- Consumes: topic, opening mystery, knowledge payoff, ending echo, and two current OpenAI Codex source images.
- Produces: `story_video_release_art_manifest_v2` with `opening_source` and `ending_source`, separate prompt hashes, artifact hashes, and locally composed opening, thumbnail, and ending cards.

- [ ] **Step 1: Write failing tests that reject one shared source hash, missing ending prompt evidence, opening art that depicts only the final payoff, and ending art that merely repeats the opening mystery.**
- [ ] **Step 2: Run release-art tests and confirm failure.**
- [ ] **Step 3: Split prompt compilation into `compile_opening_art_prompt()` and `compile_ending_art_prompt()`; request exactly two source images and compose cards with local typography.**
- [ ] **Step 4: Validate distinct source hashes and purpose bindings before render preparation.**
- [ ] **Step 5: Re-run release-art tests and commit.**

```bash
git add plugins/story_video/release_art.py plugins/story_video/visual_judge.py tests/plugins/story_video/test_release_art.py tests/plugins/story_video/test_visual_judge.py
git commit -m "feat(story-video): separate opening and ending art"
```

### Task 6: Music Direction, Cue Selection, and Bed Compilation

**Files:**
- Create: `plugins/story_video/music.py`
- Create: `scripts/build_story_video_music_library.py`
- Create: `tests/plugins/story_video/test_music.py`
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `tests/plugins/story_video/test_visual_judge.py`

**Interfaces:**
- Consumes: v1/v2 music library, engagement profile, production type, story beat timings, approved track or section metadata, and final timeline duration.
- Produces: `select_music_plan(...) -> MusicPlan`, `compile_music_bed(plan: MusicPlan, output: Path) -> dict[str, Any]`, `manifests/music_plan.json`, and a project-local 48 kHz stereo WAV passed through existing `background_music`.

- [ ] **Step 1: Add failing tests for compatibility scoring, excluded styles, insufficient cue variants, missing rights, missing source ranges, cue gaps over two seconds, timeline overflow, and deterministic selection.**

```python
plan = select_music_plan(library, story_profile, timeline)
assert [cue.role for cue in plan.cues] == ["opening", "body", "turn", "resolution"]
assert plan.compatibility_score >= MIN_COMPATIBILITY_SCORE
```

- [ ] **Step 2: Run `python3 -m pytest -q tests/plugins/story_video/test_music.py` and confirm failure.**
- [ ] **Step 3: Implement v1 migration, v2 validation, positive and negative compatibility scoring, cue placement, and stable tie-breaking.**
- [ ] **Step 4: Implement ffmpeg command construction that trims/loops approved variants, applies short crossfades, creates an exact-duration 48 kHz stereo bed, and records every source range.**
- [ ] **Step 5: Integrate music planning into `_prepare_render()`, pass the compiled bed through existing renderer input, and require music-plan plus renderer background-music QC in final-quality mode.**
- [ ] **Step 6: Re-run music, render, and phase-validation tests and commit.**

```bash
git add plugins/story_video/music.py scripts/build_story_video_music_library.py tests/plugins/story_video/test_music.py plugins/story_video/visual_judge.py plugins/story_video/tools.py tests/plugins/story_video/test_visual_judge.py
git commit -m "feat(story-video): direct and validate story music"
```

### Task 7: Runtime Skills and Local Music Library

**Files:**
- Modify local runtime skill: `/Users/simon/.hermes/skills/creative/story-video-script-review-board/SKILL.md`
- Modify local runtime skill: `/Users/simon/.hermes/skills/creative/taiwan-childrens-story-writing/SKILL.md`
- Modify local runtime skill: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/SKILL.md`
- Modify local runtime config: `/Users/simon/.hermes/story_video_music_library.json`

**Interfaces:**
- Consumes: versioned plugin contracts and the existing locally synthesized 424-second source with four provenance-recorded sections.
- Produces: aligned skill instructions and a v2 music library containing at least four compatible cue variants with exact source ranges.

- [ ] **Step 1: Back up each local runtime file and record its SHA-256.**
- [ ] **Step 2: Update only the relevant skill sections with the exact profile-v2, sequence-rescue, distinct-release-art, and final-quality music contracts.**
- [ ] **Step 3: Run `scripts/build_story_video_music_library.py` against the existing generation manifest and source WAV; validate the output schema, ranges, rights, duration, and cue-variant count.**
- [ ] **Step 4: Run each skill's local contract test and the music-library validator.**

Expected: all local skill tests PASS and library status is READY.

### Task 8: Verification, Live Artifact, Review, and Deployment

**Files:**
- No committed private media.
- Live outputs: `/Users/simon/.hermes/story_videos/<new-live-project>/`

**Interfaces:**
- Consumes: the accepted branch, local runtime skills, OpenAI Codex provider, local Qwen narration, and the approved local music library.
- Produces: a short complete MP4 and artifact-level proof for all new gates.

- [ ] **Step 1: Run focused tests, all story-video tests, Ruff, and `git diff --check`.**

```bash
python3 -m pytest -q tests/plugins/story_video
python3 -m ruff check plugins/story_video tests/plugins/story_video scripts/build_story_video_music_library.py
git diff --check
```

- [ ] **Step 2: Run a short family educational live project with one candidate per shot and final-quality music enabled.**
- [ ] **Step 3: Verify the live project has profile-v2 reviewer evidence, unique selected image hashes, zero unresolved fallback shots, two distinct release-art source hashes, at least three music cue variants, a mixed MP4, and PASS sequence/music/render reports.**
- [ ] **Step 4: Review the contact sheet, opening, ending, and representative video frames visually; inspect the mixed audio metrics and listen to a sample when possible.**
- [ ] **Step 5: Push the named branch, open an origin-only PR to `local/main`, wait for all required CI checks, and merge only when green.**
- [ ] **Step 6: Fast-forward `local/main`, deploy the exact accepted SHA to `runtime/current`, restart the supervised gateway, repeat the smallest runtime smoke, push and re-lock `origin/runtime/current`, then clean the merged topic worktree and branch.**

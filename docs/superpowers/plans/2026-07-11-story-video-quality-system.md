# Story Video Quality System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generic one-still-per-scene story-video production with a quality-first shot system that strengthens scripts, compiles specific prompts, ranks OpenAI candidates with OpenAI vision, renders narration-aligned shot changes, and proves the live workflow.

**Architecture:** Keep `plugins/story_video` as the fail-closed runtime control layer and the installed `story-video-production-pipeline` as the production playbook. Add pure shot-quality contracts to the plugin, a vision-backed internal quality tool, a dedicated script-director skill, candidate-aware source-art generation, and v2 shot rendering while preserving the four short operator calls.

**Tech Stack:** Python 3.11+, pytest, Hermes plugin hooks/tools, `PluginLlm.complete_structured`, OpenAI Codex provider, Pillow, ffmpeg/ffprobe, JSON manifests, Markdown skills.

## Global Constraints

- Story-video LLM, source-art, and visual-review provider must be OpenAI/openai-codex; xAI/Grok and generic video generation fail closed.
- Five-minute quality-first productions target 40-60 shots and an 80/100 selection threshold.
- Key evidence shots receive three candidates, normal action shots two, low-risk transitions one.
- `只規劃` and `先不要產圖或產影片` prohibit image, audio, and video generation.
- Operator syntax remains `故事影片：<主題>｜<長度>｜<風格>`, `繼續`, `出片`, and `修正：<問題>`.
- Final motion is deterministic subpixel center zoom with no default pan.
- Tests must fail for the intended missing behavior before production edits.

---

### Task 1: Baseline And Quality Contract

**Files:**
- Create: `tests/plugins/story_video/test_quality.py`
- Create: `plugins/story_video/quality.py`
- Snapshot: `/private/tmp/story-video-production-pipeline-before-quality/`
- Record: `/private/tmp/story-video-quality-baseline/`

**Interfaces:**
- Consumes: `scene_ledger.json`, production type, duration text.
- Produces: `ShotContract`, `LedgerQualityReport`, `validate_quality_ledger()`, `compile_shot_prompt()`, `candidate_budget_for_shot()`, and `rank_candidate_assessments()`.

- [ ] **Step 1: Snapshot the installed skill and run one planning-only baseline**

Run a fresh 30-second science prompt before edits. Record whether the output contains nested shots, a script quality report, explicit close-ups, and candidate budgets. Expected baseline: at least one required quality element is missing.

- [ ] **Step 2: Write failing pure-contract tests**

Start with this failing contract test:

```python
from plugins.story_video.quality import validate_quality_ledger


def test_quality_ledger_requires_nested_shots_and_visual_evidence():
    report = validate_quality_ledger(
        {
            "production_type": "science_explainer",
            "target_duration_sec": 300,
            "scenes": [{"scene_id": "S00", "viewer_takeaway": "直立腿提高移動效率"}],
        }
    )

    assert report.ok is False
    assert "S00.shots" in report.violations
```

Add focused tests named
`test_five_minute_quality_profile_requires_40_to_60_shots`,
`test_science_profile_requires_close_up_evidence_mix`,
`test_candidate_budget_uses_risk_class`,
`test_prompt_compiler_puts_takeaway_subject_action_and_evidence_first`,
`test_prompt_compiler_uses_comparison_recipe_without_global_conflict`, and
`test_ranking_blocks_when_every_candidate_scores_below_80`.

- [ ] **Step 3: Run tests and verify RED**

Run: `pytest -q tests/plugins/story_video/test_quality.py`

Expected: import failure for `plugins.story_video.quality` or missing contract functions.

- [ ] **Step 4: Implement the minimal pure quality module**

Implement typed validation errors, production profiles, required shot fields,
shot-density/scale-mix checks, positive prompt recipes, candidate budgets, hard
blockers, weighted score normalization, threshold selection, and bounded repair
metadata. Keep provider/network work out of this module.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest -q tests/plugins/story_video/test_quality.py`

Commit: `feat: add story video shot quality contracts`

---

### Task 2: Planning And Phase Proof Hardening

**Files:**
- Modify: `plugins/story_video/hooks.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `tests/plugins/story_video/test_hooks.py`
- Modify: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Consumes: pure validators from Task 1.
- Produces: planning/keyframe/batch/render proof that rejects shallow or stale artifacts.

- [ ] **Step 1: Add failing phase-proof tests**

Cover planning without `script_quality_report.json`, scenes without `shots`,
insufficient shot density, keyframes without prompt/vision score evidence, batch
with missing selected shots, duplicate selected files, and render QC without
selected-shot density evidence.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `pytest -q tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_hooks.py`

Expected: current presence-only planning/keyframe/batch validators pass invalid fixtures.

- [ ] **Step 3: Strengthen runtime instructions and validators**

Planning instructions require `script_quality_report.json` and nested shots.
Remove the blanket prohibition on loading the two story-video skills while
retaining the ban on unrelated project/skill exploration. Validate exact
selected-shot counts and OpenAI prompt/judge provenance. Keep planning-only
media prohibition explicit.

- [ ] **Step 4: Run focused and plugin suites**

Run: `pytest -q tests/plugins/story_video`

- [ ] **Step 5: Commit**

Commit: `feat: require shot quality evidence in story video phases`

---

### Task 3: OpenAI Vision Candidate Judge Tool

**Files:**
- Create: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/schemas.py`
- Modify: `plugins/story_video/__init__.py`
- Modify: `plugins/story_video/tools.py`
- Create: `tests/plugins/story_video/test_visual_judge.py`
- Modify runtime config: `/Users/simon/.hermes/config.yaml`

**Interfaces:**
- Consumes: active `StoryVideoRunContext`, a shot contract, 1-3 local candidate images, `ctx.llm`.
- Produces: `manifests/shot_candidate_manifest.json`, OpenAI vision scores, one selected current asset or a bounded blocked result.

- [ ] **Step 1: Write failing judge tests with a fake PluginLlm**

Cover explicit `provider=openai-codex`, image blocks for every candidate,
schema-validated dimensions, hard blocker handling, threshold blocking, selected
file promotion, three-round exhaustion, atomic manifest writes, and rejection of
non-OpenAI generation/judge provenance.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/plugins/story_video/test_visual_judge.py`

- [ ] **Step 3: Implement the judge and internal tool**

Register `story_video_quality_control` with actions `compile_prompt`,
`judge_candidates`, and `status`. Bind `ctx.llm` during plugin registration.
Use one structured OpenAI vision call per shot, include the shot contract and all
candidate images, validate JSON, apply pure ranking, copy only the selected file
to `images/`, and preserve candidate/rejection evidence outside that directory.

- [ ] **Step 4: Add fail-closed runtime trust configuration**

Configure `plugins.entries.story-video.llm.allow_provider_override=true` with
`allowed_providers: [openai-codex]`. Do not allow an xAI/Grok fallback.

- [ ] **Step 5: Run tests and commit**

Run: `pytest -q tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video`

Commit: `feat: add OpenAI vision selection for story video shots`

---

### Task 4: Script Director Skill

**Files:**
- Create: `/Users/simon/.hermes/skills/creative/story-video-script-director/SKILL.md`
- Create: `/Users/simon/.hermes/skills/creative/story-video-script-director/references/script-quality-contract.md`
- Create: `/Users/simon/.hermes/skills/creative/story-video-script-director/evals/evals.json`
- Create: `/Users/simon/.hermes/skills/creative/story-video-script-director/scripts/test_skill_contract.py`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/SKILL.md`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_validate_story_video_checklist.py`

**Interfaces:**
- Consumes: project contract, research/source notes, duration, production type.
- Produces: `script.md`, `storyboard.md`, nested-shot `scene_ledger.json`, and `script_quality_report.json`.

- [ ] **Step 1: Write failing skill-contract tests and eval prompts**

Tests require narrative roles, viewer takeaways, visual evidence, visualizable
actions, confidence language, transition logic, nested shots, profile selection,
and no media generation for planning-only prompts.

- [ ] **Step 2: Run RED against the existing installed skill**

Run: `pytest -q /Users/simon/.hermes/skills/creative/story-video-script-director/scripts/test_skill_contract.py`

Expected: missing skill/artifacts.

- [ ] **Step 3: Write and verify the script-director skill**

Keep the main `SKILL.md` under 500 lines, put the detailed JSON contract in the
reference file, and make the description trigger on story-video scripts,
documentary narration, generic visuals, weak hooks, and unvisualizable prose.

- [ ] **Step 4: Upgrade the pipeline skill**

Update the golden path, shot-first contract, candidate lifecycle, render v2,
repair taxonomy, and verification checklist. Cross-reference the script director
as required for new scripts instead of duplicating its full instructions.

- [ ] **Step 5: Run skill tests and record local deployment evidence**

Run both installed-skill test suites and `wc -l`/frontmatter checks.

---

### Task 5: Candidate-Aware Source-Art Generator

**Files:**
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/generate_story_video_scene_art.py`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_story_video_scene_art.py`

**Interfaces:**
- Consumes: nested shots and compiled prompt contracts.
- Produces: candidate files and manifest rows; selection occurs only from passing OpenAI vision assessments.

- [ ] **Step 1: Add failing candidate lifecycle tests**

Cover shot iteration, risk-based candidate counts, candidate directories,
prompt provenance, no first-success auto-selection, resume behavior, failed
assessment blocking, and promotion of exactly one passing candidate per shot.

- [ ] **Step 2: Run RED**

Run: `pytest -q /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_story_video_scene_art.py`

- [ ] **Step 3: Implement candidate generation and selection ingestion**

Generate into `images_candidates/<shot_id>/`, write one prompt per shot, record
OpenAI ids/providers/models, and ingest judge results from the canonical shot
candidate manifest. Promotion fails if a shot lacks a threshold-passing current
selection.

- [ ] **Step 4: Run tests and local dry-run smoke**

Use fake providers for deterministic verification; do not spend live quota yet.

---

### Task 6: Shot-Level Narration-Aligned Renderer

**Files:**
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/render_story_video.py`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_render_story_video.py`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/audit_story_video_render_contract.py`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_audit_story_video_render_contract.py`

**Interfaces:**
- Consumes: `story_video_render_input_v2` with scenes, narration audio, and selected shots.
- Produces: shot-changing scene segments, hard-burned subtitles, shot-aware render manifest and QC.

- [ ] **Step 1: Add failing v2 renderer tests**

Cover multiple selected shots per scene, narration-text duration weighting,
minimum/maximum shot duration, stable order, rejection of duplicate or unselected
assets, subpixel affine zoom, no pan, selected-shot counts, and v1 compatibility.

- [ ] **Step 2: Run RED**

Run: `pytest -q /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_render_story_video.py /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_audit_story_video_render_contract.py`

- [ ] **Step 3: Implement v2 planning and affine rendering**

Allocate scene speech duration across shots from narration spans/weights, attach
the post-speech hold only to the final shot, switch stills at shot boundaries,
render every frame from the normalized original through a floating-point affine
transform, and preserve the existing CJK subtitle/audio contract.

- [ ] **Step 4: Run deterministic dry-run and tiny encoded-video smoke**

Verify ffprobe duration, nonblank frames, stable frame-difference curve, subtitle
visibility, and no unexpected silence.

---

### Task 7: Integrated Regression And Runtime Deployment

**Files:**
- Modify runtime worktree copies under `.worktrees/hermes-v2026.7.7.2-runtime/plugins/story_video/`
- Update runtime state/config only as required for the OpenAI plugin LLM trust gate.

**Interfaces:**
- Consumes: committed repo changes and installed local skills.
- Produces: running gateway with the new plugin and skill behavior.

- [ ] **Step 1: Run all focused and wider tests**

Run plugin tests, story-video skill script tests, relevant plugin LLM tests,
`py_compile`, `git diff --check`, and repo status inspection.

- [ ] **Step 2: Deploy exact committed plugin files to runtime worktree**

Use the established runtime worktree, verify checksums, and preserve unrelated
runtime changes.

- [ ] **Step 3: Restart and verify the launchd gateway**

Confirm launchd state, fresh PID, active code path, and absence of startup errors.

- [ ] **Step 4: Run a planning-only live smoke**

Use a fresh science prompt and prove `script_quality_report.json`, nested shots,
shot density/profile evidence, no generated media, correct next call, and planning
phase PASS.

---

### Task 8: OpenAI Source-Art Live Smoke And Release Gate

**Files:**
- Create local smoke project under `/Users/simon/.hermes/story_videos/`
- Create local provider, prompt, candidate, vision-score, and quality reports.

**Interfaces:**
- Consumes: one validated close-up evidence shot from the planning smoke.
- Produces: 2-3 OpenAI candidates, OpenAI vision ranking, one selected source image, and live provider audit evidence.

- [ ] **Step 1: Generate the bounded live candidate set**

Generate only one high-value close-up/evidence shot, with explicit
`provider=openai-codex`; do not render or publish a full video.

- [ ] **Step 2: Run OpenAI vision selection and inspect the artifact**

Verify prompt adherence, focal clarity, evidence specificity, professional
quality, anatomy/science, and continuity dimensions. Confirm the selected score
is at least 80 and no hard blocker remains.

- [ ] **Step 3: Run final release gate**

Re-run all tests, inspect provider audit for xAI/Grok events, run `git diff --check`,
confirm gateway health, and report passed checks separately from residual limits.

- [ ] **Step 4: Commit final repo changes and mark deployment complete**

Commit: `feat: ship quality-first shot-driven story videos`

# Story Video Audience Engagement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make story-video visuals consistently audience-appropriate, narratively active, evidence-honest, and self-repairing across subjects without increasing the default one-candidate image budget.

**Architecture:** Add a topic-neutral engagement contract beside the existing shot-quality contract. Planning records audience, engagement role, decisive story moment, and visual truth mode; prompt compilation turns those fields into concrete visual direction; OpenAI vision QC scores the resulting artifact and routes specific failures to bounded semantic repair strategies.

**Tech Stack:** Python 3, pytest, JSON scene ledgers, Hermes plugin hooks/tools, Markdown runtime skills, OpenAI image generation and vision review.

## Global Constraints

- The feature must be topic-neutral; no dinosaur-, child-, chase-, dust-, or spectacle-specific defaults.
- Existing v2 ledgers remain valid; the stricter fields apply when `quality_contract_version >= 3` or an engagement profile is present.
- Source generation and visual judging remain OpenAI/openai-codex only.
- Generate one candidate per shot; regenerate only a shot that fails artifact QC.
- Preserve evidence, inference, reconstruction, process, and comparison as distinct visual truth modes.
- Intentional calm shots may pass when they have a focal hierarchy and `calm_reason`.
- Do not silently turn uncertain claims into dramatic certainty.

---

### Task 1: Engagement Contract

**Files:**
- Create: `plugins/story_video/engagement.py`
- Test: `tests/plugins/story_video/test_engagement.py`

**Interfaces:**
- Produces: `normalize_audience_profile(ledger) -> dict[str, str]`
- Produces: `normalize_engagement_profile(ledger) -> dict[str, Any]`
- Produces: `compile_engagement_directives(ledger, shot) -> tuple[str, ...]`
- Produces: `validate_engagement_ledger(ledger) -> EngagementReport`

- [ ] **Step 1: Write failing profile and prompt tests**

```python
def test_default_profile_is_general_not_child_specific():
    profile = normalize_audience_profile({})
    assert profile["age_band"] == "general"

def test_explicit_young_explorer_compiles_without_topic_cliches():
    directives = " ".join(compile_engagement_directives(ledger, shot))
    assert "early_childhood" in directives
    assert "decisive visible instant" in directives
    assert "chase" not in directives.lower()
```

- [ ] **Step 2: Run the focused tests and confirm import failure**

Run: `pytest -q tests/plugins/story_video/test_engagement.py`

Expected: FAIL because `plugins.story_video.engagement` does not exist.

- [ ] **Step 3: Implement normalized profiles, truth modes, directives, and sequence validation**

Use explicit enums for `engagement_role`, `composition_energy`, and `visual_truth_mode`. Require the v3 shot fields, reject a `breathe` shot without `calm_reason`, reject three repeated engagement roles or energies without an intentional reason, and flag `mixed_evidence_reconstruction` when a shot claims both direct evidence and reconstruction without a bridge.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/plugins/story_video/test_engagement.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/story_video/engagement.py tests/plugins/story_video/test_engagement.py
git commit -m "feat(story-video): add audience engagement contract"
```

### Task 2: Prompt And Planning Gates

**Files:**
- Modify: `plugins/story_video/quality.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `plugins/story_video/hooks.py`
- Test: `tests/plugins/story_video/test_quality.py`
- Test: `tests/plugins/story_video/test_tools.py`
- Test: `tests/plugins/story_video/test_hooks.py`

**Interfaces:**
- Consumes: `compile_engagement_directives`, `validate_engagement_ledger`
- Produces: v3 prompt text and planning proof while preserving v2 compatibility

- [ ] **Step 1: Add failing tests for prompt ordering and v3 planning enforcement**

```python
def test_prompt_compiles_audience_story_moment_and_truth_before_style():
    prompt = compile_shot_prompt(ledger=ledger, scene=scene, shot=shot)
    assert prompt.index("Audience contract") < prompt.index("Visual style")
    assert "Visual truth mode: reconstruction" in prompt

def test_planning_v3_rejects_missing_engagement_fields(tmp_path):
    proof = validate_planning_fixture(tmp_path, quality_contract_version=3)
    assert "S00_SH00.story_moment" in proof.violations
```

- [ ] **Step 2: Run targeted tests and confirm expected failures**

Run: `pytest -q tests/plugins/story_video/test_quality.py tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_hooks.py`

Expected: FAIL on missing engagement prompt/gate behavior.

- [ ] **Step 3: Compile engagement directives and enforce v3 in planning**

Call the engagement validator from `validate_quality_ledger`, add the audience/engagement/truth fields to planning instructions, and raise the new planning report contract to version 3 only for newly generated plans.

- [ ] **Step 4: Run targeted tests**

Run: `pytest -q tests/plugins/story_video/test_quality.py tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_hooks.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/story_video/quality.py plugins/story_video/tools.py plugins/story_video/hooks.py tests/plugins/story_video/test_quality.py tests/plugins/story_video/test_tools.py tests/plugins/story_video/test_hooks.py
git commit -m "feat(story-video): enforce engagement-aware planning"
```

### Task 3: Artifact QC And Semantic Repair

**Files:**
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/repair_planner.py`
- Modify: `plugins/story_video/schemas.py`
- Test: `tests/plugins/story_video/test_visual_judge.py`
- Test: `tests/plugins/story_video/test_repair_planner.py`

**Interfaces:**
- Produces: dimensions `narrative_engagement` and `story_moment_clarity`
- Produces: blockers `static_catalog`, `missing_story_moment`, `flat_composition`, `audience_mismatch`, `sensationalized_claim`, and `mixed_evidence_reconstruction`
- Produces: repair strategies `story_reframe`, `audience_reframe`, and `truth_reframe`

- [ ] **Step 1: Add failing QC schema and strategy tests**

```python
def test_static_catalog_routes_to_story_reframe():
    plan = plan_repair([failed_attempt("static_catalog")])
    assert plan.strategy == "story_reframe"

def test_truth_failure_routes_to_truth_reframe():
    plan = plan_repair([failed_attempt("sensationalized_claim")])
    assert plan.strategy == "truth_reframe"
```

- [ ] **Step 2: Run targeted tests and confirm failures**

Run: `pytest -q tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video/test_repair_planner.py`

Expected: FAIL because the dimensions, blockers, and strategies are absent.

- [ ] **Step 3: Implement scoring and bounded semantic repairs**

Rebalance quality weights to 100, make calm shots judgeable by declared intent, and have each strategy alter the observable action/composition/truth contract rather than append aesthetic adjectives.

- [ ] **Step 4: Run targeted tests**

Run: `pytest -q tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video/test_repair_planner.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/story_video/visual_judge.py plugins/story_video/repair_planner.py plugins/story_video/schemas.py tests/plugins/story_video/test_visual_judge.py tests/plugins/story_video/test_repair_planner.py
git commit -m "feat(story-video): repair dull or misleading visuals"
```

### Task 4: General Skills And Current Project Migration

**Files:**
- Modify: `/Users/simon/.hermes/skills/creative/story-video-script-director/SKILL.md`
- Create: `/Users/simon/.hermes/skills/creative/story-video-script-director/references/audience-engagement-contract.md`
- Modify: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/SKILL.md`
- Modify: `/Users/simon/.hermes/story_videos/story-video-2013c27dc5-826b73ee/scene_ledger.json`

**Interfaces:**
- Consumes: the v3 machine contract implemented in Tasks 1-3
- Produces: reusable authoring guidance and an age-five `young_explorer` migration without regenerating passing assets blindly

- [ ] **Step 1: Record baseline pressure failures**

Run representative planning prompts for science, history, cooking, business, and calm education against the pre-change skill and record whether the plan omits audience profile, story moment, truth mode, or calm reason.

- [ ] **Step 2: Update the two runtime skills and add the reference matrix**

The reference must define general topic adapters, anti-sensationalism rules, calm-shot exceptions, and evidence/reconstruction sequencing. The main skill stays concise and points to the reference.

- [ ] **Step 3: Validate skill text and JSON migration**

Run: `python -m json.tool /Users/simon/.hermes/story_videos/story-video-2013c27dc5-826b73ee/scene_ledger.json >/dev/null`

Expected: exit 0. Also scan the skill files for required fields and forbidden hardcoded topic defaults.

- [ ] **Step 4: Audit selected images and mark only failed shots for regeneration**

Preserve selected assets that pass the new engagement gate. Clear selection only for images with concrete `static_catalog`, `missing_story_moment`, `audience_mismatch`, or truth-mode failures, retaining their attempt history for the next adaptive repair.

### Task 5: Verification, Live A/B, Integration, And Deployment

**Files:**
- Modify as required by review findings only
- Runtime evidence remains under the current story-video project and is not committed

**Interfaces:**
- Produces: test evidence, two OpenAI live image/judge comparisons, exact deployed SHA, and restarted gateway proof

- [ ] **Step 1: Run focused and full plugin tests**

Run: `pytest -q tests/plugins/story_video`

Expected: PASS.

- [ ] **Step 2: Run two OpenAI live A/B shots**

Use one evidence/process shot and one reconstructed/action shot. Generate one candidate each, judge both with the new dimensions, and regenerate only a failing shot.

- [ ] **Step 3: Review diff and privacy hygiene**

Run: `git diff --check`, inspect staged paths, and confirm no generated media, private prompts, provider logs, or project artifacts are committed.

- [ ] **Step 4: Integrate according to branch governance**

Open an origin-only PR from `feat/story-video/audience-engagement` to `local/main`, review checks, merge when green, and fast-forward `runtime/current` to the exact accepted SHA.

- [ ] **Step 5: Restart and smoke-test the gateway**

Restart the Hermes gateway from `runtime/current`, confirm process health, and run a narrow story-video prompt/compile smoke proving the live runtime emits audience, story-moment, and truth-mode directives.


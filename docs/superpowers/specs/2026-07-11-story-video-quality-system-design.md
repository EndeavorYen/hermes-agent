# Story Video Quality System Design

## Objective

Upgrade Hermes story-video production from one generic still per narration scene
to a quality-first, shot-driven production system. A five-minute video should use
roughly 40-60 purposeful shots, OpenAI source art, vision-backed candidate
selection, narration-aligned cuts, hard-burned Traditional Chinese subtitles,
and deterministic motion.

The operator interface remains short:

```text
故事影片：<主題>｜<長度>｜<風格>
繼續
出片
修正：<問題>
```

`只規劃` and `先不要產圖或產影片` remain hard media-generation stops.

## Product Principles

1. A scene is a narrative unit; a shot is a visual unit. One scene may contain
   two to four shots.
2. Every shot has one viewer takeaway, one focal subject, and one observable
   action or evidence detail.
3. Source art must support the spoken claim instead of merely matching the
   topic or period.
4. A successful provider call is not an accepted image. Selection requires
   artifact evidence and a passing score.
5. Failed shots are repaired at the earliest faulty layer: text, shot plan,
   prompt, candidate, or render.
6. The system completes selection and repair automatically until the shot
   passes or its bounded quality budget is exhausted.
7. Only current selected artifacts enter the renderer or delivery.

## Architecture

```text
short operator call
  -> script director
  -> narrative beats
  -> shot planner
  -> prompt compiler
  -> OpenAI candidate generation
  -> visual quality judge
  -> targeted repair loop
  -> selected-shot manifest
  -> narration-aligned renderer
  -> artifact QC and clean delivery
```

### Script Director

The script director creates or validates these fields per narrative beat:

- `narrative_role`: hook, context, claim, mechanism, evidence, contrast,
  turn, payoff, recap, or close.
- `viewer_takeaway`: the one idea the viewer should retain.
- `spoken_text`: final narration written for speech.
- `visual_evidence`: concrete objects, actions, specimens, processes, or
  comparisons that support the narration.
- `visualizable_action`: what visibly happens on screen.
- `claim_confidence`: established, supported inference, or uncertain.
- `transition`: why the next beat follows.

The script gate rejects empty visual evidence, repeated filler, unsupported
certainty, and abstract beats that provide no visual proof strategy.

### Shot Planner

The existing `scene_ledger.json` remains the compatibility surface. Each scene
adds a non-empty `shots` array. Every shot includes:

- `shot_id` and narration span;
- `viewer_takeaway` and `narrative_role`;
- `subject`, `action`, and `evidence_detail`;
- `shot_scale`: establishing, wide, medium, close_up, macro, or insert;
- `camera_angle`, `focal_point`, and foreground/background hierarchy;
- `continuity_anchors`, `subtitle_safe_area`, and `acceptance_criteria`;
- `candidate_budget`, `quality_threshold`, and `repair_strategy`.

Quality-first five-minute productions target 40-60 shots. Science/documentary
profiles target approximately 20% context shots, 30% process/action shots, 30%
close-up or macro evidence shots, and 20% comparison/diagram/transition shots.
No more than two consecutive shots use the same scale unless the ledger records
an intentional reason.

Other production types use automatic profiles. Children's stories emphasize
character action and emotion; documentaries emphasize people, process, place,
and evidence; explainers emphasize mechanism and comparison.

### Prompt Compiler

Prompts are compiled per shot in this order:

1. exact visual purpose and spoken claim;
2. primary subject and observable action;
3. evidence detail that must be readable;
4. shot scale, camera angle, focal point, and subject occupancy;
5. subordinate setting and period context;
6. style, material, light, anatomy, and scientific constraints;
7. continuity anchors and subtitle-safe composition;
8. shot-specific exclusions.

Global exclusions cannot contradict a shot type. Comparison shots, diagram
backgrounds, close-ups, and single-camera natural scenes use separate recipes.

### Candidate Generation And Selection

Candidate budgets are based on risk:

- hero, key evidence, character, organism, or anatomy close-up: 3;
- normal action or narrative shot: 2;
- low-risk transition/background: 1.

All story-video source-art calls pass `provider=openai-codex`. Candidates are
stored outside the selected image directory and never become selected merely
because generation succeeded.

Hard blockers include wrong content, scientific contradiction, malformed
anatomy, generated text/watermark, continuity failure, unclear focus,
subtitle collision, and near-duplicate adjacent shots.

Passing candidates are ranked out of 100:

- text/shot alignment: 25;
- focal clarity and immediate comprehension: 20;
- evidence specificity: 15;
- professional image quality: 15;
- scientific/anatomical credibility: 15;
- continuity and shot diversity: 10.

The default threshold is 80. If no candidate passes, the workflow classifies
the failure and performs at most three targeted repair rounds. Exhaustion emits
a blocked proof with the shot id, failure class, attempts, and best score. It
does not silently promote the least-bad candidate.

### Render And Delivery

The renderer consumes selected shots in narration-span order. Shot changes
follow spoken meaning and audio timing. Individual stills use deterministic
center zoom with subpixel affine interpolation and no default pan. Cuts do not
wait for fixed 12- or 15-second scene durations.

The primary delivery contains hard-burned Traditional Chinese subtitles and an
optional accessibility subtitle track. The final manifest references one
current artifact and records source provider, selected candidates, motion QC,
subtitle QC, silence/black-frame scans, and stale-artifact protection.

## Workflow Nodes

### `story_video_script`

- Inputs: project contract, research, production type, target duration.
- Outputs: `script.md`, `storyboard.md`, nested-shot `scene_ledger.json`,
  `script_quality_report.json`.
- Blocked output: missing evidence, unvisualizable beat, unsupported certainty,
  or shot-density violation.
- Release risk: a weak script produces generic visuals even with strong models.

### `story_video_source_art`

- Inputs: validated shot ledger, visual bible, OpenAI provider contract.
- Outputs: candidate manifest, score reports, selected-shot manifest and files.
- Blocked output: no candidate reaches threshold within the repair budget.
- Release risk: first-success selection creates attractive but irrelevant art.

### `story_video_render`

- Inputs: selected-shot manifest, narration segments, subtitles, render policy.
- Outputs: final MP4, render manifest, artifact QC report.
- Blocked output: missing selected shot, stale artifact, subtitle failure,
  motion jitter, excessive silence, black frames, or provider audit failure.
- Release risk: valid source assets can still become a poor delivered video.

## Phase Proof Changes

- Planning requires valid script-quality and nested-shot structure, not only
  file presence.
- Keyframes require representative shot scales, prompt provenance, OpenAI
  provider evidence, artifact scores, and threshold-passing selections.
- Batch requires every expected shot to have exactly one current selected asset
  and a complete candidate/repair audit trail.
- Voice retains narration segment proof and aligns segments to shot spans.
- Render retains provider, subtitle, motion, duration, and artifact proof and
  adds selected-shot and shot-density evidence.

## Testing And Release

Tests begin by proving current failures: generic prompts, one-result automatic
selection, missing nested shots, shallow phase proof, and contradictory shot
rules. Implementation then follows red-green-refactor.

Release evidence includes:

1. focused unit tests for script and shot schema, prompt compilation, candidate
   budgets, ranking, blocked selection, repair bounds, and phase proof;
2. full story-video plugin and runtime-skill test suites;
3. deterministic dry-run generation/render manifests;
4. one live OpenAI keyframe smoke using a close-up evidence shot;
5. live gateway restart and a planning-only Hermes request proving the new
   nested-shot contract and next-step behavior;
6. provider audit proving no xAI/Grok story-video call.

## Scope Boundaries

- This release does not introduce generic AI-generated body video.
- It does not require users to learn new flags or long prompts.
- It does not publish externally unless the existing publish gate authorizes it.
- It does not claim subjective perfection from metadata-only checks; live visual
  evidence is required for the source-art slice.

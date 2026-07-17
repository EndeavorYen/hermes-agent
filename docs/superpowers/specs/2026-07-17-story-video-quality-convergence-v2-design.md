# Story Video Quality Convergence v2 Design

## Goal

Raise the general story-video quality floor for text, visual sequences, release
art, and background music without returning to large candidate pools or
unbounded auto-mode loops. Quality failures must repair only the affected
artifact and must never be hidden behind copied scores, duplicate files, or a
metadata-only PASS.

## Product Contract

The default story-video path remains simple: one precise image candidate per
shot, one narration take per approved text chunk, and one selected music plan.
The pipeline spends an additional provider call only when artifact evidence
identifies a specific defect. Existing v5 and v6 projects remain readable; new
projects use the v6 review bundle with `family-review-board-v2`.

Final render readiness requires all of the following:

- the approved script is hash-bound to a six-reviewer report;
- child or family scripts satisfy concrete read-aloud and curiosity metrics;
- every selected shot has current semantic evidence bound to both the shot
  contract hash and artifact hash;
- selected shot images have unique content hashes;
- no `final_qc_review_required` or unresolved continuity fallback reaches
  render;
- opening and ending artwork use distinct source images and distinct story
  purposes;
- background music is either selected from the approved library and mixed with
  QC evidence, or the run reports a setup-required music-library state before
  final delivery. Music is not silently omitted from a normal final render.

## Architecture

### 1. Editorial Quality Profile v2

Keep the existing writer, director, and six-role review-board boundaries.
Extend `script_review_report.json` for the new profile with an
`editorial_metrics` object and reviewer evidence rather than adding more full
script rewrites.

Required family metrics:

- `concrete_scene_ratio >= 0.80`;
- `abstract_only_segment_count == 0`;
- `long_sentence_ratio <= 0.25`, where a long Traditional Chinese sentence is
  more than 46 non-whitespace characters;
- `curiosity_loop_count >= max(2, ceil(runtime_minutes))`;
- `resolved_curiosity_loop_count == curiosity_loop_count`;
- `delight_beat_count >= max(1, floor(runtime_minutes / 2))`;
- `emotional_turn_count >= 3` for videos at least two minutes long;
- no repeated rhetorical template appears in more than two segments.

The validator independently recomputes sentence-length metrics from
`script.md`, validates evidence segment IDs, and rejects score-only reports.
Semantic metrics remain reviewer judgments but must cite concrete segment IDs
and resolved findings. At most two revision rounds remain allowed.

### 2. Sequence Quality Gate

Add a focused sequence-quality module between batch selection and render
preparation. It produces `qc/sequence_quality_report.json` with deterministic
violations and `repair_shot_ids`.

For every selected shot it verifies:

- selected path exists and resolves inside the project;
- artifact SHA-256 is unique across the final sequence;
- vision assessment is bound to the current artifact SHA-256 and current shot
  contract hash;
- semantic-match, style-consistency, story-moment-clarity, and
  cinematic-impact evidence are current and above the existing threshold;
- inherited or copied quality evidence cannot become current evidence;
- terminal continuity fallback and `final_qc_review_required` are unresolved
  failures, not renderable warnings.

Normal per-shot repair budgets stay unchanged. Sequence audit receives one
additional rescue attempt per defective shot, capped at three shots per wave.
The rescue prompt names only the observed sequence defect and preserves the
approved story claim. Once that rescue is spent, the workflow returns one
stable review-required state instead of repeating a blocked loop.

The gate does not require more images per minute. Several narration sentences
may remain within one shot; only distinct selected shots must be distinct
artifacts.

### 3. Release Art Separation

Generate one opening/thumbnail hero source and one separate ending source.
The opening visualizes the central mystery or irresistible question. The
ending visualizes the knowledge payoff or changed understanding. Both use
OpenAI Codex image generation and vision QC, but local typography remains the
only source of visible text.

Release-art validation rejects identical source hashes and requires each source
to be bound to its own prompt hash and purpose. The thumbnail may reuse the
opening hero source. The ending may not.

### 4. Music Direction and Selection

Move music policy into a focused `music.py` module. Version 2 of the local
library supports track metadata for:

- production types and audience bands;
- moods, energy, instrumentation, and excluded styles;
- optional named sections with mood and energy tags;
- rights, license, provenance, duration, and technical QC.

Selection is deterministic and requires a minimum compatibility score. It
scores production type, audience, story mood, energy, instrumentation, and
negative-style constraints. Stable hashing is only a tie-breaker, never the
primary selector.

The selected output is a `music_plan` with an opening cue, body cue, tension or
turn cue when the story contains one, and resolution cue. Version 1 single-bed
tracks remain compatible, but fewer than three compatible cue variants are
reported as `INSUFFICIENT_VARIETY` for final-quality mode. Variants may be
separate licensed tracks or independently tagged sections of one locally
generated source, provided each section has its own time range and technical
QC evidence.

The renderer accepts either the existing single `background_music` object or a
v2 cue plan. It mixes cues into one licensed/generated bed, applies fades and
sidechain ducking under narration, preserves video duration, and writes
artifact-level QC. Final music QC requires:

- every cue within the video timeline and no uncovered internal gaps longer
  than two seconds;
- approved rights and provenance for every source;
- no clipping;
- output duration delta at most 0.12 seconds;
- narration remains dominant according to measured mix metrics;
- cue and track IDs recorded in the render manifest.

## Auto-Mode Behavior

Quality repair is a bounded convergence loop, not a generic retry loop:

1. editorial review revises the draft before media generation;
2. normal image generation selects one candidate per shot;
3. sequence audit identifies only current defective shot IDs;
4. one rescue wave regenerates those IDs in parallel, at most three at once;
5. sequence audit reruns from new artifact hashes;
6. release art and music plan are validated;
7. render and post-composite QC run once.

The loop records attempts and costs. Repeated signatures converge to one
review-required state. Provider setup failures remain setup-required and do not
consume aesthetic repair budgets.

## Compatibility and Privacy

- v5 and `family-review-board-v1` artifacts remain valid for historical runs.
- New private media, prompts, provider responses, and user feedback remain
  outside git.
- Story-video image generation and vision QC remain locked to OpenAI Codex.
- xAI/Grok remain forbidden throughout the story-video workflow.
- Music assets must be locally generated or explicitly approved with recorded
  provenance and license.

## Testing and Acceptance

TDD coverage must prove:

- weak child text fails each deterministic editorial metric and a corrected
  report passes;
- exact duplicate images, copied assessments, stale contract hashes, and
  unresolved fallbacks fail sequence QC;
- only the defective shots enter the rescue queue and each receives at most one
  sequence rescue attempt;
- distinct opening and ending sources are required;
- music selection honors positive and negative style constraints and rejects a
  one-track final-quality library;
- cue plans reject gaps, overlap, missing rights, clipping, and duration drift;
- existing v5, review-board-v1, and single-bed renderer fixtures remain valid;
- auto mode does not repeat the same blocked or review-required signature.

Live acceptance uses a short family-oriented educational story-video fixture.
It must produce a v2 editorial report, unique selected image hashes, distinct
opening and ending sources, a selected multi-cue music plan, a mixed MP4, and
PASS reports for sequence, release-art, music, subtitle, narration, and render
quality. The live test records provider attempts and selected artifact paths;
it does not generate extra candidates after all gates pass.

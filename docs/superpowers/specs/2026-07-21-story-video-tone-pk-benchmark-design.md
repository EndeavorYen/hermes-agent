# Story Video Tone A/B PK Benchmark Design

## Status

- Approved direction: fixed-order per-utterance A/B comparison (方案 A)
- Product surface: local story-video release evidence, not a new end-user command
- First acceptance source: an operator-selected private, adult-explicit, 56-utterance dialogue ledger
- Privacy rule: source text, generated media, provider output, and acoustic traces remain under local runtime state and are never committed

## Goal

Produce one reviewable black-subtitle MP4 that makes the difference between
neutral delivery and tone-mapped delivery audible one utterance at a time.
Each pair must use the same source text, speaker, voice binding, model, and
loudness target. The controlled delivery settings are the only intentional
variable.

This is an acceptance benchmark for the deployed engine-aware tone system. It
does not add another tone model, preference learner, public benchmark command,
or durable policy mutation.

## Source Contract

The first run uses the previously produced 56-utterance private ledger. The
acceptance run binds the input ledger and story source by SHA-256 in the PK
manifest. The private text is loaded from runtime state at execution time and
is not copied into this specification or repository fixtures.

The existing locked cast binding remains authoritative:

| Role | Voice | Engine |
| --- | --- | --- |
| narrator | Vivian | Qwen CustomVoice |
| lead | Serena | Qwen CustomVoice |
| supporting role A | `simon_clean_v2` | Qwen full ICL clone |
| supporting role B | Uncle_Fu | Qwen CustomVoice |

The benchmark must fail closed if the current ledger hash, story source hash,
utterance count, utterance order, or cast-binding hash differs from the values
captured when the run is prepared.

## Pair Definition

The user-visible PK unit is one original ledger utterance. The output therefore
contains 56 ordered A/B pairs.

Long utterances may require multiple synthesis chunks. Chunk boundaries are
computed once from the exact spoken text before either variant is generated.
Both variants reuse the same canonical chunk plan. Tone-specific chunking is
not allowed because it would introduce a second comparison variable.

For each pair:

1. Show the pair number, role, display-only action, and exact text.
2. Show `A | 無情緒` and play the neutral take.
3. Hold a short silent separator.
4. Show `B | 有情緒` plus the resolved tone, modifiers, and pace, then play the expressive take.
5. Hold a slightly longer separator before the next pair.

Labels and actions are hard-burned subtitles only. They must never appear in
the spoken text.

## Controlled Variants

### A: Neutral baseline

- `tone_id = general.neutral`
- `pace = natural`
- no modifiers
- the tone adapter must report `neutral_noop`
- retain the same voice profile and cast variant used by B
- retain ordinary pronunciation normalization and safety/QC processing

The baseline is not allowed to bypass the production voice path. It differs
from B only by omitting expressive controls.

### B: Tone-mapped delivery

Before synthesis, compile a private comparison annotation table with one row
per utterance. Each row resolves an explicit catalog tone, intensity, pace,
and zero or more bounded modifiers from the original action and spoken text.

The old source ledger records every emotion as neutral and every pace as
natural, so blindly replaying those fields would make many B takes false
neutral controls. The annotation table corrects that evidence gap without
changing the text. It is run-local evidence, not durable policy.

- The run uses valid `adult_explicit` gating because the complete source text is operator supplied.
- Qwen CustomVoice may receive only catalog-owned Traditional-Chinese instructions.
- Qwen full ICL must preserve its exact reference audio and reference text and must never receive an instruction string.
- Speed, temperature delta, pauses, and modifiers remain within the deployed tone-catalog bounds.
- No take may inject breathing, gasps, moans, laughter, or other sounds that are absent from the exact source text.
- An intentionally expressive row must not resolve to `neutral_noop`.

## Rendering

- 1920x1080 H.264 MP4 with AAC audio
- pure black background; no image generation and no external media provider
- large centered Traditional-Chinese subtitles
- role color remains stable across all 56 pairs
- A uses a restrained gray comparison label
- B uses the role color plus a gold tone label
- no music, sound effects, spoken labels, or synthetic countdown
- short silent separators only; no transition may create an unbounded pause

The renderer uses deterministic overlays for all exact text and labels. Image
generation is not allowed to render, restyle, translate, or rewrite copy.

## Loudness And Fairness

Both takes are normalized to the same integrated loudness target after
synthesis. The per-pair A/B loudness difference must be no more than 0.5 LUFS.
Peak limiting must use the same ceiling for both variants.

Each pair receives a deterministic generation seed derived from the immutable
run ID and utterance ID. A and B must apply the same seed immediately before
model inference, and the applied seed is recorded in the manifest. If the
active Qwen/MLX path cannot prove that the seed was applied, the benchmark
fails closed rather than attributing uncontrolled sampling variance to tone.

Duration is allowed to differ because pace and pause are part of tone control.
The manifest records each take's speech duration, resolved pause, loudness,
engine, model, candidate count, and selected candidate.

Initial generation uses one candidate per take. A failed pronunciation or
alignment gate may retry only that failed take, up to the existing bounded
candidate limit. Green takes are never regenerated during resume or repair.

## Quality Gates

The benchmark is deliverable only when all of the following pass:

1. **Source binding:** hashes, 56 utterance IDs, order, cast binding, and exact text match.
2. **Pair completeness:** exactly one A and one B take exist for every utterance; no duplicate or missing media.
3. **Fair routing:** A and B use the same speaker, voice ID, engine, model/profile, chunk plan, and loudness target.
4. **Sampling control:** A and B record and apply the same deterministic per-pair seed.
5. **Neutral proof:** every A take reports `general.neutral`, natural pace, no modifiers, and `neutral_noop`.
6. **Tone proof:** every intentionally expressive B take records a non-neutral tone application and engine-appropriate evidence.
7. **Speech QC:** normalized ASR similarity, pronunciation, alignment, prosody, and fluency pass for both sides.
8. **Pause QC:** resolved post-utterance pauses remain at or below 0.45 seconds; internal-silence checks use the existing production thresholds.
9. **Loudness QC:** every pair remains within 0.5 LUFS after normalization.
10. **Render QC:** black background, subtitle coverage, audio stream, duration, pair ordering, and final MP4 speech evidence pass.
11. **Privacy QC:** no source text, generated media, provider response, or private acoustic output enters git.

Acoustic tone evidence may be reported as `HEURISTIC_PASS`; it must not be
presented as proof that a human listener prefers B. The finished video is the
human review surface for that judgment.

## Resume And Failure Handling

Generation checkpoints after every completed A/B pair. The run ledger stores
the source hashes, canonical chunk plan, take hashes, QC decisions, and render
timeline. A retry resumes from the first incomplete or failed take and does not
repeat completed generation or delivery.

If the adult gate, voice binding, model/profile hash, source hash, Metal/Qwen
runtime, ASR worker, or renderer is unavailable, the run stops with a specific
setup or phase failure. It must not silently downgrade content, voices, tone,
or output mode.

## Deliverables

The local review bundle contains only current selected artifacts:

- `video/tone_pk_full.mp4`
- `manifests/tone_pk_manifest.json`
- `qc/tone_pk_qc_report.json`

Rejected candidates, raw provider output, temporary stems, and source copies
remain internal. Slack upload is a separate delivery action and occurs only
after the finished bundle passes QC and the operator requests upload.

## Acceptance Criteria

- The full private source produces 56 ordered A/B pairs.
- Each A take is a proven neutral no-op and each intended B take has recorded tone controls.
- A/B text, speaker, voice, model, and chunk plan are identical for every pair.
- The final MP4 can be reviewed line by line without hearing role/action labels.
- All source, speech, loudness, pause, render, privacy, and final-MP4 gates pass.
- The review report states clearly that subjective emotional quality still requires human listening.

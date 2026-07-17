# Story Video Script Review Board v6 Design

**Status:** Approved direction; implementation pending

**Date:** 2026-07-17

## Problem

The story-video planning gate proves that required script artifacts exist, but
its current v5 report can be completed as one undifferentiated self-review. It
does not prove that the final script was checked from distinct editorial
perspectives, that findings were resolved, or that the reviewed text is the
same text later used for narration and rendering.

This allows fluent but dull, verbose, weakly sourced, age-inappropriate, or
hard-to-narrate text to pass. It also couples the current child-oriented writing
path too closely to every future content mode.

## Goals

1. Improve final scripts through six explicit editorial perspectives.
2. Keep findings, decisions, and unresolved risks machine-verifiable.
3. Bind approval to the exact final `script.md` bytes with SHA-256.
4. Limit review cost and avoid multiplying image or video generation.
5. Preserve v5 planning compatibility for existing projects.
6. Add a fail-closed content-profile extension point for a future NSFW mode
   without enabling adult-explicit generation now.
7. Keep the operator trigger simple: a normal story-video request activates
   the board automatically for new projects.

## Non-goals

- Enabling or generating adult-explicit content in this change.
- Replacing visual, voice, pronunciation, or render QC.
- Spawning six independent model sessions by default.
- Rewriting an entire script independently in every review pass.
- Increasing image candidate counts or relaxing factual source requirements.

## Architecture

The feature has three separate responsibilities:

1. **Writer and director skills** create the draft and preserve the existing
   dramatic, audience, factual, read-aloud, and visual-causality contracts.
2. **`story-video-script-review-board` skill** runs six structured reviewer
   passes, produces findings, adjudicates conflicts, and revises the script.
3. **Story-video plugin validator** verifies the v6 artifacts, final-script
   hash, reviewer thresholds, content profile, and bounded repair history.

The review board is a separate skill rather than an enlarged writer skill. The
validator enforces mechanical truth; the skill carries editorial judgment. A
future implementation may replace any logical reviewer with an independent
agent while preserving the same artifact schema.

## New Planning Contract

New projects use `quality_contract_version=6`. Existing ledgers with version 5
or lower continue to use their existing requirements.

Every v6 planning bundle contains:

- `content_profile.json`
- `script.md`
- `storyboard.md`
- `scene_ledger.json`
- `production_checklist.json`
- `script_quality_report.json`
- `script_review_report.json`
- `pronunciation_lexicon.json`

`script_quality_report.json` remains the concise director-level summary.
`script_review_report.json` becomes the auditable board record and must bind to
the final script.

## Content Profile

`content_profile.json` uses schema `story_video_content_profile_v1` and records:

```json
{
  "schema": "story_video_content_profile_v1",
  "rating": "family",
  "activation_status": "active",
  "minimum_viewer_age": 5,
  "policy_profile_id": "family-safe-v1",
  "writer_profile_id": "taiwan-childrens-story-writing-v1",
  "review_profile_id": "family-review-board-v1",
  "provider_capability_status": "available"
}
```

Supported ratings are:

- `family`: child-safe and eligible for the child-writing skill.
- `general`: broad audiences; child-specific checks are not mandatory unless
  the declared age band includes children.
- `mature`: reserved extension point for non-explicit adult themes.
- `adult_explicit`: reserved extension point for a future NSFW workflow.

The current release activates only `family` and `general`. `mature` and
`adult_explicit` must use `activation_status=reserved` and
`provider_capability_status=setup_required`. Any attempt to run them as active
fails before media or provider dispatch.

Future activation of `adult_explicit` requires a separate reviewed change with:

- explicit user opt-in for the project;
- `minimum_viewer_age >= 18`;
- dedicated writer, reviewer, safety-policy, and provider capability profiles;
- prohibition of minors and age ambiguity;
- consent and coercion review rules;
- provider-policy compatibility proven before dispatch;
- no inheritance from the family/child writer profile.

This keeps the schema extensible while preventing dormant NSFW configuration
from changing current family output.

## Reviewer Board

The board contains exactly six required reviewer IDs:

| Reviewer ID | Responsibility | Required evidence |
| --- | --- | --- |
| `language_editor` | Fluent Taiwan Traditional Chinese, grammar, transitions, natural wording | sentence-level findings and proposed replacements |
| `fact_checker` | Knowledge accuracy, source support, uncertainty, no overclaiming | claim IDs and source IDs for factual findings |
| `clarity_editor` | Concision, redundancy, cognitive load, one clear idea at a time | deletion or compression findings with rationale |
| `engagement_editor` | Curiosity, humor, dramatic rhythm, surprise, scene-to-scene momentum | beat IDs and engagement-risk findings |
| `audience_safety_editor` | Audience fit, tone, content-profile compliance, safety boundaries | age/rating rationale and policy findings |
| `performance_editor` | Read-aloud cadence, prosody opportunities, pronunciation risk, narration-to-visual causality | spoken-text and scene/shot references |

Each reviewer returns structured findings rather than a duplicate full script.
A finding contains `finding_id`, `severity`, `location`, `category`,
`evidence`, `recommendation`, and `resolution_status`. Critical findings cannot
be waived by score averaging.

## Review Flow

1. The content-aware writer creates `script.md` draft 1.
2. The director aligns story beats, evidence, narration, and visual causality.
3. All six reviewers inspect the same draft and record only findings.
4. The adjudicator deduplicates findings, resolves conflicts, and writes one
   revised script.
5. Reviewers verify the revised text. A second revision round is allowed only
   for unresolved threshold or critical findings.
6. The final verifier computes the SHA-256 of the final `script.md` and records
   it in both quality reports.
7. Planning may pass only when the report and script hash agree.

The board permits at most two revision rounds. If quality still fails, planning
returns `BLOCKED` with the exact reviewer IDs and finding IDs that remain. It
does not loop indefinitely and does not advance to images.

## Scoring And Gate

Every reviewer records an integer score from 0 to 100. Planning v6 passes only
when all conditions are true:

- all six reviewer records exist exactly once;
- every reviewer status is `PASS`;
- every reviewer score is at least 85;
- no unresolved `critical` finding exists;
- adjudication status is `PASS`;
- revision round count is 1 or 2;
- final verifier status is `PASS`;
- `final_script_sha256` exactly matches the current `script.md`;
- the director report has `quality_contract_version=6` and the same hash;
- factual or documentary productions include source IDs in fact-check evidence;
- the content profile is active and supported.

Universal v6 quality checks are `language_fluency`, `factual_integrity`,
`clarity_concision`, `engagement`, `audience_fit`,
`read_aloud_performance`, `dramatic_arc`, `visual_causality`, and
`style_consistency`. `child_curiosity` is additionally required only when the
profile or age band includes children.

## Report Shape

`script_review_report.json` uses schema `story_video_script_review_v1`:

```json
{
  "schema": "story_video_script_review_v1",
  "quality_contract_version": 6,
  "status": "PASS",
  "execution_mode": "structured_board",
  "revision_round_count": 1,
  "reviewers": [],
  "adjudication": {
    "status": "PASS",
    "resolved_finding_ids": [],
    "unresolved_finding_ids": []
  },
  "final_verification": {
    "status": "PASS",
    "final_script_sha256": "<64 lowercase hex characters>"
  }
}
```

`execution_mode=structured_board` is the current default. The schema reserves
`independent_agents` for a future higher-cost implementation. The acceptance
gate is identical in both modes.

## Cost And Performance

The board improves text before expensive media work and does not increase image
candidate budgets. To keep text cost bounded:

- reviewers emit findings, not six rewritten scripts;
- one adjudicator owns the revised full text;
- the board runs at most two rounds;
- unchanged PASS reviewers may verify only affected finding locations in round
  two;
- exact mechanical checks run locally rather than through a model;
- review occurs before keyframe generation, reducing downstream regeneration.

The runtime report records reviewer count, revision rounds, finding counts, and
script hashes so later telemetry can compare quality gains against planning
latency and token use.

## Failure Handling

- Missing or malformed v6 artifacts return exact planning violations.
- A script edited after review returns `final_script_sha256 mismatch`.
- Reviewer score or finding failures identify the reviewer and finding IDs.
- Unsupported content profiles return `SETUP_REQUIRED`, not a repair loop.
- Reaching two rounds returns a stable planning block and does not auto-repeat.
- v5 projects do not become invalid merely because v6 exists.

## Skill Routing

For `family` content aimed at children, planning applies:

1. `taiwan-childrens-story-writing`
2. `story-video-script-director`
3. `story-video-script-review-board`

For `general` content, planning selects a registered general writer instead of
forcing the child writer, then applies the same director and review board.
Reserved profiles fail before writer selection until their specialized profiles
are registered and activated.

## Verification Strategy

Implementation follows TDD and adds focused tests for:

1. v6 missing review report blocks while v5 remains valid.
2. Six valid reviewers, adjudication, hashes, and content profile pass.
3. Missing reviewer, duplicate reviewer, low score, and unresolved critical
   finding each block with exact evidence.
4. Final-script or director-report hash mismatch blocks.
5. Factual productions without fact-check source IDs block.
6. Child checks apply only to relevant profiles and age bands.
7. Reserved `mature` and `adult_explicit` profiles fail before provider/media
   dispatch.
8. Planning prompts route family content through the child writer and include
   the review board; they do not route reserved adult content through it.
9. Skill pressure tests show the unskilled baseline collapsing reviewers or
   skipping adjudication, and the new skill producing the full board contract.

After unit tests, a planning-only live smoke creates a fresh family story-video
bundle, validates all v6 artifacts, confirms no media/provider dispatch, and
checks the final script hash from disk.

## Rollout

1. Add and test the plugin schema and validator behind v6.
2. Add the standalone review-board skill and update writer/director handoffs.
3. Change new planning prompts from v5 to v6 while retaining v5 validation.
4. Run focused and wider story-video tests.
5. Deploy the exact accepted SHA to `runtime/current`, restart the gateway, and
   run the planning-only live smoke.

No content mode beyond `family` and `general` is activated by this rollout.

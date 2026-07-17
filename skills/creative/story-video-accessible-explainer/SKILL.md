---
name: story-video-accessible-explainer
description: "Use when a story-video explains science, history, economics, technology, or another difficult subject to newcomers, or when the operator asks for accessible, advanced, or professional explanation depth."
license: MIT
metadata:
  hermes:
    tags: [story-video, explainer, education, script, accessibility]
    related_skills: [story-video-script-director, story-video-script-review-board, story-video-production-pipeline]
---

# Story Video Accessible Explainer

## Scope

Own the comprehensibility of explanatory beats. Do not own story structure,
shots, media generation, voice, rendering, or release. Those remain with
`story-video-script-director`, `story-video-script-review-board`, and
`story-video-production-pipeline`.

Read the project's `explanation_profile.json`. It is authoritative and must not
be rewritten during planning.

## Modes

- `accessible` is the default. Write for a curious newcomer age 5+ and a
  non-specialist adult at the same time.
- `advanced` keeps more terminology and detail while preserving a brief entry
  path for non-specialists.
- `professional` preserves expert depth and does not require newcomer-oriented
  rewriting.

Apply the selected mode only to explanatory beats. Dialogue, suspense, humor,
and character voice remain natural story craft.

## Accessible Explanation

For each difficult idea, use this order:

1. **concrete intuition**: a visible person, object, action, or consequence;
2. **causal chain**: one short sequence of why A changes B;
3. **formal term**: name the idea after the viewer can recognize it;
4. **precision boundary**: state what the example leaves out or must not imply.

Keep useful technical terms. Explain them rather than deleting them. Use an
analogy only when its mapping and limit are both clear. Prefer one decisive
example over several decorative comparisons.

Baby talk is a blocking defect. So are false certainty, missing caveats,
patronizing questions, sing-song filler, and simplification that changes the
fact. Short sentences are useful only when the causal chain remains intact.

## Planning Handoff

Bind `content_profile.json` to the locked profile with
`explanation_profile_id`, `explanation_mode`, and
`supplemental_writer_profile_ids`. In `accessible` mode for explanatory work,
the review board must add `newcomer_comprehension_editor` and produce the
evidence in `references/accessible-explanation-contract.md`.

Only a hash-bound review PASS may enter `story-video-production-pipeline`.

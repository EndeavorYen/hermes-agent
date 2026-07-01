# Raphael LLM Public Slice

This document defines the Phase 6 public-readiness boundary for Raphael mode.
It is intentionally LLM-only. It does not certify image generation, video
generation, Grok Web Imagine, Slack media delivery, or visual artifact quality.

## What Phase 6 Can Prove

Phase 6 can mark the Raphael LLM control-layer slice ready only when all of the
following are true:

- Deterministic public-user simulations pass for summon routing, mission
  follow-up continuity, proof-gated success claims, and auditable evolution
  proposals.
- At least one LLM-only live smoke is recorded in a JSON evidence file and
  classified as passed after matching the expected session id.
- `hermes raphael readiness` reports `Overall: llm_ready`.
- The release gate writes a JSON report that records only the LLM slice as
  ready.
- Public wording says "Raphael LLM control-layer slice is ready" and does not
  claim media, visual, video, Grok, or full release readiness.

## What Phase 6 Must Not Claim

Until later phases provide separate live evidence, public copy must not claim:

- OpenAI image generation readiness.
- Grok Web Imagine readiness.
- Video generation readiness.
- Slack/native media delivery readiness.
- Artifact beauty, face fidelity, pose, wardrobe, geometry, or selected-media
  quality readiness.
- Full "ultimate Raphael" release-candidate readiness.

## Verification Commands

Run deterministic readiness:

```bash
hermes raphael readiness
```

After an approved LLM-only live smoke:

```bash
hermes raphael readiness \
  --llm-smoke-session-id phase6-smoke-session \
  --llm-smoke-evidence-file /path/to/raphael-llm-smoke.json \
  --gate-output /path/to/raphael-readiness.json
```

The first command should remain blocked without live smoke evidence. The second
may mark only the LLM slice ready when the evidence file exists, matches the
supplied session id, records a passed smoke, and contains no forbidden media,
visual, Grok, video, or full-release ready claim. Media, visual, and Grok slices
must still show `not ready`.

## Hostile Review Questions

Before merging a Phase 6 PR, review these questions:

- Would a user understand that Raphael is a control layer, not a persona skin?
- Does the summon/follow-up/proof/evolution journey feel materially upgraded?
- Did we prove the LLM slice with live evidence, or only with fixtures?
- Did any wording imply image, video, Grok, or full-release readiness?
- If a smoke failed, did the report classify the layer and next action?

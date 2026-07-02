# Raphael Media Readiness

Phase 7 proves only the OpenAI image slice. It does not certify Grok Web
Imagine, video, Slack/native delivery, or full media release readiness.

## Gate Contract

Run:

```bash
hermes raphael media-readiness \
  --openai-image-evidence-file /path/to/openai-image-evidence.json \
  --openai-image-session-id phase7-openai-image-session \
  --current-selected-artifact-id openai-image-1 \
  --gate-output /path/to/raphael-media-readiness.json
```

The command exits `0` only when the OpenAI image evidence proves:

- provider is `openai` and capability is `image`
- `session_id` matches `--openai-image-session-id`
- `selected_artifact_id` matches `--current-selected-artifact-id`
- `generated_at` is within the allowed freshness window
- the generated artifact is the current selected artifact
- the artifact is fresh, not duplicated, and not rejected
- dimensions are recorded for geometry-preserving packaging
- quality review passed with score at or above `0.80`
- structured `evidence_refs` exist for generation, selection, freshness,
  dedupe, geometry, and quality review

The same report always keeps these claims blocked in Phase 7:

- Grok Web Imagine readiness remains blocked.
- Video readiness remains blocked.
- Slack/native delivery readiness remains blocked.
- Full media readiness remains blocked.

## Failure Layers

The gate separates setup and provider failures from artifact quality:

- `setup_required`: missing credentials or equivalent operator setup
- `quota_required`: provider quota, subscription, or billing exhaustion
- `provider_health`: timeout, outage, rate limit, or empty provider response
- `prompt_moderation`: provider moderation refusal
- `artifact_selection`: wrong or missing selected artifact
- `artifact_freshness`: stale artifact
- `artifact_deduplication`: duplicate artifact
- `artifact_geometry`: missing dimensions
- `artifact_quality`: rejected or low-scoring artifact

## Evidence Shape

Minimum successful OpenAI image evidence:

```json
{
  "session_id": "phase7-openai-image-session",
  "generated_at": "2026-07-02T15:30:00+00:00",
  "provider": "openai",
  "capability": "image",
  "status": "success",
  "artifact_id": "openai-image-1",
  "selected_artifact_id": "openai-image-1",
  "fresh": true,
  "duplicated": false,
  "rejected": false,
  "dimensions": {
    "width": 1536,
    "height": 1024
  },
  "quality": {
    "passed": true,
    "score": 0.89
  },
  "evidence_refs": {
    "generation": "generation:openai-image-1",
    "selection": "selection:openai-image-1",
    "freshness": "freshness:phase7-openai-image-session",
    "dedupe": "dedupe:openai-image-1",
    "geometry": "geometry:1536x1024",
    "quality_review": "quality-review:openai-image-1"
  }
}
```

## Public Boundary

The public claim allowed by this phase is:

`OpenAI image slice is ready.`

Claims about Grok, video, Slack delivery, or full media stay outside public
copy until a later issue records separate live evidence for that slice.

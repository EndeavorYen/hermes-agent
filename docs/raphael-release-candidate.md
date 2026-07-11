# Raphael Release Candidate Gate

This is the public release gate contract for Raphael. A fresh passing artifact
can certify the verified LLM control-layer slice and the OpenAI image slice. It does
not certify Grok Web Imagine, video, Slack/native media delivery, or full media
readiness.

## Gate Contract

Run:

```bash
hermes raphael release-gate \
  --lifecycle-evidence-file /path/to/raphael-lifecycle.json \
  --llm-readiness-file /path/to/raphael-readiness.json \
  --media-readiness-file /path/to/raphael-media-readiness.json \
  --docs-file docs/raphael-llm-public-slice.md \
  --docs-file docs/raphael-media-readiness.md \
  --docs-file docs/raphael-release-candidate.md \
  --gate-output /path/to/raphael-release-candidate.json
```

The command exits `0` only when:

- install, enable, disable, and uninstall lifecycle evidence passes
- the LLM gate reports `llm_ready`
- the media gate reports `openai_image_ready`
- Grok Web Imagine, video, Slack delivery, and full media are still blocked
- public docs do not claim unverified media readiness
- gate output is privacy-safe for PR and release notes

## Public Claim

Allowed only when the matching machine-readable gate is fresh and passing:

`Raphael release candidate is ready for verified LLM and OpenAI image slices.`

Required blocked claim:

`Grok Web Imagine, video, Slack delivery, and full media remain blocked.`

Do not publish claims that Grok, video, Slack/native delivery, full media, or
general visual generation are ready until a later issue records separate live
evidence for those slices.

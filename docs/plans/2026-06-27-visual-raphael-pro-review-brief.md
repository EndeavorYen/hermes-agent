# Visual Agent And Raphael One-Shot Pro Review Brief

Date: 2026-06-27

## Purpose

Ask a pro/high-reasoning model once for strategic guidance before the next
Hermes visual-agent and Raphael autonomy pass. This review should produce
architecture direction, evidence gates, and milestone ordering. It should not
produce code, run tools, inspect private runtime media, or ask follow-up
questions.

## Goals

1. Make image/video agent mode more powerful and improve artifact quality.
2. Make Raphael mode smarter, stronger, and more autonomous.
3. Preserve the provider separation below.

## Three-Layer Provider Contract

```text
base_llm_provider = openai-codex:gpt-5.5
visual_agent_llm_provider = xai-oauth:grok-4.3
visual_media_provider_default = xai:grok-imagine-image-quality
visual_media_video_default = xai:grok-imagine-video
visual_media_provider_override = openai-codex:image2 | xai:grok-imagine
```

Interpretation:

- General Hermes conversations, coding, runtime work, and Raphael use OpenAI
  `gpt-5.5` as the base LLM route.
- Only image/video visual agent mode uses Grok as the LLM
  orchestration/planning route, because visual prompt planning benefits from a
  more aggressive creative model.
- Visual media generation defaults to xAI Grok Imagine.
- The visual media provider can switch from natural user intent to OpenAI
  Image2 or xAI Grok Imagine without exposing internal flags for ordinary use.
- Provider health, model capability, and aesthetic preference remain separate in
  evidence and reports.

## Handoff Constraint

The base OpenAI LLM must not be the only gate deciding whether a sensitive or
aggressive visual request reaches visual agent mode. Clear image/video
generation requests should be detected before the base LLM call and handed to
visual agent mode with auditable metadata. This avoids a stricter base provider
blocking or weakening a request before the Grok visual-agent planning route can
own it.

## Existing Baseline

Visual agent mode already has a natural-language entry point, package
generation, image-first video, candidate ranking, quality judgment, delivery
metadata, attempt ledger, artifact observations, provider failure
classification, bounded retry/recovery, shadow learning, controlled activation
policy, E2E automation reports, and scheduled self-validation.

Raphael mode is currently an advisor MVP: optional conversation mode, read-only
advisor prompt, turn observer, response governor, runtime state model, status
cards, action proposals, and skill traces.

## Review Questions

Please answer in one pass:

1. What is the best architecture-level strategy to strengthen visual agent mode
   without overbuilding?
2. What is the best architecture-level strategy to strengthen Raphael into a
   smarter/autonomous advisor-control layer without making it unsafe or noisy?
3. Should visual quality or Raphael autonomy come first? Explain dependency
   logic.
4. What are the 5-8 highest-leverage implementation milestones?
5. Given the three-layer provider contract, what runtime routing architecture is
   cleanest?
6. What quality rubric should visual agent mode use so it optimizes actual
   artifact quality instead of tool success?
7. What autonomy rubric should Raphael use so it can do more while keeping
   mutations, public delivery, cron, memory, and skills safe?
8. What are the main failure modes or architectural traps?
9. What is the smallest evidence package proving the first milestone is better?
10. What should explicitly not be built yet?

## Desired Output

- Executive judgment
- Recommended sequence
- Provider-routing architecture
- OpenAI-to-Grok handoff architecture
- Visual agent roadmap
- Raphael roadmap
- Shared evidence gates
- Pro model warnings
- First milestone spec
- Do-not-build-yet list

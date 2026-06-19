# Hermes Visual Agent Mode Goal

> **TL;DR** - Hermes Visual Agent Mode turns uploaded materials plus a user goal into finished visual output: images, video clips, and a packaged Slack response. The agent plans the production, generates candidates, judges artifacts, repairs failures, assembles the final result, and learns from evidence without relying on raw private prompts in the repo.

## Product Promise

Hermes should act like a visual production agent, not a single prompt generator.

Given source material and a natural-language request, Hermes should:

- understand the intended subject, style, constraints, references, and output format;
- choose an image/video production plan;
- generate multiple candidates when quality matters;
- reject stale, malformed, low-adherence, or repeated artifacts before delivery;
- pick suitable images for video generation;
- preserve aspect ratio and avoid stretched video;
- assemble the result into a clear Slack response;
- record enough evidence to improve future choices.

The user should be able to say what they want, attach materials, and receive a coherent output package without manually steering every image, clip, and retry.

## Baseline

The current visual ledger work provides the foundation:

- `agent.visual` records requests, attempts, artifacts, deliveries, and feedback.
- `image_generate` and `video_generate` add visual IDs in shadow mode.
- Slack delivery gates current artifacts and records image/video delivery rows.
- Sparse feedback can be attributed to delivered artifacts.
- Video aspect ratio can be inferred from local input image dimensions.

This goal builds on that evidence layer. It does not replace it.

## Target User Flow

The desired flow is:

```text
User uploads material and describes the desired visual result
  -> Hermes creates a VisualMission
  -> Hermes builds an AssetGraph from uploaded and generated artifacts
  -> Hermes creates a production plan
  -> Hermes generates image candidates
  -> Hermes judges, ranks, and repairs candidates
  -> Hermes selects images for video generation
  -> Hermes generates and judges video clips
  -> Hermes assembles a final package
  -> Hermes delivers only selected artifacts to Slack
  -> Hermes records feedback and strategy outcomes
```

## Mission Types

The system should support these initial mission types:

| Mission type | Expected output | Example intent |
| --- | --- | --- |
| `image_set` | A ranked batch of images | Generate several visual directions from a reference |
| `image_to_video` | One or more clips from selected frames | Animate the best generated image |
| `visual_package` | Images plus video clips plus short summary | Produce a complete showcase from uploaded material |
| `repair_existing` | Revised images or clips | Fix face drift, aspect issues, repeated artifacts, or weak composition |

## Agent Responsibilities

Hermes should separate production responsibilities into explicit stages:

| Stage | Responsibility |
| --- | --- |
| Mission planner | Convert user text and attachments into structured intent, constraints, budget, and output plan |
| Asset graph | Track relationships among uploaded references, generated images, selected images, clips, and final package |
| Candidate generator | Generate K image candidates through controlled strategies |
| Judge and ranker | Score candidates for hard validity, reference adherence, visual quality, composition, novelty, and delivery suitability |
| Repair controller | Retry or reframe when provider errors, moderation failures, wrong aspect ratio, face drift, or poor aesthetics occur |
| Clip builder | Select images for video generation and pass aspect-safe settings |
| Assembler | Create the final response package and avoid reposting stale media |
| Learning store | Update provider reliability and strategy preferences from artifacts, rankings, delivery results, and user feedback |

## Autonomy Policy

Hermes should be autonomous only when confidence is high and the action is reversible.

| Level | Behavior |
| --- | --- |
| L0 record-only | Record evidence, do not change behavior |
| L1 assisted | Generate candidates and ask before delivery when confidence is low |
| L2 auto-select | Rank and deliver selected candidates when hard gates pass |
| L3 auto-repair | Retry with bounded repairs after failures or low scores |
| L4 production loop | Plan, generate, animate, assemble, deliver, and learn within configured budgets |

The first shippable Visual Agent Mode target is L2 for images and L1 for video. L3 and L4 require stronger scoring and loop guards.

## Privacy And Safety Rules

The repo may contain schemas, generic strategies, tests, and public documentation.

Runtime-private data must stay under `~/.hermes`:

- uploaded references;
- generated images and videos;
- raw prompts and user preference evidence;
- provider responses that may reveal private inputs;
- strategy statistics tied to user taste;
- local draft-model endpoints or model names.

Learning should store compact strategy signals, not raw private prompts.

## Quality Bar

Visual Agent Mode is useful when it can do these things without manual babysitting:

- avoid posting stale artifacts from prior rounds;
- avoid stretched videos;
- show only selected current outputs in Slack;
- identify and retry malformed or low-adherence images;
- choose the best image before creating a video;
- report why it stopped when confidence is low;
- preserve enough artifact evidence to explain every choice.

## MVP Definition

The MVP is complete when a user can ask for a visual package from one prompt and optional materials, and Hermes can:

1. create a `VisualMission`;
2. generate a small candidate image batch;
3. rank and select candidates before Slack delivery;
4. create one video clip from the selected image;
5. assemble a Slack response containing only selected new artifacts;
6. record the asset graph, ranking decision, delivery rows, and feedback attribution.

The MVP does not need neural model training or a perfect aesthetic judge. It needs a reliable loop that improves from evidence.

## Current Implementation Status

As of 2026-06-20, the first Visual Agent Mode slice is implemented on `live/hermes-v2026.6.5` and pushed to `origin`.

Done:

- `visual_agent_generate` can plan a package, generate image candidates, select images, generate video clips, and return image/video paths.
- Image package prompts are split so the image stage receives a standalone still-image brief instead of a combined image/video delivery instruction.
- xAI video generation can be called safely from async Hermes tool handlers.
- Selected image and video artifact IDs join back to `visual_artifacts`.
- Gateway tests cover auto-appending only selected current package artifacts and skipping historical package media.

Latest safe CLI smoke:

- mission: `vms_915e683f14b44d7b89acb96a0602834e`
- selected image: `var_7e14ab73338344dba02533b678e7aebe`
- selected video: `var_d0d50d86318a4e588df269360a3252de`
- video: 1280x720, about 6.04 seconds

Remaining proof before calling the MVP fully live:

- Trigger one request from Slack through the running gateway and verify that Slack receives only the selected current image/video artifacts.
- Confirm `visual_deliveries` increments for that Slack-triggered request and joins to the selected artifact IDs.

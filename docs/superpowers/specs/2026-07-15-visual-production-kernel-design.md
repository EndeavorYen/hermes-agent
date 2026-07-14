# Visual Production Kernel Design

## Objective

Create a shared, artifact-driven quality kernel that lets Visual Agent turn a
natural-language request into one versioned visual contract, generate one
primary image by default, inspect the actual artifact, and take one bounded,
specific corrective action. The same kernel must remain reusable by
story-video without importing story-video phases, narration, subtitles, or
rendering concerns into ordinary image generation.

## Product Contract

- Natural language remains the user interface.
- One image candidate is the default. More candidates require an explicit user
  request or a measured QC failure that justifies one repair attempt.
- Explicit provider selection always wins.
- OpenAI Image2 and xAI Imagine are coordinated through routing and fallback,
  not unconditional parallel competition.
- Provider switching must preserve the same semantic contract.
- QC judges the generated artifact against request-specific acceptance
  criteria, not only generic aesthetics or provider success metadata.
- Repair is bounded and must target identified blocker codes.
- Only the current selected artifact is deliverable.
- Private prompts, provider responses, generated media, and preference traces
  remain local runtime evidence.

## Architecture

### Visual Intent Contract

`agent.visual.production_kernel.contract` owns a provider-neutral
`VisualIntentContract`. It records the original request, primary subject,
observable action or decisive moment, focal point, composition, style, audience
effect, reference roles, required and forbidden details, acceptance criteria,
output geometry, and optional truth mode. The canonical serialized contract has
a stable SHA-256 hash.

The hash prevents stale artifacts and judgments from being selected after the
request, reference roles, or acceptance criteria change. Provider prompt text
is not part of the identity; it is a compilation product of the contract.

### Quality Observation And Blockers

`agent.visual.production_kernel.quality` converts existing Visual Agent judge
output into a small shared blocker taxonomy:

- `subject_mismatch`
- `action_or_moment_missing`
- `composition_weak`
- `reference_identity_drift`
- `style_mismatch`
- `artifact_defect`
- `truth_or_evidence_risk`
- `provider_failure`
- `other`

Hard blockers prevent delivery. Soft preference dimensions can lower ranking
but do not create an unbounded generation loop. Every QC decision records the
contract hash and artifact identifier.

### Repair Planner

`agent.visual.production_kernel.repair` maps blocker codes to one materially
different repair strategy:

- `targeted_repair`
- `composition_reset`
- `identity_recovery`
- `story_moment_reframe`
- `style_correction`
- `truth_reframe`
- `provider_switch`

The planner prioritizes same-provider semantic repair. It recommends a provider
switch only for provider failure, an explicit capability mismatch, or a repeat
of the same blocker after a targeted repair. At most one generated repair is
allowed in the default single-image workflow.

### Provider Coordinator

`agent.visual.production_kernel.providers` chooses an authorized provider from
the explicit override, measured provider profiles, and availability evidence.
Profiles are scoped by request category and record first-pass QC rate, provider
failures, latency, and sample count. Sparse evidence cannot silently overturn
the configured default.

The coordinator returns a decision with reason and evidence; it does not call
providers. This keeps policy independently testable and lets the existing
Visual Package tool remain the execution boundary.

### Visual Agent Integration

The Visual Agent planner compiles a contract before provider execution and
passes the contract plus hash into `visual_package_generate`. The Visual Package
tool records the contract on the request and every artifact attempt, uses one
candidate by default, checks judgments against the current hash, and builds a
blocker-specific repair prompt when the selected artifact fails delivery QC.

The existing ranker, independent vision observation, attempt ledger, delivery
manifest, and image-first video path remain authoritative. The kernel adds
contract specificity and bounded decisions; it does not replace those modules.

### Story-Video Boundary

Story-video remains responsible for scene ledgers, narration timing, subtitle
safe areas, continuity across shots, render inputs, and phase proof. Its shot
contract and repair taxonomy provide the behavior model for the shared kernel,
but this change does not make Visual Agent call `story_video_quality_control`.
Future story-video adoption can use an adapter from a shot row to
`VisualIntentContract` after the Visual Agent path is proven.

## Execution State Machine

The default image path is:

1. Compile and hash the visual contract.
2. Select one primary provider.
3. Generate one image.
4. Observe and judge the artifact.
5. Deliver when hard gates pass.
6. Otherwise classify blockers and execute one targeted repair.
7. Rejudge only the repaired artifact.
8. Deliver on pass; otherwise return structured review-required evidence.

Independent multi-image outputs may run in parallel. Generation, judgment, and
repair of the same visual goal remain sequential.

## Failure Handling

- Transport, quota, authentication, and unavailable-provider failures are
  provider-health failures, not aesthetic feedback.
- Moderation can use a safe reframe only when the semantic contract is
  preserved; otherwise it returns setup/review required.
- Missing vision evidence lowers confidence and cannot create a false quality
  pass.
- A contract-hash mismatch invalidates selection and repair reuse.
- Repeated equivalent blockers stop after the bounded repair instead of
  generating more near-duplicates.

## Verification

- Unit tests cover canonical hashing, stale-artifact rejection, blocker
  classification, repair selection, provider override, sparse provider data,
  provider failure fallback, and retry bounds.
- Visual Agent planner tests prove a contract and hash are included and the
  default candidate budget is one.
- Visual Package tests prove one initial generation, blocker-specific repair,
  no unconditional provider competition, and current-artifact-only delivery.
- The existing Visual Agent suite must remain green.
- A focused runtime smoke must show the deployed planner emitting the contract,
  one-candidate default, selected provider reason, and bounded recovery policy
  without spending a live image request.

## Non-Goals

- Replacing story-video phase control or render logic.
- Generating OpenAI and xAI candidates for every request.
- Building a new vision model or aesthetic scoring system.
- Automatically promoting provider preferences from one run.
- Increasing the normal candidate budget to improve quality by brute force.

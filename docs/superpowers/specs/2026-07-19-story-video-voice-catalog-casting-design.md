# Story Video Voice Catalog And Casting Design

## Status

Approved in the operator session on 2026-07-19. This design extends the
multi-character dubbing contracts without replacing the existing full-ICL voice
profile registry.

## Goal

Treat voices as an extensible roster of voice actors. Given story text, identify
the cast, assign a suitable available voice to each role, let the operator
override the proposed cast, and then lock the mapping so a character keeps the
same voice throughout production.

The first Qwen CustomVoice actors are `Vivian`, `Serena`, and `Uncle_Fu`.
Future voices must be addable without changing story parsing, casting, or
synthesis orchestration.

## Product Model

The system has four distinct concepts:

1. **Voice catalog** — the available voice actors and their capabilities.
2. **Story cast** — the characters inferred or declared for one story.
3. **Casting proposal** — a deterministic, explainable role-to-voice mapping.
4. **Locked cast binding** — the exact mapping and engine evidence used for
   synthesis.

A voice is not a character. A character is not tied permanently to a provider.
The casting layer is the only component allowed to connect the two.

## Component Boundaries

### Voice catalog service

Builds one normalized catalog from provider-specific sources:

- the existing full-ICL clone profile registry;
- Qwen CustomVoice presets exposed by the installed model;
- future provider adapters or operator-managed catalog overlays.

It owns discovery, normalization, capability reporting, availability checks,
aliases, and stable voice identifiers. It does not parse stories or decide who
speaks a line.

The existing clone registry remains authoritative for consent, reference audio,
immutable versions, and clone lifecycle. Qwen presets do not pretend to be clone
profiles and do not require fake reference recordings or clone consent fields.

### Story cast compiler

Creates character records from supplied story text or explicit operator input.
Each record has a stable `speaker_id`, display name, role, and casting traits such
as language, gender presentation, age impression, temperament, vocal weight,
and narrative importance.

It does not select voices. Existing cast records that already contain a
`voice_id` are interpreted as explicit manual assignments for compatibility.

### Casting mapper

Consumes a story cast and a catalog snapshot. It filters unavailable or
incompatible voices, scores the remaining candidates, applies uniqueness rules,
and writes an explainable proposal. The same inputs must produce the same result.

The operator may replace any proposed assignment before synthesis. An override
is explicit data, not a prompt-only hint.

### Cast binding resolver

Turns the accepted proposal into `voice_cast_binding.json`. It locks engine and
identity evidence for each character and refuses silent changes after narration
exists. It does not synthesize audio.

### Voice executor

Dispatches each utterance through the engine recorded in the locked binding. A
full-ICL actor uses its immutable profile version; a Qwen CustomVoice actor uses
its preset speaker and locked model evidence. The executor may batch compatible
utterances so the model is loaded once.

## Normalized Voice Record

The catalog exposes a provider-neutral record with these fields:

```json
{
  "voice_id": "qwen_custom_vivian",
  "display_name": "Vivian",
  "aliases": ["Vivian", "vivian"],
  "engine": "qwen_custom_voice",
  "source_kind": "preset",
  "language": "zh",
  "locale": "zh-CN",
  "traits": {
    "gender_presentation": "female",
    "age_impression": "young",
    "styles": ["bright", "clear"]
  },
  "capabilities": {
    "preview": true,
    "single_narrator": true,
    "character_dubbing": true,
    "operator_tunable": false
  },
  "availability": {
    "status": "ready",
    "reason": ""
  }
}
```

Stable machine selectors use lowercase ASCII identifiers. Operator-facing names
and case-insensitive aliases remain accepted. Provider-specific details live in
an engine binding and do not leak into story character records.

The initial preset identifiers are:

- `qwen_custom_vivian`
- `qwen_custom_serena`
- `qwen_custom_uncle_fu`

`simon_clean_v2` remains a full-ICL catalog entry and the default narrator until
the operator changes that policy.

## Catalog Listing Contract

`story_video_voice_manager(action="list")` keeps the existing `profiles` field
for compatibility and adds a normalized `voices` field. The operator-facing
summary uses `voices`; clone lifecycle actions continue to use `profiles`.

Catalog records remain visible when setup is incomplete, but their availability
is `setup_required` or `disabled` and they are not selectable. This makes missing
models and runtimes diagnosable without returning a falsely empty list.

Adding a future voice changes only its provider source or catalog overlay. The
casting mapper and story contracts consume normalized records and require no
provider-specific branch.

## Story Cast Contract

Each speaker record supports:

```json
{
  "speaker_id": "captain",
  "display_name": "老船長",
  "role": "supporting",
  "traits": {
    "language": "zh",
    "gender_presentation": "male",
    "age_impression": "older",
    "temperament": ["calm", "authoritative"],
    "vocal_weight": "heavy"
  },
  "casting": {
    "mode": "auto",
    "requested_voice_id": ""
  }
}
```

`casting.mode="manual"` requires `requested_voice_id`. Existing records with a
top-level `voice_id` migrate in memory to manual casting and remain readable.

## Automatic Casting Policy

Casting follows a deterministic sequence:

1. Remove voices that are unavailable or lack `character_dubbing`.
2. Apply hard requirements such as language and an explicit requested voice.
3. Score compatible traits: gender presentation, age impression, vocal weight,
   temperament, style, and preferred role.
4. Prefer a distinct voice for the narrator and each principal character.
5. Permit supporting characters and extras to share voices only when the pool is
   insufficient or the operator explicitly allows sharing.
6. Break equal scores by stable `voice_id`, never by catalog iteration order.

Every proposal records candidate scores, the selected voice, rejected hard
constraints, and a short human-readable rationale. A low-confidence match is
shown as `review_required`; it is not silently presented as a strong match.

## Operator Override And Locking

The default workflow is:

```text
story text -> cast extraction -> automatic proposal -> operator may override
-> accepted mapping -> locked binding -> synthesis
```

The operator may accept the proposal implicitly by starting synthesis or may
edit any role first. Once narration artifacts exist, changing a voice requires
an explicit revoice operation that creates a new binding revision. Existing
audio is never relabeled as if a different actor produced it.

## Locked Engine Evidence

Each bound speaker stores common fields plus engine-specific evidence:

- catalog voice ID and catalog snapshot SHA-256;
- display name, engine, source kind, and assignment origin (`auto` or `manual`);
- selected traits, score, rationale, and any approved variant;
- for full ICL: immutable profile ID, profile path, and profile SHA-256;
- for Qwen presets: canonical preset speaker, model path, model config SHA-256,
  and runtime identity.

Resolution fails closed if the model, preset, runtime, profile, or locked hash
drifts. A catalog metadata wording change does not invalidate audio unless a
field included in the engine binding changes.

## Error And Recovery Policy

- Unknown manual voice: fail before binding with available alternatives.
- Missing model or runtime: mark the voice `setup_required`; do not select it.
- Unsupported preset in the installed model: mark it unavailable and surface the
  model mismatch.
- Too few distinct voices: produce a review-required proposal that names the
  roles that would share a voice.
- No compatible voice: return a structured casting failure; do not substitute a
  random actor.
- Hash drift after binding: require rebind or revoice depending on whether audio
  already exists.
- Provider generation failure: attribute the failure to the bound engine and
  preserve the accepted casting decision for retry.

## Compatibility

- Existing single-narrator projects continue to use the current voice profile
  binding.
- Existing multi-character projects with explicit `voice_id` values remain
  manual casts.
- Existing clone add, tune, archive, and delete behavior is unchanged.
- The current `profiles` list remains available to callers while `voices` becomes
  the preferred selection surface.
- The three Qwen presets become formal character-dubbing choices without being
  written into the clone registry.

## Delivery Phases

### Phase 1: extensible catalog and formal binding

- Normalize clone profiles and Qwen presets into `voices`.
- List Vivian, Serena, and Uncle_Fu as ready selectable actors when local setup is
  valid.
- Resolve and lock preset actors in multi-character bindings.
- Preserve current clone and single-narrator behavior.

### Phase 2: story-driven casting

- Extend cast compilation with traits and auto/manual casting intent.
- Implement deterministic scoring, uniqueness, rationales, and overrides.
- Add natural operator summaries of the proposed cast.

### Phase 3: multi-engine performance

- Dispatch utterances by locked engine binding.
- Batch Qwen CustomVoice lines with one model load.
- Assemble per-character outputs into the existing narration manifest and QC
  evidence without losing utterance ordering.

## Verification Strategy

Phase 1 must prove:

- the live list includes the existing clone actor plus the three Qwen actors;
- missing Qwen setup produces unavailable records rather than false choices;
- aliases resolve case-insensitively;
- all three presets can be bound to different characters;
- model config drift invalidates a locked preset binding;
- existing clone profile and dubbing tests remain green.

Phase 2 must prove deterministic casting, manual override precedence, principal
voice uniqueness, controlled sharing, low-confidence review states, and stable
tie-breaking.

Phase 3 must prove exact utterance-to-character-to-engine routing, one model load
per compatible batch, ordered output, per-line failure attribution, cancellation,
and a live local smoke that produces audibly distinct character files.

## Non-Goals

- Claiming that a preset has a Taiwan accent when its provider metadata does not
  establish that fact.
- Treating pitch shifting as a new actor identity.
- Automatically mutating durable voice preferences from one story.
- Committing local reference audio, generated samples, model files, or private
  operator preference traces.

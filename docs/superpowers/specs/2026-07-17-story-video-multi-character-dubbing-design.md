# Story Video Multi-Character Dubbing Design

## Goal

Turn an ordinary story request or supplied text into an auditable multi-character
voice production while keeping the operator interface short. Preserve the current
single-narrator path and the local Qwen Base full-ICL voice-clone policy.

## Component Boundaries

### Voice profile manager

Owns durable voice identities and immutable profile versions. It can list, add,
tune, archive, and delete profiles. Tuning creates a new version and never mutates
an existing profile. Profiles referenced by project bindings may be archived but
cannot be deleted.

### Story audio director

Owns story mode, speaker definitions, casting, and utterance ordering. It compiles
three project-local contracts:

- `story_mode.json`
- `cast_bible.json`
- `dialogue_ledger.json`

It does not synthesize audio and does not own language normalization.

### Production pipeline

Resolves each cast member to one concrete profile version, writes
`voice_cast_binding.json`, invokes local Qwen synthesis once with all utterances,
and validates routing, pronunciation, prosody, and artifact integrity evidence.

## Story Modes

### creative

The system may create the story and dialogue from the supplied topic. No source
text is required.

### remake

The system may adapt supplied source text into narration and dialogue. The source
text SHA-256 is locked in `story_mode.json`. The adapted utterances must keep
traceable source references, but their wording may differ.

### read_aloud

Display text must be an exact, ordered, gap-free partition of the supplied source
text. Each utterance stores `source_start` and `source_end`; compilation rejects
rewrites, omitted text, overlap, and reordering. Spoken normalization remains a
later pronunciation-layer operation and never changes subtitle text.

## Voice Identity And Versioning

- `voice_id` is the stable operator-facing identity, for example `simon`.
- `profile_id` is an immutable concrete version, for example `simon@v2`.
- Legacy profile identifiers remain selectable as one-version identities.
- Add creates version 1.
- Tune creates the next version and records `parent_profile_id` and tuning.
- Archive disables new selection without breaking existing locked projects.
- Delete is allowed only when no project binding references the profile.
- Reference audio and transcripts remain local runtime data and are never committed.

## Character And Utterance Contracts

Each cast member has a stable `speaker_id`, display name, role, and voice selector.
Every utterance includes:

- `utterance_id`, `scene_id`, `shot_id`, `speaker_id`
- `display_text`
- optional controlled `emotion` and `pace`
- source span fields when required by mode

All speakers must resolve before synthesis. Extras can use an explicit voice or a
deterministic variant of an existing cast voice. The variant changes performance
tuning only and does not pretend to be a distinct trained identity.

## Locked Cast Binding

`voice_cast_binding.json` records the exact profile path and SHA-256 for every
speaker plus variant tuning. Hash drift fails closed. Existing narration prevents
silent cast changes; an explicit revoice operation is required.

## Synthesis And Proof

The local generator loads Qwen once, then swaps full-ICL reference audio and
reference transcript per utterance. It runs the shared zh-TW text normalization,
pronunciation, alignment, and prosody checks per utterance. The multi-character
manifest records expected and actual speaker/profile routing, binding hashes, and
story mode. Routing proof is not mislabeled as acoustic speaker-similarity proof.

## Operator Interface

Natural requests remain primary:

- `List voices.`
- `Add voice Mom from the attached clean recording.`
- `Story dubbing, remake mode. Narrator=Simon, Mom=Mom, lead=YoungMale.`
- `Story dubbing, read-aloud mode. Do not change the source text.`

The agent routes these requests to narrow tools. Internal schema names and version
identifiers are visible for status and audit but are not required prompt syntax.

## Compatibility And Failure Policy

- Projects without dialogue contracts use the existing single-narrator binding.
- Existing narration manifest v4/v5 remains readable.
- Multi-character output uses a new manifest version.
- Missing voice, invalid source coverage, profile drift, or unresolved speaker is
  setup-required and fails before synthesis.
- Stop/cancel remains authoritative during synthesis.


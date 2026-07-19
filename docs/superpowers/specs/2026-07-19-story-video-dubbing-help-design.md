# Story Video Multi-Character Dubbing Help Design

## Goal

Extend the existing `/story-video help` surface so an operator can discover the
Phase 1 voice catalog and provide an explicit story-character-to-voice mapping
without learning internal tool names or JSON schemas.

## User Experience

`/story-video help` remains the single primary help entry. It gains a compact
`多角色配音` section with this truthful workflow:

1. Run `/story-video voices` to inspect ready voices.
2. Provide story text or a story request.
3. Explicitly map every character to a voice.

The copy-ready mapping example is:

```text
多角色配音：旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。
```

The help text states that Phase 1 requires an explicit voice for each character.
It must not promise automatic casting, automatic role analysis, or audio
synthesis capabilities that are not implemented in this phase.

`/story-video examples` and `docs/story-video-operator-guide.md` use the same
voice IDs and explicit-mapping language. Existing commands and guide sections
remain valid.

## Architecture

The change stays in the existing read-only guide path:

- `plugins/story_video/guide.py` owns the rendered help and example text.
- `plugins/story_video/hooks.py` continues routing `/story-video help` and
  natural help requests to the guide without state mutation.
- `docs/story-video-operator-guide.md` mirrors the public examples.

No new tool action, schema field, state contract, registry field, or persistent
artifact is introduced. `story_video_audio_director` remains the internal
compile-and-bind tool, while operator-facing help stays natural-language-first.

## Error And Compatibility Behavior

- Unknown guide sections keep the existing fallback to the main help text.
- `/story-video voices` remains the authoritative availability surface; help
  does not embed or cache readiness state.
- Existing `status`, `examples`, `voices`, and `writing` routes remain read-only
  and backward compatible.
- The legacy `simon` alias remains accepted internally, but new help examples use
  the approved public ID `simon_clean_v2`.

## Verification

TDD adds behavior-focused tests before copy changes:

- main help contains the multi-character workflow, voices command, four approved
  voice names, and the explicit-mapping constraint;
- examples no longer promise automatic casting and show an explicit mapping;
- slash-command help remains read-only and routes to the updated guide;
- the complete story-video test suite and affected-file Ruff checks pass.

Before integration, run diff/privacy hygiene and verify the topic worktree is
clean. Publish the named topic branch to `origin`, open a fork-local PR targeting
`local/main`, wait for required checks, merge through GitHub, then fast-forward
the local protected `local/main` checkout from `origin/local/main`.

## Non-Goals

- Automatic character extraction or casting.
- Automatic voice scoring or role matching.
- New Audio Director actions.
- Multi-engine synthesis or rendered audio delivery.
- Deployment to `runtime/current`.

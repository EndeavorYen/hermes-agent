# Multi-role Story Video Delivery Design

**Date:** 2026-07-19  
**Status:** Approved design, pending implementation  
**Branch:** `fix/story-video/multirole-video-delivery`

## Goal

Turn a natural request containing story text and an explicit character-to-voice
mapping into one playable MP4 delivered back to the originating messaging
thread. The product supports two visual modes:

- `story_visual`: selected story images, multi-role Qwen audio, and hard-burned
  subtitles.
- `black_subtitle`: a fully black background, multi-role Qwen audio, and
  hard-burned subtitles. This mode never invokes an image provider.

Audio files, subtitle files, manifests, and QC reports remain project-local
sidecars. They are evidence and resumable inputs, not the primary deliverable.

## User-visible contract

The operator may provide:

- the source story text;
- a speaker list and voice mapping, such as narrator -> `simon_clean_v2`, child
  -> `Vivian`, parent -> `Serena`, elder -> `Uncle_Fu`;
- an optional story mode: `creative`, `remake`, or `read_aloud`;
- an optional visual mode: `auto`, `story_visual`, or `black_subtitle`.

Explicit visual mode always wins. In `auto`, ordinary story requests use
`story_visual`. Requests that explicitly identify the material as NSFW/adult or
otherwise unsuitable for image generation use `black_subtitle`. When the
visual-suitability decision cannot be made safely, the workflow fails closed to
`black_subtitle`; it does not send the text to an image provider.

Completion means that the selected MP4 is playable and has been exposed to the
gateway as the only current media deliverable. A message saying that rendering
finished, an MP3, or an SRT alone is not completion.

## Existing components to reuse

The implementation extends the existing story-video system instead of creating
a parallel pipeline:

- `StoryVideoStateStore` remains the durable run/session/source binding.
- `compile_dubbing_project` and `bind_project_voice_cast` remain the formal cast
  and dialogue contract.
- `StoryVideoVoiceExecutor` remains the only production Qwen synthesis path.
- the existing story-image keyframe and batch phases remain the
  `story_visual` image path.
- the existing local deterministic story-video renderer remains the MP4
  renderer.
- Hermes process registry and `terminal(background=true,
  notify_on_complete=true)` remain the long-running job mechanism.
- gateway native `MEDIA:` handling remains the attachment delivery mechanism.

No second queue, second voice registry, direct Slack API client, or generic
video provider is introduced.

## Durable run contract

The story-video run context gains a persisted visual mode. The compiled project
also records a production job manifest with these states:

```text
queued -> running -> artifact_ready -> delivered
                    \-> failed
          \-> stopped
```

The manifest records the run id, project directory, visual mode, cast binding
hash, dialogue ledger hash, process id when known, current phase, selected MP4,
sidecars, QC report, failure class, attempts, and timestamps. Writes are atomic.

Starting production is idempotent:

- a valid `artifact_ready` or `delivered` run returns the existing selected
  MP4;
- a running job is not started twice;
- a failed or interrupted job resumes from the first unproved phase;
- delivery retry never repeats synthesis or rendering;
- stop is observed by voice and render subprocesses.

## Routing and phase behavior

Natural multi-role video requests must be recognized as story-video production,
not informational conversation. The gateway binds source, session, and reply
thread before the LLM invokes the audio director. A missing active context is
therefore a routing failure, not an invitation to improvise shell scripts.

The normal `story_visual` phase sequence stays:

```text
planning -> keyframes -> batch -> voice -> render -> complete
```

The `black_subtitle` sequence is:

```text
planning -> voice -> render -> complete
```

Its authorization scopes exclude image generation and vision QC. Phase
validation also rejects image-provider audit events for a black-background run.

During planning, the LLM produces the cast bible and dialogue ledger through
`story_video_audio_director`; it may not write replacement synthesis scripts.
Every utterance must resolve to one hash-locked catalog voice before production
can start.

## Background production

Voice synthesis and rendering are long-running local work and must not keep the
originating Codex turn open. A production tool validates the persisted contract,
then starts the versioned project runner through Hermes' existing tracked
background terminal facility with completion notification enabled.

The runner advances only deterministic local phases:

1. resolve and validate the cast binding;
2. synthesize or reuse per-utterance audio;
3. create or reuse the combined narration timeline and subtitle cues;
4. prepare mode-specific render input;
5. invoke the local renderer;
6. validate media, subtitle, audio, provenance, and mode-specific QC;
7. atomically mark the selected MP4 `artifact_ready`;
8. print a bounded machine-readable completion marker.

The background completion wakes a fresh turn in the original thread. A fast
route calls production status once and returns the selected `MEDIA:<absolute
mp4 path>`. Story-video production tools are included in the gateway's narrow
producer-tool allowlist so an artifact-bearing result is delivered even if the
model omits the tag in its prose.

## Mode-specific rendering

### Story visual

The renderer consumes the current run's selected OpenAI story images. Existing
shot provenance, narration timing, subtitle layout, motion, opening/ending art,
and render proof remain mandatory. Multi-role audio replaces the single
narrator input without weakening those visual gates.

### Black subtitle

The workflow creates a deterministic project-local black source frame and uses
it for all subtitle segments. It does not create candidate manifests, call an
image tool, or require release art. The frame remains visually black after any
renderer transform. Opening and ending are black as well; only subtitles may
be visible.

Black-mode render proof requires:

- H.264/AAC MP4 with a positive duration;
- a video duration matching the combined audio within tolerance;
- hard-burned subtitles covering every utterance in order;
- a sampled-frame luminance check proving the background is black outside the
  subtitle region;
- no image-provider audit events or selected-image provenance;
- the selected output path is inside the current project.

It deliberately does not require cinematic motion, image density, or branded
release cards.

## QC and failure classification

Pre-synthesis gates reject unresolved speakers, invalid voices, uncovered
read-aloud text, invalid source references, and changed locked contracts.

Runtime failures are classified at least as:

- `voice_runtime_missing`;
- `voice_generation_failed`;
- `voice_qc_failed`;
- `asr_accelerator_unavailable`;
- `render_runtime_missing`;
- `render_failed`;
- `render_qc_failed`;
- `delivery_failed`;
- `stopped`.

Metal/MLX aborts retain the existing bounded retry. ASR accelerator absence
must degrade to the configured local fallback or a clearly recorded reduced-QC
path; it may not crash the whole production job or silently claim full ASR
proof. A reduced-QC result is explicit in the QC report and may be accepted only
when all non-ASR audio and text-timeline gates pass.

## Deadline and stale-response hardening

Backgrounding removes voice/render duration from the originating turn. Two
generic safeguards remain:

- story-video target-artifact turns receive a bounded, artifact-aware deadline
  rather than the single-image default;
- if a Codex turn reaches its deadline after a completed media-producing tool
  result, recovery prefers that current-turn artifact result over an earlier
  assistant progress message.

The fallback is restricted to known producer tools, successful results, current
turn paths, supported media types, and existing local files. It cannot promote
arbitrary tool output or historical media.

## Delivery and deduplication

Only the selected MP4 from the current render manifest is eligible for
delivery. Sidecars are omitted unless the operator explicitly requests them.
Existing gateway media identity checks prevent historical or duplicate paths
from being appended.

If native upload fails, the run remains `artifact_ready` with failure evidence.
A retry exposes the same MP4 without regenerating audio or video. Live
acceptance records the Slack channel/thread, final file name, MIME type, size,
and the gateway upload outcome as runtime evidence; private platform details
remain local and are not committed.

## Help surface

Story-video help documents:

- the four available voices and role mapping examples;
- both visual modes and `auto` behavior;
- that the primary output is MP4;
- that black mode never generates images;
- how to request `creative`, `remake`, and exact `read_aloud` production;
- how to inspect status, stop, continue, and retry delivery.

## Test and release evidence

TDD coverage must include:

- natural multi-role MP4 requests create and bind a story-video context;
- visual-mode parsing, precedence, persistence, and fail-closed selection;
- black mode skips keyframes/batch and has no image authorization;
- formal cast/utterance compilation reaches the existing Qwen executor;
- background launch is tracked, idempotent, stoppable, and resumable;
- completion notification fast-routes to selected MP4 status;
- black render input and mode-specific render proof;
- story-visual render compatibility with multi-role narration;
- ASR accelerator fallback and honest reduced-QC evidence;
- deadline recovery prefers a current artifact over stale progress;
- delivery retry does not regenerate and media auto-append is current-turn only;
- help output reflects the production contract.

Release requires focused tests, the relevant wider suites, `git diff --check`,
privacy/diff inspection, fork-local CI, PR merge to `local/main`, exact-SHA
fast-forward to `runtime/current`, supervised gateway restart, and two live
Slack smokes:

1. a short `black_subtitle` multi-role MP4 proving zero image-provider calls;
2. a short `story_visual` multi-role MP4 proving selected images, subtitles,
   audio, render QC, and native attachment visibility.

The feature is not complete if only local tests pass, the runtime still points
to the old SHA, or Slack shows text without the playable MP4 attachment.

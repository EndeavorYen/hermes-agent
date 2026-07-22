# Story Video Role And Emotion Subtitles Design

## Outcome

In `black_subtitle` videos, each non-narrator cue visibly identifies the
character and, when available, the performance emotion. A cue is presented as
two semantic parts, for example:

```text
小王（開心）
「我爸爸看到工作，也會立刻想逃走！」
```

The narrator remains plain subtitle text. TTS synthesis, pronunciation QC, and
subtitle timing continue to use only the original dialogue.

## Current Evidence And Root Cause

The narration manifest already carries `speaker_id`, `emotion`, and raw
`display_text` on every measured voice chunk. The project-local
`voice_cast_binding.json` already maps each `speaker_id` to the requested
Traditional Chinese `display_name`. The black-subtitle render adapter currently
copies only the raw text, speaker id, voice id, timing, and color into each cue.
The renderer consequently has no role name, emotion label, or separate visual
copy to draw.

Changing the existing cue `text` would be incorrect: the renderer deliberately
compares it with scene narration to prove that subtitle timing preserves the
spoken content. A decorated string would either fail that proof or force TTS/QC
to accept non-spoken labels.

## Considered Approaches

1. **Optional `visual_text` beside raw `text` — selected.** The adapter composes
   display-only copy from the cast binding and chunk emotion. The renderer draws
   `visual_text` but continues all narration-preservation checks against `text`.
   Existing render inputs remain valid because the field is optional.
2. **Replace `text` with decorated copy — rejected.** This mixes presentation
   with spoken truth and breaks the existing QC contract.
3. **Add a new structured subtitle-layout framework — rejected.** Separate
   label and dialogue objects could support more typography later, but are not
   needed for this approved behavior and would expand the renderer contract.

## Data Contract

Each measured black-subtitle cue retains:

```json
{
  "text": "你爸爸走路像企鵝？",
  "visual_text": "小美（疑惑）\n「你爸爸走路像企鵝？」",
  "speaker_id": "xiaomei",
  "emotion": "curious",
  "color": "#FF9ECD"
}
```

`text` is the sole spoken/QC source. `visual_text` is render-only and must
contain the exact raw `text`. Narrator cues use identical `text` and
`visual_text`. Missing cast metadata falls back to `speaker_id`; missing or
neutral emotion omits the parenthesized emotion.

Emotion labels are deterministic Traditional Chinese presentation copy:

| Contract value | Visible label |
| --- | --- |
| `wonder` | 驚奇 |
| `curious` | 疑惑 |
| `joy` | 開心 |
| `sadness` | 難過 |
| `fear` | 害怕 |
| `tension` | 緊張 |
| `surprise` | 驚訝 |
| `humor` | 幽默 |
| `warmth` | 溫暖 |
| `neutral` or missing | omitted |

## Rendering And Layout

The shared Pillow renderer accepts optional `visual_text` on measured cues,
preserves forced line breaks, and uses it only for wrapping, drawing, and visual
bounding-box QC. Raw cue text remains the basis of narration coverage QC. Black
subtitle inputs allow three centered lines so one role label plus a dialogue
that wraps to two lines still fits at the existing 72 px size and role color.

## Help And Compatibility

`/story-video help` explains that black-background dialogue subtitles show the
character and emotion while those labels are not spoken. Story-visual mode,
voice generation, pronunciation aliases, pronunciation QC, and existing render
inputs without `visual_text` are unchanged.

## Completion Evidence

- A focused repository test fails before the adapter change and proves raw
  `text`/narration remain undecorated while `visual_text` is decorated.
- A focused renderer test fails before renderer support and proves visual copy
  is parsed/drawn while narration preservation still uses raw text.
- Relevant repository and shared-renderer suites pass.
- A real black-background MP4 rendered from the existing QC-passed multi-role
  narration visibly shows role/emotion labels, retains the original audio, and
  passes media/subtitle QC.
- The accepted commit is merged to `local/main`, deployed as the identical
  `runtime/current` SHA, and the gateway imports the deployed code.

## Non-goals

- No TTS regeneration, pronunciation-policy change, voice selection change, or
  role auto-casting.
- No role/emotion labels in `story_visual` mode in this change.
- No configurable emotion vocabulary or typography framework.

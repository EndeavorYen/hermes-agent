# Story Video Operator Guide

## Help

Use the deterministic story-video command when you do not remember a prompt:

```text
/story-video
/story-video status
/story-video examples
/story-video writing
/story-video voices
```

In Slack, the same command is available through the shared command router:

```text
/hermes story-video status
```

`status` is read-only. It shows the project bound to the current thread, its
phase, manual/auto state, and the exact next operator response. It never starts
or advances production. `/help` also lists `/story-video` once the plugin is
loaded.

Natural requests such as `故事影片怎麼用` and `Raphael 故事影片幫助` use the
same guide, but the slash command is faster because it does not invoke the LLM.

## Writing Depth

Science, history, economics, technology, and other explanatory beats default to
an accessible mode for curious newcomers age 5+ and non-specialist adults. It
uses concrete intuition and a short causal chain before introducing the formal
term, while preserving factual boundaries and forbidding baby talk.

```text
故事影片：凱因斯經濟學｜5分鐘｜電影感科普。全自動
故事影片：凱因斯經濟學｜5分鐘｜進階版。全自動
故事影片：凱因斯經濟學｜5分鐘｜專業版，不要淺白化。全自動
```

Use `/story-video writing` for the current controls. `進階版` keeps more
technical detail for informed generalists. `專業版` or `不要淺白化` selects
the expert-depth path. The selected mode is locked in
`explanation_profile.json` when the project starts.

All new projects also default to a topic-appropriate narrative spine: mystery,
discovery, transformation, choice and consequence, character lens, pattern
reveal, or calm wonder. The script uses a cold open, delayed cross-scene
questions, evidence-based turns, causal scene handoffs, and an ending echo.
These controls do not require extra prompt syntax. They add no fictional danger,
conflict, or certainty to factual work.

## Start

Use one short request:

```text
故事影片：<主題>｜<時長>｜<視覺風格>。全自動製作，完成後上傳 Slack 供 review。
```

Example:

```text
故事影片：恐龍起源｜5分鐘｜適合 5 歲以上、電影感寫實重建。全自動製作，完成後上傳 Slack 供 review。
```

Planning-only remains explicit:

```text
故事影片：恐龍起源｜5分鐘｜電影感寫實重建。只規劃，不產媒體。
```

## Dubbing Modes And Voices

Use `/story-video voices` or `列出故事影片聲線` to see stable voice IDs. A
project binds those stable IDs to immutable concrete profile versions before
synthesis. Phase 1 uses an explicit workflow:

1. Run `/story-video voices` to inspect the available voices.
2. Provide the story text or describe the story you want.
3. Explicitly assign a voice to every character; Phase 1 does not automatically
   cast unassigned characters.

Copy-ready example:

```text
多角色配音：旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。
```

The same explicit mapping can be included in each dubbing mode:

```text
創作模式：依這個主題寫成多角色故事。旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。
重製模式：保留附件故事的核心情節，改寫成 5 歲以上會好奇的繁中故事；旁白用 simon_clean_v2。
說書模式：旁白用 simon_clean_v2，完全照附件原文朗讀，不改字。
```

Tone is optional. Operators can describe ordinary delivery with natural
concepts such as `溫暖／開心／疑惑`; omitting tone lets the audio director map
the utterance's emotion, action, and pace automatically. Adult concepts such as
`親密／挑逗／害羞` are accepted only for a valid `adult_explicit` content
profile. Internal tone IDs remain optional rather than required prompt syntax.

```text
小美這句用溫暖、壓低聲音的方式說；動作只顯示在字幕，不要念出來。
成人全黑字幕影片：這句親密、帶點害羞；動作只顯示在字幕，不要念出來。
```

Character names, emotion labels, and stage directions enrich the visible
subtitle but never enter the TTS transcript. Tone control never silently adds
breathing, gasps, laughter, or sound effects. Lexical vocalizations are spoken
only when they exist in the supplied text. Repeated ellipses are normalized to
a bounded short pause so they cannot create a multi-second gap.

Voice management remains separate from production:

```text
新增故事影片聲線
調整故事影片聲線 simon 的速度
封存故事影片聲線 simon
刪除故事影片聲線 simon
```

## Batch Behavior

- Story-video images and vision QC are locked to `openai-codex`; the global image provider does not override this.
- The style anchor is generated and selected first. Body shots then run in native chunks of up to three images.
- Every body shot receives one initial candidate. The run-wide repair reserve is `min(4, ceil(shot_count * 0.25))`.
- Ordinary shots receive at most two generated candidates across all contract replans. Contract changes do not reset this budget.
- Fresh shots finish before repair work, so one difficult shot cannot block the rest of the film.
- Exhausted ordinary shots may reuse a compatible adjacent selected image as an audited continuity hold. A hard-blocked failed image is never force-selected by the end-to-end budget path.
- Quota, subscription, and authentication failures stop as operator setup requirements. They are not treated as visual QC failures.

## Stop And Resume

Send `停止` or `/stop`. No new provider group starts after the stop is observed. A group already dispatched may finish and persist its results.

Send `繼續` to resume the same run. Selected shots and persisted generation counts are restored from the manifests and are not regenerated.

## Review Boundary

Auto mode may complete production and upload the current selected artifact to Slack for review. YouTube publication remains a separate explicit approval step.

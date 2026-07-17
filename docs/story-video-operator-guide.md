# Story Video Operator Guide

## Help

Use the deterministic story-video command when you do not remember a prompt:

```text
/story-video
/story-video status
/story-video examples
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
synthesis.

```text
創作模式：依這個主題寫成多角色故事；旁白用 simon，其他角色自動選擇可用聲線。
重製模式：保留附件故事的核心情節，改寫成 5 歲以上會好奇的繁中故事；旁白用 simon。
說書模式：旁白用 simon，完全照附件原文朗讀，不改字。
```

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

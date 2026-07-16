# Story Video Operator Guide

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

# Three Little Pigs v7: Sentence Pauses + Stronger Next-scene Pre-roll

## Trigger

Use these notes when a storybook video is technically scene-aligned but still feels rushed because narration starts too soon after a new scene appears.

## User feedback that drove v7

- Sentence-to-sentence rhythm needs small breathing pauses.
- Paragraph/scene transitions should not rely only on silence after the previous paragraph.
- The critical moment is the **start of the next paragraph/scene**: after the image changes, the new picture should hold briefly before narration begins.

## Implementation pattern

Use three independent pause controls:

1. **Sentence micro-pauses**
   - Split scene narration into sentence-sized TTS chunks.
   - Insert short silence between chunks, around `0.25–0.40s`.
   - Keep captions off during these pauses.

2. **Post-speech hold**
   - Keep a modest hold on the current image after narration ends.
   - In v7, this was reduced relative to v6 for most scenes (`~0.22–0.35s`, final ending longer).

3. **Next-scene pre-roll**
   - After cutting to the next image, hold the new image before narration/subtitle starts.
   - In v7, this became the main breathing control: `~0.75–0.90s`.
   - This prevents the feeling that the new scene starts speaking immediately.

## Concrete v7 choices

- Output script: `scripts/render_landscape_v7_sentence_pauses_stronger_preroll.py`
- Output video: `video/three_little_pigs_landscape_v7_sentence_pauses_stronger_preroll_no_bgm.mp4`
- Output subtitles: `subtitles/tw_v3_meijia_scene_aligned_v7_sentence_pauses_stronger_preroll.srt`
- No BGM/SFX.
- 16:9 landscape.
- Stable slow zoom only; no jitter.
- Subtitles stay low and readable, but disappear during pre-roll/post-hold/sentence pauses.

## QC checklist

- `ffprobe` confirms `1920x1080`, H.264, 30fps, AAC audio.
- Contact sheet includes at least:
  - cover
  - new-scene pre-roll with no subtitle
  - matching speech frame with subtitle
  - mid-story pre-roll with no subtitle
  - wolf/action speech frame
  - back cover
- SRT check: no orphan `」` cues.
- Vision QC confirms no blank frames, broken text, watermark, severe crop, or unsafe/scary imagery.

## Lesson

If viewers feel rushed at a scene boundary, first increase **next-scene pre-roll** rather than only adding silence after the previous line. For illustrated narration, the viewer needs time to visually register the new picture before hearing the next sentence.

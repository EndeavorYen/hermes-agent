# Three Little Pigs v4 Scene-Alignment Notes

Concrete lessons from the 2026-05-06 v4 pass of `~/story-video-projects/three-little-pigs-mvp/`.

## User correction that triggered v4

After v3, the user requested:

1. Stable motion only: slow zoom is enough; no shake/jitter because it makes the picture feel unstable.
2. Subtitle/voice/image alignment should be paragraph-level accurate. It does not need word-level precision, but it must not keep showing the old image after narration has moved to the next story paragraph.
3. Temporarily remove BGM/SFX and upgrade that layer later.
4. Add short silent pauses between paragraphs/scenes so the narration feels less rushed and viewers can feel the paragraph boundary.

## Implemented approach

- Output: `video/three_little_pigs_landscape_v4_scene_aligned_no_bgm.mp4`
- Render script: `scripts/render_landscape_v4_scene_aligned.py`
- Subtitle source: `subtitles/tw_v3_meijia_scene_aligned_v4.srt`
- Scene audio folder: `audio/scene_aligned_v4/`

Instead of using one full narration file and estimating timing across the whole script:

1. Split the final narration into storyboard scene paragraphs.
2. Generate one `say -v Meijia` audio file per scene.
3. Measure each scene audio duration using `ffprobe`.
4. Hold each scene image for its own audio duration, plus a deliberate breath gap when the scene ends.
5. Split subtitles into phrase cues inside that scene window only; normally keep captions off during the silent gap unless a deliberate line needs to linger.
6. Concatenate scene MP3 files by re-encoding with `libmp3lame`, not `-c copy`, to avoid non-monotonic timestamp warnings. When adding breath gaps, insert silence segments intentionally instead of relying on accidental encoder padding.
7. Render only mild center zoom (~2.5%) and fades. No shake, no jitter, no visible wandering pan.
8. Mix no BGM/SFX in this alignment pass.

## Recommended pause policy

For children’s storybook videos, silence is part of pacing, not dead air.

- Ordinary scene/paragraph boundary: ~0.4–0.8s silence.
- Major transition, danger beat, emotional turn, or moral lesson: ~0.8–1.2s silence.
- Opening-to-story or story-to-ending: ~1.0–1.5s silence if it feels natural.
- Avoid making every pause identical; use a small set of pause lengths tied to story beats.
- During silence, keep the current image or use a gentle fade/hold. Do not switch too early if the pause belongs to the previous emotional beat.

## Verification outcome

`ffprobe` verified the final MP4:

- Duration: ~135.233s
- Size: ~50.99 MB
- Video: H.264, 1920x1080, 30fps, duration ~135.233s
- Audio: AAC, 22050 Hz, mono, duration ~135.233s

QC frames:

- `video/qc_frames_v4/frame_cover.png`
- `video/qc_frames_v4/frame_scene01_start.png`
- `video/qc_frames_v4/frame_scene03.png`
- `video/qc_frames_v4/frame_wolf.png`
- `video/qc_frames_v4/frame_back_cover.png`

Vision QC passed for all sampled frames. The scene 03 subtitle bug was fixed: no more orphan right quote at the start of the `於是...` caption.

## Reusable rule

For illustrated storybook narration videos, scene/paragraph-level alignment should be the default once a rough cut exposes drift. It is cheaper and usually better than immediate word-level forced alignment:

- scene audio duration controls image duration;
- deliberate scene silence creates breathable paragraph boundaries;
- phrase subtitles live inside the spoken portion of the scene window;
- image changes occur only at story paragraph boundaries;
- forced alignment remains a later upgrade, not the first fix.

For children’s storybook motion, use stable slow center zoom + fades. Avoid shake/jitter.

For alignment/debug passes, remove BGM/SFX until the narration + subtitle + image timing triangle passes QC.

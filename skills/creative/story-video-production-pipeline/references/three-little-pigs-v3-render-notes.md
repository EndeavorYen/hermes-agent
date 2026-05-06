# Three Little Pigs v3 Render Notes — 2026-05-06

Session-specific production notes from the story-video pipeline MVP. Use these as concrete reference points when building the next illustrated narration video.

## Successful v3 structure

- Output: 16:9 landscape storybook video.
- Opening: 4.0s illustrated book-cover image with editable title text.
- Body: 10 scene illustrations with restrained Ken Burns motion and burned Traditional Chinese subtitles.
- Narration: macOS `say -v Meijia` draft voiceover, delayed until after opening.
- Ending: 5.0s illustrated book-back-cover image with closing moral and `酥雞故事書` branding.
- Final verified specs from this run:
  - H.264 MP4, 1920x1080, 30fps
  - AAC mono audio, 22050 Hz
  - Duration ~137.05s
  - File size ~61 MB

## Meijia-specific subtitle handling

`Meijia` / macOS `say` does not emit word or phrase timestamps. For a draft cut:

1. Split the v3 spoken script into short caption phrases.
2. Estimate phrase durations by character count across the real voiceover duration.
3. Offset all subtitle timestamps by the opening-card duration.
4. Burn subtitles via PIL/Pillow if ffmpeg lacks `subtitles`, `ass`, or `drawtext` filters.

Caveat: estimated captions are acceptable for MVP review, but publishable cuts should use scene-by-scene narration files, forced alignment, provider timestamps, or manual timing QC.

## Audible BGM/SFX draft mix

The previous preview had BGM/SFX too quiet for the user to notice. The v3 draft used a deliberately more audible but still narration-subordinate mix:

- Loop gentle placeholder BGM under the full timeline.
- Delay narration until after opening.
- Add sparse story-relevant SFX: page turns, straw rustle, wood/brick taps, wolf wind puffs, ending chime.
- Example draft mix levels from the successful run:
  - BGM around volume `0.135`
  - SFX around volume `0.55`
  - Final volumedetect: mean volume ~`-25.1 dB`, max volume ~`-10.0 dB`
- Verify with `ffmpeg -af volumedetect`, but also do human listening QC because metrics cannot prove the BGM is perceptible or pleasant.

## QC outcomes

Vision spot-checks to run before delivery:

- Front cover: storybook cover feel, readable title/subtitle, no watermark/garbled text.
- Early subtitle frame: Traditional Chinese readable; ensure subtitle box does not cover faces/core action.
- Wolf/action frame: child-friendly tension, not too scary, subtitle readable.
- Back cover: storybook back-cover feel, readable `酥雞故事書`, no watermark/garbled text.

Known minor issue from v3: subtitle boxes may overlap lower bodies/feet. This is acceptable for MVP if faces/core action remain unobscured, but future prompts/renders should reserve more lower safe space or shrink/lower captions.

## Publishability caveats

- Generated placeholder BGM/SFX require replacement or a license ledger before public/commercial release.
- `Meijia` is an MVP/smoke-test voice, not a polished final narrator.
- For commercial-clear Taiwan Mandarin TTS, prefer official licensed voices or local/open-source pipelines with authorized Taiwan Mandarin prompt recordings.

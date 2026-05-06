---
name: story-video-production-pipeline
description: "Use when turning a user's story idea into a reusable illustrated narration video workflow: story discussion, script, storyboard, TTS voiceover, image prompts/generation, subtitles, and final MP4 editing."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [video, storytelling, tts, image-generation, editing, pipeline]
    related_skills: [reference-photo-social-editorial, codex, humanizer, ocr-and-documents]
---

# Story Video Production Pipeline

## Overview

This skill turns a story concept into an illustrated narration video through a repeatable pipeline:

1. Clarify the story and target format.
2. Convert the idea into a spoken script.
3. Break the script into scenes/shots.
4. Generate TTS narration or ingest/clean human-recorded narration audio.
5. Generate scene illustrations with consistent visual direction.
6. Assemble illustrations, voiceover, subtitles, music/SFX, and simple motion into an MP4.
7. Review, iterate, and preserve reusable assets/prompts for future episodes.

The goal is not merely to produce a one-off video; it is to evolve a reusable production system that improves over repeated projects.

## When to Use

Use this skill when the user asks to:

- Develop a story idea into a narrated video.
- Create YouTube/Shorts/Reels/TikTok-style illustrated story content.
- Combine generated illustrations and voiceover into a video.
- Build or refine a repeatable AI-assisted video production workflow.
- Use Codex/image-generation plus TTS plus editing tools to produce story videos.

Do not use this skill for:

- Pure video trimming of existing footage with no story/script pipeline.
- Professional NLE-only tasks that require manual timeline editing in Premiere/DaVinci unless the user specifically wants guidance.
- Image-only generation without narration or video assembly.

## Default Deliverables

For a complete run, produce these artifacts unless the user asks for a narrower slice:

1. `story_brief.md` — concept, audience, tone, theme, format, constraints.
2. `script.md` — final spoken narration, written to sound natural aloud.
3. `storyboard.md` — scene table with narration chunks, visual descriptions, timing, and prompts.
4. `visual_bible.md` — recurring characters, locations, palette, style, negative prompts, aspect ratio.
5. `audio/voiceover.*` — generated TTS narration or cleaned human narration audio.
6. `images/scene_XX.*` — generated illustrations.
7. `subtitles.srt` or `.vtt` — captions aligned to narration.
8. `video/final.mp4` — assembled draft video.
9. `production_notes.md` — what worked, what failed, and prompt/style changes for next iteration.

## Phase 1 — Story Intake

Ask only for information that materially affects the first draft. If the user already gave enough, proceed with assumptions and label them.

Minimum intake fields:

- **Core idea:** what happens?
- **Audience:** children, adults, investors, education, entertainment, etc.
- **Tone:** warm, dark, funny, suspenseful, mythic, documentary, etc.
- **Length:** e.g. 60s, 2 min, 5 min.
- **Format:** 16:9, 9:16, 1:1. If the user says screen/TV/YouTube/storybook, default to 16:9 landscape; use 9:16 only when the target is explicitly mobile shorts/Reels/TikTok.
- **Language:** usually Traditional Chinese unless the user chooses otherwise.
- **Visual style:** watercolor, cinematic anime, children’s book, editorial, 3D, ink, etc.
- **Voice:** gender/age/accent/emotion/speed.
- **Must include / must avoid:** plot points, sensitive content, brands, likenesses, copyrighted styles.

If the user says “先做 MVP”, default to:

- 60–120 seconds
- 6–10 scenes
- 16:9 landscape for general screen/storybook viewing; 9:16 only for social short/mobile-first delivery
- Traditional Chinese narration
- simple low-volume background music/SFX if it helps the story
- subtle Ken Burns motion only

## Phase 2 — Script Writing

Write for speech, not prose.

Rules:

- Use short sentences.
- Prefer concrete imagery and action.
- Avoid dense exposition.
- Read it aloud mentally; remove awkward phrasing.
- Mark emotional beats where the narrator should slow down or pause.
- Keep one narration chunk roughly aligned to one visual scene.
- For children's stories, keep the plot rhythm light and quick: do not over-extend the ending with repeated morals or extra reconciliation beats. Close shortly after the emotional turn lands.
- When polishing a user's oral story, preserve their core plot mechanics and comic turns. If the user corrects a beat (e.g. “the door was simply unlocked”), treat that as canonical instead of replacing it with a more conventional structure.

Recommended script structure for short videos:

1. **Hook** — first 3–8 seconds: a question, surprise, mystery, or emotional image.
2. **Setup** — who/where/what is at stake.
3. **Escalation** — 2–4 beats of change or conflict.
4. **Turn** — discovery, reversal, realization.
5. **Resolution** — consequence, feeling, or lesson.
6. **Closing line** — memorable sentence; optional CTA if appropriate.

## Phase 3 — Storyboard

Convert the script into a table:

| Scene | Time | Narration | Visual | Motion | Image Prompt | Notes |
|---|---:|---|---|---|---|---|
| 01 | 0:00–0:08 | ... | ... | slow push-in | ... | ... |

For illustrated children's story videos, use one image per meaningful situation/setting change, not only one image per paragraph. Add a new illustration when the location changes, a house/room changes, a character takes a visually distinct action, a joke lands, or the emotional state flips. This is especially important when the user says “配圖可以多張一點，有情境切換就需要一張圖.”

Timing heuristics:

- Chinese narration: estimate roughly 4–6 Chinese characters per second depending on voice speed and pauses.
- English narration: estimate roughly 130–160 words per minute.
- Add 0.3–0.8s silence at strong emotional transitions.
- For children’s storybook narration, add short intentional breath gaps between scenes/paragraphs so the story does not feel rushed: usually 0.4–0.8s between ordinary scenes, 0.8–1.2s after major turns, danger beats, or morals, and 1.0–1.5s before/after opening or ending cards when it feels natural.
- Prefer a two-part scene transition rhythm: first hold the previous scene briefly after its narration ends, then cut to the next image and wait a clearly perceptible pre-roll pause before starting the next narration. This solves the common rushed feeling where the picture changes and the next sentence starts immediately. For children’s storybook pacing, bias toward stronger next-scene pre-roll rather than only adding silence after the previous paragraph.
- Avoid scenes shorter than 3s unless intentionally fast-cutting.

## Phase 4 — Visual Bible

Before generating images, create a visual bible to improve consistency.

Include:

- Aspect ratio and resolution.
- Global style line: medium, lighting, palette, detail level, lens/camera feel.
- Character sheets: name, age, face, hair, clothing, silhouette, recurring objects.
- Environment sheets: recurring locations and mood.
- Negative prompts: avoid text artifacts, extra fingers, warped faces, logo/watermark, inconsistent outfit, etc.
- Continuity notes: what must remain identical across scenes.

For recurring characters, generate or select a reference image early when possible, then use it as a reference for later scenes if the image backend supports it.

### Character and Story-Match Gate

When a story has recurring named characters, do not proceed directly from storyboard to full batch generation. Add a consistency gate first:

1. **Character lineup / cast sheet:** generate or create one reference image showing all recurring characters together, with stable names, silhouettes, clothing/accessories, relative sizes, and color accents. Example: three wolves with distinct scarf/vest/tail cues and three pigs with distinct hat/bow/overalls cues.
2. **Per-scene cast ledger:** in the storyboard, explicitly list `characters_present`, `must_show`, `must_not_show`, and `plot_beat` for every scene. This prevents images that are aesthetically good but narratively wrong.
3. **Keyframe preflight:** before generating all scenes, generate 2–4 high-risk keyframes using the cast sheet as reference: one group scene, one action/conflict scene, one joke/reversal scene, and one ending scene.
4. **Vision QC before batch:** inspect the cast sheet and keyframes for: character count, recurring outfit/accessory consistency, correct house/material, correct action, child-safe tone, subtitle-safe composition, and no contradiction with the canonical plot. Regenerate failed keyframes before spending the full image budget.
5. **Reference-based batch:** when supported, use the cast sheet and accepted keyframes as reference images for all scene generations. Repeat identity anchors in every prompt; do not rely on style alone.
6. **Contact-sheet narrative QC:** after batch generation, build a numbered contact sheet and check every scene against the per-scene cast ledger. Mark each scene `pass`, `minor`, or `regenerate`. Regenerate any scene where the wrong characters appear, house type/action is wrong, or the punchline/plot beat is missing.

This gate is mandatory when the user reports that characters changed across images or that images do not match the script. A pretty but story-wrong frame is a failed frame.

## Phase 5 — Image Generation

For each scene, create prompts in this pattern:

```text
[Scene purpose]. [Subject/characters with visual bible details]. [Action/emotion]. [Environment]. [Composition/camera]. [Lighting/color]. [Style]. [Continuity constraints]. No text, no watermark, no logo.
```

Quality checklist per image:

- The scene matches the narration beat.
- Main character identity is consistent.
- Composition has a clear focal point.
- No unwanted text, logo, watermark, broken limbs, or distracting artifacts.
- There is enough negative/empty space if subtitles will overlay the image.
- The image works at the target aspect ratio.

If the user specifically wants Codex image2, use the available Codex/image generation path in the environment. If unavailable, clearly state the fallback image-generation method used.

For a new story style, generate only 1–2 keyframes first and run vision QC before spending generations on the full scene list. Prefer one calm character-introduction image and one high-stakes story image; this tests both character consistency and dramatic readability.

## Phase 6 — Voiceover / TTS

Prepare TTS input separately from the full script:

- Remove markdown, scene numbers, and image notes.
- Keep punctuation that helps pacing.
- Add deliberate pauses using punctuation, provider-supported pause tags, or per-sentence audio chunking if available. Storybook narration should have micro-pauses between sentences, not only between big paragraphs; otherwise it still feels breathless even when scene transitions are aligned.
- Generate one whole voiceover for simple projects, or one file per scene when scene/paragraph alignment matters. For illustrated storybook videos, per-scene narration is the preferred default once the first rough cut shows image/subtitle drift.
- When using per-scene narration, insert explicit silence between scene audio segments during assembly instead of concatenating speech back-to-back. This gives viewers time to absorb the picture and makes paragraph boundaries feel intentional rather than rushed.
- For scene changes, split silence into a post-speech hold and a next-scene pre-roll where possible: e.g. 0.20–0.45s holding the current image after speech, then 0.60–0.95s showing the next image before its narration starts. If the user says the next paragraph still starts too quickly, increase the next-scene pre-roll first, not the previous-scene post-hold.

### Human Narration Mode

Human narration and TTS should coexist as two interchangeable voiceover modes. If the user wants to record their own reading, replace the TTS generation step with a human-recorded audio intake and cleanup step, while keeping the rest of the pipeline: storyboard, image generation, subtitles, timeline assembly, QC, and publishing.

Supported modes:

1. **TTS mode:** generate narration from `voiceover_text.txt` or per-scene text chunks.
2. **Human narration mode:** user records the final script and uploads audio/video; extract and use the human voice as the canonical narration.
3. **Hybrid mode:** use TTS for drafts/timing, then swap in human narration for final render.

Recommended recording instructions for the user:

- Record in a quiet room, close enough to the mic but without popping.
- Use a consistent mic and distance for the whole story.
- Read the exact final script when possible.
- Leave a small pause between paragraphs/scenes; do not rush after page/scene breaks.
- If a sentence goes wrong, pause, clap or say “重來”, then reread the sentence; this makes cleanup easier.
- Upload WAV/M4A/MP3 audio, or a video file if audio is embedded. Prefer WAV/M4A for quality.

Human narration intake checklist:

- Save the original upload under `audio/source/` without overwriting it.
- Extract audio if needed: `ffmpeg -i input.mov -vn audio/source/human_raw.wav`.
- Normalize format for editing: mono or stereo WAV, 44.1k/48kHz.
- Light cleanup only by default: trim leading/trailing silence, remove obvious retakes, normalize loudness, avoid heavy noise reduction that makes the voice metallic.
- Measure duration with `ffprobe`.
- If the user recorded one full file, align scenes by waveform/manual markers, transcript timing, or rough forced alignment.
- If the user can record one file per scene, prefer that for easiest scene-level synchronization.

Alignment strategy for human narration:

- Treat the human audio as the timing source of truth; do not force it to match earlier TTS estimates.
- Build scene `speech_ranges` from actual audio timing.
- Keep the same visual rhythm rule: after each scene's speech, hold briefly, cut to the next scene, then allow a visible next-scene pre-roll before the next narration begins when possible.
- If the human recording already contains natural pauses, preserve them unless they feel too long or accidental.
- Captions should follow what was actually spoken. If the narrator paraphrased the script, update subtitles to the spoken version rather than blindly using the original script.

Human narration QC:

- Confirm language and voice are correct.
- Check for clipping, room hum, mouth noise, sudden volume changes, missing lines, and accidental retakes.
- Spot-check that scene changes happen at natural breath points.
- If a major line is missing or unclear, ask for a pickup recording for that line/scene instead of rerecording the entire story.

Voice selection notes:

- Children’s story: warm, gentle, moderate speed.
- Suspense: lower energy, slower, more pauses.
- Educational explainer: clear, crisp, neutral warmth.
- Emotional story: natural breath and slower cadence.

After TTS, verify duration and listen/inspect enough to catch major issues: wrong language, clipped audio, unnatural speed, or pronunciation errors.

If the configured Hermes TTS provider fails during a Traditional Chinese draft, use a local fallback when available before blocking the workflow. On macOS, a practical draft-quality fallback is:

```bash
say -v Meijia -r 165 -o voiceover.aiff -f voiceover_text.txt
ffmpeg -y -i voiceover.aiff -codec:a libmp3lame -q:a 4 voiceover.mp3
```

Treat this as preview audio unless the user approves the voice quality for final delivery.

If Hermes TTS fails but `edge-tts` CLI is available, prefer direct Edge neural TTS for a stronger Traditional Chinese draft before falling back to `say`. Example:

```bash
edge-tts --voice zh-TW-HsiaoYuNeural --rate=+0% --pitch=+0Hz \
  -f audio/voiceover_text.txt \
  --write-media audio/voiceover_edge_hsiaoyu.mp3 \
  --write-subtitles subtitles/edge_hsiaoyu.vtt
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 audio/voiceover_edge_hsiaoyu.mp3
```

When `edge-tts` produces `.vtt`, use it as the preferred editable timing source, then offset subtitle timestamps by the opening-card duration before burning subtitles into the MP4.

For publishable narration, evaluate a higher-quality neural TTS path instead of relying on `say`. Preferred improvement dimensions:

- More natural Traditional Chinese prosody and sentence rhythm.
- Stable narrator identity across episodes.
- Adjustable speaking rate and pauses.
- Better handling of expressive lines such as 「呼——」.
- Audio post-processing: trim silence, normalize loudness, light compression/EQ, and avoid clipped peaks.

TTS engine selection guidance for Traditional Chinese / Taiwan Mandarin story videos:

1. **Fast free prototype:** `edge-tts` with `zh-TW-HsiaoYuNeural`, `zh-TW-HsiaoChenNeural`, or `zh-TW-YunJheNeural`. It is practical and produces subtitle timing, but it uses an unofficial Microsoft Edge Read Aloud path; avoid treating it as a clear commercial license.
2. **Formal/commercial cloud path:** Azure AI Speech with official zh-TW neural voices. This is the cleanest upgrade from `edge-tts` because the voices are similar/related but the API/license path is official. Use SDK word-boundary/bookmark events for subtitles.
3. **Best open-source/local Chinese experiments:** CosyVoice 2/3, F5-TTS, and GPT-SoVITS. CosyVoice is the strongest Apache-licensed Chinese candidate; F5-TTS is Mac-friendlier but many pretrained models are non-commercial; GPT-SoVITS is useful for a fixed authorized narrator voice but is heavier.
4. **Local voice-studio experiments:** Voicebox (`jamiepine/voicebox`, MIT) and Moxin Voice (`moxin-org/Moxin-Voice`, Apache-2.0) are promising local GUI/studio options. Treat them as experimental until Taiwan Mandarin quality, CLI/API stability, long-text chunking, and model licensing are verified. Moxin is Apple-Silicon-only and not clearly zh-TW; Voicebox supports `zh` but not explicitly Taiwan Mandarin.
5. **Lightweight offline fallbacks:** Kokoro, MeloTTS, sherpa-onnx, Piper. These are useful for local/offline tests or product embedding, but usually need listening tests before using as a polished children's narrator.

When quality matters, generate short A/B samples first: baseline `edge-tts`, one official/commercial candidate, and one local/open-source candidate. Compare pronunciation, warmth, pacing, Taiwan usage, listener fatigue, subtitle timing support, and license risk before rendering the full narration.

Commercial-use filter for free/local TTS:

- Do not treat `edge-tts` as commercially clear; it is useful as a quality/reference draft through an unofficial Microsoft Edge Read Aloud path, but publish/commercial use should move to an official license path or permissively licensed local model.
- Strongest commercially permissive Chinese candidates to sample first: CosyVoice2 (`Apache-2.0`) for quality, Kokoro (`Apache-2.0`) for lightweight multilingual experiments, Piper voices (`MIT`, but Mandarin quality is basic), Moxin-Voice (`Apache-2.0`, Apple-Silicon GUI/early-stage), GPT-SoVITS code (`MIT`) only when the chosen pretrained model and speaker data are also commercially cleared.
- CosyVoice2 commercial/quality caveat: the repo/model license can be Apache-2.0, but zero-shot voice identity inherits risk from the prompt voice and can fail Mandarin intelligibility when the prompt is a synthetic/system voice. For commercial-clear Taiwan Mandarin, use an explicitly authorized natural prompt recording (e.g. user/paid narrator consent), not Apple `say`, Edge voices, official demo prompts, or random public clips. A `say -v Meijia` prompt is useful only as a negative/technical smoke test and must not be presented as a candidate final narrator unless human listening QC confirms standard, intelligible Chinese.
- F5-TTS official HF model card currently marks the main pretrained release as `CC-BY-NC-4.0`; do not use those weights commercially unless a separate commercial-clear model/voice is selected.
- Orpheus-TTS repo/model card is `Apache-2.0` and therefore commercially permissive at the model/license layer, but current primary release is English and Llama-based; verify multilingual/Taiwan Mandarin quality and any base-model/license notices before using it in a commercial zh-TW story pipeline.
- Voicebox app code is `MIT`, but it can wrap external models; commercial safety depends on the specific bundled/downloaded model and voice-clone consent, not the app license alone.

## Phase 7 — Subtitles

Default subtitle style:

- Traditional Chinese: 1–2 lines max.
- High contrast: white text with dark stroke/shadow.
- Bottom safe area, but avoid covering main subject; for storybook videos, place subtitles low enough to leave the main artwork open, while still inside TV/mobile safe margins. If the user says subtitles cover too much of the scene, move the subtitle box down before shrinking text.
- Break captions by spoken phrase, not by arbitrary character count.
- Keep Chinese closing punctuation with its sentence; do not allow orphan cues such as a standalone `」` or captions beginning with `」於是...`.

Alignment rule for illustrated story videos:

- If the user complains that narration has moved to the next paragraph while the old image is still on screen, switch from one global estimated subtitle timeline to scene/paragraph-level alignment.
- Preferred practical method: split the final script into storyboard scenes, generate or render one narration file per scene, measure each scene audio duration with `ffprobe`, add a deliberate inter-scene silence pad, hold the corresponding image for `audio duration + silence pad`, and distribute phrase captions only inside the spoken portion of that scene window.
- Implement scene pauses as first-class timeline data, not as accidental TTS/encoder padding: keep separate `speech_ranges` for subtitles and `visual_ranges` for image holds, and when possible split transition silence into `post_hold` and `pre_roll`: `scene_i_visual_end = scene_i_speech_end + post_hold_i`, `scene_{i+1}_visual_start = scene_i_visual_end`, `scene_{i+1}_speech_start = scene_{i+1}_visual_start + pre_roll_{i+1}`. Concatenate audio as `[scene_01, post_hold_01 + pre_roll_02 silence, scene_02, ...]`, render visuals from visual ranges, and subtitles from speech ranges.
- Captions should normally disappear or stay off during the inter-scene silence pad unless a deliberate closing line needs to linger briefly. This keeps the pause visually breathable instead of feeling like a subtitle timing error.
- This paragraph/scene-level alignment is usually enough for children's storybook videos; do not spend effort on word-level forced alignment unless the user needs karaoke-like precision or the scene-level pass still fails QC.
- If per-scene audio is unavailable, use forced alignment or manual timing QC as the next fallback. Always keep an editable `.srt` / `.vtt` source.

Use `.srt` for broad compatibility or `.ass` when styling matters. Always keep an editable subtitle source in addition to any burned-in preview.

If the local ffmpeg build lacks `ass`, `subtitles`, or `drawtext` filters, do not block. Use a fallback renderer: generate subtitle-overlaid frames with PIL/Pillow, then pipe raw RGB frames into ffmpeg and attach/mix the voiceover, BGM, and SFX. Preserve the render script under the project, for example `scripts/render_landscape_v1.py`, so later cuts are reproducible.

When using the PIL renderer, verify the final MP4 with `ffprobe` because audio-filter duration choices can silently cut ending audio. Prefer padding/trim logic that makes video and audio durations match the intended timeline, e.g. `apad`, `amix=duration=longest`, then `atrim=0:<TOTAL>` and `-shortest`.

## Phase 7.5 — Opening and Ending Cards

For story videos, reserve timeline space unless the user declines:

- Opening: 2–4 seconds with title, story mood, optional episode label.
- Ending: 3–5 seconds with closing moral, credits, or CTA.

These cards should match the visual bible and should be included in the storyboard timing so subtitle and narration offsets stay correct.

For higher-quality story videos, generate opening and ending as real illustration assets through the same image-generation path as the story scenes, not as plain programmatic cards. The ending should unify the visual style and emotional closure of the episode. Generate without text/watermark, then overlay editable title/ending text during video assembly so typography stays controllable.

## Phase 8 — Video Assembly

Preferred simple assembly approach:

- Use Python MoviePy or ffmpeg.
- Set canvas to target aspect ratio.
- For each scene, display the image for the narration segment duration plus its planned inter-scene breath gap.
- Apply subtle motion: slow center zoom and gentle fades are the default for storybook videos.
- Keep motion restrained for children's storybook videos; avoid shake, jitter, constant aggressive movement, and obvious directional wandering. Prefer about 2–4% slow center zoom over a scene with short fades or gentle dips between major beats. Add pan only when it clearly supports composition.
- Add voiceover.
- Add subtitles.
- Align subtitles to the actual rendered voiceover duration, not only the estimated script timing. If the voiceover starts after an opening card, offset subtitle timestamps by the opening duration.
- Add background music/SFX only after the core narration + image + subtitle alignment passes QC, unless the user explicitly asks for audio design in the first draft. For alignment-fix passes, omit BGM/SFX entirely so narration clarity and scene timing can be judged cleanly.
- When adding background music/SFX, use only licensed/generated assets and mix low enough not to obscure speech. For drafts, generated placeholder music/SFX is acceptable; for final delivery, document licensing or generation provenance.
- For free/commercial-safer BGM/SFX, prioritize: YouTube Audio Library, Pixabay Music/SFX, Mixkit, and Freesound CC0. If attribution is acceptable, Uppbeat free tier and Zapsplat free tier are usable but require careful credit/license tracking. Avoid NonCommercial licenses. For serious long-term monetized channels, consider paid libraries like Epidemic Sound, Artlist, Soundstripe, Envato Elements, or Zapsplat paid.
- Keep a per-asset license ledger: asset name, author, source URL, download date, license type, commercial/YouTube monetization status, attribution requirement, usage timecode, and saved license screenshot/terms.
- Mix audibly but under narration: start BGM roughly 18–24 dB below narration with ducking around important lines; place sparse SFX around 10–18 dB below narration. For children’s storybook videos, use gentle cues such as page turn, forest ambience, soft wind, straw rustle, wood taps, brick placement, friendly wolf puff, and warm ending chime.
- Export H.264/AAC MP4.

Recommended technical defaults:

- 1920x1080 for landscape screen/storybook/YouTube output.
- 1080x1920 only for vertical shorts/mobile-first output.
- 30 fps.
- H.264 video, AAC audio.
- Loudness: voice clear; music/SFX low enough to support, not compete. For drafts, keep music very low and add only sparse story-relevant SFX such as wind, footsteps, door knock, or page-turn.

Basic ffmpeg/MoviePy verification:

- Confirm video duration roughly matches voiceover plus opening/ending plus planned inter-scene pauses.
- Confirm audio exists and is not silent.
- Confirm dimensions/aspect ratio.
- Spot-check opening, middle, ending frames.
- Spot-check at least one planned inter-scene pause frame: it should usually hold the previous/owning scene image with no subtitle, not flash blank or jump early to the next scene.
- Ensure subtitles are readable.

## Phase 8.5 — YouTube Publishing Automation

When the user wants Hermes to upload story-video outputs to YouTube automatically, treat publishing as a separate gated phase after render QC. Do not upload before the final MP4 has been verified and the user has approved title/description/visibility unless they explicitly authorized autonomous publishing for this project.

Recommended OAuth setup for YouTube uploads:

1. In Google Cloud, enable **YouTube Data API v3** for the project.
2. Create an OAuth 2.0 **Desktop app** client and download the JSON file.
3. If the OAuth consent screen is in Testing, add the user's Google account as a test user.
4. Use the narrow upload scope `https://www.googleapis.com/auth/youtube.upload` rather than broad Google Workspace scopes.
5. Prefer storing the client secret/token under `~/.hermes/` with `chmod 600`; never paste secrets into chat or save them in project artifacts.
6. Generate an auth URL, have the user approve it in the browser, then exchange the returned `http://localhost/?code=...` redirect URL for a token. The browser may show “unable to connect” after redirect; this is expected because no local web server is listening. Ask the user to paste the complete redirected URL.

A reusable OAuth helper is available at `scripts/youtube_oauth.py`. Copy or run it from the skill directory, for example:

```bash
python scripts/youtube_oauth.py auth-url --client-secret ~/.hermes/youtube_client_secret.json
python scripts/youtube_oauth.py auth-code 'http://localhost/?code=...'
python scripts/youtube_oauth.py check
```

OAuth pitfalls learned from live setup:

- `redirect_uri_mismatch` usually means the OAuth client type/redirect URI is wrong. For this local uploader, prefer a **Desktop app** client whose JSON has top-level `installed` and usually `redirect_uris: ["http://localhost"]`; update the helper redirect URI to match exactly.
- If the app is in Google OAuth **Testing**, add the signing-in Google account under **Audience → Test users** before retrying; otherwise Google returns `403 access_denied` / app not verified.
- Google OAuth with PKCE requires persisting the generated `code_verifier` between `auth-url` and `auth-code`. If token exchange returns `invalid_grant: Missing code verifier`, regenerate the auth URL using a helper that stores pending state/verifier (the bundled helper writes `~/.hermes/youtube_oauth_pending.json`) and have the user authorize again.
- OAuth codes are single-use and state-bound. If a helper is patched or the auth URL is regenerated, old redirect URLs cannot be reused.

macOS/Hermes gateway pitfall: a file in `~/Downloads` can exist but still fail with `PermissionError: [Errno 1] Operation not permitted` because the background agent lacks TCC permission for Downloads. If that happens, ask the user to copy the OAuth JSON into `~/.hermes/youtube_client_secret.json` themselves, then continue from there:

```bash
mkdir -p ~/.hermes
cp "/Users/simon/Downloads/client_secret_....json" ~/.hermes/youtube_client_secret.json
chmod 600 ~/.hermes/youtube_client_secret.json
```

Publishing defaults for this user's story-video workflow:

- Treat YouTube upload as a real external side effect: after OAuth is authenticated, still ask for explicit approval of the exact file and metadata before the first upload unless the user has already authorized autonomous publishing for that project.
- Use `private` or `unlisted` for first automated uploads.
- Include title, description, child-directed/audience setting, tags, language, thumbnail/cover if available, and license notes.
- Preserve upload metadata in `production_notes.md` without storing tokens or client secrets.

## Phase 9 — Iteration Loop

After each draft, review along these axes:

1. **Story clarity:** does a viewer understand the premise in the first 10 seconds?
2. **Emotional pull:** is there a reason to keep watching?
3. **Voice quality:** natural, paced, correct language/pronunciation? For human narration: clean, unclipped, complete, and free of accidental retakes?
4. **Visual continuity:** characters and world remain consistent?
5. **Scene rhythm:** does it feel like video, not slides?
6. **Subtitle readability:** readable on mobile?
7. **Production efficiency:** which steps were manual and should be automated next?

Record lessons in `production_notes.md`. If the workflow changes in a reusable way, update this skill.

## Common Pitfalls

1. **Writing article prose instead of spoken narration.** Fix by reading aloud and shortening sentences.
2. **Generating images before locking the visual bible.** This causes inconsistent characters and wasted generations.
3. **One image per paragraph instead of per beat.** Story videos need visual rhythm; split at emotional/action beats.
4. **Subtitles or images drift from narration.** Fix at the scene/paragraph level first: split narration by storyboard scene, measure each audio chunk, hold that scene image for the chunk duration, and constrain captions to that scene window. Use forced alignment only if scene-level alignment is insufficient.
5. **Treating TTS as the only narration path.** Human narration should be a first-class mode: ingest the user's recording, clean it lightly, make the actual recording the timing source of truth, and continue with subtitles/image/video assembly.
6. **Story narration feels rushed even though scenes are aligned.** Distinguish three pause types: (a) sentence micro-pauses inside a scene, (b) post-speech holds after a paragraph ends, and (c) next-scene pre-roll before the new paragraph begins. If the picture changes and narration starts immediately, the problem is insufficient pre-roll, not insufficient ending silence. Make captions disappear during these pauses so they feel intentional.
7. **Subtitles cover the subject.** Reserve safe space in prompts or move captions.
8. **Music too loud or added too early.** Voice must be dominant; for timing/debug passes, remove BGM/SFX until narration, subtitles, and image changes pass QC.
9. **No verification pass.** Always inspect duration, audio, dimensions, and sample frames before delivery.
10. **Overbuilding the first run.** Start with a small MVP, then improve automation after seeing failures.
12. **Publishing automation failures are often OAuth state/config issues, not YouTube upload issues.** For local story-video uploaders, use a Desktop OAuth client, exact `http://localhost` redirect when that is what the JSON declares, add the account as a Test user while the app is in Testing, and persist PKCE `code_verifier` between auth URL generation and token exchange.

## MVP Recipe

Use this when the user wants to start quickly:

1. Draft a `story_brief.md` with assumptions.
2. Write a 60–120 second spoken script.
3. Split into 6–10 scenes.
4. Create a visual bible.
5. Generate one image prompt per scene.
6. Generate TTS voiceover, or ingest/clean the user's human-recorded narration.
7. Generate scene images.
8. Assemble MP4 with simple zoom/fade and subtitles.
9. Deliver draft plus notes for next iteration.

## References

- `references/three-little-pigs-v3-render-notes.md` — concrete v3 MVP notes for a 16:9 children’s storybook video using Meijia draft narration, estimated subtitle timing, illustrated front/back covers, and an audible-but-subordinate BGM/SFX mix.
- `references/three-little-pigs-v4-scene-alignment-notes.md` — concrete v4/v5 notes for fixing drift with scene-by-scene narration, paragraph-level subtitle/image alignment, deliberate inter-scene silent breath gaps, stable slow zoom, and no BGM/SFX during timing QC.
- `references/three-wolves-story-draft-notes.md` — session notes for a Traditional Chinese children's story video: light pacing, preserving the user's unlocked-door joke, using more images at situation changes, contact-sheet vision QC, and avoiding ffmpeg concat duration drift from mixed-rate MP3s.
- `templates/scene_aligned_pauses_timeline.py` — reusable starter pattern for per-scene TTS, explicit silence pads, separate `speech_ranges`/`visual_ranges`, and duration probing with `ffprobe`.
- `scripts/youtube_oauth.py` — reusable narrow-scope YouTube upload OAuth helper for story-video publishing (`youtube.upload` token, Desktop-app `http://localhost` redirect, PKCE pending verifier/state persistence).
- `scripts/youtube_upload.py` — reusable YouTube upload helper using `~/.hermes/youtube_token.json`; supports title, description, privacy, made-for-kids flag, tags, category, and optional thumbnail. Thumbnail setting can briefly fail right after upload because YouTube has not indexed the new private video yet; the helper retries thumbnail upload before reporting final status.

## Verification Checklist

Before telling the user the video is ready:

- [ ] Script is spoken-language friendly.
- [ ] Scene count and duration match requested length.
- [ ] Visual bible exists before image prompts.
- [ ] All required images exist and pass basic visual QC.
- [ ] Voiceover exists, duration is plausible, and language is correct. If human-recorded, the cleaned file is complete, unclipped, and free of obvious retakes.
- [ ] Subtitles exist or user explicitly declined subtitles.
- [ ] Final MP4 exists.
- [ ] MP4 duration, dimensions, video stream, and audio stream are verified.
- [ ] Opening/middle/ending frames are spot-checked.
- [ ] Production notes capture reusable improvements for next run.

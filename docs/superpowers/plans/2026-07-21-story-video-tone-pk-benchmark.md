# Story Video Tone A/B PK Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and verify a 56-pair black-subtitle MP4 that compares neutral and tone-mapped Qwen delivery while holding text, cast, model, chunking, random seed, and loudness constant.

**Architecture:** Add one internal operator harness that prepares two private variant projects from a hash-bound source, validates fair A/B routing, normalizes takes, builds a paired timeline, and renders the final MP4. Extend the machine-local Qwen generator with explicit canonical chunks and deterministic per-chunk MLX seeds so both variants use the same sampling control. Private annotations, scripts, audio, ASR output, and video remain in runtime state; only generic harness code, sanitized tests, spec, and plan are versioned.

**Tech Stack:** Python 3.11, pytest, Qwen3-TTS through MLX-Audio, `mlx.core.random.seed`, existing Hermes story-video tone catalog, FFmpeg/FFprobe, ASS subtitles, Qwen3-ASR, JSON manifests.

## Global Constraints

- The first acceptance run binds the existing private 56-utterance ledger and locked cast binding by SHA-256; no source text enters git.
- The user-visible output contains exactly 56 ordered A/B pairs.
- A is `general.neutral`, natural pace, no modifiers, and `neutral_noop`.
- B uses an explicit run-local non-neutral annotation for every intended expressive utterance.
- A and B use the same speaker, voice ID, engine, model/profile, canonical chunks, deterministic seed, and loudness target.
- Qwen full ICL preserves exact reference audio/reference text and receives no instruction string.
- CustomVoice instructions are catalog-owned Traditional Chinese only.
- No hidden breath, gasp, moan, laughter, label, action, or sound effect is added.
- Post-utterance pauses remain at or below 0.45 seconds.
- Per-pair integrated-loudness difference is at most 0.5 LUFS.
- The final output is 1920x1080 H.264/AAC with pure black background and hard-burned Traditional-Chinese subtitles.
- Source text, annotations, generated media, provider output, and acoustic traces remain local and uncommitted.

---

### Task 1: Build The Hash-Bound Pair Plan

**Files:**
- Create: `scripts/story_video_tone_pk.py`
- Create: `tests/scripts/test_story_video_tone_pk.py`

**Interfaces:**
- Consumes: source `dialogue_ledger.json`, `voice_cast_binding.json`, `story_mode.json`, and a run-local `tone_annotations.json`.
- Produces: `stable_pair_seed(run_id: str, utterance_id: str, chunk_index: int) -> int`, `split_canonical_chunks(text: str, expressive_tone_id: str) -> list[str]`, `build_pair_plan(source_project: Path, run_id: str, annotations: dict[str, dict[str, Any]], expected_utterance_count: int) -> dict[str, Any]`, and the `prepare` CLI subcommand.

- [ ] **Step 1: Write failing tests for stable seeds, exact chunking, and source binding**

```python
def test_pair_plan_holds_seed_text_voice_and_chunks_constant(tmp_path):
    source = sanitized_source_project(tmp_path, utterance_count=2)
    annotations = {
        "U0001": {"tone_id": "general.puzzled", "intensity": 2, "pace": "quick", "modifiers": []},
        "U0002": {"tone_id": "adult.breathless", "intensity": 2, "pace": "quick", "modifiers": ["urgent"]},
    }
    plan = tone_pk.build_pair_plan(
        source_project=source,
        run_id="tone-pk-test",
        annotations=annotations,
        expected_utterance_count=2,
    )
    for pair in plan["pairs"]:
        assert pair["neutral"]["generation_seeds"] == pair["expressive"]["generation_seeds"]
        assert pair["neutral"]["spoken_text"] == pair["expressive"]["spoken_text"]
        assert pair["neutral"]["voice_id"] == pair["expressive"]["voice_id"]
        assert pair["neutral"]["canonical_voice_chunks"] == pair["expressive"]["canonical_voice_chunks"]
    assert max(map(len, plan["pairs"][1]["neutral"]["canonical_voice_chunks"])) <= 18


def test_pair_plan_rejects_hash_or_annotation_drift(tmp_path):
    source = sanitized_source_project(tmp_path, utterance_count=2)
    with pytest.raises(tone_pk.TonePkError, match="annotation IDs"):
        tone_pk.build_pair_plan(
            source_project=source,
            run_id="tone-pk-test",
            annotations={"U0001": expressive_annotation()},
            expected_utterance_count=2,
        )
```

- [ ] **Step 2: Run the tests and confirm the expected RED state**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/scripts/test_story_video_tone_pk.py -q
```

Expected: collection fails because `scripts.story_video_tone_pk` does not exist.

- [ ] **Step 3: Implement the pure pair-plan contract**

Use these exact public signatures:

```python
class TonePkError(RuntimeError):
    pass


def stable_pair_seed(run_id: str, utterance_id: str, chunk_index: int) -> int:
    payload = f"{run_id}\0{utterance_id}\0{chunk_index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFFFFFF


def split_canonical_chunks(text: str, expressive_tone_id: str) -> list[str]:
    max_chars = 18 if expressive_tone_id == "adult.breathless" else 36
    chunks = split_exact_text_on_sentence_then_clause(text, max_chars=max_chars)
    if "".join(chunks) != " ".join(text.split()):
        raise TonePkError("canonical chunking changed spoken text")
    return chunks


def build_pair_plan(
    *,
    source_project: Path,
    run_id: str,
    annotations: dict[str, dict[str, Any]],
    expected_utterance_count: int,
) -> dict[str, Any]:
    """Validate immutable inputs and return same-seed/same-chunk A/B specs."""
```

The returned schema is `story_video_tone_pk_plan_v1`. Each pair contains
`pair_id`, `utterance_id`, `order`, `speaker_id`, `action`, `display_text`,
`spoken_text`, `voice_id`, `engine`, `canonical_voice_chunks`, plus `neutral`
and `expressive` take objects. Each chunk records its own seed from
`stable_pair_seed(run_id, utterance_id, chunk_index)`.

- [ ] **Step 4: Implement `prepare` without committing private content**

The CLI must write the following under the requested local output project:

```text
manifests/tone_pk_plan.json
annotations/tone_annotations.json
variants/neutral/dialogue_ledger.json
variants/neutral/voice_cast_binding.json
variants/expressive/dialogue_ledger.json
variants/expressive/voice_cast_binding.json
```

Both ledgers use `story_video_dialogue_ledger_v2`, `content_rating =
adult_explicit`, identical utterance IDs/text/chunks/seeds, and different tone
objects only. Copied story-mode and cast files stay inside the local output
project.

- [ ] **Step 5: Run focused and privacy tests**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/scripts/test_story_video_tone_pk.py -q
rtk git diff --check
rtk git status --short
```

Expected: focused tests pass; only the generic script and sanitized test are visible to git.

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/story_video_tone_pk.py tests/scripts/test_story_video_tone_pk.py
git commit -m "feat(story-video): prepare tone PK pairs"
```

---

### Task 2: Add Deterministic Seed And Canonical-Chunk Evidence To Local Qwen

**Files:**
- Modify locally: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/generate_qwen_story_narration.py`
- Modify locally: `/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py`

**Interfaces:**
- Consumes: optional `canonical_voice_chunks: list[str]` and `generation_seeds: list[int]` on each v2 ledger utterance.
- Produces: the same canonical chunks and `generation_seed` evidence in every v7 narration-manifest voice chunk.

- [ ] **Step 1: Write failing local-runtime tests**

```python
def test_cast_synthesis_applies_seed_immediately_before_each_inference(tmp_path):
    applied = []
    model = RecordingCustomVoiceModel()
    module.synthesize_qwen_cast_segments(
        segments=[custom_segment(tmp_path, generation_seed=12345)],
        offline=True,
        model_loader=lambda _path: model,
        seed_setter=applied.append,
        audio_writer=fake_audio_writer,
        postprocessor=fake_postprocessor,
        cache_clearer=lambda: None,
    )
    assert applied == [12345]
    assert model.calls[0]["speaker"] == "Vivian"


def test_manifest_honors_supplied_canonical_chunks_and_seeds(project):
    project.utterance["canonical_voice_chunks"] = ["第一段，", "第二段。"]
    project.utterance["generation_seeds"] = [11, 22]
    result = run_generator_with_fakes(project)
    chunks = result["outputs"][0]["segments"][0]["voice_chunks"]
    assert [row["display_text"] for row in chunks] == ["第一段，", "第二段。"]
    assert [row["generation_seed"] for row in chunks] == [11, 22]
```

- [ ] **Step 2: Run the local test and confirm RED**

Run:

```bash
PYTHONPATH=/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts:/Users/simon/.hermes/.venvs/mlx-audio/lib/python3.11/site-packages \
  /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py \
  -q
```

Expected: the new tests fail because `seed_setter` and canonical chunks are unsupported.

- [ ] **Step 3: Implement seed injection at the model boundary**

Add `seed_setter: Callable[[int], Any] | None = None` to the existing function
signature. Immediately after the optional MLX dependency wiring, insert:

```python
if seed_setter is None and any("generation_seed" in row for row in segments):
    import mlx.core as mx

    seed_setter = mx.random.seed
```

Inside the per-segment loop, immediately before the `qwen_full_icl` versus
`qwen_custom_voice` branch and therefore immediately before model inference,
insert:

```python
seed = segment.get("generation_seed")
if seed is not None:
    if type(seed) is not int or not 0 <= seed <= 0x7FFFFFFF:
        raise ValueError("cast generation seed is invalid")
    if seed_setter is None:
        raise RuntimeError("cast generation seed setter is unavailable")
    seed_setter(seed)
```

Pass `generation_seed` from each benchmark manifest row into the synthesis
segment. Existing non-benchmark callers without this field retain their
current behavior and must not import MLX solely for seed handling.

- [ ] **Step 4: Honor the supplied canonical chunk plan fail-closed**

If `canonical_voice_chunks` is present, require a non-empty list of non-empty
strings whose concatenation equals the normalized utterance text. Require a
same-length `generation_seeds` list of bounded integers. Otherwise retain the
normal production splitter for non-benchmark callers.

- [ ] **Step 5: Run the complete local generator suite and static checks**

```bash
PYTHONPATH=/Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts:/Users/simon/.hermes/.venvs/mlx-audio/lib/python3.11/site-packages \
  /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py \
  -q
/Users/simon/.hermes/hermes-agent/venv/bin/python -m ruff check \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/generate_qwen_story_narration.py \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py
shasum -a 256 \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/generate_qwen_story_narration.py \
  /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/test_generate_qwen_story_narration.py
```

Expected: the full local suite and Ruff pass; record both SHA-256 values in the task report. These runtime-local files are not committed to the Hermes repo.

---

### Task 3: Add Pair QC, Loudness Normalization, Resume, And Rendering

**Files:**
- Modify: `scripts/story_video_tone_pk.py`
- Modify: `tests/scripts/test_story_video_tone_pk.py`

**Interfaces:**
- Consumes: the neutral and expressive v7 narration manifests and their selected WAV chunks.
- Produces: `normalize_take(source: Path, output: Path, runner: Callable[[list[str]], Any]) -> None`, `validate_pair_evidence(pair: dict[str, Any]) -> dict[str, Any]`, `build_pk_timeline(pairs: list[dict[str, Any]]) -> dict[str, Any]`, `render_pk_video(project: Path, output: Path, width: int, height: int) -> dict[str, Any]`, plus `status`, `qc`, and `render` CLI subcommands.

- [ ] **Step 1: Write failing tests for fairness and resume**

```python
def test_pair_qc_rejects_voice_seed_text_chunk_or_loudness_drift():
    pair = passing_pair_evidence()
    pair["expressive"]["generation_seeds"][0] += 1
    with pytest.raises(tone_pk.TonePkError, match="generation seed"):
        tone_pk.validate_pair_evidence(pair)


def test_resume_keeps_green_take_hashes_and_regenerates_only_failed_take(tmp_path):
    state = state_with_green_neutral_and_failed_expressive(tmp_path)
    pending = tone_pk.pending_takes(state)
    assert [(row["pair_id"], row["variant"]) for row in pending] == [("PK-0007", "expressive")]
```

- [ ] **Step 2: Write failing renderer tests**

```python
def test_timeline_is_fixed_a_then_b_with_display_only_labels():
    timeline = tone_pk.build_pk_timeline([passing_pair_evidence()])
    assert [row["variant"] for row in timeline["takes"]] == ["neutral", "expressive"]
    assert timeline["spoken_text"] == "同一句。同一句。"
    assert "無情緒" not in timeline["spoken_text"]
    assert "有情緒" not in timeline["spoken_text"]
```

- [ ] **Step 3: Run the focused tests and confirm RED**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/scripts/test_story_video_tone_pk.py -q
```

Expected: failures for missing QC, resume, timeline, and render helpers.

- [ ] **Step 4: Implement normalization and measurement**

`normalize_take` invokes FFmpeg with the same filter and target for every take:

```python
["ffmpeg", "-y", "-v", "error", "-i", str(source),
 "-af", "loudnorm=I=-18:LRA=7:TP=-2,aresample=48000",
 "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(output)]
```

`probe_loudness` uses `ebur128=peak=true` and parses the integrated LUFS value.
`validate_pair_evidence` rejects more than 0.5 LUFS A/B delta, mismatched
text/voice/engine/model/profile/chunks/seeds, A adapter status other than
`neutral_noop`, B adapter status other than `applied`, any B neutral tone, or
post-utterance pause above 0.45 seconds.

- [ ] **Step 5: Implement checkpointed state and compatible final narration contract**

Write `manifests/tone_pk_manifest.json` atomically after each take. Build a
comparison `manifests/narration_manifest.json` whose ordered voice chunks are
prefixed `PK-####__A__` and `PK-####__B__`, so the existing final-speech worker
can bind the rendered MP4 to the exact repeated A/B transcript and ordered
chunk IDs.

- [ ] **Step 6: Implement ASS subtitles and deterministic FFmpeg render**

The render timeline contains one gray A label and one role-colored/gold B
label per pair, exact role/action/text overlays, 0.35-second A/B silence, and
0.80-second inter-pair silence. Render 1920x1080 black video with hard-burned
ASS subtitles, concatenate normalized takes, and encode H.264/AAC.

- [ ] **Step 7: Run focused and wider story-video tests**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/scripts/test_story_video_tone_pk.py \
  tests/plugins/story_video/test_tone_map.py \
  tests/plugins/story_video/test_delivery_speech.py \
  tests/plugins/story_video/test_render_modes.py -q
/Users/simon/.hermes/hermes-agent/venv/bin/python -m ruff check \
  scripts/story_video_tone_pk.py tests/scripts/test_story_video_tone_pk.py
rtk git diff --check
```

Expected: all selected tests and static checks pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add scripts/story_video_tone_pk.py tests/scripts/test_story_video_tone_pk.py
git commit -m "feat(story-video): render tone PK benchmark"
```

---

### Task 4: Prepare And Validate The Private 56-Row Annotation Set

**Files:**
- Create locally: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/annotations/tone_annotations.json`
- Create locally: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/manifests/tone_pk_plan.json`
- Create locally: variant projects under `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/variants/`

**Interfaces:**
- Consumes: the exact private source project selected in the approved spec.
- Produces: one validated non-neutral catalog annotation and one canonical chunk/seed plan per utterance.

- [ ] **Step 1: Generate the private annotation skeleton**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python \
  scripts/story_video_tone_pk.py annotate \
  --source-project /Users/simon/.hermes/story_videos/story-video-b6be83c4bd-5fad824d \
  --output /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/annotations/tone_annotations.json \
  --expected-utterances 56
```

The skeleton contains IDs and source action/emotion/pace but no generated
media. Author the tone fields locally from the original action and spoken text,
using only IDs from `story_video_tone_catalog_v1`. Every row must be deliberate;
no B row may remain `general.neutral`.

- [ ] **Step 2: Validate annotation coverage and adult gating**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python \
  scripts/story_video_tone_pk.py validate-annotations \
  --source-project /Users/simon/.hermes/story_videos/story-video-b6be83c4bd-5fad824d \
  --annotations /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/annotations/tone_annotations.json \
  --content-rating adult_explicit \
  --expected-utterances 56
```

Expected: 56/56 IDs, all catalog-valid, all non-neutral, bounded intensity,
pace, and modifiers, with adult tones accepted only because the run is
`adult_explicit`.

- [ ] **Step 3: Prepare both private variant projects**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python \
  scripts/story_video_tone_pk.py prepare \
  --source-project /Users/simon/.hermes/story_videos/story-video-b6be83c4bd-5fad824d \
  --output-project /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721 \
  --run-id tone-pk-jiamei-56-20260721 \
  --annotations /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/annotations/tone_annotations.json \
  --expected-utterances 56
```

Expected: the plan contains 56 pairs; A/B text, cast, chunks, and seeds match;
A is neutral no-op and B is non-neutral.

- [ ] **Step 4: Run the privacy gate**

```bash
rtk git status --short
rtk git diff --cached --name-only
```

Expected: no private project file, annotation, text, media, or provider output appears in git.

---

### Task 5: Generate, Repair, Normalize, And QC All 112 Takes

**Files:**
- Generate locally under: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/variants/`
- Update locally: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/manifests/tone_pk_manifest.json`
- Write locally: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/qc/tone_pk_qc_report.json`

**Interfaces:**
- Consumes: the prepared neutral/expressive ledgers and local Qwen models.
- Produces: 112 selected normalized utterance takes and complete per-pair evidence.

- [ ] **Step 1: Run offline Qwen generation with resume enabled**

```bash
env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=/Users/simon/.hermes/hermes-agent/.worktrees/feat-story-video-tone-pk-benchmark \
  /Users/simon/.hermes/.venvs/mlx-audio/bin/python \
  /Users/simon/.hermes/hermes-agent/.worktrees/feat-story-video-tone-pk-benchmark/scripts/story_video_tone_pk.py generate \
  --project /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721 \
  --generator /Users/simon/.hermes/skills/creative/story-video-production-pipeline/scripts/generate_qwen_story_narration.py \
  --resume
```

Expected: both models load offline; every completed take is checkpointed; a
restart skips hash-matching green takes.

- [ ] **Step 2: Run per-take speech QC and bounded repair**

```bash
env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=/Users/simon/.hermes/hermes-agent/.worktrees/feat-story-video-tone-pk-benchmark \
  /Users/simon/.hermes/.venvs/mlx-audio/bin/python \
  /Users/simon/.hermes/hermes-agent/.worktrees/feat-story-video-tone-pk-benchmark/scripts/story_video_tone_pk.py qc \
  --project /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721 \
  --repair-failed \
  --max-candidates 3
```

Expected: normalized ASR, pronunciation, alignment, prosody, and fluency pass
for every selected take. Only failed takes are regenerated.

- [ ] **Step 3: Normalize and verify loudness fairness**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python \
  scripts/story_video_tone_pk.py normalize \
  --project /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721 \
  --target-lufs -18 \
  --max-pair-delta-lufs 0.5
```

Expected: 56/56 pairs have same routing/chunks/seeds/text and at most 0.5 LUFS A/B delta.

- [ ] **Step 4: Audit checkpoint idempotency**

Run `generate --resume` again and assert the manifest reports zero regenerated
green takes and unchanged selected audio SHA-256 values.

---

### Task 6: Render, Final-ASR Verify, Review, And Integrate

**Files:**
- Generate locally: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/video/tone_pk_full.mp4`
- Generate locally: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/manifests/narration_manifest.json`
- Generate locally: `/Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/qc/final_speech_qc_report.json`
- Update versioned code only if review finds a generic defect.

**Interfaces:**
- Consumes: 112 green normalized takes and the paired timeline.
- Produces: the final review MP4 and fail-closed final artifact evidence.

- [ ] **Step 1: Render the full paired MP4**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python \
  scripts/story_video_tone_pk.py render \
  --project /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721 \
  --width 1920 --height 1080 \
  --output /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/video/tone_pk_full.mp4
```

- [ ] **Step 2: Run final MP4 speech verification with local Qwen ASR**

```bash
env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=. \
  /Users/simon/.hermes/.venvs/mlx-audio/bin/python \
  -m plugins.story_video.final_speech_worker \
  --project-dir /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721 \
  --video /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/video/tone_pk_full.mp4 \
  --run-id tone-pk-jiamei-56-20260721
```

Expected: `story_video_final_speech_qc_v1`, status `PASS`, exact ordered A/B
chunk IDs, matching narration-manifest hash, and a final video SHA-256.

- [ ] **Step 3: Run final media and privacy checks**

```bash
ffprobe -v error -show_entries stream=codec_name,width,height,sample_rate,channels \
  -of json /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721/video/tone_pk_full.mp4
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python \
  scripts/story_video_tone_pk.py status \
  --project /Users/simon/.hermes/story_videos/tone-pk-jiamei-56-20260721
rtk git status --short
rtk git diff --check
```

Expected: H.264 1920x1080, AAC audio, 56 complete pairs, all QC PASS, and no private runtime artifact in git.

- [ ] **Step 4: Run the repository release gate and independent review**

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/scripts/test_story_video_tone_pk.py \
  tests/plugins/story_video/ -q
/Users/simon/.hermes/hermes-agent/venv/bin/python -m ruff check \
  scripts/story_video_tone_pk.py tests/scripts/test_story_video_tone_pk.py
rtk git diff --check
```

Request review for source privacy, exact-text fairness, seed placement,
resume/dedup behavior, and false-green QC paths. Fix all findings and rerun the
same gate.

- [ ] **Step 5: Integrate through the governed fork-local PR path**

Push the exact topic ref, open a PR to `local/main`, wait for `All required
checks pass`, merge, fast-forward local `local/main`, then cut
`runtime/current` to the identical merge SHA with the documented temporary
unlock/push/re-lock sequence. Restart and verify the launchd-supervised gateway
only if merged runtime code is imported by the live process.

- [ ] **Step 6: Deliver the current selected MP4 for human listening review**

Surface `video/tone_pk_full.mp4`, the pair/QC summary, merge SHA, and the honest
boundary that `HEURISTIC_PASS` does not prove listener preference. Do not
deliver temporary stems, rejected candidates, old media, or duplicate files.

# Multi-role Story Video Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert story text plus explicit character-to-voice mapping into one automatically delivered MP4 in either story-image or black-subtitle mode.

**Architecture:** Extend the existing story-video run context and audio director instead of introducing a parallel pipeline. Reuse the Qwen voice executor, deterministic renderer, Hermes tracked background terminal, and gateway native media delivery; add one project-local production manifest to make launch, resume, render, and delivery idempotent.

**Tech Stack:** Python 3.11, pytest, dataclasses/JSON atomic state, Qwen/MLX local TTS, Pillow, ffmpeg/ffprobe, Hermes process registry, Slack gateway native media delivery.

## Global Constraints

- The primary deliverable is one playable current-run MP4; MP3/WAV/SRT/QC files are sidecars.
- `story_visual` uses the existing selected-image workflow; `black_subtitle` invokes no image provider.
- Explicit visual mode wins; `auto` fails closed to black mode for explicit adult/NSFW material.
- Use only the existing voice catalog and hash-locked cast bindings.
- Do not add a second queue, direct Slack API client, generic video provider, or network TTS fallback.
- Long voice/render work must use Hermes tracked background execution with completion notification.
- Every behavior change begins with a failing focused test.
- Generated media, provider logs, session data, and Slack evidence remain local and uncommitted.

---

## File map

- `plugins/story_video/state.py`: parse and persist `visual_mode`, choose mode-specific phases and authorization scopes.
- `plugins/story_video/production.py`: own the production manifest, safe tracked background launch, status, resume, and selected-media response.
- `plugins/story_video/production_runner.py`: deterministic voice/render worker and machine-readable completion result.
- `plugins/story_video/render_modes.py`: prepare black-subtitle render input and mode-specific render proof helpers.
- `plugins/story_video/tools.py`: expose `start_production`, `production_status`, and mode-aware phase validation through the existing audio director.
- `plugins/story_video/schemas.py`: describe new audio-director actions and fields.
- `plugins/story_video/hooks.py`: route natural multi-role video requests, phase-skip black runs, and fast-route background completion.
- `plugins/story_video/guide.py`: document MP4 modes, examples, status, stop, resume, and retry delivery.
- `gateway/run.py`: narrowly auto-append successful current-turn MP4 results from the story-video audio director.
- `agent/codex_runtime.py`: select a bounded story-video artifact deadline.
- `agent/transports/codex_app_server_session.py`: prefer a successful current-turn media artifact over stale progress during deadline recovery.
- `tests/plugins/story_video/*`, `tests/gateway/*`, `tests/agent/*`: focused and integration regression coverage.

---

### Task 1: Persist visual mode and route multi-role video requests

**Files:**
- Modify: `plugins/story_video/state.py`
- Modify: `plugins/story_video/hooks.py`
- Modify: `tools/story_video_provider_guard.py`
- Test: `tests/plugins/story_video/test_state.py`
- Test: `tests/plugins/story_video/test_hooks.py`
- Test: `tests/tools/test_story_video_provider_guard.py`

**Interfaces:**
- Produces: `resolve_visual_mode(text: str, requested: str = "auto") -> str`
- Produces: `StoryVideoRunContext.visual_mode: str`
- Produces: `StoryVideoRunContext.phase_order: tuple[str, ...]`
- Consumes later: mode-specific runner and validator read `context.visual_mode` and `context.phase_order`.

- [ ] **Step 1: Write failing visual-mode and route tests**

```python
def test_explicit_black_subtitle_mode_wins():
    call = parse_operator_call("故事影片：夜班故事，全黑背景加字幕，多角色配音")
    assert call is not None
    assert call.visual_mode == "black_subtitle"


def test_auto_adult_video_fails_closed_without_image_scope(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call("製作 NSFW 成人故事短片，多角色配音並出片")
    context = store.create_or_load(
        source_key="slack:thread", session_id="s1", call=call,
        original_request="製作 NSFW 成人故事短片，多角色配音並出片",
    )
    assert context.visual_mode == "black_subtitle"
    assert context.phase_order == ("planning", "voice", "render", "complete")
    assert "openai_image_generation" not in context.provider_policy["scopes"]


def test_multi_role_video_is_story_video_request():
    assert story_video_request_detected(
        "請把以下故事做成短片，旁白用 simon_clean_v2，安安用 Vivian，多角色配音"
    )
```

- [ ] **Step 2: Run tests and verify the expected failures**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/plugins/story_video/test_state.py \
  tests/plugins/story_video/test_hooks.py \
  tests/tools/test_story_video_provider_guard.py -q
```

Expected: failures for missing `visual_mode`, `phase_order`, and multi-role route detection.

- [ ] **Step 3: Implement mode parsing and persistence**

Add the following stable values and resolver in `state.py`:

```python
VISUAL_MODES = {"auto", "story_visual", "black_subtitle"}
STORY_VISUAL_PHASES = PHASES
BLACK_SUBTITLE_PHASES = ("planning", "voice", "render", "complete")


def resolve_visual_mode(text: str, requested: str = "auto") -> str:
    normalized = str(requested or "auto").strip().lower()
    if normalized not in VISUAL_MODES:
        raise ValueError(f"Unknown story-video visual mode: {requested}")
    if normalized != "auto":
        return normalized
    compact = re.sub(r"\s+", "", str(text or "").casefold())
    if any(marker in compact for marker in (
        "全黑背景", "黑底字幕", "blacksubtitle", "blackbackground",
        "nsfw", "成人內容", "成人内容", "色情", "性愛", "性爱",
    )):
        return "black_subtitle"
    return "story_visual"
```

Extend `OperatorCall` and `StoryVideoRunContext` with `visual_mode`, add a
`phase_order` property, preserve backward compatibility in `from_dict`, and
make authorization scopes derive from visual mode. Add a multi-role-video
structure regex to `story_video_provider_guard.py`; audio-only dubbing requests
without a video/output marker remain outside story-video routing.

- [ ] **Step 4: Run focused tests until green**

Expected: all Task 1 tests pass, including serialization of an old context that
has no `visual_mode` field.

- [ ] **Step 5: Commit Task 1**

```bash
git add plugins/story_video/state.py plugins/story_video/hooks.py \
  tools/story_video_provider_guard.py tests/plugins/story_video/test_state.py \
  tests/plugins/story_video/test_hooks.py tests/tools/test_story_video_provider_guard.py
git commit -m "feat(story-video): persist multirole visual mode"
```

---

### Task 2: Add an idempotent tracked production job

**Files:**
- Create: `plugins/story_video/production.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `plugins/story_video/schemas.py`
- Test: `tests/plugins/story_video/test_production.py`
- Test: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Produces: `ProductionJobStore.load(project_dir: Path) -> dict[str, Any] | None`
- Produces: `ProductionJobStore.transition(..., status: str, **evidence) -> dict[str, Any]`
- Produces: `start_production(context, *, terminal_runner=terminal_tool) -> dict[str, Any]`
- Produces: `production_status(context) -> dict[str, Any]`
- Consumes: a compiled and bound dubbing project from Task 1/current audio director.

- [ ] **Step 1: Write failing job-state and launch tests**

```python
def test_start_production_launches_one_tracked_background_process(context, monkeypatch):
    calls = []
    def fake_terminal(**kwargs):
        calls.append(kwargs)
        return json.dumps({"status": "running", "session_id": "proc-1"})
    payload = start_production(context, terminal_runner=fake_terminal)
    assert payload["work_status"] == "running"
    assert payload["process_session_id"] == "proc-1"
    assert calls == [{
        "command": payload["command"], "background": True,
        "notify_on_complete": True, "workdir": str(context.project_dir),
        "session_id": context.session_ids[-1],
    }]


def test_start_production_is_idempotent_when_artifact_is_ready(context, tmp_path):
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    ProductionJobStore(context.project_dir).transition(
        run_id=context.run_id, visual_mode=context.visual_mode,
        status="artifact_ready", selected_mp4=str(final),
    )
    payload = start_production(context, terminal_runner=lambda **_: pytest.fail("relaunched"))
    assert payload["already_complete"] is True
    assert payload["media"] == [f"MEDIA:{final.resolve()}"]
```

- [ ] **Step 2: Run focused tests and verify missing-module/action failures**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/plugins/story_video/test_production.py \
  tests/plugins/story_video/test_tools.py -q
```

- [ ] **Step 3: Implement atomic manifest and safe launch**

`production.py` writes `manifests/production_job.json` with schema
`story_video_production_job_v1`. Allowed transitions are:

```python
TRANSITIONS = {
    "queued": {"running", "stopped", "failed"},
    "running": {"artifact_ready", "stopped", "failed"},
    "artifact_ready": {"delivered", "failed"},
    "delivered": set(),
    "failed": {"queued", "running", "artifact_ready"},
    "stopped": {"queued", "running"},
}
```

Construct the runner command only with `shlex.join` over:

```python
[
    sys.executable, "-m", "plugins.story_video.production_runner",
    "--run-id", context.run_id,
    "--project-dir", str(context.project_dir.resolve()),
]
```

Call `terminal_tool` with `background=True` and
`notify_on_complete=True`. Parse and persist its process session id. Validate
that selected media is an existing `.mp4` inside `context.project_dir` before
returning `MEDIA:`.

- [ ] **Step 4: Expose existing audio-director actions**

Extend `story_video_audio_director` and its schema with:

```text
start_production  - requires compiled, bound dubbing contracts
production_status - returns state and selected current-run MP4 when ready
retry_delivery    - returns the same selected MP4 without relaunching production
```

All actions continue to resolve the canonical current session context; no
arbitrary project path is accepted from model arguments.

- [ ] **Step 5: Run focused tests and commit**

```bash
git add plugins/story_video/production.py plugins/story_video/tools.py \
  plugins/story_video/schemas.py tests/plugins/story_video/test_production.py \
  tests/plugins/story_video/test_tools.py
git commit -m "feat(story-video): track background video production"
```

---

### Task 3: Implement black-subtitle rendering and the deterministic runner

**Files:**
- Create: `plugins/story_video/render_modes.py`
- Create: `plugins/story_video/production_runner.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `plugins/story_video/visual_judge.py`
- Modify: `plugins/story_video/voice_executor.py`
- Test: `tests/plugins/story_video/test_render_modes.py`
- Test: `tests/plugins/story_video/test_production_runner.py`
- Test: `tests/plugins/story_video/test_voice_executor.py`
- Test: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Produces: `prepare_black_subtitle_render(context) -> dict[str, Any]`
- Produces: `validate_black_subtitle_render(context) -> PhaseProof`
- Produces: `run_production(run_id: str, project_dir: Path, ...) -> dict[str, Any]`
- Consumes: `ProductionJobStore`, `StoryVideoVoiceExecutor`, existing
  `_prepare_render`, renderer script, and phase validators.

- [ ] **Step 1: Write failing black-render tests**

```python
def test_black_render_input_uses_only_project_black_frame(context, narration_manifest):
    payload = prepare_black_subtitle_render(context)
    render_input = json.loads((context.project_dir / "render_input.json").read_text())
    assert payload["visual_mode"] == "black_subtitle"
    assert render_input["visual_mode"] == "black_subtitle"
    assert {shot["image"] for scene in render_input["scenes"] for shot in scene["shots"]} == {
        "assets/black-background.png"
    }
    assert not (context.project_dir / "manifests/shot_candidate_manifest.json").exists()


def test_black_render_proof_rejects_image_provider_audit_event(context):
    write_passing_black_render(context)
    append_provider_event(context, kind="image", provider="openai-codex")
    proof = validate_black_subtitle_render(context)
    assert proof.ok is False
    assert "black_subtitle run invoked an image provider" in proof.violations
```

- [ ] **Step 2: Write failing runner resume and ASR fallback tests**

```python
def test_runner_resumes_at_render_when_voice_proof_already_passes(context, monkeypatch):
    calls = []
    result = run_production(
        context.run_id, context.project_dir,
        voice_runner=lambda *_a, **_k: calls.append("voice"),
        renderer=lambda *_a, **_k: calls.append("render") or CommandResult(0),
    )
    assert calls == ["render"]
    assert result["work_status"] == "artifact_ready"


def test_voice_executor_records_reduced_qc_when_asr_has_no_metal(context):
    result = executor_with_asr_accelerator_failure.run(context)
    assert result.work_status == "complete"
    report = json.loads((context.project_dir / "manifests/narration_qc_report.json").read_text())
    assert report["asr_qc"]["status"] == "DEGRADED"
    assert report["asr_qc"]["reason"] == "accelerator_unavailable"
```

- [ ] **Step 3: Implement black render preparation**

Use Pillow to create an RGB 1920x1080 `(0, 0, 0)` PNG at
`assets/black-background.png`. Convert narration manifest outputs and measured
segments into the existing renderer v2 scene/shot shape, preserving every
utterance's display text, measured duration, and subtitle cues. Set black
opening/ending cards, disable background music, and keep output
`video/final.mp4`.

- [ ] **Step 4: Implement mode-specific proof**

Reuse ffprobe metadata already recorded by the renderer. Black proof requires:

```python
required = {
    "container_status": "PASS",
    "audio_status": "PASS",
    "duration_match_status": "PASS",
    "hard_burned_subtitles": True,
    "subtitle_coverage_status": "PASS",
    "black_background_status": "PASS",
}
```

Reject any image-provider audit event for the current run. Do not require
motion, release art, or selected-image density. Leave story-visual proof
unchanged.

- [ ] **Step 5: Implement deterministic runner and honest ASR degradation**

The runner:

```python
context = store.for_run(run_id=run_id, project_dir=project_dir)
job.transition(status="running", phase=context.phase)
if context.phase == "voice":
    run_voice_phase(context)
    validate_and_advance(context)
if context.phase == "render":
    prepare_mode_render(context)
    run_cancellable_renderer(context)
    validate_and_advance(context)
job.transition(status="artifact_ready", selected_mp4=str(selected), qc_report=str(qc))
return {"success": True, "work_status": "artifact_ready", "media": [f"MEDIA:{selected}"]}
```

Catch only the recognized `No Metal device available`/MLX accelerator error
from ASR. Record `DEGRADED` and run non-ASR duration, silence, text-order,
binding, and subtitle-timeline gates. Other ASR errors remain failures.

- [ ] **Step 6: Run focused suites and commit**

```bash
git add plugins/story_video/render_modes.py plugins/story_video/production_runner.py \
  plugins/story_video/tools.py plugins/story_video/visual_judge.py \
  plugins/story_video/voice_executor.py tests/plugins/story_video/test_render_modes.py \
  tests/plugins/story_video/test_production_runner.py \
  tests/plugins/story_video/test_voice_executor.py tests/plugins/story_video/test_tools.py
git commit -m "feat(story-video): render multirole black subtitle videos"
```

---

### Task 4: Auto-complete the original thread and harden media recovery

**Files:**
- Modify: `plugins/story_video/hooks.py`
- Modify: `gateway/run.py`
- Modify: `agent/codex_runtime.py`
- Modify: `agent/transports/codex_app_server_session.py`
- Test: `tests/plugins/story_video/test_hooks.py`
- Test: `tests/gateway/test_media_extraction.py`
- Test: `tests/agent/test_codex_runtime.py`
- Test: `tests/agent/transports/test_codex_app_server_session.py`

**Interfaces:**
- Produces: background completion fast-route instruction.
- Produces: `_codex_turn_timeout_for_target(target_artifact, image_target) -> float`.
- Produces: deadline recovery that selects a successful current-turn media result.
- Consumes: `story_video_audio_director production_status` JSON from Tasks 2-3.

- [ ] **Step 1: Write failing completion/delivery tests**

```python
def test_background_story_video_completion_fast_routes_to_status(context):
    message = pre_llm_call(
        session_id="s1",
        user_message="[IMPORTANT: Background process p1 completed normally.\n"
                     "Output:\nSTORY_VIDEO_PRODUCTION_COMPLETE run_id=r1]",
    )
    assert "story_video_audio_director action=production_status exactly once" in message["context"]


def test_gateway_auto_appends_current_story_video_mp4(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"video")
    messages = tool_turn(
        "story_video_audio_director",
        {"success": True, "action": "production_status", "media": [f"MEDIA:{final}"]},
    )
    tags, _ = _collect_auto_append_media_tags(messages)
    assert tags == [f"MEDIA:{final}"]
```

- [ ] **Step 2: Write failing deadline recovery tests**

```python
def test_story_video_artifact_turn_uses_bounded_1800_second_deadline():
    assert _codex_turn_timeout_for_target("story_video_workflow", None) == 1800.0


def test_deadline_recovery_prefers_completed_current_media_tool_result(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"video")
    result = run_fake_deadline_turn(
        assistant_progress="仍在品質檢查",
        completed_tool_result={"success": True, "media": [f"MEDIA:{final}"]},
    )
    assert result.final_text.endswith(f"MEDIA:{final}")
    assert "仍在品質檢查" not in result.final_text
```

- [ ] **Step 3: Implement fast route and producer allowlist**

Recognize only internal process-completion messages containing
`STORY_VIDEO_PRODUCTION_COMPLETE` or `STORY_VIDEO_PRODUCTION_FAILED` with the
active run id. Inject a read-only fast route that calls production status once,
runs no shell command, and preserves the returned current MP4 media tag.

Add `story_video_audio_director` to `_AUTO_APPEND_MEDIA_TOOL_NAMES`, but accept
its media only when JSON has `success=true`, action is `production_status` or
`retry_delivery`, and each path is an existing current-turn `.mp4`.

- [ ] **Step 4: Implement bounded deadline and artifact fallback**

Return 1800 seconds only for `target_artifact == "story_video_workflow"`; keep
existing image-target math and 600-second default unchanged. Track successful
producer-tool media results inside the current Codex turn. On the existing
incomplete-turn recovery branch, synthesize a terminal media response only when
the path exists, has a supported media suffix, and belongs to the current turn;
otherwise retain current progress-text behavior.

- [ ] **Step 5: Run focused tests and commit**

```bash
git add plugins/story_video/hooks.py gateway/run.py agent/codex_runtime.py \
  agent/transports/codex_app_server_session.py tests/plugins/story_video/test_hooks.py \
  tests/gateway/test_media_extraction.py tests/agent/test_codex_runtime.py \
  tests/agent/transports/test_codex_app_server_session.py
git commit -m "fix(gateway): deliver completed story videos after long runs"
```

---

### Task 5: Update operator help and close integration gaps

**Files:**
- Modify: `plugins/story_video/guide.py`
- Modify: `plugins/story_video/hooks.py`
- Test: `tests/plugins/story_video/test_guide.py`
- Test: `tests/plugins/story_video/test_hooks.py`
- Modify: `docs/superpowers/specs/2026-07-19-multirole-story-video-delivery-design.md`
- Modify: `docs/superpowers/plans/2026-07-19-multirole-story-video-delivery.md`

**Interfaces:**
- Produces: operator-readable help examples and truthful status fields.
- Consumes: exact action/mode names implemented by Tasks 1-4.

- [ ] **Step 1: Write failing help tests**

```python
def test_help_describes_both_mp4_modes_and_no_image_black_mode():
    text = format_story_video_guide(None, "help")
    assert "MP4" in text
    assert "story_visual" in text
    assert "black_subtitle" in text
    assert "不會產圖" in text
    assert "Vivian" in text and "Serena" in text and "Uncle_Fu" in text
    assert "重試交付" in text
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/plugins/story_video/test_guide.py tests/plugins/story_video/test_hooks.py -q
```

- [ ] **Step 3: Update help and examples**

Document one concise prompt for each mode, explicit role mappings, creative /
remake / read-aloud semantics, status, stop, continue, and retry-delivery. Do
not expose internal process ids, authorization ids, or runner commands as
required user syntax.

- [ ] **Step 4: Run all story-video and gateway regression suites**

Run:

```bash
PYTHONPATH=. /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest \
  tests/plugins/story_video tests/tools/test_story_video_provider_guard.py \
  tests/gateway/test_media_extraction.py \
  tests/agent/test_codex_runtime.py \
  tests/agent/transports/test_codex_app_server_session.py -q
```

Expected: all selected tests pass with no warnings introduced by the new code.

- [ ] **Step 5: Commit docs/help**

```bash
git add plugins/story_video/guide.py plugins/story_video/hooks.py \
  tests/plugins/story_video/test_guide.py tests/plugins/story_video/test_hooks.py
git add -f docs/superpowers/specs/2026-07-19-multirole-story-video-delivery-design.md \
  docs/superpowers/plans/2026-07-19-multirole-story-video-delivery.md
git commit -m "docs(story-video): explain multirole MP4 production"
```

---

### Task 6: Release gate, PR, deployment, and live acceptance

**Files:**
- No production file changes expected.
- Local-only evidence: `/Users/simon/.hermes/runtime_evidence/`
- Local-only generated runs: `/Users/simon/.hermes/story_videos/`

**Interfaces:**
- Consumes: all Tasks 1-5.
- Produces: accepted `local/main`, exact deployed `runtime/current`, supervised gateway, and two visible Slack MP4 attachments.

- [ ] **Step 1: Run static and privacy gates**

```bash
git diff --check
git status --short
git diff --stat origin/local/main...
git diff --name-only origin/local/main... | rg -n '(\.mp4|\.mp3|\.wav|\.srt|\.jsonl|logs/|sessions/)'
```

Expected: diff check clean; no generated media, provider logs, sessions, or
private runtime state is tracked.

- [ ] **Step 2: Run fresh release-quality gate**

Run the focused suites from Task 5 plus the repository's required aggregate
test/check command. Record commands, timestamps, exit status, and failing test
names if any. Do not reuse baseline evidence.

- [ ] **Step 3: Review and publish topic branch**

Use `superpowers:requesting-code-review`, address findings, then push the exact
matching ref:

```bash
git push origin \
  refs/heads/fix/story-video/multirole-video-delivery:refs/heads/fix/story-video/multirole-video-delivery
```

Open a fork-local PR with base `local/main`, wait for the aggregate required
check, review the final diff, and merge only when green.

- [ ] **Step 4: Fast-forward accepted local integration**

```bash
git -C /Users/simon/.hermes/hermes-agent fetch origin local/main
git -C /Users/simon/.hermes/hermes-agent merge --ff-only origin/local/main
```

Record the accepted SHA.

- [ ] **Step 5: Deploy exact SHA to runtime/current**

Verify both protected worktrees are clean, prove runtime/current is an ancestor,
fast-forward it to local/main, confirm the editable install points to the
runtime worktree, restart the launchd-supervised gateway, and verify PID/command
plus tool smoke. The final deployed SHA must exactly equal local/main.

- [ ] **Step 6: Run black-subtitle Slack live E2E**

Submit a short, safe test story with at least narrator + Vivian in explicit
`black_subtitle` mode. Prove:

- run context visual mode is black;
- provider audit has zero image calls;
- background job completes and resumes the original thread;
- final attachment is a playable `video/mp4`;
- subtitles and both voices are present;
- no MP3/SRT is delivered as the primary artifact.

- [ ] **Step 7: Run story-visual Slack live E2E**

Submit a short test story with narrator + Serena or Uncle_Fu in explicit
`story_visual` mode. Prove selected image provenance, multi-role voice binding,
subtitle/render QC PASS, current-run MP4 native upload, and no stale/duplicate
media.

- [ ] **Step 8: Push and verify runtime pointer, then clean topic lifecycle**

After live evidence is green, follow the documented temporary unlock / exact
ref push / immediate relock / readback procedure for `origin/runtime/current`.
Verify remote SHA equals accepted SHA. Then use
`superpowers:finishing-a-development-branch` to remove the merged topic
worktree/branch only after both fork-local and upstream PR lookups are clean.

---

## Self-review

- Spec coverage: intake, two modes, role binding, background lifecycle,
  black-render proof, story-render reuse, ASR fallback, deadline recovery,
  current-only delivery, help, PR/deploy, and two live smokes each map to a
  task above.
- Placeholder scan: no TBD/TODO/"similar to" implementation gaps remain.
- Type consistency: `visual_mode`, `ProductionJobStore`, `start_production`,
  `production_status`, `prepare_black_subtitle_render`, and `run_production`
  have one spelling and one ownership location throughout the plan.

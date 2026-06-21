# Visual Evidence Loop After v2026.6.19 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the visual package workflow on the upgraded Hermes v2026.6.19 line by adding an evidence-first Visual Attempt Ledger, Artifact Store, deterministic judges, ranker, and self-smoke before adding learning.

**Architecture:** Keep the upstream v2026.6.19 provider/tool architecture as the base. Add narrow `agent.visual` primitives that observe image/video generation, artifact caching, delivery, and feedback without turning prompt mediation into the learning system. Treat Qwen/Image2 mediation as one optional strategy generator, not the source of truth.

**Tech Stack:** Python 3.11, SQLite, existing Hermes image/video provider registry, xAI image/video plugins, Slack gateway delivery, pytest, `scripts/run_tests.sh`.

## Global Constraints

- Base branch: `upgrade/hermes-v2026.6.19-local`.
- Push local integration work to `origin` only unless an explicit upstream PR workflow is requested.
- Use TDD for every behavior change; write the failing test first, run it, implement the smallest fix, then re-run.
- Runtime-private data stays under `/Users/simon/.hermes`; do not commit raw prompts, generated media, user preference corpora, LAN model endpoints, tokens, or provider responses.
- Do not restore the old Visual Agent Mode wholesale. Port only contracts that still earn their place on the upgraded upstream base.
- Do not add autonomous learning until ledger, artifact identity, delivery evidence, deterministic judges, and ranker gates exist.
- Separate provider failure, policy rewrite, delivery health, reference adherence, and user aesthetic preference in data and scoring.
- Slack must never post stale or duplicate generated artifacts as if they were new.
- Provider-specific prompt strategy belongs in provider profiles or strategy generators, not generic image/video tool code.

---

## Current Reassessment

The upgrade changed the implementation surface:

- Present and verified on v2026.6.19 line:
  - xAI image/video provider contracts;
  - image-to-video aspect selection and no-stretch handling;
  - reference-image alias compatibility at image tool boundary;
  - generated-image delivery filtering;
  - Raphael runtime contract;
  - Slack gateway running at PID `95909`;
  - `grok-4.3` through `xai-oauth` proven by fresh chat smoke and agent log.
- Removed from the upgraded branch and not currently available:
  - `tools/visual_agent_tool.py`;
  - `agent/visual/agent_mode/*`;
  - visual attempt ledger, artifact store, delivery dedupe, feedback parser, live proof/report, and self-smoke scripts;
  - old Visual Agent Mode v2 docs.
- Risk to resolve early:
  - `hermes status` currently reports xAI OAuth as not logged in while the live chat smoke and agent log prove `xai-oauth` is usable. This is an operator-trust bug or status reader drift.
- Privacy note:
  - `docs/image2-adaptive-mediator.md` is currently untracked and contains machine-local configuration. Do not commit it directly. Redact or move it to runtime-private docs before any commit.

## Updated Target

The next target is no longer “restore old Visual Agent v2.” The new target is:

```text
Build a minimal, upstream-friendly visual evidence loop:
request -> provider attempt -> stable artifact -> deterministic judgment
-> rank/select -> Slack delivery -> feedback attribution -> report/self-smoke.
```

Learning remains phase 2. The phase 1 deliverable is reliable evidence and winner-only delivery.

## File Structure

Create or modify these files in phases:

- Create `agent/visual/ids.py`
  - Generates `vrq_*`, `vat_*`, `var_*`, `vjg_*`, `vrk_*`, `vdl_*`, `vfb_*` IDs.
- Create `agent/visual/media_probe.py`
  - Probes local image/video paths and safe data URIs for MIME, size, hash, dimensions, and freshness.
- Create `agent/visual/artifact_store.py`
  - Copies generated image/video files into stable runtime-private storage under `get_hermes_home()/visual/artifacts/<request_id>/`.
- Create `agent/visual/error_taxonomy.py`
  - Normalizes provider, policy, delivery, and artifact errors into shared visual error types.
- Create `agent/visual/attempt_ledger.py`
  - Owns SQLite schema and record/query helpers for requests, attempts, artifacts, judgments, rankings, deliveries, and feedback.
- Create `agent/visual/tracking.py`
  - Best-effort hooks used by image/video tools to create ledger rows and import artifacts.
- Create `agent/visual/delivery_dedupe.py`
  - Hash/destination/request scoped delivery dedupe for generated artifacts.
- Create `agent/visual/judges/deterministic.py`
  - Scores artifact existence, freshness, MIME, aspect, duration, and delivery possibility.
- Create `agent/visual/ranker.py`
  - Rule-based v0 ranker that consumes deterministic scores and selects `post`, `ask_user`, `retry`, or `fail`.
- Create `agent/visual/feedback.py`
  - Parses sparse natural feedback such as “第 2 張不錯”, “wrong face”, “more motion”, and “退貨”.
- Create `scripts/visual_evidence_self_smoke.py`
  - Isolated temporary-Hermes-home smoke that proves ledger, artifacts, delivery, feedback, proof, and report without live providers.
- Create `scripts/visual_evidence_report.py`
  - Privacy-safe aggregate report for operator review.
- Modify `tools/image_generation_tool.py`
  - Add best-effort tracking after successful and failed image generation.
- Modify `tools/video_generation_tool.py`
  - Add best-effort tracking after successful and failed video generation.
- Modify `gateway/platforms/base.py`
  - Add artifact delivery gate and record sent/failed/skipped deliveries.
- Modify `gateway/run.py`
  - Add task-local visual source context for generation requests when required by the tracking hook.
- Tests:
  - `tests/visual/test_ids.py`
  - `tests/visual/test_media_probe.py`
  - `tests/visual/test_artifact_store.py`
  - `tests/visual/test_error_taxonomy.py`
  - `tests/visual/test_attempt_ledger.py`
  - `tests/visual/test_tracking.py`
  - `tests/visual/test_delivery_dedupe.py`
  - `tests/visual/test_deterministic_judges.py`
  - `tests/visual/test_ranker.py`
  - `tests/visual/test_feedback_parser.py`
  - `tests/scripts/test_visual_evidence_self_smoke.py`
  - gateway/media regression tests near existing `tests/gateway/test_send_image_file.py` and `tests/gateway/test_tts_media_routing.py`.

## Milestone 0: Hygiene and Status Truth

**Purpose:** Start from a clean, trustworthy upgraded baseline.

- [ ] **Step 1: Preserve private mediator notes outside tracked docs**

  Run:

  ```bash
  mkdir -p /Users/simon/.hermes/docs/private
  mv docs/image2-adaptive-mediator.md /Users/simon/.hermes/docs/private/image2-adaptive-mediator.md
  ```

  Expected:

  ```text
  rtk git status --short
  ```

  does not show `docs/image2-adaptive-mediator.md`.

- [ ] **Step 2: Add a redacted public note if needed**

  Create `docs/visual-mediator-runtime-private.md` containing:

  ```markdown
  # Visual Mediator Runtime Configuration

  Visual prompt mediation may use machine-local draft models and runtime-private
  memory under `/Users/simon/.hermes`. Do not commit raw prompts, generated
  media, local network endpoints, user preference corpora, tokens, or provider
  responses to this repository.

  The repository only tracks provider-agnostic contracts, tests, and operator
  proof commands. Machine-specific mediator configuration lives in runtime
  state.
  ```

- [ ] **Step 3: Write the xAI OAuth status drift tests**

  Extend the existing xAI OAuth auth/status tests instead of creating a parallel
  status collector. Add the resolver truth test near the current
  `get_xai_oauth_auth_status()` tests in
  `tests/hermes_cli/test_auth_xai_oauth_provider.py`:

  ```python
  from __future__ import annotations

  def test_get_xai_oauth_auth_status_uses_runtime_resolver(monkeypatch):
      import hermes_cli.auth as auth_mod

      monkeypatch.setattr(
          auth_mod,
          "resolve_xai_oauth_runtime_credentials",
          lambda: {
              "api_key": "redacted-access-token",
              "auth_mode": "oauth_pkce",
              "source": "runtime-resolver",
              "last_refresh": "2026-06-21T00:00:00+00:00",
          },
      )

      status = auth_mod.get_xai_oauth_auth_status()

      assert status["logged_in"] is True
      assert status["source"] == "runtime-resolver"
      assert status["auth_mode"] == "oauth_pkce"
  ```

  Also extend `tests/hermes_cli/test_status.py` with a display-level regression:

  ```python
  def test_xai_oauth_runtime_resolver_login_truth_is_printed(monkeypatch, capsys, tmp_path):
      import hermes_cli.auth as auth_mod

      status_mod = _base_xai_mocks(monkeypatch, tmp_path)
      monkeypatch.setattr(
          auth_mod,
          "get_xai_oauth_auth_status",
          lambda: {
              "logged_in": True,
              "auth_store": str(tmp_path / "auth.json"),
              "source": "runtime-resolver",
          },
          raising=False,
      )

      status_mod.show_status(SimpleNamespace(all=False, deep=False))
      out = capsys.readouterr().out

      xai_line = out.split("xAI OAuth", 1)[1].splitlines()[0]
      assert "logged in" in xai_line
      assert "not logged in" not in xai_line
  ```

- [ ] **Step 4: Run the red test**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/hermes_cli/test_auth_xai_oauth_provider.py::test_get_xai_oauth_auth_status_uses_runtime_resolver tests/hermes_cli/test_status.py::TestShowStatusXaiOAuth::test_xai_oauth_runtime_resolver_login_truth_is_printed -q
  ```

  Expected: FAIL because the status reader does not yet report resolver-backed xAI OAuth truth.

- [ ] **Step 5: Implement the status truth fix**

  Modify `hermes_cli/auth.py` so `get_xai_oauth_auth_status()` reports the same
  credential truth that the runtime uses through
  `resolve_xai_oauth_runtime_credentials()`. Keep `hermes_cli/status.py` as a
  presentation layer unless the display regression proves formatting drift.

- [ ] **Step 6: Verify status truth**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/hermes_cli/test_auth_xai_oauth_provider.py::test_get_xai_oauth_auth_status_uses_runtime_resolver tests/hermes_cli/test_status.py::TestShowStatusXaiOAuth::test_xai_oauth_runtime_resolver_login_truth_is_printed -q
  rtk hermes status
  rtk hermes chat -Q --max-turns 1 -q "Reply exactly: OK"
  ```

  Expected:

  - pytest passes;
  - `hermes status` no longer contradicts the live `xai-oauth` smoke;
  - chat returns `OK`.

- [ ] **Step 7: Commit hygiene/status baseline**

  Run:

  ```bash
  rtk git add docs/visual-mediator-runtime-private.md tests/hermes_cli/test_auth_xai_oauth_provider.py tests/hermes_cli/test_status.py hermes_cli/auth.py hermes_cli/status.py
  rtk git commit -m "fix: report xai oauth status truthfully"
  ```

## Milestone 1: Ledger and Artifact Identity

**Purpose:** Make every generated image/video traceable before ranking or learning.

**Interfaces:**

```python
def new_request_id() -> str: ...
def new_attempt_id() -> str: ...
def new_artifact_id() -> str: ...

class VisualAttemptLedger:
    def initialize(self) -> None: ...
    def record_request(self, **kwargs) -> str: ...
    def record_attempt(self, **kwargs) -> str: ...
    def record_artifact(self, **kwargs) -> str: ...
    def record_delivery(self, **kwargs) -> str: ...
```

- [ ] **Step 1: Write ID tests**

  Create `tests/visual/test_ids.py`:

  ```python
  def test_visual_ids_have_expected_prefixes_and_unique_values():
      from agent.visual.ids import (
          new_artifact_id,
          new_attempt_id,
          new_delivery_id,
          new_feedback_id,
          new_judgment_id,
          new_ranking_id,
          new_request_id,
      )

      ids = {
          new_request_id(),
          new_attempt_id(),
          new_artifact_id(),
          new_judgment_id(),
          new_ranking_id(),
          new_delivery_id(),
          new_feedback_id(),
      }

      assert len(ids) == 7
      assert any(value.startswith("vrq_") for value in ids)
      assert any(value.startswith("vat_") for value in ids)
      assert any(value.startswith("var_") for value in ids)
      assert any(value.startswith("vjg_") for value in ids)
      assert any(value.startswith("vrk_") for value in ids)
      assert any(value.startswith("vdl_") for value in ids)
      assert any(value.startswith("vfb_") for value in ids)
  ```

- [ ] **Step 2: Run the ID red test**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_ids.py -q
  ```

  Expected: FAIL because `agent.visual.ids` does not exist.

- [ ] **Step 3: Implement `agent/visual/ids.py`**

  Create small UUID-backed prefix functions.

- [ ] **Step 4: Write ledger schema test**

  Create `tests/visual/test_attempt_ledger.py` with:

  ```python
  def test_attempt_ledger_records_request_attempt_artifact_and_delivery(tmp_path):
      from agent.visual.attempt_ledger import VisualAttemptLedger

      ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
      ledger.initialize()

      request_id = ledger.record_request(
          user_prompt="private prompt stays runtime-local",
          normalized_intent={"modality": "image", "operation": "text_to_image"},
          modality="image",
          operation="text_to_image",
          platform="slack",
          channel_id="C123",
          thread_id="T123",
          user_id="U123",
          message_id="M123",
          conversation_id="slack:C123",
          status="completed",
      )
      attempt_id = ledger.record_attempt(
          request_id=request_id,
          candidate_index=0,
          provider="xai",
          model="grok-imagine-image",
          prompt_original="private prompt stays runtime-local",
          prompt_mediated="compiled prompt",
          parameters_requested={"aspect_ratio": "16:9"},
          parameters_effective={"aspect_ratio": "16:9"},
      )
      artifact_id = ledger.record_artifact(
          request_id=request_id,
          attempt_id=attempt_id,
          kind="image",
          local_path="/tmp/generated.png",
          content_hash="sha256:test",
          mime_type="image/png",
          bytes=12,
          width=1280,
          height=720,
          is_stable=True,
          freshness_status="fresh",
      )
      delivery_id = ledger.record_delivery(
          request_id=request_id,
          attempt_id=attempt_id,
          artifact_id=artifact_id,
          platform="slack",
          destination_id="C123",
          thread_id="T123",
          message_id="M456",
          delivery_status="sent",
      )

      assert ledger.get_request(request_id)["platform"] == "slack"
      assert ledger.get_attempt(attempt_id)["provider"] == "xai"
      assert ledger.get_artifact(artifact_id)["freshness_status"] == "fresh"
      assert ledger.get_delivery(delivery_id)["delivery_status"] == "sent"
  ```

- [ ] **Step 5: Run the ledger red test**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_attempt_ledger.py -q
  ```

  Expected: FAIL because `VisualAttemptLedger` does not exist.

- [ ] **Step 6: Implement `agent/visual/attempt_ledger.py`**

  Implement SQLite tables:

  - `visual_requests`
  - `visual_attempts`
  - `visual_artifacts`
  - `visual_judgments`
  - `visual_rankings`
  - `visual_deliveries`
  - `visual_feedback`

  Use JSON encoding for structured columns and row decoding helpers for query results.

- [ ] **Step 7: Verify milestone 1**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_ids.py tests/visual/test_attempt_ledger.py -q
  rtk git diff --check
  ```

  Expected: tests pass and diff check is clean.

- [ ] **Step 8: Commit milestone 1**

  Run:

  ```bash
  rtk git add agent/visual/ids.py agent/visual/attempt_ledger.py tests/visual/test_ids.py tests/visual/test_attempt_ledger.py
  rtk git commit -m "feat: add visual attempt ledger"
  ```

## Milestone 2: Artifact Store, Media Probe, and Freshness

**Purpose:** Avoid stale URL/file reposts by stabilizing generated media locally.

- [ ] **Step 1: Write media probe tests**

  Create `tests/visual/test_media_probe.py`:

  ```python
  def test_probe_local_png_reports_hash_mime_dimensions_and_freshness(tmp_path):
      from agent.visual.media_probe import probe_local_media

      image = tmp_path / "one.png"
      image.write_bytes(
          b"\x89PNG\r\n\x1a\n"
          b"\x00\x00\x00\rIHDR"
          b"\x00\x00\x00\x01\x00\x00\x00\x01"
          b"\x08\x02\x00\x00\x00"
          b"\x90wS\xde"
          b"\x00\x00\x00\x00IEND\xaeB`\x82"
      )

      meta = probe_local_media(image)

      assert meta.exists is True
      assert meta.mime_type == "image/png"
      assert meta.width == 1
      assert meta.height == 1
      assert meta.sha256.startswith("sha256:")
      assert meta.is_stable is True
      assert meta.freshness_status == "fresh"
  ```

- [ ] **Step 2: Write artifact store tests**

  Create `tests/visual/test_artifact_store.py`:

  ```python
  def test_artifact_store_imports_local_file_under_request_directory(tmp_path):
      from agent.visual.artifact_store import ArtifactStore

      source = tmp_path / "source.png"
      source.write_bytes(
          b"\x89PNG\r\n\x1a\n"
          b"\x00\x00\x00\rIHDR"
          b"\x00\x00\x00\x01\x00\x00\x00\x01"
          b"\x08\x02\x00\x00\x00"
          b"\x90wS\xde"
          b"\x00\x00\x00\x00IEND\xaeB`\x82"
      )

      store = ArtifactStore(tmp_path / "artifacts")
      artifact = store.import_local_file(
          source,
          request_id="vrq_test",
          attempt_id="vat_test",
          kind="image",
          artifact_id="var_test",
      )

      assert artifact.artifact_id == "var_test"
      assert artifact.local_path is not None
      assert "vrq_test" in artifact.local_path
      assert artifact.content_hash.startswith("sha256:")
      assert artifact.mime_type == "image/png"
      assert artifact.is_stable is True
      assert artifact.freshness_status == "fresh"
  ```

- [ ] **Step 3: Run red tests**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_media_probe.py tests/visual/test_artifact_store.py -q
  ```

  Expected: FAIL because media probe and artifact store are missing.

- [ ] **Step 4: Implement media probe and artifact store**

  Implement:

  - local path and `file://` support;
  - image MIME/dimension parsing;
  - byte count and SHA-256;
  - stable local copy;
  - remote URL references marked `freshness_status="unknown"` unless cached.

- [ ] **Step 5: Verify milestone 2**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_media_probe.py tests/visual/test_artifact_store.py -q
  rtk git diff --check
  ```

  Expected: tests pass and diff check is clean.

- [ ] **Step 6: Commit milestone 2**

  Run:

  ```bash
  rtk git add agent/visual/media_probe.py agent/visual/artifact_store.py tests/visual/test_media_probe.py tests/visual/test_artifact_store.py
  rtk git commit -m "feat: store visual artifacts with freshness metadata"
  ```

## Milestone 3: Tracking Hooks for Image and Video Tools

**Purpose:** Record provider attempts without changing provider behavior.

- [ ] **Step 1: Write tracking tests**

  Create `tests/visual/test_tracking.py`:

  ```python
  def test_tracking_records_successful_image_attempt(tmp_path, monkeypatch):
      from agent.visual.attempt_ledger import VisualAttemptLedger
      from agent.visual.tracking import record_visual_generation_attempt

      monkeypatch.setenv("HERMES_HOME", str(tmp_path))
      image = tmp_path / "generated.png"
      image.write_bytes(
          b"\x89PNG\r\n\x1a\n"
          b"\x00\x00\x00\rIHDR"
          b"\x00\x00\x00\x01\x00\x00\x00\x01"
          b"\x08\x02\x00\x00\x00"
          b"\x90wS\xde"
          b"\x00\x00\x00\x00IEND\xaeB`\x82"
      )

      payload = record_visual_generation_attempt(
          {"success": True, "image": str(image), "provider": "xai", "model": "grok-imagine-image"},
          user_prompt="runtime-only prompt",
          prompt_original="runtime-only prompt",
          prompt_mediated="compiled prompt",
          modality="image",
          operation="text_to_image",
          artifact_key="image",
          kind="image",
          provider="xai",
          model="grok-imagine-image",
          parameters_requested={"aspect_ratio": "16:9"},
          parameters_effective={"aspect_ratio": "16:9"},
      )

      assert payload["visual_request_id"].startswith("vrq_")
      assert payload["visual_attempt_id"].startswith("vat_")
      assert payload["visual_artifact_id"].startswith("var_")

      ledger = VisualAttemptLedger(tmp_path / "visual" / "attempt_ledger.sqlite3")
      artifact = ledger.get_artifact(payload["visual_artifact_id"])
      assert artifact["freshness_status"] == "fresh"
  ```

- [ ] **Step 2: Run red tracking tests**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_tracking.py -q
  ```

  Expected: FAIL because tracking hook is missing.

- [ ] **Step 3: Implement best-effort tracking**

  Create `agent/visual/tracking.py` with:

  - `default_visual_ledger_path()`;
  - `record_visual_generation_attempt(payload, ...)`;
  - best-effort exception handling that returns original payload if tracking fails;
  - request, attempt, artifact recording;
  - provider error taxonomy for failures.

- [ ] **Step 4: Wire image and video tools**

  Modify:

  - `tools/image_generation_tool.py`
  - `tools/video_generation_tool.py`

  so successful and failed tool payloads call `record_visual_generation_attempt()` with operation:

  - `text_to_image`;
  - `reference_image_edit`;
  - `text_to_video`;
  - `image_to_video`.

- [ ] **Step 5: Verify milestone 3**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_tracking.py tests/tools/test_image_generation.py tests/plugins/video_gen/test_xai_plugin.py -q
  rtk git diff --check
  ```

  Expected: tests pass and existing image/video contracts remain unchanged.

- [ ] **Step 6: Commit milestone 3**

  Run:

  ```bash
  rtk git add agent/visual/tracking.py tools/image_generation_tool.py tools/video_generation_tool.py tests/visual/test_tracking.py
  rtk git commit -m "feat: record visual generation attempts"
  ```

## Milestone 4: Delivery Deduplication and Slack Attribution

**Purpose:** Stop old/new artifact confusion and make feedback attachable.

- [ ] **Step 1: Write delivery dedupe tests**

  Create `tests/visual/test_delivery_dedupe.py`:

  ```python
  def test_artifact_delivery_deduper_scopes_hash_by_destination_and_request():
      from agent.visual.delivery_dedupe import ArtifactDeliveryDeduper

      deduper = ArtifactDeliveryDeduper(ttl_seconds=60)

      assert deduper.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is True
      assert deduper.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is False
      assert deduper.mark_if_new("sha256:a", "slack:C1:T1", "vrq_2") is True
      assert deduper.mark_if_new("sha256:a", "slack:C2:T1", "vrq_1") is True
  ```

- [ ] **Step 2: Write gateway delivery attribution test**

  Add a focused test near gateway media tests using the existing
  `BasePlatformAdapter` media path and a concrete stub adapter:

  ```python
  import pytest

  from gateway.config import PlatformConfig
  from gateway.platforms.base import BasePlatformAdapter, SendResult


  class _VisualDeliveryStubAdapter(BasePlatformAdapter):
      async def connect(self) -> bool:
          return True

      async def disconnect(self) -> None:
          return None

      async def send_message(self, chat_id, content, **kwargs):
          return SendResult(success=True, message_id="msg_text")

      async def send_image_file(self, chat_id, image_path, caption=None, **kwargs):
          return SendResult(success=True, message_id="msg_image")


  @pytest.mark.asyncio
  async def test_generated_artifact_delivery_records_sent_status(tmp_path, monkeypatch):
      from agent.visual.attempt_ledger import VisualAttemptLedger
      from agent.visual.tracking import visual_delivery_metadata

      monkeypatch.setenv("HERMES_HOME", str(tmp_path))
      ledger = VisualAttemptLedger(tmp_path / "visual" / "attempt_ledger.sqlite3")
      ledger.initialize()
      request_id = ledger.record_request(
          source="test",
          platform="slack",
          channel_id="C123",
          thread_ts="T123",
          intent={"kind": "image"},
      )
      attempt_id = ledger.record_attempt(request_id, provider="xai", operation="text_to_image")
      image_path = tmp_path / "candidate.png"
      image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
      artifact_id = ledger.record_artifact(
          attempt_id,
          kind="image",
          uri=str(image_path),
          content_hash="sha256:current",
          mime_type="image/png",
      )

      adapter = _VisualDeliveryStubAdapter(PlatformConfig(enabled=True, token="redacted"))
      metadata = visual_delivery_metadata(
          request_id=request_id,
          attempt_id=attempt_id,
          artifact_ids=[artifact_id],
          artifact_paths=[str(image_path)],
      )

      await adapter.send_multiple_images("C123", [(str(image_path), "caption")], metadata=metadata)

      deliveries = ledger.list_deliveries(request_id=request_id)
      assert len(deliveries) == 1
      assert deliveries[0]["artifact_id"] == artifact_id
      assert deliveries[0]["delivery_status"] == "sent"
      assert deliveries[0]["destination"] == "slack:C123:T123"
  ```

  If the current adapter API differs at execution time, keep the assertions
  fixed and adapt only the test harness to the actual helper names.

- [ ] **Step 3: Run red delivery tests**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_delivery_dedupe.py tests/gateway/test_send_image_file.py -q
  ```

  Expected: new dedupe test fails until `ArtifactDeliveryDeduper` exists.

- [ ] **Step 4: Implement delivery dedupe and metadata gate**

  Modify `gateway/platforms/base.py` so native media delivery:

  - builds visual metadata from current artifact paths;
  - skips unselected/stale artifacts;
  - records `sent`, `failed`, `skipped_duplicate`, or `skipped_stale`;
  - never blocks ordinary non-visual files if visual metadata is absent.

- [ ] **Step 5: Verify milestone 4**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_delivery_dedupe.py tests/gateway/test_send_image_file.py tests/gateway/test_tts_media_routing.py tests/gateway/test_slack.py -q
  rtk git diff --check
  ```

  Expected: tests pass and ordinary media delivery remains unchanged.

- [ ] **Step 6: Commit milestone 4**

  Run:

  ```bash
  rtk git add agent/visual/delivery_dedupe.py gateway/platforms/base.py tests/visual/test_delivery_dedupe.py tests/gateway
  rtk git commit -m "feat: gate visual artifact delivery"
  ```

## Milestone 5: Deterministic Judges and Ranker v0

**Purpose:** Rank by artifact evidence before using VLM or learning.

- [ ] **Step 1: Write deterministic judge tests**

  Create `tests/visual/test_deterministic_judges.py`:

  ```python
  def test_deterministic_judge_hard_gate_fails_stale_artifact():
      from agent.visual.judges.deterministic import judge_artifact

      score = judge_artifact(
          {
              "kind": "image",
              "mime_type": "image/png",
              "bytes": 100,
              "width": 1280,
              "height": 720,
              "freshness_status": "stale",
              "is_stable": True,
          },
          expected_kind="image",
          requested_parameters={"aspect_ratio": "16:9"},
      )

      assert score["hard_gate"]["passed"] is False
      assert score["hard_gate"]["artifact_fresh"] is False
  ```

- [ ] **Step 2: Write ranker tests**

  Create `tests/visual/test_ranker.py`:

  ```python
  def test_ranker_selects_highest_fresh_candidate_and_excludes_failed_gate():
      from agent.visual.ranker import rank_visual_candidates

      decision = rank_visual_candidates(
          request_id="vrq_test",
          candidates=[
              {
                  "attempt_id": "vat_stale",
                  "artifact_id": "var_stale",
                  "scores": {"final_score": 0.95},
                  "hard_gate": {"passed": False},
              },
              {
                  "attempt_id": "vat_good",
                  "artifact_id": "var_good",
                  "scores": {"final_score": 0.78},
                  "hard_gate": {"passed": True},
              },
          ],
          post_threshold=0.70,
          ask_threshold=0.55,
      )

      assert decision.decision == "post"
      assert decision.selected_artifact_id == "var_good"
  ```

- [ ] **Step 3: Run red judge/ranker tests**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_deterministic_judges.py tests/visual/test_ranker.py -q
  ```

  Expected: FAIL because judge and ranker modules are missing.

- [ ] **Step 4: Implement deterministic judge and ranker**

  Implement:

  - hard gates: exists, fresh, MIME valid, kind match, no provider error, delivery possible;
  - soft scores: aspect match, resolution, duration, provider reliability neutral default fixed at `0.5`;
  - decision: `post`, `ask_user`, `retry`, `fail`;
  - version labels: `deterministic_judge.v0.1`, `visual_ranker.v0.1`.

- [ ] **Step 5: Verify milestone 5**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_deterministic_judges.py tests/visual/test_ranker.py -q
  rtk git diff --check
  ```

  Expected: tests pass and diff check is clean.

- [ ] **Step 6: Commit milestone 5**

  Run:

  ```bash
  rtk git add agent/visual/judges agent/visual/ranker.py tests/visual/test_deterministic_judges.py tests/visual/test_ranker.py
  rtk git commit -m "feat: rank visual artifacts with deterministic gates"
  ```

## Milestone 6: Minimal Visual Package Orchestrator

**Purpose:** Restore user-friendly “image + video” package behavior without restoring the old large Visual Agent stack.

**Interface:**

```python
async def visual_package_generate(prompt: str, attachments: list[str] | None = None) -> dict:
    """Generate image/video package, rank artifacts, and return selected media paths."""
```

- [ ] **Step 1: Write orchestration tests**

  Create `tests/tools/test_visual_package_tool.py`:

  ```python
  import json
  import pytest

  @pytest.mark.asyncio
  async def test_visual_package_generate_returns_selected_image_and_video(monkeypatch, tmp_path):
      from tools import visual_package_tool

      image = tmp_path / "image.png"
      video = tmp_path / "video.mp4"
      image.write_bytes(
          b"\x89PNG\r\n\x1a\n"
          b"\x00\x00\x00\rIHDR"
          b"\x00\x00\x00\x01\x00\x00\x00\x01"
          b"\x08\x02\x00\x00\x00"
          b"\x90wS\xde"
          b"\x00\x00\x00\x00IEND\xaeB`\x82"
      )
      video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")

      monkeypatch.setattr(
          visual_package_tool,
          "generate_image",
          lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image-fixture"},
      )
      monkeypatch.setattr(
          visual_package_tool,
          "generate_video",
          lambda **kwargs: {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"},
      )

      payload = json.loads(
          await visual_package_tool._handle_visual_package_generate(
              {"prompt": "請產出一張圖片和一段影片：霧黑鋼筆，柔和窗光。"}
          )
      )

      assert payload["success"] is True
      assert payload["images"] == [str(image)]
      assert payload["videos"] == [str(video)]
      assert payload["package_status"] == "success"
      assert payload["delivery_metadata"]["selected_visual_artifact_ids"]
  ```

- [ ] **Step 2: Run red orchestration test**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py -q
  ```

  Expected: FAIL because `tools.visual_package_tool` does not exist.

- [ ] **Step 3: Implement `tools/visual_package_tool.py`**

  Implement minimal package flow:

  - detect image/video request from prompt;
  - call existing `image_generate` and `video_generate` handlers;
  - use generated image as reference for image-to-video when video is requested;
  - record attempts through tracking hook;
  - run deterministic judge/ranker;
  - return only selected image/video paths and `delivery_metadata`.

- [ ] **Step 4: Add tool routing guidance**

  Modify prompt/tool guidance so natural requests like:

  ```text
  請產出一張圖片和一段影片
  做一組視覺素材
  image plus short video
  product photo and 6 second clip
  ```

  prefer `visual_package_generate`.

- [ ] **Step 5: Verify milestone 6**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/tools/test_visual_package_tool.py tests/tools/test_image_generation.py tests/plugins/video_gen/test_xai_plugin.py -q
  rtk git diff --check
  ```

  Expected: tests pass and existing image/video tools still pass.

- [ ] **Step 6: Commit milestone 6**

  Run:

  ```bash
  rtk git add tools/visual_package_tool.py tests/tools/test_visual_package_tool.py agent/prompt_builder.py agent/tool_executor.py
  rtk git commit -m "feat: add visual package generation tool"
  ```

## Milestone 7: Self-Smoke, Report, and Live Proof

**Purpose:** Let the agent verify the visual loop without requiring Simon to drive every Slack round.

- [ ] **Step 1: Write self-smoke test**

  Create `tests/scripts/test_visual_evidence_self_smoke.py`:

  ```python
  import json

  def test_visual_evidence_self_smoke_passes_in_isolated_home(tmp_path, capsys):
      from scripts.visual_evidence_self_smoke import main

      exit_code = main(["--work-dir", str(tmp_path), "--json"])

      payload = json.loads(capsys.readouterr().out)
      assert exit_code == 0
      assert payload["success"] is True
      assert payload["proof"]["duplicate_artifact_delivery_count"] == 0
      assert payload["proof"]["missing_source_metadata_count"] == 0
      assert payload["feedback"]["count"] >= 2
      assert "raw_prompt" not in json.dumps(payload).lower()
  ```

- [ ] **Step 2: Run red self-smoke test**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/scripts/test_visual_evidence_self_smoke.py -q
  ```

  Expected: FAIL because script is missing.

- [ ] **Step 3: Implement self-smoke and report**

  Create:

  - `scripts/visual_evidence_self_smoke.py`
  - `scripts/visual_evidence_report.py`

  Self-smoke must:

  - create temporary Hermes home;
  - create synthetic image and video artifacts;
  - record request/attempt/artifact/delivery rows;
  - record feedback rows;
  - run proof checks;
  - emit JSON without raw prompts or media bytes.

- [ ] **Step 4: Verify milestone 7**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/scripts/test_visual_evidence_self_smoke.py -q
  rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
  rtk git diff --check
  ```

  Expected:

  - tests pass;
  - script returns `success: true`;
  - duplicate deliveries are 0;
  - missing source metadata is 0;
  - feedback count is at least 2.

- [ ] **Step 5: Commit milestone 7**

  Run:

  ```bash
  rtk git add scripts/visual_evidence_self_smoke.py scripts/visual_evidence_report.py tests/scripts/test_visual_evidence_self_smoke.py
  rtk git commit -m "feat: add visual evidence self smoke"
  ```

## Milestone 8: Feedback Parser Without Learning

**Purpose:** Attribute user feedback to the right artifact before changing future behavior.

- [ ] **Step 1: Write feedback parser tests**

  Create `tests/visual/test_feedback_parser.py`:

  ```python
  def test_feedback_parser_extracts_selection_and_quality_signal():
      from agent.visual.feedback import parse_visual_feedback

      feedback = parse_visual_feedback("第 2 張不錯，腿部構圖更好，但臉有點不自然")

      assert feedback.selection_hint == 2
      assert feedback.polarity > 0
      assert "composition_positive" in feedback.parsed["signals"]
      assert "face_unnatural" in feedback.parsed["issues"]
  ```

- [ ] **Step 2: Run red feedback test**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_feedback_parser.py -q
  ```

  Expected: FAIL because feedback parser is missing.

- [ ] **Step 3: Implement parser and ledger recording helper**

  Implement `agent/visual/feedback.py`:

  - `selection_hint`;
  - polarity;
  - issue tags: `reference_identity_drift`, `face_unnatural`, `not_beautiful`, `not_sexy_enough`, `composition_bad`, `static_video`, `motion_good`, `stale_repost`;
  - no automatic strategy update.

- [ ] **Step 4: Verify milestone 8**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual/test_feedback_parser.py tests/scripts/test_visual_evidence_self_smoke.py -q
  rtk git diff --check
  ```

  Expected: tests pass and self-smoke still records feedback.

- [ ] **Step 5: Commit milestone 8**

  Run:

  ```bash
  rtk git add agent/visual/feedback.py tests/visual/test_feedback_parser.py
  rtk git commit -m "feat: parse visual feedback without learning"
  ```

## Milestone 9: Live Rollout Gate

**Purpose:** Prove the upgraded runtime can run the new loop safely.

- [ ] **Step 1: Run deterministic suite**

  Run:

  ```bash
  rtk ./venv/bin/python -m pytest tests/visual tests/tools/test_visual_package_tool.py tests/scripts/test_visual_evidence_self_smoke.py -q
  rtk ./venv/bin/python -m pytest tests/tools/test_image_generation.py tests/plugins/video_gen/test_xai_plugin.py tests/gateway/test_send_image_file.py tests/gateway/test_tts_media_routing.py tests/gateway/test_slack.py -q
  ```

  Expected: all selected tests pass.

- [ ] **Step 2: Run self-smoke**

  Run:

  ```bash
  rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
  ```

  Expected: `success: true`.

- [ ] **Step 3: Restart gateway after code deployment**

  Run:

  ```bash
  rtk hermes gateway restart
  rtk hermes gateway status
  rtk hermes cron status
  ```

  Expected:

  - gateway PID changes;
  - service definition matches current install;
  - Slack reconnects in logs;
  - cron reports gateway running.

- [ ] **Step 4: Run live provider smoke**

  Run:

  ```bash
  rtk hermes chat -Q --max-turns 1 -q "Reply exactly: OK"
  tail -220 /Users/simon/.hermes/logs/agent.log | rg "provider=xai-oauth|model=grok-4.3|Reply exactly: OK"
  ```

  Expected:

  - chat returns `OK`;
  - agent log shows `provider=xai-oauth` and `model=grok-4.3`.

- [ ] **Step 5: Run live visual package smoke**

  Send a low-risk Slack prompt:

  ```text
  請產出一張圖片和一段影片：一支霧黑鋼筆放在白紙上，柔和窗光，乾淨產品攝影。完成後直接貼在 Slack。
  ```

  Expected:

  - one image and one video are delivered;
  - no old media is reposted;
  - report shows current request rows, fresh artifacts, sent deliveries, duplicate count 0.

- [ ] **Step 6: Push to origin**

  Run:

  ```bash
  rtk git status --short --branch
  rtk git push origin upgrade/hermes-v2026.6.19-local
  ```

  Expected:

  - worktree clean before push;
  - origin branch receives all milestone commits.

## Phase 2: Learning After Evidence Exists

Start this only after Milestones 1-9 are green.

Phase 2 scope:

- strategy atoms;
- provider reliability priors;
- user style preference priors;
- VLM image/video judges;
- candidate sets with counterfactual logging;
- active learning prompts;
- shadow-mode learning report.

Phase 2 must not mutate prompts automatically until shadow-mode reports show stable evidence across multiple real requests.

## Final Acceptance Criteria

- The upgraded branch stays based on v2026.6.19 and does not revive old Visual Agent code wholesale.
- `hermes status`, `fallback list`, live chat smoke, gateway status, and logs agree on active provider state.
- Every visual generation attempt can be joined from request to attempt to artifact to delivery.
- Every selected artifact has stable local identity, hash, freshness status, and delivery status.
- Slack delivery posts only selected current artifacts and records skipped duplicates/stale candidates.
- Deterministic ranker can choose a winner or ask/retry/fail without VLM judges.
- Self-smoke passes without live providers or human Slack interaction.
- Live visual package smoke posts exactly the current image/video pair.
- No tracked file contains raw prompts, generated media, user preference corpora, local model endpoints, tokens, or provider responses.

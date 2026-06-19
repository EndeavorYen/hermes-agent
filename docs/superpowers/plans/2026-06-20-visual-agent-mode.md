# Visual Agent Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Hermes Visual Agent Mode: a bounded production loop that plans, generates, judges, repairs, animates, assembles, delivers, and learns from image/video artifacts based on user-provided materials and instructions.

**Architecture:** Extend the existing visual evidence layer instead of replacing it. Add `agent.visual.agent_mode` for mission planning, asset graph, package assembly, and loop policy; use existing `image_generate_mission`, `image_generate`, `video_generate`, `agent.visual.attempt_ledger`, and Slack delivery gates as the execution substrate. Keep the first version provider-agnostic and shadow-friendly, with behavior gates controlled by config.

**Tech Stack:** Python stdlib (`dataclasses`, `enum`, `json`, `sqlite3`, `pathlib`, `typing`), existing Hermes tool registry, `pytest`, current image/video provider interfaces, existing `agent.visual` ledger/artifact/ranker modules. Do not commit private prompts, generated media, LAN endpoints, local draft-model configuration, or user preference raw data.

## Global Constraints

- Use TDD for feature work, bug fixes, refactors, behavior changes, and upgrade ports.
- Runtime data stays under `~/.hermes`, not the repo checkout.
- Public fixtures must use generic examples such as `fashion editorial portrait`, `product showcase`, `reference character portrait`, or `animate this generated frame`.
- Push integration branches to `origin` only unless an explicit upstream PR workflow is requested.
- Existing `image_generate_mission` remains the image QC execution path; do not create a competing image mission tool.
- Visual Agent Mode must degrade gracefully when a provider, judge, or video backend fails.
- Slack delivery must only post selected current artifacts when visual metadata exists.
- Generated video must use aspect settings inferred from selected image dimensions unless the user explicitly overrides aspect ratio.
- Learning stores strategy atoms and scores, not raw private prompts.

## Execution Status

Status as of 2026-06-20 05:05 Asia/Taipei:

| Area | Status | Evidence |
| --- | --- | --- |
| Goal and plan documents | Done | `docs/visual-agent-mode-goal.md`, this plan |
| Mission model and asset graph | Done | `tests/visual/agent_mode/test_mission_planner.py`, `test_asset_graph.py` |
| Candidate, selection, clip, and assembler loop | Done | `tests/visual/agent_mode/test_loop_policy.py`, `test_image_batch.py`, `test_clip_builder.py`, `test_assembler.py` |
| Tool surface | Done | `tools/visual_agent_tool.py`, `tests/tools/test_visual_agent_tool.py` |
| Learning store slice | Done | `agent/visual/agent_mode/learning.py`, `tests/visual/agent_mode/test_learning.py` |
| Gateway package delivery path | Done in tests | `tests/gateway/test_media_extraction.py`, `tests/gateway/platforms/test_slack_visual_delivery.py`, `tests/gateway/test_send_multiple_images.py` |
| User-friendly natural trigger | Done in tests | Chinese image+video package requests infer `VISUAL_PACKAGE`; `visual_agent_generate` defaults to L2 auto-select and ignores model-invented internal args |
| Privacy gate | Done in tracked files | Runtime video/visual paths are ignored; private visual fixture wording was replaced with generic test data |
| Live CLI image+video smoke | Done | mission `vms_915e683f14b44d7b89acb96a0602834e`, image `var_7e14ab73338344dba02533b678e7aebe`, video `var_d0d50d86318a4e588df269360a3252de` |
| Live Slack delivery proof | Done | `scripts/visual_agent_live_proof.py --since-local-date 2026-06-20 --timezone Asia/Taipei` reports `success: true`, 1 image, 1 video, no missing artifact joins, and no duplicate artifact deliveries |

Implemented follow-up fixes from live smoke:

- `6feaf6134` preserves QC fallback candidates instead of dropping every near-miss.
- `2fb55962f` lets the xAI video provider run from async Hermes tool handlers without nested event-loop failure.
- `363f32b8a` splits visual-package still-image prompts so the image model does not render split-screen still/video contact sheets.
- `4cce96266` preserves image mission `visual_artifact_id` values so selected image/video IDs join back to `visual_artifacts`.
- Natural-language trigger follow-up teaches the planner Chinese image/video/count terms and makes the package tool default to auto-select, so users do not need to say `visual_agent_generate` or `autonomy_level=2`.
- User-friendly hardening ignores model-invented internal args such as
  `autonomy_level=1` unless the user explicitly wrote the matching `key=...`,
  so a normal image+video request stays in L2 auto-select mode.
- Live-proof self-evaluation follow-up rejects duplicate sent deliveries for
  the same artifact ID, so the final Slack proof cannot pass when Hermes posts
  the same selected image or video twice.
- Live-proof timestamp follow-up adds `--since-local-date` and `--timezone`,
  preventing local-day acceptance windows from being accidentally interpreted
  as UTC timestamps.
- Focused verification passed with 41 tests covering routing guidance, wrong-tool guardrails, natural tool defaults, gateway current-turn media append, and Slack selected-artifact delivery metadata.
- Privacy follow-up removed tracked user-specific visual prompt fixtures, added runtime video/visual ignore rules, and kept feedback/parser tests on generic examples.
- Final focused verification passed with 376 Visual Agent Mode, routing, delivery, privacy-fixture, and feedback tests after the scrub.
- Live gateway is running from the patched checkout and Slack Socket Mode is connected, but only a real user-originated Slack request can close the final inbound proof gate. Bot-authored Slack messages and CLI handoff notices are not counted as proof because they do not exercise the same user inbound path.
- Gate F now has a reusable read-only verifier:

```bash
/Users/simon/.hermes/hermes-agent/venv/bin/python scripts/visual_agent_live_proof.py \
  --ledger-path /Users/simon/.hermes/visual/attempt_ledger.sqlite3 \
  --since-local-date <YYYY-MM-DD> \
  --timezone Asia/Taipei \
  --platform slack \
  --destination-id <slack_chat_id> \
  --json
```

Current live run result for local date `2026-06-20` in `Asia/Taipei`:
`success: true`, `sent_delivery_count: 2`, `artifact_kind_counts:
{"image": 1, "video": 1}`, `missing_artifact_join_count: 0`, and
`duplicate_artifact_delivery_count: 0`. The resolved ledger timestamp is
`2026-06-19T16:00:00Z`.

Evidence boundary: the live proof verifies Slack delivery rows and artifact
joins. Current legacy `visual_requests` rows for those artifacts do not carry
platform/channel metadata, so the acceptance proof is Slack delivery evidence
rather than a request-row source assertion.
- Self-evaluation follow-up strengthened package evidence: `assemble_visual_package`
  now includes `asset_graph`, `selection_summary`, and image `ranking_decisions`
  in `delivery_metadata`, so a package can be traced from selected artifacts
  back to source request/attempt IDs and the rank/score that chose the image
  before Slack delivery.
- Feedback attribution follow-up groups recent selected package deliveries that
  have no shared platform `message_id`, so image/video packages posted as
  separate Slack messages can still receive per-artifact feedback such as
  `第 1 張... 第 2 張...`.
- Partial-success follow-up adds `package_status`, `missing_outputs`, and
  `stop_reasons` to `visual_agent_generate` results, so a failed video stage is
  reported as `partial_success` instead of looking like a complete package.
- Assisted-mode stop-reason follow-up distinguishes `manual_selection_required`
  from `low_image_confidence`, so L1 human confirmation is not misclassified as
  a low-quality result.

User-facing trigger contract:

- Users should ask in ordinary language, for example: `請幫我產出一張圖片和一段影片：一支霧黑鋼筆放在白紙上，柔和窗光，乾淨產品攝影。`
- More casual forms should also work, for example: `幫我產圖產影片：霧黑鋼筆產品攝影。` or `做一組產品視覺素材，含短片。`
- Users should not need to mention `visual agent mode`, `visual_agent_generate`, `autonomy_level`, `candidate_budget`, `video_budget`, or provider names.
- When a request clearly asks for a combined image/video package, Hermes should call `visual_agent_generate` exactly once and let it plan, generate, select, animate, and package the result.
- Internal knobs remain available only for debugging or explicit advanced
  overrides. If the model supplies those args without the user writing the
  corresponding `key=...` in the prompt, the tool ignores them.

---

## Product Boundary

Visual Agent Mode is the layer above individual image and video tools.

It should produce a `VisualMissionResult` that contains:

- mission metadata;
- selected image artifacts;
- selected video artifacts;
- ranking and stop reasons;
- delivery metadata;
- a compact user-facing summary.

It should not train a neural model, invent a new provider SDK, bypass existing provider policy, or store private prompt examples in tracked files.

## File Structure

Create:

```text
agent/visual/agent_mode/
  __init__.py
  types.py
  mission_planner.py
  asset_graph.py
  loop_policy.py
  image_batch.py
  clip_builder.py
  assembler.py
  learning.py

tests/visual/agent_mode/
  test_mission_planner.py
  test_asset_graph.py
  test_loop_policy.py
  test_image_batch.py
  test_clip_builder.py
  test_assembler.py
  test_learning.py

tools/visual_agent_tool.py
tests/tools/test_visual_agent_tool.py
```

Modify only after the isolated modules are green:

```text
tools/image_mission_tool.py
tools/video_generation_tool.py
tools/registry.py
gateway/run.py
gateway/platforms/base.py
gateway/platforms/slack.py
tests/gateway/test_media_extraction.py
tests/gateway/platforms/test_slack_visual_delivery.py
```

## Interfaces

These names are the contract for all tasks.

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class VisualMissionType(str, Enum):
    IMAGE_SET = "image_set"
    IMAGE_TO_VIDEO = "image_to_video"
    VISUAL_PACKAGE = "visual_package"
    REPAIR_EXISTING = "repair_existing"

class VisualArtifactRole(str, Enum):
    UPLOADED_REFERENCE = "uploaded_reference"
    GENERATED_IMAGE = "generated_image"
    SELECTED_IMAGE = "selected_image"
    GENERATED_VIDEO = "generated_video"
    FINAL_DELIVERY = "final_delivery"

@dataclass(frozen=True)
class VisualMission:
    mission_id: str
    mission_type: VisualMissionType
    user_prompt: str
    output_goal: str
    requested_outputs: List[str]
    constraints: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    input_assets: List[str] = field(default_factory=list)
    candidate_budget: int = 3
    video_budget: int = 1
    autonomy_level: int = 1

@dataclass(frozen=True)
class VisualAssetNode:
    asset_id: str
    role: VisualArtifactRole
    artifact_id: Optional[str] = None
    local_path: Optional[str] = None
    source_url: Optional[str] = None
    parent_asset_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class VisualMissionResult:
    success: bool
    mission_id: str
    selected_image_artifact_ids: List[str]
    selected_video_artifact_ids: List[str]
    delivery_metadata: Dict[str, Any]
    summary: str
    stop_reason: Optional[str] = None
```

---

## Milestone 1: Mission And Asset Model

Goal: define the production contract without invoking image or video providers.

### Task 1: Visual Mission Planner

**Files:**
- Create: `agent/visual/agent_mode/__init__.py`
- Create: `agent/visual/agent_mode/types.py`
- Create: `agent/visual/agent_mode/mission_planner.py`
- Test: `tests/visual/agent_mode/test_mission_planner.py`

**Interfaces:**
- Consumes: no prior task.
- Produces: `VisualMission`, `VisualMissionType`, `VisualArtifactRole`, `VisualMissionResult`, `plan_visual_mission(user_prompt: str, attachments: list[str] | None = None, autonomy_level: int = 1) -> VisualMission`.

- [ ] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualMissionType


def test_plans_visual_package_when_image_and_video_requested():
    mission = plan_visual_mission(
        "Create a product showcase with three images and one short video.",
        attachments=["/tmp/reference.png"],
        autonomy_level=2,
    )

    assert mission.mission_id.startswith("vms_")
    assert mission.mission_type == VisualMissionType.VISUAL_PACKAGE
    assert mission.input_assets == ["/tmp/reference.png"]
    assert mission.candidate_budget == 3
    assert mission.video_budget == 1
    assert mission.autonomy_level == 2
    assert "image" in mission.requested_outputs
    assert "video" in mission.requested_outputs


def test_plans_image_set_for_image_only_request():
    mission = plan_visual_mission(
        "Generate four editorial image options from this reference.",
        attachments=["/tmp/reference.png"],
    )

    assert mission.mission_type == VisualMissionType.IMAGE_SET
    assert mission.candidate_budget == 4
    assert mission.video_budget == 0
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_mission_planner.py -q
```

Expected: fails because `agent.visual.agent_mode` does not exist.

- [ ] **Step 3: Implement minimal planner**

Create the dataclasses and enums from the **Interfaces** section. Implement `plan_visual_mission` with rule-based parsing:

```python
def plan_visual_mission(user_prompt, attachments=None, autonomy_level=1):
    text = (user_prompt or "").strip()
    lowered = text.lower()
    wants_video = any(token in lowered for token in ("video", "clip", "animate", "animation"))
    wants_image = any(token in lowered for token in ("image", "images", "photo", "picture", "portrait"))
    count = _extract_requested_count(text, default=3)
    mission_type = VisualMissionType.VISUAL_PACKAGE if wants_video and wants_image else (
        VisualMissionType.IMAGE_TO_VIDEO if wants_video else VisualMissionType.IMAGE_SET
    )
    return VisualMission(
        mission_id=new_mission_id(),
        mission_type=mission_type,
        user_prompt=text,
        output_goal=text,
        requested_outputs=(["image"] if wants_image or not wants_video else []) + (["video"] if wants_video else []),
        input_assets=list(attachments or []),
        candidate_budget=count if wants_image or not wants_video else 1,
        video_budget=1 if wants_video else 0,
        autonomy_level=max(0, min(4, int(autonomy_level))),
    )
```

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_mission_planner.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/__init__.py agent/visual/agent_mode/types.py agent/visual/agent_mode/mission_planner.py tests/visual/agent_mode/test_mission_planner.py
/opt/homebrew/bin/rtk git commit -m "feat: add visual mission planner"
```

### Task 2: Asset Graph

**Files:**
- Create: `agent/visual/agent_mode/asset_graph.py`
- Test: `tests/visual/agent_mode/test_asset_graph.py`

**Interfaces:**
- Consumes: `VisualAssetNode`, `VisualArtifactRole`.
- Produces: `VisualAssetGraph`, `add_asset(...)`, `link(parent_asset_id: str, child_asset_id: str)`, `selected_artifact_ids(role: VisualArtifactRole) -> list[str]`, `to_dict() -> dict`.

- [ ] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.types import VisualArtifactRole


def test_asset_graph_tracks_reference_image_video_lineage():
    graph = VisualAssetGraph(mission_id="vms_test")
    ref = graph.add_asset(role=VisualArtifactRole.UPLOADED_REFERENCE, local_path="/tmp/ref.png")
    image = graph.add_asset(
        role=VisualArtifactRole.SELECTED_IMAGE,
        artifact_id="var_image",
        local_path="/tmp/generated.png",
    )
    video = graph.add_asset(
        role=VisualArtifactRole.GENERATED_VIDEO,
        artifact_id="var_video",
        local_path="/tmp/generated.mp4",
    )
    graph.link(ref.asset_id, image.asset_id)
    graph.link(image.asset_id, video.asset_id)

    assert graph.parents(image.asset_id) == [ref.asset_id]
    assert graph.parents(video.asset_id) == [image.asset_id]
    assert graph.selected_artifact_ids(VisualArtifactRole.SELECTED_IMAGE) == ["var_image"]
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_VIDEO) == ["var_video"]
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_asset_graph.py -q
```

Expected: fails because `asset_graph.py` does not exist.

- [ ] **Step 3: Implement graph**

Implement an in-memory graph backed by `dict[str, VisualAssetNode]`. Asset IDs must use prefix `vas_`. `link` must replace the child node with an updated dataclass containing the parent ID exactly once.

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_asset_graph.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/asset_graph.py tests/visual/agent_mode/test_asset_graph.py
/opt/homebrew/bin/rtk git commit -m "feat: add visual asset graph"
```

---

## Milestone 2: Production Policy And Image Candidate Loop

Goal: create bounded autonomous behavior before adding video and Slack assembly.

### Task 3: Loop Policy

**Files:**
- Create: `agent/visual/agent_mode/loop_policy.py`
- Test: `tests/visual/agent_mode/test_loop_policy.py`

**Interfaces:**
- Consumes: `VisualMission`.
- Produces: `VisualLoopPolicy`, `decide_next_action(mission: VisualMission, *, candidate_count: int, accepted_count: int, failure_count: int, confidence: float) -> str`.

- [ ] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.loop_policy import decide_next_action
from agent.visual.agent_mode.mission_planner import plan_visual_mission


def test_policy_generates_until_candidate_budget_is_met():
    mission = plan_visual_mission("Generate three image options.")

    assert decide_next_action(
        mission,
        candidate_count=1,
        accepted_count=0,
        failure_count=0,
        confidence=0.0,
    ) == "generate_image"


def test_policy_asks_when_confidence_is_low_after_candidates_exist():
    mission = plan_visual_mission("Generate three image options.", autonomy_level=1)

    assert decide_next_action(
        mission,
        candidate_count=3,
        accepted_count=1,
        failure_count=0,
        confidence=0.42,
    ) == "ask_user"


def test_policy_can_auto_select_at_autonomy_two():
    mission = plan_visual_mission("Generate three image options.", autonomy_level=2)

    assert decide_next_action(
        mission,
        candidate_count=3,
        accepted_count=2,
        failure_count=0,
        confidence=0.81,
    ) == "select_images"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_loop_policy.py -q
```

Expected: fails because `loop_policy.py` does not exist.

- [ ] **Step 3: Implement policy**

Rules:

- return `generate_image` while `candidate_count < mission.candidate_budget`;
- return `fail` when `failure_count >= max(3, mission.candidate_budget)` and `accepted_count == 0`;
- return `ask_user` when `confidence < 0.55`;
- return `select_images` when `mission.autonomy_level >= 2 and accepted_count > 0 and confidence >= 0.70`;
- return `ask_user` otherwise.

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_loop_policy.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/loop_policy.py tests/visual/agent_mode/test_loop_policy.py
/opt/homebrew/bin/rtk git commit -m "feat: add visual agent loop policy"
```

### Task 4: Image Candidate Batch From Existing Mission Tool

**Files:**
- Create: `agent/visual/agent_mode/image_batch.py`
- Test: `tests/visual/agent_mode/test_image_batch.py`

**Interfaces:**
- Consumes: `VisualMission`, `VisualAssetGraph`, existing `tools.image_mission_tool.run_image_generation_mission`.
- Produces: `generate_image_candidates(mission: VisualMission, graph: VisualAssetGraph, generate_once: Callable[..., dict]) -> dict`.

- [ ] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.image_batch import generate_image_candidates
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole


def test_generate_image_candidates_records_successful_candidates():
    mission = plan_visual_mission("Generate two image options.")
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    calls = []

    def fake_generate_once(**kwargs):
        calls.append(kwargs)
        idx = len(calls)
        return {
            "success": True,
            "image": f"/tmp/generated-{idx}.png",
            "visual_artifact_id": f"var_image_{idx}",
            "visual_request_id": f"vrq_image_{idx}",
            "visual_attempt_id": f"vat_image_{idx}",
        }

    result = generate_image_candidates(mission, graph, generate_once=fake_generate_once)

    assert result["success"] is True
    assert len(calls) == 2
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_IMAGE) == [
        "var_image_1",
        "var_image_2",
    ]
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_image_batch.py -q
```

Expected: fails because `image_batch.py` does not exist.

- [ ] **Step 3: Implement candidate batch**

Implement a synchronous wrapper that calls `generate_once` exactly `mission.candidate_budget` times. For each successful payload with `visual_artifact_id`, add a `GENERATED_IMAGE` asset to the graph. Return:

```python
{
    "success": bool(successful),
    "candidate_count": len(successful),
    "failure_count": len(failures),
    "candidates": successful,
    "failures": failures,
}
```

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_image_batch.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/image_batch.py tests/visual/agent_mode/test_image_batch.py
/opt/homebrew/bin/rtk git commit -m "feat: generate visual agent image candidates"
```

---

## Milestone 3: Ranking, Selection, And Video Clip Builder

Goal: choose images before delivery and create aspect-safe video clips from selected images.

### Task 5: Candidate Selection Using Existing Ranker

**Files:**
- Modify: `agent/visual/agent_mode/image_batch.py`
- Test: `tests/visual/agent_mode/test_image_batch.py`

**Interfaces:**
- Consumes: existing `agent.visual.ranker.rank_visual_candidates`.
- Produces: `select_image_candidates(graph: VisualAssetGraph, candidates: list[dict], max_selected: int = 2) -> list[str]`.

- [ ] **Step 1: Write failing test**

```python
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.image_batch import select_image_candidates
from agent.visual.agent_mode.types import VisualArtifactRole


def test_select_image_candidates_marks_selected_images():
    graph = VisualAssetGraph(mission_id="vms_test")
    graph.add_asset(role=VisualArtifactRole.GENERATED_IMAGE, artifact_id="var_low", local_path="/tmp/low.png")
    graph.add_asset(role=VisualArtifactRole.GENERATED_IMAGE, artifact_id="var_high", local_path="/tmp/high.png")

    selected = select_image_candidates(
        graph,
        [
            {"artifact_id": "var_low", "score": 0.55},
            {"artifact_id": "var_high", "score": 0.91},
        ],
        max_selected=1,
    )

    assert selected == ["var_high"]
    assert graph.selected_artifact_ids(VisualArtifactRole.SELECTED_IMAGE) == ["var_high"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_image_batch.py::test_select_image_candidates_marks_selected_images -q
```

Expected: fails because `select_image_candidates` does not exist.

- [ ] **Step 3: Implement selection**

Sort candidates by `score` descending. For each selected artifact, copy the generated image node into a `SELECTED_IMAGE` node with the original asset as its parent.

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_image_batch.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/image_batch.py tests/visual/agent_mode/test_image_batch.py
/opt/homebrew/bin/rtk git commit -m "feat: select visual agent image candidates"
```

### Task 6: Video Clip Builder

**Files:**
- Create: `agent/visual/agent_mode/clip_builder.py`
- Test: `tests/visual/agent_mode/test_clip_builder.py`

**Interfaces:**
- Consumes: `VisualMission`, `VisualAssetGraph`, existing `tools.video_generation_tool._handle_video_generate`.
- Produces: `build_video_clips(mission: VisualMission, graph: VisualAssetGraph, generate_video: Callable[[dict], dict]) -> dict`.

- [ ] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.clip_builder import build_video_clips
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole


def test_build_video_clips_uses_selected_images_only():
    mission = plan_visual_mission("Create images and one video.", autonomy_level=2)
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    generated = graph.add_asset(
        role=VisualArtifactRole.GENERATED_IMAGE,
        artifact_id="var_generated",
        local_path="/tmp/generated.png",
    )
    selected = graph.add_asset(
        role=VisualArtifactRole.SELECTED_IMAGE,
        artifact_id="var_selected",
        local_path="/tmp/selected.png",
    )
    graph.link(generated.asset_id, selected.asset_id)
    calls = []

    def fake_video(args):
        calls.append(args)
        return {
            "success": True,
            "video": "/tmp/clip.mp4",
            "visual_artifact_id": "var_video",
            "aspect_ratio": "9:16",
        }

    result = build_video_clips(mission, graph, generate_video=fake_video)

    assert result["success"] is True
    assert calls[0]["image_url"] == "/tmp/selected.png"
    assert calls[0]["prompt"] == mission.output_goal
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_VIDEO) == ["var_video"]
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_clip_builder.py -q
```

Expected: fails because `clip_builder.py` does not exist.

- [ ] **Step 3: Implement clip builder**

For the first `mission.video_budget` selected image assets, call:

```python
generate_video({
    "prompt": mission.output_goal,
    "image_url": selected.local_path,
    "duration": mission.constraints.get("duration", 6),
})
```

If the video payload has `visual_artifact_id`, add a `GENERATED_VIDEO` node and link it to the selected image node. Do not pass an explicit aspect ratio unless `mission.constraints["aspect_ratio"]` exists.

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_clip_builder.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/clip_builder.py tests/visual/agent_mode/test_clip_builder.py
/opt/homebrew/bin/rtk git commit -m "feat: build visual agent video clips"
```

---

## Milestone 4: Assembly And Tool Surface

Goal: expose one agent-facing tool that returns a packaged image/video result.

### Task 7: Visual Package Assembler

**Files:**
- Create: `agent/visual/agent_mode/assembler.py`
- Test: `tests/visual/agent_mode/test_assembler.py`

**Interfaces:**
- Consumes: `VisualMission`, `VisualAssetGraph`, `VisualMissionResult`.
- Produces: `assemble_visual_package(mission: VisualMission, graph: VisualAssetGraph) -> VisualMissionResult`.

- [ ] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.assembler import assemble_visual_package
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole


def test_assembler_returns_selected_image_and_video_artifacts():
    mission = plan_visual_mission("Create images and one video.", autonomy_level=2)
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    graph.add_asset(role=VisualArtifactRole.SELECTED_IMAGE, artifact_id="var_image", local_path="/tmp/image.png")
    graph.add_asset(role=VisualArtifactRole.GENERATED_VIDEO, artifact_id="var_video", local_path="/tmp/video.mp4")

    result = assemble_visual_package(mission, graph)

    assert result.success is True
    assert result.mission_id == mission.mission_id
    assert result.selected_image_artifact_ids == ["var_image"]
    assert result.selected_video_artifact_ids == ["var_video"]
    assert result.delivery_metadata["selected_visual_artifact_ids"] == ["var_image", "var_video"]
    assert "1 image" in result.summary
    assert "1 video" in result.summary
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_assembler.py -q
```

Expected: fails because `assembler.py` does not exist.

- [ ] **Step 3: Implement assembler**

Collect `SELECTED_IMAGE` and `GENERATED_VIDEO` nodes. Build delivery metadata:

```python
{
    "visual_mission_id": mission.mission_id,
    "selected_visual_artifact_ids": image_ids + video_ids,
    "visual_artifacts": {
        asset.local_path: {
            "artifact_id": asset.artifact_id,
            "request_id": asset.metadata.get("request_id", mission.mission_id),
            "attempt_id": asset.metadata.get("attempt_id", ""),
            "content_hash": asset.metadata.get("content_hash", ""),
        }
    }
}
```

Return `success=False` with `stop_reason="no_selected_artifacts"` when no selected images or videos exist.

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_assembler.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/assembler.py tests/visual/agent_mode/test_assembler.py
/opt/homebrew/bin/rtk git commit -m "feat: assemble visual agent package"
```

### Task 8: Agent-Facing Tool

**Files:**
- Create: `tools/visual_agent_tool.py`
- Test: `tests/tools/test_visual_agent_tool.py`

**Interfaces:**
- Consumes: `plan_visual_mission`, `VisualAssetGraph`, `generate_image_candidates`, `select_image_candidates`, `build_video_clips`, `assemble_visual_package`.
- Produces: tool `visual_agent_generate` with handler `_handle_visual_agent_generate(args: dict) -> str`.

- [ ] **Step 1: Write failing tests**

```python
import json


def test_visual_agent_generate_runs_image_video_package(monkeypatch):
    from tools import visual_agent_tool

    monkeypatch.setattr(
        visual_agent_tool,
        "generate_image_candidates",
        lambda mission, graph: {
            "success": True,
            "candidates": [{"artifact_id": "var_image", "score": 0.9, "image": "/tmp/image.png"}],
            "candidate_count": 1,
            "failure_count": 0,
        },
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "select_image_candidates",
        lambda graph, candidates, max_selected=2: ["var_image"],
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "build_video_clips",
        lambda mission, graph: {"success": True, "clips": [{"artifact_id": "var_video"}]},
    )

    payload = json.loads(visual_agent_tool._handle_visual_agent_generate({
        "prompt": "Create one image and one video.",
        "attachments": ["/tmp/ref.png"],
        "autonomy_level": 2,
    }))

    assert payload["success"] is True
    assert payload["mission_id"].startswith("vms_")
    assert payload["selected_image_artifact_ids"] == ["var_image"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tools/test_visual_agent_tool.py -q
```

Expected: fails because `tools.visual_agent_tool` does not exist.

- [ ] **Step 3: Implement tool**

Register:

```python
registry.register(
    name="visual_agent_generate",
    toolset="image_gen",
    schema=VISUAL_AGENT_GENERATE_SCHEMA,
    handler=_handle_visual_agent_generate,
    requires_env=[],
    emoji="VA",
)
```

The schema must accept `prompt`, `attachments`, `autonomy_level`, `candidate_budget`, and `video_budget`. The handler must:

1. plan mission;
2. build graph;
3. generate images;
4. select images when policy allows;
5. build clips when requested;
6. assemble package;
7. return JSON with `success`, `mission_id`, selected artifact IDs, summary, and delivery metadata.

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tools/test_visual_agent_tool.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add tools/visual_agent_tool.py tests/tools/test_visual_agent_tool.py
/opt/homebrew/bin/rtk git commit -m "feat: add visual agent generate tool"
```

---

## Milestone 5: Conservative Learning

Goal: convert outcomes into strategy signals without storing raw private prompts.

### Task 9: Strategy Atom Store

**Files:**
- Create: `agent/visual/agent_mode/learning.py`
- Test: `tests/visual/agent_mode/test_learning.py`

**Interfaces:**
- Consumes: `VisualMissionResult`, rows from `visual_feedback`, rows from `visual_deliveries`.
- Produces: `StrategyAtomStore(path)`, `record_outcome(bucket: str, strategy_id: str, reward: float, evidence: dict) -> None`, `top_strategies(bucket: str, limit: int = 5) -> list[dict]`.

- [ ] **Step 1: Write failing tests**

```python
from agent.visual.agent_mode.learning import StrategyAtomStore


def test_strategy_atom_store_updates_ewma_without_raw_prompt(tmp_path):
    store = StrategyAtomStore(tmp_path / "strategy_atoms.sqlite3")
    store.initialize()
    store.record_outcome(
        bucket="portrait_reference",
        strategy_id="low_angle_leg_emphasis",
        reward=0.8,
        evidence={"artifact_id": "var_1", "raw_prompt": "must not persist"},
    )

    rows = store.top_strategies("portrait_reference")

    assert rows[0]["strategy_id"] == "low_angle_leg_emphasis"
    assert rows[0]["score"] == 0.8
    assert "raw_prompt" not in rows[0]["evidence"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_learning.py -q
```

Expected: fails because `learning.py` does not exist.

- [ ] **Step 3: Implement learning store**

Use SQLite under a caller-provided path. Store columns:

```text
bucket TEXT
strategy_id TEXT
score REAL
count INTEGER
updated_at TEXT
evidence_json TEXT
PRIMARY KEY(bucket, strategy_id)
```

EWMA update:

```python
new_score = reward if count == 0 else (0.8 * old_score + 0.2 * reward)
```

Filter evidence keys to `artifact_id`, `request_id`, `attempt_id`, `provider`, `model`, `error_type`, `feedback_polarity`, and `score_components`.

- [ ] **Step 4: Re-run tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_learning.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add agent/visual/agent_mode/learning.py tests/visual/agent_mode/test_learning.py
/opt/homebrew/bin/rtk git commit -m "feat: add visual strategy atom store"
```

---

## Milestone 6: Gateway Delivery Integration

Goal: Slack receives only the assembled package artifacts, not every candidate.

### Task 10: Auto-Attach Visual Agent Package

**Files:**
- Modify: `gateway/run.py`
- Modify: `gateway/platforms/base.py`
- Test: `tests/gateway/test_media_extraction.py`
- Test: `tests/gateway/platforms/test_slack_visual_delivery.py`

**Interfaces:**
- Consumes: `visual_agent_generate` tool result JSON containing `delivery_metadata`, selected image paths, and selected video paths.
- Produces: gateway auto-append behavior that treats visual agent package artifacts as current-turn media.

- [ ] **Step 1: Write failing media extraction test**

Add a test in `tests/gateway/test_media_extraction.py`:

```python
def test_gateway_auto_append_keeps_current_visual_agent_package_only():
    payload = {
        "success": True,
        "mission_id": "vms_test",
        "images": ["/tmp/current.png"],
        "videos": ["/tmp/current.mp4"],
        "delivery_metadata": {
            "visual_mission_id": "vms_test",
            "selected_visual_artifact_ids": ["var_image", "var_video"],
        },
    }

    extracted = extract_media_from_tool_result(
        tool_name="visual_agent_generate",
        result_json=json.dumps(payload),
        current_tool_call_ids={"call_visual"},
        tool_call_id="call_visual",
    )

    assert "/tmp/current.png" in extracted.image_paths
    assert "/tmp/current.mp4" in extracted.video_paths
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/gateway/test_media_extraction.py::test_gateway_auto_append_keeps_current_visual_agent_package_only -q
```

Expected: fails because `visual_agent_generate` is not recognized as an auto-append visual tool.

- [ ] **Step 3: Implement gateway extraction**

Add `visual_agent_generate` to the current-turn visual tool allowlist. Copy `delivery_metadata` into the send metadata for both images and videos.

- [ ] **Step 4: Re-run focused tests**

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/gateway/test_media_extraction.py tests/gateway/platforms/test_slack_visual_delivery.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
/opt/homebrew/bin/rtk git add gateway/run.py gateway/platforms/base.py tests/gateway/test_media_extraction.py tests/gateway/platforms/test_slack_visual_delivery.py
/opt/homebrew/bin/rtk git commit -m "feat: deliver visual agent packages"
```

---

## Verification Gates

Do not call the feature complete until all gates pass.

### Gate A: Mission Model

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_mission_planner.py tests/visual/agent_mode/test_asset_graph.py -q
```

Required evidence:

- missions classify image, video, package, and repair requests;
- asset graph preserves lineage from reference to image to video.

### Gate B: Candidate And Clip Loop

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/visual/agent_mode/test_loop_policy.py tests/visual/agent_mode/test_image_batch.py tests/visual/agent_mode/test_clip_builder.py -q
```

Required evidence:

- loop policy respects budget and autonomy;
- image candidates are recorded;
- selected images are the only video inputs.

### Gate C: Tool Surface

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/tools/test_visual_agent_tool.py tests/tools/test_image_mission_tool.py tests/tools/test_video_generation_dispatch.py -q
```

Required evidence:

- `visual_agent_generate` returns a package result;
- existing `image_generate_mission` behavior remains intact;
- video generation aspect inference remains intact.

### Gate D: Slack Delivery

Run:

```bash
/opt/homebrew/bin/rtk /Users/simon/.hermes/hermes-agent/venv/bin/python -m pytest tests/gateway/test_media_extraction.py tests/gateway/platforms/test_slack_visual_delivery.py tests/gateway/test_send_multiple_images.py -q
```

Required evidence:

- only selected current package artifacts are sent;
- stale candidate artifacts are not posted;
- image and video delivery rows are recorded.

### Gate E: Privacy

Run tracked-file greps for private LAN endpoints, local draft-model names, hard preference files, raw prompt corpora, generated images, generated videos, and runtime SQLite files.

Expected:

- no private endpoint, local draft-model, raw prompt, generated media, or user preference data is tracked;
- `.gitignore` continues to exclude runtime visual data.

Current evidence:

- `.gitignore` excludes `cache/images/`, `cache/videos/`, `video_cache/`, root `visual/`, Visual Arsenal data, mediator memories, ranking runs, preference buckets, style strategies, and hard-preference files.
- Tracked visual tests use generic product/editorial/reference-library fixtures instead of user-specific prompt or feedback examples.
- Focused tracked-file greps found no private LAN endpoint or local draft-model references. Remaining token-looking matches are fake test/doc examples, not real credentials.

### Gate F: Live Smoke

Use safe, generic materials only.

Expected:

- one `visual_agent_generate` call creates a mission;
- at least one image artifact is generated and selected;
- one video clip is generated from the selected image when requested;
- Slack posts only selected image/video artifacts;
- `visual_requests`, `visual_artifacts`, `visual_deliveries`, and mission package output can be joined by artifact IDs.

Current evidence:

- CLI smoke passed for a safe product brief after gateway restart.
- Tool output selected image artifact `var_7e14ab73338344dba02533b678e7aebe` and video artifact `var_d0d50d86318a4e588df269360a3252de`.
- Ledger rows exist for both selected artifact IDs, with xAI image and `grok-imagine-video-1.5` attempts and no provider errors.
- Video file verified at 1280x720, about 6.04 seconds.
- Slack delivery proof for local date `2026-06-20` in `Asia/Taipei` passes with
  image artifact `var_59ebd6bb3a6f423d9b5172edee801633` and video artifact
  `var_fcd4e3a726874b669afcb009f909a884`.
- The proof has `sent_delivery_count: 2`, `artifact_kind_counts: {"image": 1,
  "video": 1}`, `missing_artifact_join_count: 0`, and
  `duplicate_artifact_delivery_count: 0`.
- The acceptance command uses `--since-local-date 2026-06-20 --timezone
  Asia/Taipei`, which resolves to `2026-06-19T16:00:00Z` before querying the
  UTC ledger timestamps.
- Evidence boundary: current legacy `visual_requests` rows for those artifacts
  have empty platform/channel fields, so the live proof verifies Slack delivery
  rows and artifact joins, not request-row source metadata.

## First Execution Slice

Start with Tasks 1-4.

Why:

- no Slack behavior change;
- no provider policy change;
- creates the mission and asset graph contract;
- lets reviewers reject the orchestration shape before video and Slack delivery are wired.

First slice commits:

```text
feat: add visual mission planner
feat: add visual asset graph
feat: add visual agent loop policy
feat: generate visual agent image candidates
```

After Task 4, review:

- Are mission fields sufficient for image and video package requests?
- Does the asset graph explain reference -> image -> video lineage?
- Does the loop policy keep autonomy bounded?
- Are private prompts absent from tests and docs?

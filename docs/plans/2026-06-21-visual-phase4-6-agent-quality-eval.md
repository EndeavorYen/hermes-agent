# Visual Phase 4-6 Agent Quality and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the next visual-agent layer by adding self-supervised quality judges, natural-language visual agent planning, and continuous regression gates that make Hermes improve with less human intervention.

**Architecture:** Phase 4 adds privacy-safe quality evidence before ranking. Phase 5 adds a natural-language trigger/planner that converts user-friendly requests into `visual_package_generate` arguments. Phase 6 adds a repeatable regression report/release gate over the ledger and fixture smokes. These phases remain evidence-led: provider output is scored and audited, but production prompt mutation remains disabled unless separately promoted by controlled autonomy gates.

**Tech Stack:** Python 3.11, SQLite, existing `agent.visual` modules, Hermes `visual_package_generate`, pytest, ruff, `scripts/visual_evidence_self_smoke.py`, `scripts/visual_phase2_self_check.py`, `scripts/visual_strategy_activation_report.py`.

## Global Constraints

- Base branch: `upgrade/hermes-v2026.6.19-local`.
- Push local integration work to `origin` only unless an explicit upstream PR workflow is requested.
- Use TDD for every behavior change; write the failing test first, run it, implement the smallest fix, then re-run.
- Runtime-private data stays under `/Users/simon/.hermes`; do not commit raw prompts, generated media, local network endpoints, tokens, provider responses, or user preference corpora.
- Judge output is evidence, not ground truth.
- Aesthetic scores must not hide provider, delivery, safety, or duplicate failures.
- Provider reliability must remain separate from aesthetic preference.
- User-friendly triggering must not require `autonomy_level`, `candidate_budget`, or `video_budget`.
- Slack delivery must receive only selected current artifacts.
- Prompt mutation remains disabled unless a separate controlled activation explicitly enables it.

---

## Phase 4 Goal: Visual Quality Judges

Add a local, deterministic quality-judge layer that creates stronger self-supervised signals before candidates are ranked.

### Phase 4 Milestone 1: Quality Judge Interface

**Files:**

- Create: `agent/visual/judges/quality.py`
- Test: `tests/visual/test_quality_judges.py`

**Interfaces:**

- Produces:
  - `judge_visual_quality(candidate: dict[str, Any], *, request_context: dict[str, Any] | None = None, recent_artifact_hashes: set[str] | None = None) -> dict[str, Any]`

**Acceptance:**

- Returns privacy-safe score dimensions:
  - `reference_adherence`
  - `aesthetic_fit`
  - `composition`
  - `novelty`
  - `motion_quality`
  - `aspect_integrity`
  - `delivery_readiness`
- Includes `confidence` and `uncertainty_reasons`.
- Does not echo raw prompt text.
- Penalizes duplicate content hashes through novelty.
- Penalizes missing reference evidence when a reference was supplied.

### Phase 4 Milestone 2: Package Tool Quality Integration

**Files:**

- Modify: `tools/visual_package_tool.py`
- Test: `tests/tools/test_visual_package_tool.py`

**Acceptance:**

- `_score_candidates()` attaches `candidate["judge_scores"]`.
- Reward model consumes quality judge scores before ranking.
- Ledger records a `visual_judgments` row for each judged candidate.
- Existing self-smoke remains green.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_quality_judges.py tests/tools/test_visual_package_tool.py tests/visual/test_reward_model.py -q
rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
rtk ./venv/bin/python -m ruff check agent/visual tools/visual_package_tool.py tests/visual/test_quality_judges.py tests/tools/test_visual_package_tool.py
rtk git diff --check
```

**Phase 4 Self-Review:**

- Did the judge improve automatic scoring without hiding hard failures?
- Is every score explainable from artifact/request metadata?
- Is raw prompt text excluded from judge output?
- Does missing evidence lower confidence instead of inventing certainty?

## Phase 5 Goal: Visual Agent Mode Planner

Add a user-friendly natural-language planner so callers can route requests into visual package generation without exposing advanced knobs.

### Phase 5 Milestone 1: Trigger and Planner

**Files:**

- Create: `agent/visual/agent_mode/__init__.py`
- Create: `agent/visual/agent_mode/planner.py`
- Test: `tests/visual/test_agent_mode_planner.py`

**Interfaces:**

- Produces:
  - `plan_visual_agent_request(prompt: str, *, attachments: list[str] | None = None) -> dict[str, Any]`

**Acceptance:**

- Detects image-only, video-only, and image-plus-video requests.
- Converts natural-language requests into `visual_package_generate` arguments.
- Defaults to one image candidate and one video when the user asks for both.
- Keeps advanced knobs optional.
- Does not include raw prompt in diagnostic fields beyond the tool argument that must be sent to the generator.

### Phase 5 Milestone 2: Provider-Neutral Failure Negotiation Contract

**Files:**

- Modify: `agent/visual/agent_mode/planner.py`
- Test: `tests/visual/test_agent_mode_planner.py`

**Acceptance:**

- Returns a `recovery_policy` block with:
  - `retry_budget`
  - `safe_reframe_allowed`
  - `ask_user_on_low_confidence`
- Does not bypass provider policy or content controls.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_agent_mode_planner.py tests/tools/test_visual_package_tool.py -q
rtk ./venv/bin/python -m ruff check agent/visual/agent_mode tests/visual/test_agent_mode_planner.py
rtk git diff --check
```

**Phase 5 Self-Review:**

- Can a normal user trigger the package path without parameter syntax?
- Does the planner preserve the user's actual requested output types?
- Are recovery decisions provider-neutral and policy-respecting?
- Does this reduce human intervention without hiding uncertainty?

## Phase 6 Goal: Continuous Evaluation and Regression Control

Add repeatable evaluation reports and a release gate so visual changes cannot silently regress delivery correctness, duplicate suppression, or strategy safety.

### Phase 6 Milestone 1: Regression Report

**Files:**

- Create: `agent/visual/eval_report.py`
- Create: `scripts/visual_regression_report.py`
- Test: `tests/visual/test_eval_report.py`
- Test: `tests/scripts/test_visual_regression_report.py`

**Interfaces:**

- Produces:
  - `build_visual_regression_report(db_path: str | Path) -> dict[str, Any]`

**Acceptance:**

- Reports:
  - request count
  - artifact count
  - duplicate delivery count
  - missing source metadata count
  - unsafe activation count
  - strategy read count
  - prompt mutation read count
  - judgment count
- Fails closed when duplicate delivery, missing source metadata, unsafe activation, or prompt mutation reads are detected.
- Output is privacy-safe.

### Phase 6 Milestone 2: Release Gate CLI

**Files:**

- Modify: `scripts/visual_regression_report.py`
- Test: `tests/scripts/test_visual_regression_report.py`

**Acceptance:**

- `--json` prints a machine-readable report.
- Exit code is `0` only when `success` is true.
- Missing ledger is reported as success with zero counts for fixture-first workflows.

**Verification:**

```bash
rtk ./venv/bin/python -m pytest tests/visual/test_eval_report.py tests/scripts/test_visual_regression_report.py tests/scripts/test_visual_evidence_self_smoke.py tests/scripts/test_visual_strategy_activation_report.py -q
rtk ./venv/bin/python scripts/visual_evidence_self_smoke.py --json
rtk ./venv/bin/python scripts/visual_regression_report.py --json
rtk ./venv/bin/python -m ruff check agent/visual/eval_report.py scripts/visual_regression_report.py tests/visual/test_eval_report.py tests/scripts/test_visual_regression_report.py
rtk git diff --check
```

**Phase 6 Self-Review:**

- Does the report catch stale/duplicate/unsafe regressions?
- Is it privacy-safe?
- Can it run without live providers?
- Is it suitable as the pre-push visual release gate?

## Phase 4-6 Completion Criteria

- Phase 4 quality judge exists, is tested, and feeds candidate reward/ranking evidence.
- Phase 5 natural-language planner exists, is tested, and produces `visual_package_generate` arguments.
- Phase 6 regression report exists, is tested, and can be used as a release gate.
- Roadmap is updated so the next step no longer points at completed Phase 3 work.
- Full visual test slice passes.
- Self-smoke, Phase 2 self-check, shadow report, activation report, and regression report all pass.
- Work is committed in phase-sized commits and pushed to `origin/upgrade/hermes-v2026.6.19-local`.

## Execution Status: 2026-06-21

Not started at plan creation.

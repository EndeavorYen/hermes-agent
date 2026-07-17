# Story Video Script Review Board v6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every new story-video script pass a bounded, six-role editorial board and exact final-script verification while preserving existing v5 projects and reserving future NSFW profiles fail-closed.

**Architecture:** Add a focused `plugins/story_video/review_board.py` validator and call it from the existing planning gate only for v6 ledgers. Update the planning prompt to create the two new artifacts and route family writing, general writing, and the standalone runtime review-board skill explicitly. Keep all existing v5 validation paths unchanged.

**Tech Stack:** Python 3.11+, pytest, JSON planning artifacts, Markdown Hermes skills, SHA-256 from `hashlib`.

## Global Constraints

- New planning bundles use `quality_contract_version=6`; ledgers at version 5 or lower remain backward compatible.
- Required reviewer score is 85; unresolved critical findings are forbidden.
- Revision rounds are bounded to 1 or 2.
- `mature` and `adult_explicit` remain reserved and fail before media/provider dispatch.
- Current active ratings are `family` and `general` only.
- No new image candidates or media generation are part of this change.
- Use TDD: observe each focused test fail before adding production behavior.
- `$REPO_ROOT` is the topic worktree; `$HERMES_ROOT` is the machine-local Hermes state root.
- Local runtime skill edits stay under `$HERMES_ROOT/skills/creative`; private runtime artifacts are not committed.

---

### Task 1: Validate v6 Content And Review Artifacts

**Files:**
- Create: `plugins/story_video/review_board.py`
- Modify: `plugins/story_video/tools.py`
- Modify: `tests/plugins/story_video/test_tools.py`

**Interfaces:**
- Consumes: `project_dir: Path`, parsed v6 `ledger: dict`, parsed director report.
- Produces: `validate_v6_review_bundle(project_dir, ledger, director_report) -> tuple[str, ...]` with exact planning violations.

- [ ] **Step 1: Write failing v6 fixture and pass-path test**

Add a `_write_v6_review_fixture()` helper that upgrades the existing planning
fixture, writes `content_profile.json`, writes all six reviewer records, and
computes the final script SHA. Assert `_validate_planning(context).ok is True`.

- [ ] **Step 2: Verify RED**

Run:

```bash
$REPO_ROOT/.venv/bin/python -m pytest -q \
  tests/plugins/story_video/test_tools.py -k v6_review_board
```

Expected: FAIL because v6 review artifacts are not parsed or validated.

- [ ] **Step 3: Add the focused validator**

Implement constants and entrypoint:

```python
REVIEW_CONTRACT_VERSION = 6
REVIEW_SCORE_THRESHOLD = 85
REQUIRED_REVIEWER_IDS = (
    "language_editor",
    "fact_checker",
    "clarity_editor",
    "engagement_editor",
    "audience_safety_editor",
    "performance_editor",
)

def validate_v6_review_bundle(
    project_dir: Path,
    ledger: dict[str, Any],
    director_report: dict[str, Any],
) -> tuple[str, ...]:
    violations: list[str] = []
    profile = _load_json_object(project_dir / "content_profile.json")
    review = _load_json_object(project_dir / "script_review_report.json")
    if profile is None:
        violations.append("content_profile.json is missing or invalid")
    else:
        violations.extend(validate_content_profile(profile, ledger))
    if review is None:
        violations.append("script_review_report.json is missing or invalid")
    else:
        violations.extend(
            validate_script_review_report(
                review,
                ledger=ledger,
                director_report=director_report,
                script_bytes=(project_dir / "script.md").read_bytes(),
            )
        )
    return tuple(violations)
```

The implementation validates content-profile schema/routing, report schema,
exact reviewer set, PASS statuses, integer scores, finding shape, critical
resolution, adjudication, one-to-two rounds, factual source evidence, and exact
SHA-256 agreement across disk, board report, and director report.

- [ ] **Step 4: Wire v6 into planning without changing v5 requirements**

Parse the two new JSON files only when ledger quality version is at least 6,
append validator violations, and require the new universal quality checks.
For versions below 6, retain the existing required artifact and check sets.

- [ ] **Step 5: Verify GREEN**

Run the Task 1 test command. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/story_video/review_board.py plugins/story_video/tools.py \
  tests/plugins/story_video/test_tools.py
git commit -m "feat(story-video): validate v6 script review board"
```

### Task 2: Prove Every Fail-Closed Boundary

**Files:**
- Modify: `tests/plugins/story_video/test_tools.py`
- Modify: `plugins/story_video/review_board.py`

**Interfaces:**
- Consumes: valid fixture from Task 1.
- Produces: stable, specific violations suitable for autopilot repair or operator setup.

- [ ] **Step 1: Add parameterized failing tests**

Cover each defect independently:

```python
def test_v6_review_board_blocks_low_reviewer_score(tmp_path) -> None:
    _, context = _active_context(tmp_path)
    _write_v6_review_fixture(context)
    path = context.project_dir / "script_review_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["reviewers"][0]["score"] = 84
    path.write_text(json.dumps(report), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert "script_review_report reviewer language_editor score<85" in proof.violations
```

Repeat this exact fixture-mutation pattern for missing reviewer, duplicate
reviewer, unresolved critical finding, and final hash mismatch.

Add separate tests for missing fact-check source IDs and active or reserved
`adult_explicit` returning `SETUP_REQUIRED`.

- [ ] **Step 2: Verify RED**

Run the v6 subset and confirm every new test fails for its missing rule.

- [ ] **Step 3: Implement minimal exact violations**

Complete validation branches without adding retries or model calls. Reserved
profiles always produce one stable setup-required violation.

- [ ] **Step 4: Verify GREEN and v5 regression**

```bash
$REPO_ROOT/.venv/bin/python -m pytest -q \
  tests/plugins/story_video/test_tools.py
```

Expected: all tests pass, including existing v2-v5 fixtures.

- [ ] **Step 5: Commit**

```bash
git add plugins/story_video/review_board.py tests/plugins/story_video/test_tools.py
git commit -m "test(story-video): cover v6 review failure boundaries"
```

### Task 3: Route New Planning Through v6

**Files:**
- Modify: `plugins/story_video/hooks.py`
- Modify: `tests/plugins/story_video/test_hooks.py`

**Interfaces:**
- Consumes: story-video planning context and original request.
- Produces: planning instructions for v6 artifacts and content-aware skill routing.

- [ ] **Step 1: Update hook tests first**

Assert the planning context contains:

```python
assert "quality_contract_version=6" in context
assert "content_profile.json" in context
assert "script_review_report.json" in context
assert "story-video-script-review-board" in context
assert "at most two revision rounds" in context
assert "final_script_sha256" in context
assert "adult_explicit" in context
assert "SETUP_REQUIRED" in context
```

Also assert the prompt says the child writer is conditional on a family/child
profile, not unconditional for every project.

- [ ] **Step 2: Verify RED**

Run:

```bash
$REPO_ROOT/.venv/bin/python -m pytest -q \
  tests/plugins/story_video/test_hooks.py -k planning
```

Expected: FAIL on the new v6 contract assertions.

- [ ] **Step 3: Update planning instructions**

Make new runs create both new artifacts, default to active `family`, allow
active `general`, reserve other ratings, run the six-role board, revise at most
twice, and compute the final hash after revision. Preserve narration headings,
pronunciation lexicon, pacing, and all existing visual contracts.

- [ ] **Step 4: Verify GREEN**

Run the Task 3 test command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/story_video/hooks.py tests/plugins/story_video/test_hooks.py
git commit -m "feat(story-video): route planning through v6 review"
```

### Task 4: Create The Standalone Runtime Review Skill

**Files:**
- Create: `$HERMES_ROOT/skills/creative/story-video-script-review-board/SKILL.md`
- Create: `$HERMES_ROOT/skills/creative/story-video-script-review-board/references/review-contract.md`
- Create: `$HERMES_ROOT/skills/creative/story-video-script-review-board/templates/script_review_report.template.json`
- Create: `$HERMES_ROOT/skills/creative/story-video-script-review-board/evals/evals.json`
- Create: `$HERMES_ROOT/skills/creative/story-video-script-review-board/scripts/test_skill_contract.py`
- Modify: `$HERMES_ROOT/skills/creative/story-video-script-director/SKILL.md`
- Modify: `$HERMES_ROOT/skills/creative/story-video-script-director/references/script-quality-contract.md`
- Modify: `$HERMES_ROOT/skills/creative/story-video-script-director/scripts/test_skill_contract.py`
- Modify: `$HERMES_ROOT/skills/creative/story-video-production-pipeline/SKILL.md`
- Modify: `$HERMES_ROOT/skills/creative/story-video-production-pipeline/scripts/test_modular_story_quality_contracts.py`

**Interfaces:**
- Consumes: draft `script.md`, director planning artifacts, sources, content profile.
- Produces: revised script, v6 director report, and `script_review_report.json`.

- [ ] **Step 1: Write failing skill contract tests**

Require all six reviewer IDs, findings-only review, adjudication, bounded rounds,
hash binding, conditional child routing, active rating allowlist, and reserved
NSFW setup-required behavior. Run tests and observe missing-file/assertion RED.

- [ ] **Step 2: Create the minimal skill and resources**

Keep `SKILL.md` below 500 lines and place schema details in the reference and
template. The skill must explicitly forbid score averaging over a critical
finding and forbid editing the final script after hash generation.

- [ ] **Step 3: Update director and pipeline handoffs**

The director emits v6 reports and hands review to the board. The pipeline
requires v6 review proof before keyframes but retains v5 compatibility for old
projects.

- [ ] **Step 4: Verify skill GREEN**

Run the three local skill contract test files. Expected: all pass.

### Task 5: Integration, Review, And Runtime Proof

**Files:**
- Modify only files found defective by review.

**Interfaces:**
- Consumes: all worktree commits and local runtime skills.
- Produces: accepted `local/main`, exact deployed `runtime/current`, and live planning-only evidence.

- [ ] **Step 1: Run focused and wider tests**

```bash
$REPO_ROOT/.venv/bin/python -m pytest -q \
  tests/plugins/story_video/test_tools.py \
  tests/plugins/story_video/test_hooks.py \
  tests/plugins/story_video/test_story_contract.py \
  tests/plugins/story_video/test_engagement.py
```

Run all local skill contract tests, then `git diff --check` and privacy audit.

- [ ] **Step 2: Review requirement-by-requirement**

Confirm v6 pass, every fail-closed case, v5 compatibility, no child/NSFW policy
leakage, and no provider/media dispatch in planning-only mode.

- [ ] **Step 3: Publish through the governed local PR path**

Push the named topic branch, open a fork-local PR to `local/main`, verify CI,
merge, and fast-forward the local protected branch.

- [ ] **Step 4: Deploy exact SHA**

Fast-forward `runtime/current` to the exact accepted SHA, verify editable install,
restart the launchd-supervised gateway, and confirm the process truth surfaces.

- [ ] **Step 5: Run planning-only live smoke**

Start one fresh short family story-video request with explicit planning-only
language. Verify v6 artifacts, all six reviewer records, script hash equality,
planning PASS, and zero image/audio/video outputs or provider dispatches.

- [ ] **Step 6: Record final evidence**

Report test counts, accepted/deployed SHA, gateway status, live run ID/project
directory, reviewer scores, revision count, and media/provider dispatch count.

# Story Video Multi-Character Dubbing Help Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/story-video help` teach the implemented Phase 1 explicit character-to-voice mapping workflow and keep examples and operator documentation truthful.

**Architecture:** Keep the change inside the existing read-only guide surface. Update static guide copy in `plugins/story_video/guide.py`, prove slash-command routing remains non-mutating through the existing hook handler, and mirror the same public IDs and constraints in the operator guide; do not add actions, schemas, state, or synthesis behavior.

**Tech Stack:** Python, pytest, Ruff, Markdown, Git/GitHub fork-local integration.

## Global Constraints

- `/story-video help` remains the single primary help entry.
- The workflow is: run `/story-video voices`, provide story text or a story request, then explicitly map every character to a voice.
- Use this copy-ready example exactly: `多角色配音：旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。`
- State that Phase 1 requires an explicit voice for every character.
- Do not promise automatic casting, automatic role analysis, or audio synthesis.
- The legacy `simon` alias stays compatible internally, while all new help examples use `simon_clean_v2`.
- Do not deploy or move `runtime/current`.

---

### Task 1: Add truthful multi-character dubbing help

**Files:**
- Modify: `tests/plugins/story_video/test_guide.py`
- Modify: `plugins/story_video/guide.py`
- Modify: `docs/story-video-operator-guide.md`

**Interfaces:**
- Consumes: `format_story_video_guide(context, section, voices=None) -> str` and `hooks.handle_story_video_command(raw_args, event) -> str`.
- Produces: Updated read-only `help` and `examples` strings; no new callable interface or persisted state.

- [ ] **Step 1: Write failing behavior tests**

Extend `test_help_is_compact_and_copy_ready` with:

```python
assert "多角色配音" in text
assert "/story-video voices" in text
assert "多角色配音：旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。" in text
assert "每個角色都要明確指定聲線" in text
```

Extend `test_examples_cover_creation_and_dubbing_modes` with:

```python
assert "旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu" in text
assert "自動選擇可用聲線" not in text
```

Add a slash-command regression test that creates a bound run, snapshots its state file, calls `hooks.handle_story_video_command("help", event=event)`, and asserts both the new copy and unchanged state bytes:

```python
def test_slash_help_routes_to_updated_guide_without_mutating_state(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    event = _event("/story-video help")
    source_key = hooks._source_key(event)
    call = parse_operator_call("故事影片：恐龍起源｜5分｜電影感")
    assert call is not None
    context = store.create_or_load(
        source_key=source_key,
        session_id="session-1",
        call=call,
        original_request="故事影片：恐龍起源｜5分｜電影感",
    )
    monkeypatch.setattr(hooks, "_STORE", store)
    state_path = store.run_state_root / f"{context.run_id}.json"
    before = state_path.read_bytes()

    result = hooks.handle_story_video_command("help", event=event)

    assert "多角色配音" in result
    assert "simon_clean_v2" in result
    assert state_path.read_bytes() == before
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
rtk pytest -q \
  tests/plugins/story_video/test_guide.py::test_help_is_compact_and_copy_ready \
  tests/plugins/story_video/test_guide.py::test_examples_cover_creation_and_dubbing_modes \
  tests/plugins/story_video/test_guide.py::test_slash_help_routes_to_updated_guide_without_mutating_state
```

Expected: FAIL because the main help and examples do not yet contain the approved explicit mapping and the examples still promise automatic voice selection.

- [ ] **Step 3: Implement the minimal guide-copy change**

In `_format_help()`, add this compact section after `快速查詢`:

```python
"",
"多角色配音",
"1. 先用 `/story-video voices` 查看可用聲線。",
"2. 提供故事文本或故事需求。",
"3. 每個角色都要明確指定聲線（Phase 1 不會自動選角）。",
"`多角色配音：旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。`",
```

In `_format_examples()`, replace the automatic-casting creation example and normalize the other new examples to the public voice ID:

```python
"`創作模式：依這個主題寫成多角色故事。旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。`",
"`重製模式：保留附件故事的核心情節，改寫成 5 歲以上會好奇的繁中故事；旁白用 simon_clean_v2。`",
"`說書模式：旁白用 simon_clean_v2，完全照附件原文朗讀，不改字。`",
```

In `docs/story-video-operator-guide.md`, explain the same three-step workflow, explicit Phase 1 constraint, and copy-ready mapping. Remove the automatic-casting promise and use `simon_clean_v2` in all new examples.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same focused pytest command from Step 2.

Expected: `3 passed`.

- [ ] **Step 5: Run affected-file static checks**

Run:

```bash
rtk ruff check plugins/story_video/guide.py tests/plugins/story_video/test_guide.py
```

Expected: no Ruff errors.

- [ ] **Step 6: Self-review the implementation boundary**

Confirm from the diff that the work changes only tests, guide copy, and operator documentation. Answer: target drift is absent; there is no new action/schema/state; RED-to-GREEN evidence proves the operator-visible contract; the next smallest step is the complete story-video suite and integration review.

- [ ] **Step 7: Commit the help implementation**

```bash
rtk git add tests/plugins/story_video/test_guide.py plugins/story_video/guide.py docs/story-video-operator-guide.md
rtk git commit -m "docs(story-video): explain multi-character dubbing"
```

### Task 2: Verify and integrate the completed topic branch

**Files:**
- Verify only: all files changed from `local/main...HEAD`
- Integration target: protected branch `local/main` through a fork-local GitHub PR

**Interfaces:**
- Consumes: the complete topic branch and fork-local repository checks.
- Produces: an accepted PR on `origin/local/main` and a local `local/main` fast-forwarded to the accepted commit.

- [ ] **Step 1: Run complete story-video verification**

```bash
rtk pytest -q tests/plugins/story_video
rtk ruff check plugins/story_video tests/plugins/story_video
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 2: Review scope and privacy hygiene**

```bash
rtk git diff --check local/main...HEAD
rtk git diff --stat local/main...HEAD
rtk git status --short --branch
```

Inspect changed paths for generated media, caches, private prompts, provider logs, platform metadata, and runtime ledgers. Expected: only intended source, tests, docs, and sanitized configuration fixtures are present; the topic worktree is clean.

- [ ] **Step 3: Push the exact named topic branch**

```bash
rtk git push origin refs/heads/feat/story-video/voice-catalog-casting:refs/heads/feat/story-video/voice-catalog-casting
```

Expected: the same topic ref exists on `origin`; no upstream remote is mutated.

- [ ] **Step 4: Open and validate the fork-local PR**

Create a ready PR from `feat/story-video/voice-catalog-casting` to `local/main`. The PR body must summarize the normalized voice catalog, explicit cast binding, truthful help workflow, compatibility behavior, and exact test commands. Confirm the base and head refs before merge.

- [ ] **Step 5: Wait for required checks and merge through GitHub**

Use the repository's accepted merge method only after all required checks pass. Do not merge directly into the local protected branch and do not move `runtime/current`.

- [ ] **Step 6: Fast-forward the local protected checkout**

From `/Users/simon/.hermes/hermes-agent`:

```bash
rtk git switch local/main
rtk git fetch origin local/main
rtk git merge --ff-only origin/local/main
```

Expected: local `local/main` and `origin/local/main` resolve to the same accepted commit.

- [ ] **Step 7: Verify final integration state and clean accepted topic refs**

Confirm the PR is merged, the worktree is clean, local and remote protected SHAs match, and no runtime pointer moved. Only then remove the accepted topic worktree and obsolete topic refs according to `docs/hermes-branch-governance.md`; the merged work remains recoverable from `local/main` and the PR.

# Hermes Memory Phase 1 + Minimum Phase 3 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Generalize the current cron-only Layer-2 sidecar into a generic Hermes memory ledger and add the minimum viable runtime context-pack retrieval path without breaking prompt-cache stability or existing cron behavior.

**Architecture:** Preserve the existing frozen Layer-1 prompt snapshot model and existing cron Layer-2 MVP. Extend `cron/layer2_memory.py` into a more generic ledger with canonical internal destination names and richer provenance fields, then add a small `agent/layer2_recall.py` adapter that compiles a bounded context pack and injects it through the existing `<memory-context>` runtime seam in `run_agent.py`. Do not route this slice through the external provider abstraction yet.

**Tech Stack:** Python, SQLite, existing Hermes runtime and cron infrastructure, pytest.

---

## Scope of this slice

This slice includes only:
1. Phase 1 from the memory architecture spec:
   - generalize the current Layer-2 ledger schema and routing names
2. The minimum viable part of Phase 3:
   - minimal retrieval query/result abstraction
   - bounded context-pack compiler
   - runtime injection through the existing `memory-context` path

This slice explicitly does **not** include:
- graph/entity memory
- embedding retrieval
- provider abstraction rewrite
- builtin memory provider refactor
- automatic skill candidacy/promotion
- broad non-cron write producers
- Memory OS abstractions

---

## Grounded constraints from the current codebase

### Constraint 1: Prompt-cache stability is non-negotiable
`MEMORY.md` and `USER.md` are frozen per session/run. Mid-session writes hit disk but do not mutate the active system prompt.

### Constraint 2: Existing cron Layer-2 behavior must stay working
Current branch already has:
- `cron/layer2_memory.py`
- `cron/scheduler.py`
- `tests/cron/test_layer2_memory.py`
- `tests/cron/test_scheduler.py`
- `tests/tools/test_cronjob_tools.py`

This slice must preserve existing cron payload compatibility and audit behavior.

### Constraint 3: There is no builtin `MemoryProvider`
Even though `agent/memory_manager.py` / `agent/memory_provider.py` define the external provider abstraction, built-in `MEMORY.md` / `USER.md` handling still lives directly in `run_agent.py`. Do **not** force this slice through the provider abstraction.

### Constraint 4: External `memory` target must remain accepted
Existing cron payloads may still emit:
- `target: "memory"`

Internal normalization should map that to:
- `prior`

But the durable write boundary must still reverse-map:
- `prior -> memory`
when calling `MemoryStore`.

### Constraint 5: Worktree is already dirty
Relevant files already have local changes or are untracked. Implement carefully and stage narrowly.

---

## Target files for this slice

### Core code
- Modify: `cron/layer2_memory.py`
- Create: `agent/layer2_recall.py`
- Modify: `run_agent.py`

### Possibly touched only if needed
- Modify: `cron/scheduler.py`
- Modify: `cron/jobs.py`
- Modify: `tools/cronjob_tools.py`

### Tests
- Modify: `tests/cron/test_layer2_memory.py`
- Modify: `tests/cron/test_scheduler.py`
- Modify: `tests/tools/test_cronjob_tools.py`
- Modify or create in existing run-agent test area:
  - likely `tests/run_agent/test_run_agent.py`

---

## Task 1: Normalize Layer-2 destination names

**Objective:** Introduce canonical internal destination names while preserving external compatibility.

**Files:**
- Modify: `cron/layer2_memory.py`
- Test: `tests/cron/test_layer2_memory.py`

**Step 1: Write failing tests for destination normalization**

Add tests covering:
- external `memory` target is accepted
- stored internal destination becomes `prior`
- external `user` remains `user`
- durable write still reaches `MemoryStore` with `memory`, not `prior`

Suggested test names:
```python
def test_normalizes_memory_target_to_prior_in_ledger():
    ...

def test_promotion_to_prior_reverse_maps_to_memory_store_target():
    ...
```

**Step 2: Run targeted tests to verify failure**

Run:
```bash
pytest tests/cron/test_layer2_memory.py -q
```

Expected: FAIL on new normalization assertions.

**Step 3: Add normalization helpers in `cron/layer2_memory.py`**

Implement small pure helpers:
```python
def normalize_destination(raw: str | None) -> str | None:
    if raw == "memory":
        return "prior"
    return raw


def durable_store_target(destination: str | None) -> str | None:
    if destination == "prior":
        return "memory"
    return destination
```

Use them in:
- candidate event application
- promotion handling
- any read-path that exposes internal destination semantics

**Step 4: Run targeted tests to verify pass**

Run:
```bash
pytest tests/cron/test_layer2_memory.py -q
```

Expected: PASS for normalization tests.

**Step 5: Commit**

```bash
git add cron/layer2_memory.py tests/cron/test_layer2_memory.py
git commit -m "feat: normalize layer2 prior destination names"
```

---

## Task 2: Add idempotent schema migration for generic-ledger fields

**Objective:** Extend the existing SQLite schema with generic memory-ledger fields without breaking existing DBs.

**Files:**
- Modify: `cron/layer2_memory.py`
- Test: `tests/cron/test_layer2_memory.py`

**Step 1: Write failing tests for migration behavior**

Add tests covering:
- creating a fresh DB includes new nullable columns
- re-initializing an existing DB does not fail
- existing rows remain readable

Recommended columns:
- `candidates.routing_destination`
- `candidates.subject_scope`
- `candidates.subject_id`
- `candidate_events.job_id`
- `candidate_events.job_run_id`
- `candidate_events.session_id`
- `candidate_events.prompt_snapshot_id`
- `candidate_events.routing_reason_codes`

**Step 2: Run targeted tests to verify failure**

Run:
```bash
pytest tests/cron/test_layer2_memory.py -q
```

Expected: FAIL because schema/columns are missing.

**Step 3: Implement idempotent migration logic**

In `Layer2Store._init_db()`:
- keep current table creation
- add an idempotent `ALTER TABLE` migration helper
- do **not** rewrite historical rows in this task

Suggested helper shape:
```python
def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    ...
```

**Step 4: Run targeted tests to verify pass**

Run:
```bash
pytest tests/cron/test_layer2_memory.py -q
```

Expected: PASS for migration/idempotency tests.

**Step 5: Commit**

```bash
git add cron/layer2_memory.py tests/cron/test_layer2_memory.py
git commit -m "feat: extend layer2 sqlite schema for generic memory ledger"
```

---

## Task 3: Extend event recording with generic provenance and routing fields

**Objective:** Make Layer-2 events generic enough to serve beyond cron while keeping all existing callers compatible.

**Files:**
- Modify: `cron/layer2_memory.py`
- Possibly Modify: `cron/scheduler.py`
- Test: `tests/cron/test_layer2_memory.py`
- Test: `tests/cron/test_scheduler.py`

**Step 1: Write failing tests for richer event persistence**

Add tests covering:
- `record_event(...)` accepts optional generic metadata
- `apply_layer2_payload(...)` stores normalized `routing_destination`
- event rows persist `job_id`, `session_id` or `job_run_id` where available
- `routing_reason_codes` persists as JSON text when provided

**Step 2: Run targeted tests to verify failure**

Run:
```bash
pytest tests/cron/test_layer2_memory.py tests/cron/test_scheduler.py -q
```

Expected: FAIL on missing event metadata.

**Step 3: Extend `record_event(...)` conservatively**

Add only optional kwargs so old callsites still work:
```python
record_event(
    ...,
    routing_destination=None,
    subject_scope=None,
    subject_id=None,
    job_id=None,
    job_run_id=None,
    session_id=None,
    prompt_snapshot_id=None,
    routing_reason_codes=None,
)
```

In `apply_layer2_payload(...)`:
- normalize destinations
- derive/store `job_id` and `session_id`/`job_run_id` where easy
- keep current behavior if metadata is missing

Prefer parsing current `source_ref` first before widening scheduler plumbing.

**Step 4: Run targeted tests to verify pass**

Run:
```bash
pytest tests/cron/test_layer2_memory.py tests/cron/test_scheduler.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add cron/layer2_memory.py cron/scheduler.py tests/cron/test_layer2_memory.py tests/cron/test_scheduler.py
git commit -m "feat: persist generic provenance on layer2 events"
```

---

## Task 4: Add minimal retrieval query over active Layer-2 candidates

**Objective:** Create the smallest useful read-path from the generic ledger for runtime context-pack assembly.

**Files:**
- Modify: `cron/layer2_memory.py`
- Test: `tests/cron/test_layer2_memory.py`

**Step 1: Write failing tests for candidate retrieval ordering**

Add tests covering:
- only `active` candidates are returned
- results can be filtered by destination
- retrieval is ordered by:
  1. `support_count DESC`
  2. `updated_at DESC`
- optional suppression of weak entries (for example `support_count >= 2`)
- result count is bounded by `max_items`

Suggested function shape:
```python
def query_candidates_for_pack(...):
    ...
```

**Step 2: Run targeted tests to verify failure**

Run:
```bash
pytest tests/cron/test_layer2_memory.py -q
```

Expected: FAIL because query helper does not exist yet.

**Step 3: Implement minimal retrieval helper**

Keep it SQLite-first and simple:
- no FTS yet
- no embeddings
- no graph logic
- no provider abstraction

Suggested API:
```python
def query_candidates_for_pack(
    self,
    destinations: list[str] | None = None,
    max_items: int = 6,
    min_support_count: int = 2,
) -> list[dict]:
    ...
```

**Step 4: Run targeted tests to verify pass**

Run:
```bash
pytest tests/cron/test_layer2_memory.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add cron/layer2_memory.py tests/cron/test_layer2_memory.py
git commit -m "feat: add minimal layer2 retrieval query"
```

---

## Task 5: Create `agent/layer2_recall.py` for bounded context-pack assembly

**Objective:** Isolate runtime recall assembly from cron scheduler code.

**Files:**
- Create: `agent/layer2_recall.py`
- Test: likely `tests/run_agent/test_run_agent.py` or a new focused test file if a better home exists

**Step 1: Write failing tests for bounded pack assembly**

Add tests covering:
- pack builder returns empty when there are no hits
- pack builder formats compact lines with destination/kind/support
- pack respects `max_items`
- pack respects `char_budget`
- output is plain text suitable for `build_memory_context_block(...)`

Suggested output shape:
```text
- [user/preference] User prefers concise answers. (support=3)
- [prior/environment] GitHub HTTPS pushes may need gh auth setup-git. (support=2)
```

**Step 2: Run targeted tests to verify failure**

Run:
```bash
pytest tests/run_agent/test_run_agent.py -q
```

Expected: FAIL or missing-module failure.

**Step 3: Implement `agent/layer2_recall.py`**

Recommended minimal public function:
```python
def prefetch_layer2_context(
    *,
    max_items: int = 6,
    char_budget: int = 1500,
    min_support_count: int = 2,
) -> str | None:
    ...
```

This function should:
1. open `Layer2Store`
2. query active candidates
3. render bounded recall lines
4. return plain text or `None`

Do **not** add graph/entity logic.

**Step 4: Run targeted tests to verify pass**

Run:
```bash
pytest tests/run_agent/test_run_agent.py -q
```

Expected: PASS for pack assembly tests.

**Step 5: Commit**

```bash
git add agent/layer2_recall.py tests/run_agent/test_run_agent.py
git commit -m "feat: add bounded layer2 context pack assembly"
```

---

## Task 6: Wire Layer-2 context into `run_agent.py` using the existing memory-context seam

**Objective:** Inject Layer-2 recall ephemerally without altering the stable system prompt.

**Files:**
- Modify: `run_agent.py`
- Test: `tests/run_agent/test_run_agent.py`

**Step 1: Write failing integration tests for runtime injection**

Add tests covering:
- when Layer-2 has active candidates, a bounded pack is injected into the current user turn
- injection occurs via the existing memory-context path, not system prompt mutation
- no injection occurs when `skip_memory=True`
- system prompt hash/content remains stable across turns while context pack can differ

**Step 2: Run targeted tests to verify failure**

Run:
```bash
pytest tests/run_agent/test_run_agent.py -q
```

Expected: FAIL because Layer-2 prefetch is not wired yet.

**Step 3: Implement minimal integration in `run_agent.py`**

Add a Hermes-native prefetch branch alongside the current provider prefetch logic:
- call `prefetch_layer2_context(...)`
- if non-empty, wrap via existing `build_memory_context_block(...)`
- append to the current user message only

Do **not** route this through `MemoryManager` yet.

**Step 4: Run targeted tests to verify pass**

Run:
```bash
pytest tests/run_agent/test_run_agent.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add run_agent.py tests/run_agent/test_run_agent.py
git commit -m "feat: inject layer2 recall through existing memory-context seam"
```

---

## Task 7: Re-run focused regression suite for cron + runtime recall

**Objective:** Verify the slice did not break current cron behavior while adding runtime recall.

**Files:**
- No new files

**Step 1: Run focused tests**

Run:
```bash
pytest \
  tests/cron/test_layer2_memory.py \
  tests/cron/test_scheduler.py \
  tests/tools/test_cronjob_tools.py \
  tests/run_agent/test_run_agent.py \
  -q
```

Expected: PASS.

**Step 2: Spot-check compatibility assumptions**

Verify specifically:
- old cron payloads with `memory` still work
- stored ledger uses `prior`
- durable write still goes to `MemoryStore` target `memory`
- runtime context pack is bounded and ephemeral

**Step 3: Commit**

```bash
git add -A
git commit -m "test: verify phase1 phase3 layer2 recall slice"
```

---

## Compatibility risks to watch during implementation

### Risk 1: Mixed historical target names
Old rows may still contain `memory`; new rows should use `prior` internally.

Mitigation:
- normalize on write
- normalize on read if needed
- do not backfill historical rows in this slice

### Risk 2: Wrong durable-write target mapping
If `prior` accidentally reaches `MemoryStore.add(...)`, durable writes will fail.

Mitigation:
- centralize reverse mapping at the MemoryStore boundary
- test it explicitly

### Risk 3: Prompt bloat from over-retrieval
If the pack is too large or too noisy, runtime quality will drop.

Mitigation:
- low initial `max_items`
- low initial `char_budget`
- minimum support threshold

### Risk 4: Provider abstraction scope creep
Trying to make Layer-2 a full `MemoryProvider` in this slice will expand scope and likely stall.

Mitigation:
- use direct runtime seam in `run_agent.py`
- defer provider unification

### Risk 5: Dirty worktree overlap
This branch already has modifications in relevant files.

Mitigation:
- stage narrowly
- inspect diffs carefully
- keep commits small and sequential

---

## Acceptance bar for this slice

This slice is done when all of the following are true:
- existing cron Layer-2 tests still pass
- external cron payloads using `memory` still work
- internal ledger stores canonical `prior`
- Layer-2 retrieval returns bounded active candidates
- a small context pack can be injected into the live turn path
- system prompt/frozen snapshot behavior remains unchanged
- no graph, embeddings, provider rewrite, or skill promotion work slipped into scope

---

## Execution handoff

Plan complete and saved. Ready to execute using subagent-driven-development — dispatch one narrow implementation slice at a time, with spec-compliance review first and code-quality review second before moving on.

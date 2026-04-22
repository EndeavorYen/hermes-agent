# Hermes Memory Architecture Rollout Plan

This plan evolves the current cron Layer-2 MVP into the broader Hermes memory architecture without breaking working behavior.

---

## Starting point

Already implemented on this branch:
- cron Layer-2 SQLite sidecar
- candidate events and support/contradiction tracking
- guarded durable promotions
- Layer-2 audit section in cron outputs
- narrow durable memory path into `MEMORY.md` / `USER.md`

Already implemented elsewhere in Hermes:
- frozen prompt snapshots for durable priors
- `MemoryManager.prefetch()` for ephemeral memory context injection
- skills as procedural memory

This means the architecture should evolve by extension, not rewrite.

---

## Phase 0 — Freeze the architecture contracts

### Goal
Stop debating basic semantics and freeze the doc set as the source of truth.

### Deliverables
- this doc set lands in repo
- old cron-specific MVP spec remains as the current implementation slice
- internal terminology normalizes toward:
  - `prior`
  - `user`
  - `episodic`
  - `context_pack`
  - `skill`
  - `discard`

### Verification
- doc set reviewed and accepted
- new implementation work references this doc set

---

## Phase 1 — Lift Layer-2 from cron-specific to generic memory ledger

### Goal
Evolve the current SQLite sidecar from cron-only candidate memory into a generic Hermes memory ledger.

### Scope
Extend the current Layer-2 schema to support:
- subject scope / subject id
- session id / turn id
- job id / job run id
- prompt snapshot id
- canonical internal destination names
- routing reason codes

### Non-goals
- no graph layer yet
- no skill auto-promotion yet
- no provider rewrite yet

### Verification
- current cron tests still pass
- new generic Layer-2 objects can coexist with cron-produced objects
- old cron payload compatibility remains intact

---

## Phase 2 — Add episodic records and retrieval-oriented indexing

### Goal
Make Layer 2 capable of storing and retrieving scene-like episodic memory.

### Scope
Add support for:
- episodes
- observations
- entity or tag links
- lexical / metadata lookup
- recurrence-aware retrieval filters

### Design posture
Start SQLite-first and FTS-first.
Use embeddings only as optional augmentation later.

### Verification
- can retrieve recent relevant episodes for a given user/project/task
- retrieval returns bounded, source-linked items
- irrelevant recalls are suppressible

---

## Phase 3 — Implement runtime Context Pack assembly

### Goal
Make scene-triggered recall available at live turn time without touching the stable prompt prefix.

### Scope
Build:
- retrieval query builder
- retrieval result ranking
- bounded context-pack compiler
- runtime injection using the current ephemeral memory-context path

### Required constraints
- context packs are ephemeral
- bounded by token/char budget
- source-linked
- do not count as evidence by themselves

### Verification
- active session prompt hash remains stable while context packs change per turn
- retrieved packs are visible in logs/audit surfaces
- answer quality improves on recall-needed tasks without bloating every turn

---

## Phase 4 — Add broader write producers conservatively

### Goal
Allow non-cron Hermes contexts to emit Layer-2 observations and candidates.

### Candidate producers
- explicit runtime post-turn extractor
- session-end summarizer
- compression hook candidate writer
- review-oriented operator tools

### Constraints
- subagents remain memory-isolated by default
- producer authority must be explicit
- candidate-only remains default
- durable writes remain narrow

### Verification
- new producers create auditable Layer-2 entries
- no hidden durable writes appear
- provenance remains intact

---

## Phase 5 — Add context-pack registry and reusable digests

### Goal
Support reusable retrieval bundles that are not durable priors and not skills.

### Scope
Add `context_pack` as a durable retrieval-oriented destination for:
- repo digests
- workflow digests
- incident packs
- operator packs

### Why this phase matters
This is the clean answer to a lot of "memory but not belief" use cases.

### Verification
- runtime can request named or auto-selected packs
- packs are not injected by default into every session
- packs have provenance and refresh policy

---

## Phase 6 — Add lightweight temporal graph overlay only if needed

### Goal
Support higher-value associative recall where simple lexical/metadata retrieval is insufficient.

### Scope
Add optional:
- entities
- relations
- validity windows
- supersession links

### Entry condition
Do this only after:
- retrieval evaluation shows real misses
- contradiction and promotion policy are stable
- provenance discipline is strong

### Verification
- graph retrieval solves identified failure cases better than simpler retrieval
- graph does not become the hidden truth source

---

## Phase 7 — Add governed skill candidacy and promotion

### Goal
Let repeated successful procedures become candidate skills under review.

### Scope
Layer 2 may route some candidates to:
- `skill` candidate
- or `discard`

Skill installation remains:
- explicit
- reviewed
- procedural-only

### Verification
- skills extracted this way are truly reusable procedures
- contextual facts are not leaking into skills

---

## What stays stable throughout rollout

These are the architectural invariants that should not change during rollout:
- `MEMORY.md` and `USER.md` remain small
- Layer 1 prompt snapshots remain frozen per session/run
- skills remain procedural memory
- retrieval remains advisory
- durable promotion remains explicit and auditable

---

## Recommended first implementation slice after spec approval

If implementation starts immediately, the best next slice is:

> **Phase 1 + the minimum viable part of Phase 3**

Concretely:
1. generalize the existing Layer-2 schema and routing names
2. add a minimal retrieval query/result abstraction
3. compile a bounded ephemeral context pack from Layer 2 records
4. inject it through the existing memory-context runtime path

This produces the highest architectural leverage with the least framework risk.

---

## Success bar for rollout

The rollout is succeeding if:
- Layer 1 stays small
- Layer 2 becomes the main evidence and recall substrate
- runtime context packs become the main scene-triggered recall mechanism
- skills stay cleanly procedural
- no hidden durable write paths appear
- prompt-cache stability remains intact

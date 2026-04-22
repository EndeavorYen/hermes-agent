# Hermes Memory Runtime Architecture

## Goal

Define a formal memory architecture for Hermes Agent that:
- preserves prompt-cache stability
- keeps durable priors compact and high-confidence
- supports human-like associative recall without bloating the system prompt
- preserves skills as procedural memory only
- evolves naturally from the existing cron Layer-2 sidecar MVP

---

## Current grounded baseline

The current codebase already has the essential primitives for the architecture we want.

### 1. Durable priors already exist
`tools/memory_tool.py` defines two bounded stores:
- `MEMORY.md`
- `USER.md`

These are:
- persisted immediately to disk on write
- rendered into the system prompt as a frozen snapshot
- intentionally not hot-reloaded into the current session after mutation

This is the correct implementation for constitutional priors.

### 2. Runtime ephemeral recall already has an injection point
`agent/memory_manager.py` and `run_agent.py` already support provider `prefetch()` and call-time injection of a fenced `<memory-context>` block into the current user turn.

This is the correct insertion point for dynamic recall.

### 3. Skills are already a separate memory class
`tools/skill_manager_tool.py` treats skills as procedural memory.

This is correct and should be preserved.

### 4. Cron Layer-2 already exists
`cron/layer2_memory.py` plus scheduler integration already implement:
- candidate ledger
- support/contradict tracking
- guarded durable promotion
- audit logging

This is the correct first memory-governance slice.

---

## Problem to solve

The current architecture is good at:
- compact priors
- prompt-cache stability
- procedural memory
- cron candidate capture

But it still lacks a formal default answer to:
- where scene-triggered recall lives
- how associative recall is represented
- how recall differs from durable belief
- how evidence, candidate, recall, and skill relate to each other

Without that formal split, Hermes risks drifting into one of two bad designs:
1. stuffing more content into `MEMORY.md` / `USER.md`
2. overloading skills to serve as both procedural memory and contextual recall

Both are wrong.

---

## Canonical layer model

## Layer 0 — Working / session memory

### Purpose
The active context for the current task or session.

### Includes
- current conversation history
- tool results
- compression summaries
- session DB state
- open loops
- transient reasoning state
- active cron output for a run

### Properties
- volatile
- task-shaped
- not durable by default
- can reference durable memory, but is not itself durable memory

### Current implementation mapping
- session transcript storage
- `hermes_state.py`
- context compression
- tool result chain inside `run_agent.py`

---

## Layer 1 — Durable priors

### Purpose
Store the small, stable, always-relevant facts that should influence nearly every future interaction.

### Stores
- `MEMORY.md`
- `USER.md`

### Interpretation
This is the constitutional / priors layer.
It is closest to:
- stable beliefs
- long-lived user preferences
- environment facts
- project conventions
- durable operating doctrine

It is not the main recall engine.

### Allowed content
#### `USER.md`
- user communication preferences
- recurring expectations
- stable habits
- user-specific workflow preferences

#### `MEMORY.md`
- environment facts
- machine quirks
- repo conventions
- durable non-user operating facts
- broad durable doctrine

### Disallowed content
Do not store here:
- task progress
- recent incidents
- episodic history
- open loops
- evidence chains
- tentative findings
- long tactical playbooks
- procedures or workflows that should be skills
- scene-triggered recall bundles

### Runtime semantics
- injected into system prompt
- frozen at session start / cron run start
- mid-session writes hit disk but do not mutate the active prompt snapshot

### Why this layer must stay small
Because everything in this layer is paid for on every turn and affects prompt-cache stability.

---

## Layer 2 — Associative recall ledger

### Purpose
Provide the main long-term recall substrate for Hermes.

This is where human-like memory should mostly live:
- episodes
- associations
- recurrence
- contradiction
- contextual retrieval
- pre-promotion candidates

### What belongs here
#### A. Observation events
Atomic observations with provenance.

#### B. Episodes / scenes
Compact representations of what happened in a prior interaction, run, or task.

#### C. Candidates
Canonicalized claims under evaluation, with support and contradiction tracking.

#### D. Associations
Links between:
- entities
- projects
- users
- tags
- episodes
- candidates
- skills

#### E. Recall cache / precomputed packs
Optional retrieval-optimized summaries built for specific domains or contexts.

### Interpretation
Layer 2 is both:
- the evidence/governance substrate
- the recall substrate

It is not directly injected by default into every turn.

### Storage model
Use a local sidecar database, SQLite-first.

Recommended initial tables:
- `episodes`
- `observations`
- `candidates`
- `candidate_events`
- `entities`
- `edges`
- `recall_cache`
- `promotion_decisions`

### Retrieval model
Layer 2 should support multi-channel retrieval:
- lexical / FTS
- entity / tag overlap
- recurrence weight
- contradiction suppression
- scope filters
- optional embeddings later

### Injection model
Layer 2 should be injected ephemerally via runtime context pack assembly, not via prompt-prefix mutation.

---

## Layer 3 — Procedural memory

### Purpose
Reusable “how to do things” memory.

### Storage model
Skills.

### Allowed content
- workflows
- checklists
- procedures
- tactics
- tool usage patterns
- repo-specific implementation playbooks

### Disallowed content
- user preferences
- raw episodic recall
- transient incidents
- unsupported facts
- general context packs

### Interpretation
Skills are not general memory.
Skills are procedures.

---

## Layer 4 — Runtime context pack

### Purpose
Assemble a bounded, ephemeral retrieval bundle for one turn or one cron run.

### Inputs
- Layer 1 priors (by reference, not duplication)
- Layer 2 retrieval results
- relevant skills from Layer 3
- current session/task intent
- current scope metadata

### Output
A compact context pack injected outside the frozen system prompt.

### Properties
- ephemeral
- per-turn or per-run
- explainable
- source-linked
- suppressible
- bounded by token/char budget

### Why this layer exists
This is the answer to the user’s main critique.

Hermes needs a place for scene-triggered recall that is:
- not a durable prior
- not a skill
- not raw transcript history

That place is the runtime context pack.

---

## Canonical runtime flow

### Normal interactive turn
1. Load frozen Layer 1 priors from the session snapshot.
2. Determine whether contextual recall is warranted.
3. Query Layer 2 with a retrieval query bounded by scope and budget.
4. Optionally retrieve one or more relevant skills.
5. Assemble a Layer 4 context pack.
6. Inject that pack ephemerally into the current turn.
7. Produce the answer/tool calls.
8. Write any new observations/candidates back into Layer 2 via governed paths.
9. Promote to Layer 1 only via explicit policy.

### Cron run
1. Freeze the run-start Layer 1 snapshot.
2. Run the job with its current prompt and any allowed runtime context pack.
3. Parse/validate memory payloads if the job is memory-pipeline enabled.
4. Apply candidate events and promotions to Layer 2.
5. Write durable priors only if allowlisted.
6. Append audit output.
7. Do not mutate the current run’s frozen prompt snapshot.

---

## Architectural consequences

### 1. `MEMORY.md` / `USER.md` are not expanding layers
They are stable priors only.

### 2. Layer 2 becomes the center of memory gravity
The future of Hermes memory is primarily about:
- candidate routing
- evidence accumulation
- contradiction handling
- retrieval quality
- context-pack assembly

### 3. Skills stay procedural-only
They should not become a dumping ground for associative context.

### 4. Prompt-cache stability remains a hard invariant
Dynamic memory belongs in Layer 4.
Not in the stable prompt prefix.

---

## Non-goals of the architecture
This architecture does not require Hermes to become:
- a graph-first memory system
- a memory operating system
- a cloud memory product
- a giant RAG wrapper over all transcripts

The first objective is architectural clarity and governable recall, not maximal abstraction.

---

## Recommended first implementation slice
The best next slice is:

> **generalize the current cron Layer-2 sidecar into a broader associative recall ledger plus runtime context-pack assembly, while leaving `MEMORY.md`, `USER.md`, and skills in their current roles.**

This is the smallest change that meaningfully advances Hermes toward the desired memory architecture.

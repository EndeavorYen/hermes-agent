# Hermes Formal Memory Architecture Spec Memo

## Purpose

Define a memory architecture for Hermes Agent that preserves the existing strengths of the codebase:
- compact durable priors in `MEMORY.md` and `USER.md`
- prompt-cache stability via frozen prompt snapshots
- procedural knowledge in skills
- sidecar candidate-memory capture already proven in cron Layer-2 MVP
- optional external memory providers via `MemoryManager`

This memo is opinionated: **Hermes should use a layered memory stack, not a single general-purpose memory bucket.**

---

## Executive recommendation

Adopt a **4-layer memory architecture**:

1. **Layer 0 — Working/session memory**  
   Conversation history, session DB, context compression, tool results, transient task state.
2. **Layer 1 — Durable priors**  
   `MEMORY.md` and `USER.md`, kept small, declarative, and frozen per session for cache stability.
3. **Layer 2 — Associative recall / episodic sidecar**  
   A separate retrieval-oriented memory substrate for scene-triggered recall, evidence, candidates, episodes, and links. This is where “human-like recall” lives.
4. **Layer 3 — Procedural memory**  
   Skills only. Skills remain the place for reusable workflows and “how to” knowledge.

**Key design choice:**
`MEMORY.md` and `USER.md` should stay compact and durable. They are not the main recall engine. Associative recall must be separated into Layer 2 and injected ephemerally at API-call time, not baked into the cached system prompt.

---

## Current codebase grounding

### Already implemented and should be preserved

1. **Frozen durable priors**
   - `tools/memory_tool.py` states `MEMORY.md` and `USER.md` are injected as a **frozen snapshot at session start**.
   - Mid-session writes are durable on disk but do not mutate the current prompt snapshot, preserving prefix cache behavior.

2. **Compact-memory guidance already exists**
   - `agent/prompt_builder.py` explicitly says memory is injected into every turn and must stay compact.
   - It also distinguishes declarative memory from skills.

3. **Associative recall already has an injection slot**
   - `agent/memory_manager.py` supports provider `prefetch()` and wraps returned context with `build_memory_context_block()`.
   - `run_agent.py` injects prefetched memory into the **current user turn only**, at API-call time, preserving the stable cached system prompt.

4. **Layer-2 cron MVP already exists**
   - `cron/layer2_memory.py` implements an SQLite candidate/event ledger.
   - `cron/scheduler.py` parses fenced `hermes-layer2` payloads from opted-in jobs and applies them separately from durable memory.
   - Existing MVP correctly separates raw evidence, candidate ledger, and durable promotion.

5. **Skills are already treated as procedural memory**
   - `tools/skill_manager_tool.py` explicitly defines skills as procedural memory and contrasts them with broad declarative memory.

### Current architectural gap

Hermes has:
- good compact priors,
- good prompt-cache behavior,
- good skill separation,
- an MVP candidate ledger for cron,
- and a plugin abstraction for external memory providers.

What it lacks is a **formal default architecture for associative recall across all agent contexts**, not just cron pipelines.

---

## Design principles

### 1. Keep priors small and expensive
If content is injected into every turn, it must earn that cost. `MEMORY.md` and `USER.md` are scarce resources.

### 2. Recall should be cheap to ignore
Associative memory should be ephemeral, query-triggered, and fenced as background context. The model should be able to use it when relevant and ignore it when not.

### 3. Evidence before belief
A recalled item should ideally trace back to observations, episodes, or repeated support. Layer 2 should be an evidence-aware substrate, not a flat list of vibes.

### 4. Promotion should be narrow
Promotion into `MEMORY.md` or `USER.md` should be selective and conservative. Most memory should never become a durable prior.

### 5. Procedural knowledge is different
Workflows, step sequences, and reusable methods belong in skills, not in user/profile memory or associative recall blobs.

### 6. Cache stability is a hard constraint
Anything dynamic should be injected ephemerally at call time. Stable priors stay in the frozen prompt snapshot.

---

## Recommended formal layers

## Layer 0 — Working / session memory

### Responsibility
Handle the current task and immediate conversation context.

### Includes
- active conversation history
- context-compressed summaries
- session DB / transcript search
- tool outputs and trajectory state
- pending task state, open loops, temporary conclusions

### Storage model
Use the current session/transcript systems. No major architectural change required.

### Retrieval model
- direct history inclusion
- context compression summaries
- `session_search` for transcript recall

### Design note
This is **not durable memory**. It is the agent’s current train of thought and task context.

---

## Layer 1 — Durable priors (`MEMORY.md`, `USER.md`)

### Responsibility
Store the small set of stable facts that should influence nearly every future conversation.

### Split
- `USER.md`: user preferences, communication norms, recurring expectations, stable habits
- `MEMORY.md`: environment facts, project conventions, infrastructure quirks, durable non-user facts

### Allowed content
Only facts that are:
- durable across sessions
- broadly useful
- low-ambiguity
- worth injecting into every turn

### Disallowed content
Do not store:
- task progress
- recent outcomes
- one-off episode summaries
- open TODOs
- rich histories
- evidence chains
- procedural workflows
- “when X then do Y” playbooks

### Storage model
Keep existing file-backed markdown stores and current char caps.

### Retrieval model
No retrieval step. These are always part of the frozen session snapshot.

### Write policy
Promotion into Layer 1 should require one of:
- explicit user statement of stable preference or identity
- repeated evidence across independent episodes
- high-confidence operator or policy promotion

### Recommendation
Do **not** replace `MEMORY.md` / `USER.md`. Tighten their role. They are the agent’s compact priors, not its general memory warehouse.

---

## Layer 2 — Associative recall / episodic sidecar

### Responsibility
Serve as Hermes’s main long-term recall substrate.

This layer should answer:
- “What past scenes resemble this one?”
- “What prior observations are relevant here?”
- “What recurring candidate beliefs exist?”
- “What evidence supports or contradicts them?”

This is the human-like memory layer: episodic, associative, contextual, partially latent until triggered.

### What belongs here
1. **Episodes / scenes**
   - salient slices of prior conversations, jobs, reviews, or tool sessions
   - short structured summaries of “what happened”

2. **Observations**
   - atomic extracted facts with provenance
   - may be tentative or local to an episode

3. **Candidates / beliefs**
   - canonicalized statements with support and contradiction counts
   - includes proposed target (`user`, `memory`, `skill`, `none`)

4. **Associations**
   - links between episodes, candidates, entities, tags, files, projects, tools, and skills

5. **Recall packets**
   - pre-rendered compact snippets optimized for turn-time injection

### Strong recommendation on representation
Use a **hybrid SQLite-first local sidecar** rather than a pure vector database.

#### Core tables
Recommended entities:
- `episodes`
- `observations`
- `candidates`
- `candidate_events`
- `entities`
- `edges`
- `recall_cache`
- `promotion_decisions`

#### Why SQLite-first
- Hermes already uses SQLite patterns successfully
- local, inspectable, auditable, portable
- easy to version and migrate
- fits cron and on-device workflows
- preserves deterministic behavior better than outsourcing core memory semantics

#### Optional index augmentation
Add optional:
- FTS5 lexical index for exact/semantic-ish lookup
- embeddings table for vector recall when configured

The architecture should be **hybrid retrieval**, not vector-only.

### Recommended retrieval model
Use a 3-stage retrieval pipeline:

#### Stage A — Trigger detection
Before each turn, detect whether recall is warranted and what kind:
- user/profile recall
- project/environment recall
- episodic similarity recall
- contradiction/sanity recall
- skill-related recall

#### Stage B — Candidate retrieval
Retrieve from Layer 2 using multiple channels in parallel:
- lexical match over episodes/observations/candidates
- entity/tag overlap
- recency / recurrence priors
- optional embedding similarity
- session/project/user scope filters

#### Stage C — Recall shaping
Compress retrieved items into a small **recall packet** for injection:
- max 3–7 items
- each item includes short claim + provenance hint + confidence/status
- grouped by “likely relevant” rather than raw dump

### Injection model
Inject Layer-2 recall exactly the way current external provider prefetch works:
- ephemeral
- fenced with `<memory-context>`
- attached to the current user turn
- never written into the stable cached system prompt

This matches the current `build_memory_context_block()` pattern and should become the standard.

### Scope model
Each Layer-2 item should support scopes such as:
- `global_profile`
- `user_identity`
- `chat_or_session`
- `workspace_or_project`
- `job_family`
- `skill_domain`

Scope prevents false recall contamination.

### Status model
Candidates should support explicit status:
- `candidate`
- `supported`
- `contested`
- `promoted`
- `pruned`
- `archived`

### Promotion model
Layer 2 should be the source of promotion into:
- Layer 1 priors (`MEMORY.md`, `USER.md`)
- Layer 3 skills

But promotion must be policy-gated and relatively rare.

---

## Layer 3 — Procedural memory (skills)

### Responsibility
Store reusable procedures and workflows.

### Content types
- repeatable task recipes
- environment-specific workflows
- structured troubleshooting playbooks
- templates, scripts, references

### Non-goal
Skills are not user memories, not agent autobiography, and not general episodic recall.

### Promotion policy
Promote to a skill when knowledge is:
- procedural
- reusable across tasks
- tested or repeatedly successful
- too detailed or imperative for Layer 1

### Recommendation
Keep the current skill model. Formally define skills as the only first-class procedural memory layer.

---

## Formal data flow

## A. Turn-time inference flow

1. User message arrives
2. Layer 0 provides active conversation context
3. Layer 1 priors are already present from frozen prompt snapshot
4. Layer 2 recall engine runs prefetch on the clean user query
5. Retrieval returns a ranked recall packet
6. Recall packet is injected ephemerally into the current user turn
7. Model answers using:
   - stable priors from Layer 1
   - relevant episodic recall from Layer 2
   - current-session context from Layer 0
   - skills from Layer 3

## B. Post-turn memory write flow

1. Turn finishes
2. Observation extractor emits zero or more Layer-2 observations/candidates/events
3. Writes go to Layer 2 sidecar first, not directly to Layer 1
4. Promotion policy may later promote a subset to Layer 1 or Layer 3
5. Background prefetch cache may warm likely-next-turn recall

## C. Cron / offline analysis flow

1. Cron job runs with `skip_memory=True` for prompt safety
2. Job emits visible content plus optional structured Layer-2 payload
3. Scheduler parses payload into Layer-2 sidecar
4. Promotion remains guarded by target allowlists / later policy
5. Human or higher-level jobs inspect candidate quality before wider promotion

This generalizes the current cron MVP instead of replacing it.

---

## Recommended storage model in detail

## 1. Keep Layer 1 as markdown
Reason:
- human-editable
- profile-local
- simple and robust
- already integrated with prompt snapshots

## 2. Expand Layer 2 SQLite schema
The cron MVP schema should be evolved, not discarded.

### Minimum schema evolution

#### `episodes`
- `id`
- `scope`
- `source_type` (`conversation`, `cron`, `tool_run`, `review`, `delegation`)
- `source_ref`
- `summary`
- `salience`
- `created_at`
- `updated_at`

#### `observations`
- `id`
- `episode_id`
- `canonical_text`
- `kind`
- `entity_refs`
- `confidence`
- `source_ref`
- `created_at`

#### `candidates`
- current MVP fields plus:
- `scope`
- `confidence`
- `last_supported_at`
- `last_contradicted_at`
- `promotion_policy`

#### `candidate_events`
Keep current MVP structure and add optional richer provenance handles.

#### `edges`
- `src_type`, `src_id`
- `edge_type`
- `dst_type`, `dst_id`
- `weight`

#### `recall_cache`
- query signature / scene signature
- ranked packet text
- ttl / invalidation metadata

### Why add episodes and edges
The current MVP is candidate-centric. Human-like recall requires more than candidate counting:
- some things should be recalled as scenes, not beliefs
- some recall should be triggered by associated entities/projects/tools
- contradiction and ambiguity need provenance, not just counts

---

## Retrieval policy

## Default retrieval budget
For each turn, inject at most:
- 0–2 user-related recalls
- 0–2 environment/project recalls
- 0–3 episodic recalls
- 0–1 contradiction warning

Total target: roughly **300–900 chars**, not an essay.

## Ranking features
Rank by weighted combination of:
- scope match
- lexical similarity
- optional vector similarity
- recurrence/support
- recency
- salience
- contradiction penalty
- prior user correction relevance

## Recall output format
Recommended injected format:

```xml
<memory-context>
[System note: The following is recalled memory context, NOT new user input. Treat as informational background data.]

Relevant recall:
- [user-preference | strong] User prefers compact durable priors over verbose persistent notes. (seen repeatedly; promoted candidate)
- [project-context | medium] This repo preserves prompt-cache stability by freezing system-prompt snapshots per session. (`tools/memory_tool.py`, `run_agent.py`)
- [episode | medium] Prior design discussions favored associative recall as a separate layer from MEMORY/USER and procedural skills.
- [conflict-check | low] Do not treat cron-derived summaries alone as recurrence evidence.
</memory-context>
```

Short, typed, and provenance-aware beats long prose.

---

## Write / extraction policy

## Default extraction path
After a turn or offline job, extract into Layer 2 only:
- episodes when a meaningful scene occurred
- observations when a durable fact-like statement appeared
- candidates when an observation looks reusable beyond the episode

## Promotion path
Promotion should be asynchronous and policy-driven:

### Promote to Layer 1 when
- stable across time
- broad future utility
- low ambiguity
- compactly expressible
- safe to inject every turn

### Promote to Layer 3 when
- knowledge is procedural
- reusable workflow exists
- enough detail would bloat Layer 1

### Keep only in Layer 2 when
- useful only in certain contexts
- uncertain, contradictory, or episodic
- primarily provenance-bearing

---

## Implementation architecture recommendation

## Core recommendation
Make Layer 2 a **built-in local provider** under the `MemoryManager` abstraction, not just a cron-only subsystem and not only an optional external plugin.

### Proposed components
- `agent/recall_manager.py` or `agent/layer2_recall.py`
- `memory/layer2_store.py` or evolve `cron/layer2_memory.py` into a general module
- `memory/extractors/` for observation/candidate extraction
- `memory/retrievers/` for lexical/vector/hybrid retrieval
- `memory/promotion.py` for promotion rules

### Important refactor
Move `cron/layer2_memory.py` from cron-specific framing into a general-purpose memory package, then keep cron as one producer/consumer of that package.

Cron should become a client of Layer 2, not the owner of Layer 2.

---

## Recommended phased rollout

## Phase 0 — Formalize roles (now)
Produce spec docs and align naming.

Deliverables:
- declare 4-layer model
- redefine current cron Layer-2 MVP as first implementation slice of general Layer 2
- document strict content rules for Layer 1 vs Layer 2 vs Layer 3

## Phase 1 — Generalize Layer 2 substrate
Refactor current cron ledger into a reusable module.

Deliverables:
- shared SQLite Layer-2 package
- current cron payload path still works
- add generic APIs for episode/observation/candidate writes
- preserve existing candidate/event tables for migration compatibility

## Phase 2 — Turn-time associative recall
Add a built-in Layer-2 recall provider to `MemoryManager`.

Deliverables:
- prefetch from Layer 2 on normal user turns
- inject compact recall packets via `build_memory_context_block()`
- keep prompt cache intact by using API-call-time user-message injection only
- start lexical + scope-based retrieval before embeddings

## Phase 3 — General online extraction
Extract observations/candidates after normal conversations, not just cron jobs.

Deliverables:
- post-turn extractor
- minimal episode summaries
- candidate creation/strengthening/contradiction from conversational evidence
- no auto-promotion yet

## Phase 4 — Promotion engine
Add conservative promotion into Layer 1 and skills.

Deliverables:
- promotion scoring / policy
- operator review commands
- explicit “why promoted” provenance
- skill-promotion suggestions or draft generation, but only after review

## Phase 5 — Optional semantic augmentation
Add optional embeddings / graph-style link enrichment.

Deliverables:
- embeddings table or pluggable semantic index
- richer cross-entity recall
- hybrid lexical + semantic ranking

This should be optional, not foundational.

---

## Non-goals

Do not:
- replace compact priors with a giant memory database dump in the prompt
- collapse skills into the same memory substrate as user/environment facts
- make vector search the only retrieval path
- auto-promote large volumes of observations into `MEMORY.md` / `USER.md`
- inject dynamic memory into the system prompt mid-session
- let cron jobs directly rewrite user priors without policy gates

---

## Opinionated calls

### 1. `MEMORY.md` and `USER.md` should remain small forever
They are priors, not archives.

### 2. Layer 2 should become the default long-term recall engine
Not optional in concept, even if some retrieval features are configurable.

### 3. The cron MVP is the seed of the real architecture
Do not throw it away. Generalize it.

### 4. Retrieval should be hybrid and provenance-aware
Pure vector memory is too opaque. Pure flat notes are too weak. Hermes should use auditable hybrid retrieval.

### 5. Skills should remain separate
This separation is already correct in the codebase and should become formal policy.

---

## Proposed spec doc set

Recommended follow-up docs:

1. `docs/design/memory-architecture-overview.md`
   - canonical 4-layer model
   - terminology and responsibilities

2. `docs/design/layer1-durable-priors-spec.md`
   - rules for `MEMORY.md` and `USER.md`
   - promotion criteria and examples

3. `docs/design/layer2-associative-recall-spec.md`
   - schema, retrieval, extraction, ranking, scopes
   - evolution of current MVP

4. `docs/design/layer2-promotion-policy-spec.md`
   - when Layer 2 promotes into Layer 1 or Layer 3

5. `docs/design/procedural-memory-skills-spec.md`
   - formal definition of skills as procedural memory

6. Replace or supersede:
   - `docs/design/layer2-sidecar-memory-mvp.md`

---

## Bottom line

The best Hermes memory architecture is:
- **Layer 1:** compact durable priors (`MEMORY.md`, `USER.md`)
- **Layer 2:** associative episodic recall and candidate ledger, injected ephemerally
- **Layer 3:** procedural memory as skills
- **Layer 0:** session/transcript working memory

This preserves the current codebase’s strongest design win — frozen prompt-cache-friendly priors — while giving Hermes a real human-like recall layer that is contextual, evidence-aware, and implementation-feasible from the existing cron MVP.

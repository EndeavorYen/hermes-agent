# Hermes Memory Architecture Doc Set

Status: proposed formal architecture for the `feat/hermes-custom-autonomy` branch.

This doc set replaces the old mental model that treated durable memory as the main place where all learning should land.

## Why this exists

Hermes already has several good pieces:
- compact durable priors in `MEMORY.md` and `USER.md`
- frozen prompt snapshots for prompt-cache stability
- procedural memory in skills
- a working Layer-2 sidecar memory MVP for cron pipelines
- an existing runtime injection path for ephemeral memory context via `MemoryManager.prefetch()`

What Hermes lacks is a single formal architecture that says:
- what each memory layer is for
- what data belongs in each layer
- what can become durable belief
- what should remain associative recall only
- how recall should be injected without breaking the cached system prompt

This doc set defines that architecture.

## Reading order

1. `runtime-architecture.md`
   - the main architecture, layer model, runtime flow, and design decisions
2. `interfaces-and-schemas.md`
   - the canonical contracts for events, candidates, durable records, retrieval, and context packs
3. `guardrails-and-non-goals.md`
   - skeptical constraints, anti-fake-progress rules, and what not to build first
4. `rollout-plan.md`
   - phased plan from the current cron Layer-2 MVP to a broader Hermes memory system
5. `adr-001-priors-vs-recall.md`
   - why `MEMORY.md` / `USER.md` must stay small and frozen
6. `adr-002-skills-are-procedural-only.md`
   - why associative recall must not be collapsed into skills

## Relationship to existing docs

This doc set does not delete the current cron-specific MVP spec:
- `docs/design/layer2-sidecar-memory-mvp.md`

That existing doc remains the authoritative spec for the current cron implementation slice.
This new doc set is broader. It defines the future memory architecture that the current Layer-2 cron MVP should evolve into.

## Current grounded baseline

The architecture here is grounded in the current codebase:
- `tools/memory_tool.py`
- `run_agent.py`
- `agent/memory_manager.py`
- `agent/memory_provider.py`
- `agent/prompt_builder.py`
- `tools/skill_manager_tool.py`
- `cron/layer2_memory.py`
- `cron/scheduler.py`
- `cron/jobs.py`
- `tools/cronjob_tools.py`
- `tests/cron/test_layer2_memory.py`
- `tests/cron/test_scheduler.py`
- `tests/tools/test_cronjob_tools.py`

## Core architecture direction

Hermes should use a layered memory system:

- **Layer 0 — Working/session memory**
  - conversation-local context, tool outputs, transcripts, compression state
- **Layer 1 — Durable priors**
  - compact `MEMORY.md` and `USER.md`, frozen per session
- **Layer 2 — Associative recall ledger**
  - evidence, episodes, candidates, contradictions, retrieval-oriented records
- **Layer 3 — Procedural memory**
  - skills only
- **Layer 4 — Runtime context pack**
  - ephemeral per-turn retrieval bundle assembled from Layer 1/2/3 and injected outside the frozen system prompt

The most important architectural choice is:

> `MEMORY.md` and `USER.md` are not the general memory store.
> They are the constitutional priors layer.

## Implementation posture

This architecture should be built incrementally and upstream-friendly:
- preserve the current cache-stable prompt model
- preserve the current cron Layer-2 implementation as the first slice
- generalize the Layer-2 ledger rather than replacing it with an imported framework
- add associative recall before graph-heavy abstractions
- keep skills procedural only

## Bottom line

This doc set defines the memory architecture Hermes should implement next:
- small durable priors
- explicit evidence and candidate ledger
- associative/contextual recall as a separate layer
- procedural skills as a separate layer
- ephemeral runtime context packs instead of prompt-prefix bloat

# ADR-001: Durable Priors Must Stay Small and Frozen

## Status
Accepted for the proposed Hermes memory architecture.

## Context
Hermes already injects `MEMORY.md` and `USER.md` into the system prompt as frozen snapshots at session start.
Mid-session writes update disk but do not mutate the active prompt prefix.

The redesign question is whether these files should become the general long-term memory store.

## Decision
They should not.

`MEMORY.md` and `USER.md` are the constitutional priors layer only.
They must remain:
- compact
- durable
- high-confidence
- broadly reusable
- frozen per session/run

## Rationale
1. Everything in this layer is paid for on nearly every turn.
2. Growing this layer harms prompt-cache economics and signal quality.
3. Most human-like recall is scene-triggered, not always-on.
4. Associative recall belongs in a retrieval layer, not in the prompt prefix.

## Consequences
- episodic and contextual memory must live elsewhere
- durable promotions into this layer stay narrow
- the success metric is not how much reaches Layer 1
- runtime context packs become more important than expanding these files

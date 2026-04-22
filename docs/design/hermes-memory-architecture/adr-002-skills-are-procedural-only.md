# ADR-002: Skills Are Procedural Memory Only

## Status
Accepted for the proposed Hermes memory architecture.

## Context
Hermes already treats skills as procedural memory.
The redesign question is whether associative or scene-triggered recall should simply be modeled as skills.

## Decision
It should not.

Skills remain the home for reusable procedures only:
- workflows
- checklists
- tactics
- tool usage patterns
- repeatable implementation methods

Associative/contextual recall belongs in the recall ledger and runtime context-pack path.

## Rationale
1. Procedural memory and situational recall are not the same kind of object.
2. Mixing them would pollute skill retrieval and skill governance.
3. Skills should answer "how to do this repeatedly?"
4. Recall should answer "what matters in this scene right now?"

## Consequences
- skill promotion requires stronger validation than contextual recall
- runtime context-pack assembly becomes the main home for scene-triggered memory
- contextual facts should not be promoted into skills unless they become reusable procedures

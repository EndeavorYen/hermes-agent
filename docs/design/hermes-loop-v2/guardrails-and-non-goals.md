# Loop v2 Guardrails and Non-Goals

Primary references:
- `runtime-architecture.md`
- the skeptical design review that informed this doc (summarized here so the guardrails stay self-contained in committed docs)

This doc captures the skeptical constraints that keep loop v2 from turning into fake autonomy by narration.

## Core thesis

The main failure mode is not insufficient sophistication. It is **plausible-looking continuation without credible progress**.

Bad pattern:
- planner produces a convincing next prompt
- verifier approves transcript-level motion
- review logs say `meaningful_result`
- but no durable, externally checkable goal progress actually happened

Loop v2 must optimize for **credible continuation**, not impressive self-talk.

## Hard guardrails

### 1. Goal invariance
- Only user-originated input may create or replace the active loop goal.
- Assistant-generated subgoals are advisory only.
- Every planner/verifier judgment must be evaluated against the persisted goal contract, not the latest assistant summary.

### 2. One-step boundedness
A valid next step must be:
- concrete
- singular
- executable in one turn
- directly tied to the persisted goal

These are invalid as next steps:
- "continue"
- "keep going"
- "do the next best thing"
- multi-objective roadmap paragraphs

### 3. Evidence hierarchy
The verifier should rank evidence in this order:
1. **external evidence** — file changes, tool outputs, tests, API responses, persisted artifacts
2. **session delta** — a new concrete deliverable or resolved blocker visible in the transcript
3. **self-report only** — the assistant claims it progressed

Lower-tier evidence must not override the absence of higher-tier evidence.

### 4. Fail closed on uncertainty
If the loop cannot credibly establish progress, it should stop or pause.

Preferred failure mode:
- false-stop

Disallowed failure mode:
- fake progress

### 5. Review artifacts are logs, not proof
`background_reviews.jsonl` and future loop audit rows are derived judgments.
They are useful for observability, but they are not source-of-truth evidence that progress happened.

## Minimum viable architecture

Loop v2 should stay thin:
- durable loop state
- append-only event ledger
- compact checkpoint
- bounded planner/executor/verifier cycle
- deterministic stop evaluator
- explicit pause/resume/stop controls

That is enough to solve the real user problem:
- keep going by default when justified
- stop with explanation when not justified
- survive restart without losing control state

## Explicit non-goals for initial v2

Do **not** build these in the first implementation phase:
- multi-agent planner/critic/executor stacks
- workflow DAGs or event-bus orchestration frameworks
- long-horizon strategic plan memory
- verifier committees / scoring theater
- hidden background autonomy the user cannot inspect

## Trust-stop class

The runtime should reserve a stop/pause path for trust failures such as:
- no observable delta
- unverifiable implementation/completion claim
- invalid verifier payload
- persistence mismatch
- recovery ambiguity after restart

These are different from ordinary semantic completion and should be surfaced separately.

## Implementation consequence

If there is a tradeoff between:
- richer autonomy behavior
- stronger evidence and clearer stop semantics

choose the second.

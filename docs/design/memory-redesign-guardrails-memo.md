# Hermes Memory Redesign Guardrails Memo

Status: adversarial design memo for the current `feat/hermes-custom-autonomy` branch.

Grounding:
- Existing L2 sidecar spec: `docs/design/layer2-sidecar-memory-mvp.md`
- Existing implementation: `cron/layer2_memory.py`, `cron/scheduler.py`
- Built-in durable memory semantics: `tools/memory_tool.py`
- Existing provider/plugin abstraction: `agent/memory_provider.py`, `run_agent.py`
- Existing subagent isolation rule: `SECURITY.md`

## Executive stance

Do **not** start the Hermes memory redesign by building a graph memory, a "memory OS", or another imported memory framework. Hermes already has the beginnings of the correct separation:

- **L1** raw evidence
- **L2** candidate ledger with auditability
- **L3** durable curated memory (`MEMORY.md` / `USER.md`)

The immediate failure modes are not lack of abstraction. They are:

1. **retrieval theater** — retrieving impressive-looking context with weak evidence provenance,
2. **prompt-cache breakage** — changing the injected memory prefix too often,
3. **silent belief drift** — summaries and retrievals turning into beliefs without explicit promotion,
4. **uncontrolled durable writes** — cron/subagent/provider paths mutating durable memory without clear governance.

The current Layer-2 MVP is directionally right precisely because it is narrow, audit-first, and promotion-gated.

## What should NOT be built first

### 1) Do not build graph-first memory

Why this is a bad first move:
- Graphs create a strong illusion of structure before you have reliable facts.
- They encourage teams to model relations, entities, and edges **before** they have solved evidence quality, contradiction handling, and promotion policy.
- A graph layer makes belief drift harder to detect because inferred edges look just as real as observed facts unless provenance is brutally enforced.
- Graph retrieval is high-risk retrieval theater: the model sees a neat connected subgraph and over-trusts it.

Current code already tells you what matters more than graph shape:
- `cron/layer2_memory.py` records **candidate events** with `source_ref`, `source_event_id`, recurrence flags, and explicit support/contradiction deltas.
- The MVP spec explicitly distinguishes **raw evidence**, **candidate belief**, and **durable write**.

Conclusion: until event provenance, contradiction policy, and promotion review are solid, a graph is just prettier ambiguity.

### 2) Do not build a "memory OS" abstraction layer

Why this is a trap:
- Hermes already has a substantial abstraction surface in `agent/memory_provider.py` and plugin loading in `run_agent.py`.
- That abstraction already includes initialization, system-prompt injection, prefetch, background writes, tools, session-end hooks, compression hooks, and delegation hooks.
- Expanding this into a generalized "memory OS" now will mostly multiply extension points and hide where durable truth is actually formed.

Likely failure mode:
- every provider/framework gets mapped into a common interface,
- but their semantics do not actually match,
- so Hermes ends up with a lowest-common-denominator API and undefined truth model.

If the team cannot answer "what exact operation creates a durable belief, under what evidence rule, and who can do it?" then a memory OS is cargo-cult architecture.

### 3) Do not import an external memory framework as the redesign center

Why this is specifically dangerous in Hermes:
- Hermes already supports multiple memory providers/plugins; importing another framework as the core risks semantic conflict, not capability gain.
- External systems often mix retrieval, extraction, summarization, and durable writes in ways that are hard to audit locally.
- Provider-side extraction is especially risky for **silent belief drift** because the durable state may be synthesized outside Hermes' explicit L1/L2/L3 model.

The existing codebase already warns about this class of problem:
- `agent/memory_provider.py` says only **one external provider** runs at a time to avoid tool-schema bloat and conflicting backends.
- `SECURITY.md` isolates subagents with `skip_memory=True` so delegated work does not directly mutate persistent memory.

That is the correct instinct. Preserve it. Do not replace it with "let the framework manage memory for us."

### 4) Do not make retrieval itself look like memory

If a retrieval result is shown to the model as if it were a trusted belief, you have already lost.

Bad patterns to avoid:
- semantic recall injected without confidence/provenance labels,
- summaries of prior summaries used as recurrence evidence,
- auto-linked related memories presented as canonical truth,
- hidden reranking logic that changes what the model sees without audit.

The MVP spec already calls this out: **recurrence is evidence-based, not summary-based**.

### 5) Do not let cron jobs, providers, or subagents write durable memory by default

Current branch has the right shape:
- Layer-2 is **opt-in** per cron job,
- promotions are **target-allowlisted** per job,
- empty-visible-output runs do **not** mutate L2,
- duplicate `source_event_id` values do **not** count again,
- subagents run with `skip_memory=True`.

Any redesign that broadens write authority before sharpening governance is a regression.

## Minimum viable architecture

This is the smallest architecture that solves the real problems without pretending to solve all of memory.

### A. Keep the three layers explicit

#### L1: raw evidence (immutable or append-only references)
Store references to what was actually observed, not just the derived claim.

Minimum rule:
- Every candidate event must point to a concrete `source_ref` and preferably a stable `source_event_id`.

Do not require a giant evidence warehouse yet. Just preserve enough provenance to answer:
- what run/session/tool output produced this claim?
- is this a genuinely new observation or a restatement?

#### L2: candidate ledger (the center of gravity)
This is the real product, not the durable memory file and not a graph.

Required properties:
- append audit events,
- explicit candidate state,
- support/contradiction counts,
- duplicate suppression,
- promotion records,
- blocked/failed write records.

In practice, the current SQLite ledger is close to the right MVP center.

#### L3: durable curated memory
Keep durable memory boring.

For now it should remain:
- bounded,
- human-readable,
- explicitly written,
- snapshot-injected at session start,
- not mutated in-session in ways that alter the current prompt prefix.

This matches `tools/memory_tool.py`, which explicitly keeps a frozen system-prompt snapshot so mid-session writes do **not** change the injected prompt and break prompt caching.

## Hard guardrails

### 1) Guardrail: durable belief requires explicit promotion

Nothing becomes L3 because it was retrieved often, summarized well, or embedded near another fact.

A durable belief requires:
- an existing candidate in L2,
- explicit promotion action,
- an allowlisted target,
- durable-write audit event,
- failure logging when the write fails.

This is already the right shape in `apply_layer2_payload()`.

### 2) Guardrail: retrieval output is advisory, never self-authenticating

Any retrieved memory shown to the model must be treated as **context**, not as proof.

Rules:
- retrieval cannot increment recurrence counts,
- retrieval cannot create durable memory directly,
- retrieval-generated summaries cannot count as fresh evidence,
- inferred relations must stay outside L3 unless separately promoted from grounded evidence.

### 3) Guardrail: no mid-session mutation of the system prompt memory block

This is non-negotiable if you care about prompt-cache stability and conversational consistency.

`tools/memory_tool.py` already states the right rule:
- memory snapshots are frozen at session start,
- mid-session durable writes hit disk,
- the prompt snapshot refreshes only next session.

Therefore:
- do not build a design that hot-swaps memory into the active system prompt,
- do not let retrieval layers rewrite the prefix dynamically under the banner of "freshness",
- do not tie every durable write to immediate prompt reinjection.

### 4) Guardrail: every durable write path must be enumerated and gated

There should be a short list of write authorities, not a magical mesh.

Allowed write paths should be explicitly named:
- built-in memory tool,
- Layer-2 promotion path from approved cron jobs,
- any future operator-reviewed promotion command.

Everything else is read-only by default.

Specifically:
- subagents remain `skip_memory=True`,
- provider hooks cannot silently mirror arbitrary retrievals into durable memory,
- external providers cannot become hidden durable authorities.

### 5) Guardrail: contradiction is first-class, not an afterthought

A memory system that can strengthen but not cleanly contradict will only accumulate myths.

Minimum contradiction policy:
- contradictions must be evented in L2,
- contradiction counts must be visible beside support counts,
- contradiction does not silently delete prior candidate history,
- promotion policy must consider contradiction state.

Do **not** hide contradiction inside a confidence score.

### 6) Guardrail: empty or hidden outputs do not mutate memory

Current scheduler behavior is correct: if stripping the fenced payload leaves no human-visible response, Layer-2 is not applied.

Preserve this rule. It prevents hidden write-only cron behavior.

### 7) Guardrail: schema growth must lag policy clarity

Do not add ontology, entity typing, relations, edge taxonomies, or confidence algebra until the team can explain exactly how each affects promotion and retrieval behavior.

If policy is fuzzy, richer schema only hides the fuzziness.

## Governance rules

### Write governance
- Default posture: **candidate-only**, not durable write.
- Durable promotion must be **opt-in by job/tool/provider**.
- Promotion target must be allowlisted per source.
- Every promotion must emit both:
  - an L2 `promote` event,
  - a durable write audit entry.
- Failed promotions must be preserved as explicit failures, not dropped.

### Source governance
- Every candidate event must carry provenance.
- Stable dedupe key (`source_event_id`) is mandatory for any automated producer.
- Re-emission of the same event is a no-op for recurrence.
- Summaries of prior candidates must never count as new evidence without a new L1 source.

### Session governance
- Session-start memory snapshot is authoritative for prompt injection.
- Mid-session durable writes do not change active prompt memory.
- Retrieval injections should be visibly separated from durable curated memory.

### Scope governance
- User-specific beliefs go to `USER.md`; environment/project facts go to `MEMORY.md`.
- Jobs/providers should be constrained to the narrowest target set they truly need.
- Cron jobs should not get broad `memory` + `user` write power by default.

### Review governance
- Before broadening promotion rights, inspect actual L2 audits for several runs.
- Promotion policy changes should follow observed payload quality, not architecture enthusiasm.
- Keep operator review simple before making it fancy.

## Do now / defer / avoid

### DO NOW
1. **Make the Layer-2 spec the contract**
   - Freeze the payload schema for the MVP.
   - Add versioning only if needed for a breaking change.
   - Treat `cron/layer2_memory.py` as the reference implementation to formalize, not as a prototype to bypass.

2. **Harden provenance requirements**
   - Require `source_ref` on every automated candidate event.
   - Prefer stable `source_event_id` for any recurring producer.
   - Keep duplicate suppression mandatory.

3. **Keep durable promotion narrow**
   - Start candidate-only for most jobs.
   - Allow durable promotion only for the few jobs already recommended in the MVP spec, and only after audit inspection.
   - Prefer `user`-only promotion before broad `memory` writes.

4. **Separate retrieval context from durable memory in prompts/UI**
   - Label retrieval as retrieved context, not stored truth.
   - Keep L3 injected memory distinct from transient recall.

5. **Enumerate all durable write authorities in one doc**
   - Memory tool
   - Layer-2 cron promotions
   - future operator-reviewed promotion command
   - explicitly exclude subagents and passive provider sync paths unless approved

6. **Add belief-drift checks to reviews/tests**
   - Test that retrieval/prefetch cannot increment recurrence.
   - Test that summaries of prior memory do not count as new evidence.
   - Test that provider-side hooks cannot silently write L3 without promotion.

### DEFER
1. Graph storage, graph retrieval, entity linking, and relation inference
2. A generic memory OS / memory bus / unified cross-provider substrate
3. Importing a new external memory framework as the system of record
4. Auto-promotion thresholds and confidence-based durable writes
5. Rich operator UI before policy and audit semantics are stable
6. Skill synthesis or automatic skill generation from memory candidates
7. Heavy ontology/schema work beyond current `kind`, target, status, and provenance

### AVOID
1. **"Let retrieval become truth"**
2. **"Let summaries count as recurrence"**
3. **"Let providers write durable memory implicitly"**
4. **"Hot-reload memory into the active prompt"**
5. **"Use a graph to hide weak evidence quality"**
6. **"Adopt an external framework and inherit its truth model by accident"**
7. **"Broaden write access before audit tooling exists"**

## Bottom line

The redesign should be less ambitious and more disciplined:
- keep memory **ledger-first**, not graph-first,
- keep durable memory **curated and boring**,
- keep retrieval **advisory**,
- keep prompt memory **snapshot-stable**,
- keep write authority **explicit, narrow, and auditable**.

If Hermes gets those rules right, a graph or richer provider ecosystem can be added later without corrupting the truth model. If Hermes gets those rules wrong, no architecture will save it.
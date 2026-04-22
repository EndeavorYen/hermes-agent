# Hermes Memory Interfaces and Schemas

This document defines the canonical contracts for the Hermes memory architecture.

The goal is not to freeze implementation details too early. The goal is to freeze the architectural contracts that future implementation should obey.

---

## Naming conventions

### Canonical destination names
Use these canonical destinations internally:
- `prior`
- `user`
- `episodic`
- `context_pack`
- `skill`
- `discard`

### Backward compatibility
Existing cron Layer-2 MVP uses `memory` as a durable target name.
That should remain accepted externally for compatibility, but normalize internally as:
- `memory` -> `prior`

---

## Core invariants

```yaml
invariants:
  - durable priors are frozen per session or per cron run
  - runtime context packs are ephemeral and never part of the stable prompt prefix
  - every candidate or durable write must carry provenance
  - routing decisions are explicit, even when the destination is discard
  - retrieval does not itself count as evidence
  - summaries do not count as recurrence evidence without new grounded source events
  - skills are procedural objects, not generic recall objects
```

---

## Canonical objects

## 1. MemoryEvent
Normalized event unit for observations, candidate mutations, promotions, retrieval logging, and discards.

```json
{
  "schema_version": "memory-event/v1",
  "event_id": "evt_01H...",
  "idempotency_key": "sha256:...",
  "event_type": "observe|create_candidate|strengthen_candidate|contradict_candidate|prune_candidate|promote|write_durable|retrieve|pack|discard|expire|supersede",
  "actor": {
    "kind": "user|assistant|system|cron_job|tool|provider|reviewer",
    "id": "cron:daily-learning|tool:memory|assistant:primary"
  },
  "subject": {
    "scope": "user|agent|workspace|project|session|job",
    "subject_id": "user:slack:U123"
  },
  "object": {
    "canonical_text": "User prefers concise answers.",
    "kind": "preference",
    "destination": "user",
    "candidate_id": "cand_...",
    "record_id": null
  },
  "evidence": {
    "counts_for_recurrence": true,
    "source_event_id": "session:abc:msg12",
    "source_refs": ["session:abc#msg12"],
    "artifact_refs": [],
    "excerpt": "Please keep it brief."
  },
  "runtime": {
    "session_id": "sess_...",
    "turn_id": "turn_...",
    "job_id": null,
    "job_run_id": null,
    "prompt_snapshot_id": "psnap_...",
    "platform": "slack"
  },
  "routing": {
    "destination": "user",
    "decision": "accepted|deferred|discarded|blocked",
    "reason_codes": ["explicit_user_preference"]
  },
  "created_at": "2026-04-22T00:00:00Z"
}
```

---

## 2. MemoryCandidate
Layer-2 aggregate object.

```json
{
  "schema_version": "memory-candidate/v1",
  "candidate_id": "cand_01H...",
  "canonical_text": "User prefers concise answers.",
  "kind": "preference",
  "proposed_destination": "user",
  "status": "active|promoted|pruned|rejected|conflicted",
  "support_count": 3,
  "contradict_count": 0,
  "confidence": 0.8,
  "subject": {
    "scope": "user",
    "subject_id": "user:slack:U123"
  },
  "evidence_window": {
    "first_seen_at": "2026-04-01T00:00:00Z",
    "last_seen_at": "2026-04-22T00:00:00Z"
  },
  "promotion": {
    "eligible": true,
    "review_state": "none|pending|approved|rejected",
    "promoted_record_id": null
  },
  "created_at": "2026-04-01T00:00:00Z",
  "updated_at": "2026-04-22T00:00:00Z"
}
```

---

## 3. MemoryRecord
Canonical durable record across destinations.

```json
{
  "schema_version": "memory-record/v1",
  "record_id": "mem_01H...",
  "destination": "prior|user|episodic|context_pack|skill",
  "kind": "preference|identity|environment|workflow|project|fact|summary|procedure|other",
  "status": "active|superseded|contradicted|expired|archived",
  "canonical_text": "User prefers concise answers.",
  "rendered_text": "User prefers concise answers.",
  "subject": {
    "scope": "user|agent|workspace|project|session|job",
    "subject_id": "user:slack:U123"
  },
  "salience": 0.7,
  "confidence": 0.8,
  "stability": "volatile|session|recurring|stable",
  "visibility": "default|retrieval_only|hidden_system",
  "source_policy": {
    "requires_review": false,
    "promotion_rule": "manual|threshold|allowlisted_job|tool_write",
    "frozen_snapshot_eligible": true
  },
  "provenance": {
    "first_event_id": "evt_...",
    "last_event_id": "evt_...",
    "support_count": 3,
    "contradict_count": 0,
    "source_refs": ["session:abc#msg12"]
  },
  "supersedes": [],
  "tags": ["communication"],
  "ttl": null,
  "created_at": "2026-04-22T00:00:00Z",
  "updated_at": "2026-04-22T00:00:00Z"
}
```

---

## 4. PromptSnapshot
Reference object for frozen prompt state.

```json
{
  "schema_version": "prompt-snapshot/v1",
  "prompt_snapshot_id": "psnap_01H...",
  "scope": "session|cron_run",
  "session_id": "sess_...",
  "job_run_id": null,
  "assembled_at": "2026-04-22T00:00:00Z",
  "hash": "sha256:...",
  "components": {
    "identity_hash": "sha256:...",
    "tool_guidance_hash": "sha256:...",
    "prior_snapshot_hash": "sha256:...",
    "user_snapshot_hash": "sha256:...",
    "skills_index_hash": "sha256:...",
    "context_files_hash": "sha256:..."
  },
  "frozen_records": {
    "prior_record_ids": ["mem_1", "mem_2"],
    "user_record_ids": ["usr_1"]
  }
}
```

---

## 5. RetrievalQuery
The runtime request for memory recall.

```json
{
  "schema_version": "retrieval-query/v1",
  "query_id": "rq_01H...",
  "session_id": "sess_...",
  "turn_id": "turn_...",
  "text": "The user asks for a shorter answer.",
  "intent": "response|tool_use|planning|cron_review|session_recall",
  "destinations": ["user", "prior", "episodic", "skill"],
  "filters": {
    "subject_ids": ["user:slack:U123"],
    "kinds": ["preference", "workflow", "procedure"],
    "min_confidence": 0.55,
    "freshness_window_s": null
  },
  "budget": {
    "max_items": 8,
    "max_tokens": 1500,
    "max_per_destination": {
      "user": 3,
      "prior": 2,
      "episodic": 2,
      "skill": 1
    }
  },
  "prompt_snapshot_id": "psnap_..."
}
```

---

## 6. RetrievalResult
The set of retrieved records before packing.

```json
{
  "schema_version": "retrieval-result/v1",
  "query_id": "rq_01H...",
  "hits": [
    {
      "record_id": "mem_1",
      "destination": "user",
      "score": 0.93,
      "match_features": ["semantic", "tag:communication", "recent_use"],
      "rendered_text": "User prefers concise answers.",
      "provenance": {
        "last_event_id": "evt_...",
        "support_count": 3
      }
    }
  ],
  "timing_ms": 15
}
```

---

## 7. ContextPack
Ephemeral retrieval bundle for one live model call or one cron run.

```json
{
  "schema_version": "context-pack/v1",
  "context_pack_id": "cp_01H...",
  "session_id": "sess_...",
  "turn_id": "turn_...",
  "prompt_snapshot_id": "psnap_...",
  "query": {
    "text": "Current user requests concise reply.",
    "intent": "response",
    "max_items": 6,
    "token_budget": 1200
  },
  "items": [
    {
      "item_id": "mem_1",
      "destination": "user",
      "kind": "preference",
      "score": 0.93,
      "reason": "matches communication-style request",
      "rendered_text": "User prefers concise answers.",
      "source_ref": "mem:user:123"
    }
  ],
  "assembly": {
    "packing_strategy": "score_desc_then_diversity",
    "input_tokens_est": 180,
    "truncated": false
  },
  "injection_mode": "memory-context-fence",
  "created_at": "2026-04-22T00:00:00Z"
}
```

---

## 8. SkillRecord
Canonical procedural memory object.

```json
{
  "schema_version": "skill-record/v1",
  "record_id": "skill_01H...",
  "destination": "skill",
  "name": "repo-code-review-checklist",
  "summary": "Checklist for reviewing Hermes repo changes.",
  "procedure": {
    "steps": ["read diff", "run targeted tests", "check prompt-cache impacts"],
    "tools": ["read_file", "search_files", "terminal"]
  },
  "activation": {
    "triggers": ["code review", "Hermes repo"],
    "scope": "workspace|global"
  },
  "validation": {
    "source_candidate_id": "cand_...",
    "requires_human_install": true
  }
}
```

---

## Routing contract

### Destination routing rules

```yaml
routing_rules:
  to_user:
    when:
      - statement is about stable user preferences, identity, expectations, or recurring habits
    block_if:
      - content is transient task state
      - content is actually workspace or project fact

  to_prior:
    when:
      - statement is about environment, project, workspace, repo convention, or agent doctrine
    block_if:
      - content is user-specific
      - content is a one-off episode

  to_episodic:
    when:
      - content is useful later but time-bound or run-bound
      - content answers "what happened" more than "what is generally true"

  to_context_pack:
    when:
      - content is a reusable digest or retrieval bundle
      - intended for runtime recall rather than durable belief

  to_skill:
    when:
      - content is a reusable validated procedure with triggers and steps
    block_if:
      - content is just contextual fact or recent history

  to_discard:
    when:
      - duplicate
      - unsupported
      - low-signal
      - blocked by policy
      - missing provenance
      - hidden-output-only cron emission
```

### Default kind-to-destination map

```yaml
kind_to_destination:
  preference: user
  identity: user
  communication_style: user
  environment: prior
  project_convention: prior
  tool_quirk: prior
  episode_summary: episodic
  task_outcome: episodic
  digest: context_pack
  procedure: skill
  unknown: discard
```

---

## Cron integration contract

### Job config shape

```json
{
  "memory_pipeline": {
    "enabled": true,
    "schema_version": "cron-memory-pipeline/v1",
    "read_destinations": ["prior", "user", "episodic", "context_pack"],
    "candidate_destinations": ["prior", "user", "episodic", "skill", "discard"],
    "allow_durable_promotion_targets": ["prior", "user"],
    "allow_context_pack_writes": true,
    "allow_skill_candidates": false,
    "review_required_for": ["skill"],
    "snapshot_policy": "job_start_frozen",
    "visible_output_required": true
  }
}
```

### Cron run rules
- each run gets a unique `job_run_id`
- each run references a frozen `prompt_snapshot_id`
- writes during the run do not alter the run-start prompt snapshot
- all events and promotions must carry `job_id` and `job_run_id`
- candidate-only remains the default posture

### Fenced payload compatibility rule
Continue accepting:
- `memory`
- `user`

But normalize internally:
- `memory` -> `prior`
- `user` -> `user`

---

## Provider integration contract

The existing `MemoryProvider` abstraction should map conceptually to these phases:

```yaml
provider_phases:
  initialize(session_id, platform, agent_context, user_id, parent_session_id)
  system_prompt_block(prompt_snapshot_id) -> static provider metadata only
  prefetch(retrieval_query) -> retrieval_result
  sync_turn(turn_artifacts) -> observation events and optional candidates
  on_pre_compress(messages) -> candidate or context-pack suggestions
  on_session_end(messages) -> episodic/context-pack extraction
  on_delegation(task, result, child_session_id) -> episodic observation only
```

### Required guarantees
```yaml
provider_guarantees:
  - provider output must not impersonate user-authored content
  - provider writes must emit provenance-bearing events
  - provider retrieval is advisory, not self-authenticating
  - subagent memory isolation must remain respected
```

---

## Session snapshot rules

### Layer 1
- included in frozen prompt snapshot
- references stored via `prompt_snapshot_id`
- disk writes may happen mid-session
- active session prompt does not change unless explicitly rebuilt

### Layer 2
- never part of the frozen prompt by default
- only reachable via retrieval and context-pack assembly

### Layer 3 skills
- available procedurally
- not auto-injected as generic recall

### Layer 4 context packs
- ephemeral only
- injected outside the stable prompt prefix
- must be bounded and source-linked

---

## Minimal migration guidance

### Existing cron Layer-2 implementation
Current `candidates` + `candidate_events` tables are valid as the beginning of Layer 2.

Recommended future evolution:
- add `schema_version`
- add `subject_scope` / `subject_id`
- add `session_id` / `turn_id`
- add `job_id` / `job_run_id`
- add `prompt_snapshot_id`
- add `routing_destination`
- add `routing_reason_codes`

### Existing `memory` target
Continue to accept it externally for compatibility, but normalize it to `prior` in all new documentation and future internal contracts.

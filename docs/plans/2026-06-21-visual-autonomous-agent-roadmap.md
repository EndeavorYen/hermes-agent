# Visual Autonomous Agent Roadmap

**Goal:** Evolve the Hermes visual workflow from a shadow learning loop into a practical visual agent mode that can accept natural user requests and assets, generate images and videos, self-rank results, deliver only current selected outputs, and learn from evidence with minimal human intervention.

**Current Baseline:** Phase 1 and Phase 2 are complete on `upgrade/hermes-v2026.6.19-local`. Hermes has an evidence ledger, artifact store, deterministic checks, ranker, feedback parser, reward model, active-learning decisions, shadow learning records, privacy-safe reports, and live proof for `visual_package_generate` in shadow mode.

**Primary Constraint:** The system must stay evidence-led. User intent is the target, provider prompts are negotiable interfaces, provider output is evidence, and user feedback is the strongest signal. Autonomous learning must not mutate production behavior until gates prove enough quality, safety, and delivery reliability.

---

## Clean Start Boundary

The previous phase is closed when these are true:

- Repo worktree is clean and synced to `origin/upgrade/hermes-v2026.6.19-local`.
- Repo-local Python cache and temporary Phase 2 fixture directories are removed.
- Runtime evidence is preserved:
  - Visual Attempt Ledger stays under runtime-private Hermes state.
  - Generated media stays in runtime cache/artifact storage unless the user requests explicit media cleanup.
  - Raw prompts, local provider endpoints, private preference corpora, provider responses, and generated media are not committed.
- Phase 2 proof remains reproducible:
  - visual evidence report succeeds;
  - Phase 2 self-check succeeds;
  - shadow learning report shows no active mutations unless a later gated rollout explicitly enables them.

## Phase 3: Controlled Autonomy

**Objective:** Convert shadow observations into a controlled, reversible autonomy layer.

Phase 3 does not make Hermes "fully autonomous." It adds the missing promotion and rollback contract between shadow learning and production behavior.

### Deliverables

- Promotion gate that evaluates whether a shadow update can be promoted to controlled mode.
- Strategy version records with activation status, scope, confidence, evidence counts, and rollback metadata.
- Runtime report that explains why a strategy remains shadow-only, controlled, disabled, or rolled back.
- Package-tool integration that can read a controlled strategy but still defaults to shadow until gates pass.
- Self-validation that fails if active strategies exist without gate evidence.

### Promotion Rules

Promotion from shadow to controlled requires all of these:

- explicit local config flag or operator approval;
- minimum request count for the bucket;
- minimum successful artifact count;
- duplicate delivery count is zero for the evaluated scope;
- missing source metadata count is zero for the evaluated scope;
- provider reliability confidence meets threshold;
- self-validation passes;
- no recent negative feedback veto in the bucket;
- no unresolved policy/provider failure spike;
- strategy change is scoped to one intent bucket and one strategy signature.

### Self-Review Gate

After each Phase 3 milestone:

- prove under-sampled evidence stays shadow-only;
- prove a fully qualified fixture can be promoted;
- prove missing approval blocks activation;
- prove active strategies are visible in reports;
- prove rollback disables the strategy without deleting evidence.

## Phase 4: Visual Quality Judges

**Objective:** Add stronger self-supervised quality signals without requiring the user to review every batch.

Phase 4 introduces judge diversity. It should not rely on a single model or a single aesthetic heuristic.

### Deliverables

- Privacy-safe vision judge interface.
- Rubric dimensions:
  - reference adherence;
  - beauty or product appeal;
  - glamour/visual impact where allowed;
  - composition;
  - novelty against recent outputs;
  - motion quality for video;
  - aspect-ratio and stretch correctness;
  - delivery readiness.
- Judge disagreement and uncertainty model.
- Calibration script against existing Visual Arsenal and ledger feedback.
- Pre-Slack ranking report that explains why candidates were selected or suppressed.

### Guardrails

- Judge output is evidence, not ground truth.
- Aesthetic scores cannot hide provider delivery failures.
- Provider reliability cannot inflate aesthetic preference.
- Any private prompt or raw user text must stay out of committed fixtures and reports.

## Phase 5: Visual Agent Mode

**Objective:** Provide a user-friendly visual agent mode comparable to Grok Imagine agent mode, but integrated with Hermes evidence, delivery, feedback, and self-validation.

The user should be able to say natural requests such as:

```text
Make a product photo and short video from this image.
Generate a sexy cosplay photo set and animate the best one.
Use this reference and produce a clean image plus a short motion clip.
```

Hermes should infer whether the request needs image, video, or a package. Advanced knobs such as `autonomy_level`, `candidate_budget`, and `video_budget` remain available but are not required for normal usage.

### Deliverables

- Natural-language trigger classifier for visual package work.
- Asset ingestion that understands uploaded images, existing visual references, and current thread context.
- Lightweight visual brief planner:
  - user intent;
  - required outputs;
  - immutable constraints;
  - soft preferences;
  - provider strategy;
  - validation criteria.
- Multi-step orchestration:
  - generate candidates;
  - score and rank;
  - select images;
  - generate video from best image where requested;
  - package final outputs;
  - post selected current artifacts to Slack automatically.
- Failure negotiation:
  - classify provider errors;
  - rewrite to a safe feasible variant when allowed;
  - retry within budget;
  - ask user only when the system lacks confidence.

### UX Requirements

- The normal trigger is natural language, not parameter syntax.
- Slack delivery posts current selected media without requiring a second user message.
- No stale prior-round media is posted.
- Duplicate videos are suppressed even if provider returns different filenames for the same content.
- Image/video aspect settings follow the source media and requested output, not hard-coded defaults.

## Phase 6: Continuous Evaluation and Regression Control

**Objective:** Make the system measurably improve over time without overfitting to a few hand-picked prompts.

### Deliverables

- Fixture suite for common visual request classes:
  - product image plus video;
  - character/reference variation;
  - fashion/glamour editorial;
  - anime illustration;
  - provider refusal and timeout recovery;
  - duplicate/stale artifact prevention.
- Offline replay over ledger history with privacy-safe summaries.
- Quality trend dashboard or report:
  - success rate;
  - delivery correctness;
  - duplicate suppression;
  - provider health;
  - reward distribution;
  - ask-user rate;
  - retry effectiveness;
  - strategy promotion/rollback history.
- Release gate that runs before pushing visual workflow changes.

## Execution Policy

- Keep each milestone independently testable and commit-sized.
- Commit and push to `origin` after verified milestones.
- Do not push runtime-private docs or user prompt corpora.
- Start every behavior change with a failing test.
- Use fixture/self-check proof before live provider proof.
- Use live provider proof only when the behavior cannot be proven offline.
- Self-review after each milestone:
  - identify what was proven;
  - identify what remains shadow-only;
  - identify whether the change reduces human intervention;
  - identify rollback path.

## Immediate Next Step

Implement Phase 3 Milestone 1:

```text
Add a promotion gate that evaluates shadow updates and returns a promotion
decision without changing runtime behavior.
```

This is the correct next step because Phase 2 already records shadow updates, but there is no formal policy for deciding when a shadow update is eligible to influence production behavior.

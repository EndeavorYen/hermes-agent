# Image2 Adaptive Mediator

Hermes is the adaptive mediator between the user's visual intent and Image2's
feasible input surface. It is not just a prompt generator. The target is the
user's intent; the prompt is a negotiable interface; Image2 output and user
feedback are evidence.

## Runtime Role

The mediator does five jobs before Image2 sees a prompt:

1. Extract intent: subject, scene, style, mood, hard locks, soft preferences,
   avoid terms, risk level, and success definition.
2. Choose a strategy: `codex_direct`, `qwen36_desire_draft`, `hybrid_refine`,
   `safe_reframe`, `element_lock`, `post_failure_repair`, or exact-success
   reuse.
3. Ask Qwen only for a creative draft when that strategy benefits from it.
   Hermes remains the final compiler and validator.
4. Validate typed constraint locks before accepting a Qwen draft.
5. Record attempts, Qwen health, and user feedback as append-only evidence.

## Qwen Contract

Use the Windows Ollama model only as a specialized visual draft model.

```yaml
image_gen:
  adaptive_mediator:
    enabled: true
    log_attempts: true
    exploration_rate: 0.2
    qwen_json_contract: true
    memory_path: /Users/simon/.hermes/hermes_image2_adaptive_memory.jsonl
    memory_dir: /Users/simon/.hermes/image2_mediator_memory
  prompt_preprocessor:
    enabled: true
    base_url: http://192.168.50.178:11434/v1
    api_key: ollama
    model: qwen36-image-prompt
    reasoning_effort: none
    transport: curl
    temperature: 0.85
    max_tokens: 2048
    timeout_seconds: 45
```

Qwen should return JSON only. Hermes accepts either the canonical
`candidates[]` shape or a compact top-level `positive_prompt` candidate, then
rejects drafts that violate hard locks.

## Memory Files

When `memory_dir` is configured, the mediator writes split JSONL files:

- `attempts.jsonl`: Image2 attempts, strategy, final prompt, status, scores,
  and constraint validation evidence.
- `qwen_calls.jsonl`: Qwen call health, latency, transport, status, and short
  error metadata. It intentionally does not store request prompts.
- `user_feedback.jsonl`: explicit user feedback events. These are the strongest
  learning signal.
- `strategy_summaries.jsonl`: reserved for future offline summary snapshots.

The legacy `memory_path` is still read so older evidence is not dropped during
the split-memory migration.

## Learning Policy

The mediator uses rule-based learning summaries, not black-box training.

Sample policy thresholds:

- `0-9` attempts: `rules_only`
- `10-29` attempts: `weak_reference`
- `30-99` attempts: `moderate_reference`
- `100-299` attempts: `strong_reference`
- `300+` attempts: `bandit_candidate`

Compact Qwen memory hints are bucketed by similar intent. A hard-locked object,
clothing, identity, or scene only learns from records with overlapping locks.
This prevents one visual task from teaching unrelated tasks the wrong phrases.

User feedback is weighted above automatic success or failure scores. For
example, a technically successful Image2 attempt that the user marks as
`too_tame` is treated as user evidence that the bucket still needs stronger
editorial intensity.

## Operator Report

The `image2_mediator_memory` tool report includes:

- total records, attempts, feedback, statuses, strategies, and failure classes
- Qwen health over the last 24 hours
- `learning_summary.sample_policy`
- per-bucket strategy outcomes and user feedback failure counts
- recent public records without raw Qwen request bodies

Use this report before changing prompt rules. Small samples should be treated as
debug clues, not durable preference rules.

## Verification Gate

Before claiming this mediator is ready after a code change, run:

```bash
rtk ./venv/bin/python -m pytest tests/tools/test_image2_adaptive_mediator.py -q
rtk ./venv/bin/python -m pytest tests/tools/test_image_generation.py tests/tools/test_image_generation_plugin_dispatch.py tests/tools/test_image_mission_tool.py tests/tools/test_image2_adaptive_mediator.py -q
rtk ./venv/bin/ruff check tools/image2_adaptive_mediator.py tools/image_generation_tool.py tests/tools/test_image2_adaptive_mediator.py
rtk git diff --check
```

For live runtime validation, restart the gateway after config or plugin changes,
then confirm the gateway is running and the mediator report is readable. If LAN
Qwen access fails inside a Codex tool session, rerun the network smoke outside
the sandbox before changing Hermes logic.

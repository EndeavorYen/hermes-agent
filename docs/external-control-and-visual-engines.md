# External Control And Visual Engines

Hermes is the host process, not the owner of control policy or visual production
policy.

## Ownership Boundary

- Raphael Control Engine owns turn preparation, proof requirements, evidence,
  finalization, and self-review policy.
- Visual Production Engine owns image providers, references, candidate aliases,
  quality evaluation, repair, selection, persistence, and delivery evidence.
- Hermes exposes generic plugin hooks, transports opaque `turn_control`
  envelopes, dispatches `visual_engine_generate`, and uploads the selected local
  artifact.

Hermes must not import `agent.raphael` or
`agent.visual.production_kernel`. The architecture test in
`tests/architecture/test_external_engine_boundaries.py` enforces this rule.

## Adapter Contracts

The Raphael adapter uses:

- `pre_llm_call` to return an opaque `turn_control` envelope and optional
  context.
- `post_tool_call` to forward sanitized evidence.
- `transform_llm_output` to return `response_text`, `turn_control_status`, and
  `completed`.
- `post_llm_call` to record the outcome.

The Visual Engine adapter registers `visual_engine_generate`. A successful
response includes the current run, selected artifact, session aliases, native
delivery path, and explicit evidence for provider execution, artifact quality,
selection freshness, reference mapping, and delivery.

## Deployment Order

Deploy the external engines before deploying the Hermes adapter cutover.

1. Install each accepted external-engine commit.
2. Require real HTTP readiness, not only a running process identifier.
3. Install the thin Hermes adapters.
4. Deploy the accepted Hermes commit to `runtime/current`.
5. Verify provider status, a no-cost routed image request fixture, structured
   turn finalization, and gateway startup.

## Rollback

Restore the previous `runtime/current` and adapter snapshots. Engine
databases and generated artifacts are preserved.

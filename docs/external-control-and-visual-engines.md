# External Control And Visual Engines

Hermes is the host process, not the owner of control policy or visual production
policy.

## Ownership Boundary

- Raphael Control Engine owns turn preparation, proof requirements, evidence,
  finalization, and self-review policy.
- Visual Production Engine owns image providers, references, candidate aliases,
  quality evaluation, repair, selection, persistence, and delivery evidence.
- Toonflow owns project, run, artifact-selection, and media-orchestration state.
  Hermes supervises it only through the loopback Control Contract 1.0.
- Hermes exposes generic plugin hooks, transports opaque `turn_control`
  envelopes, dispatches `visual_engine_generate`, and uploads the selected local
  artifact.

Hermes must not import `agent.raphael` or
`agent.visual.production_kernel`. The architecture test in
`tests/architecture/test_external_engine_boundaries.py` enforces this rule.
Hermes also must not import Toonflow or subscription-media-bridge code. The
`plugins/toonflow_control` adapter may construct only `/control/v1` paths and
uses a dedicated control token.

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

The Toonflow adapter registers six supervisory tools: capabilities, project
creation, run creation, run status, cancellation, and artifact selection.
Capabilities are negotiated before optional routes or mutations. Hermes sees
Toonflow run IDs and public artifacts, never media-service job IDs or
generation credentials.

## Deployment Order

Deploy the external engines before deploying the Hermes adapter cutover.

1. Start an accepted subscription-media-bridge release or its fake driver.
2. Start the accepted Toonflow Control API and verify its health.
3. Install the thin Hermes adapters.
4. Run `scripts/smoke_toonflow_control.py --fake-server --no-spend`.
5. Deploy the accepted Hermes commit to `runtime/current`.
6. Verify provider status, a no-cost routed image request fixture, structured
   turn finalization, and gateway startup.

## Rollback

Disable or remove the Toonflow plugin, then restore the previous
`runtime/current` and adapter snapshots. Toonflow and media-service databases,
run state, and generated artifacts are preserved.

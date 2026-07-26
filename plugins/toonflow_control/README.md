# Toonflow Control

This bundled plugin lets Hermes supervise Toonflow through the external Control
Contract 1.0. It is intentionally a thin client: Hermes owns neither Toonflow
workflow state nor media generation state.

## Configuration

Set these environment variables for the Hermes process:

```text
TOONFLOW_CONTROL_URL=http://127.0.0.1:10588
TOONFLOW_CONTROL_TOKEN=<dedicated-control-token>
```

Version 1 accepts loopback URLs only. The control token is separate from
Toonflow's UI JWT and from the media service token. The configuration check
validates URL shape and token presence without making a network request, so
Toonflow being stopped does not block Hermes startup; its tools simply remain
unavailable.

Start services in this order:

1. Start the media service and confirm its health.
2. Start Toonflow with its Control API enabled.
3. Start Hermes with the variables above.
4. Call `toonflow_capabilities` before requesting a workflow route.

Hermes does not provide media OAuth, browser sessions, or generation
credentials. It does not ask Codex or Grok to build Toonflow media. Toonflow
chooses a logical route and delegates generation behind its own external
boundary.

Failures are returned as a stable class, retryable flag, user action, and
message. `setup_required` means local configuration is missing;
`capability_unavailable` means the requested logical route is not advertised;
`provider_unavailable` means the local Control API could not be reached.

# Deep Fix Ledger: Toonflow Control Plugin

Scope: add a low-coupling Hermes plugin that supervises Toonflow exclusively
through the versioned `/control/v1` contract. Do not modify Hermes core, import
Toonflow or subscription-media-bridge code, expose provider credentials, or
perform paid generation.

## Ordered repair set

1. `fixed` — Control client
   - Outcome: a stdlib-only loopback client sends authenticated, versioned
     `/control/v1` requests and normalizes failures without leaking secrets.
   - Current evidence: `plugins/toonflow_control/` and its focused tests do not
     exist.
   - Focused proof:
     `PYTHONPATH=. venv/bin/python -m pytest tests/plugins/toonflow_control/test_client.py -q`
   - Evidence: 13 tests passed using the checkout virtualenv; the worktree has
     no private virtualenv. The four HTTP fixture tests required loopback socket
     permission from the managed sandbox.

2. `fixed` — Supervisory tools
   - Outcome: six strict tools expose only logical workflow controls and
     capability-gate optional routes.
   - Current evidence: no Toonflow tool schemas or handlers exist.
   - Focused proof:
     `PYTHONPATH=. venv/bin/python -m pytest tests/plugins/toonflow_control/test_tools.py -q`
   - Evidence: 9 tests passed. Schemas use the accepted Control 1.0 integer
     project/shot identifiers and omit non-functional candidate/repair knobs
     that the accepted Toonflow endpoint rejects. All optional route choices
     and mutations negotiate capabilities first, and responses are allowlisted
     so internal job fields cannot escape.

3. `fixed` — Plugin registration
   - Outcome: Hermes discovers and registers the six tools under the
     `toonflow` toolset; configuration checks are local and do not contact a
     provider or block startup.
   - Current evidence: no Toonflow plugin manifest, registration module, or
     discovery tests exist.
   - Focused proof:
     `PYTHONPATH=. venv/bin/python -m pytest tests/plugins/toonflow_control/test_plugin.py -q`
   - Evidence: 7 tests passed. Hermes discovers the bundled backend under the
     manifest key `toonflow-control`; all six runtime handlers serialize to
     registry-compatible JSON strings, while the availability gate remains a
     network-free boolean check.

4. `pending` — External-boundary and no-spend proof
   - Outcome: source and smoke tests prove Hermes calls only `/control/v1`,
     never `/media/v1` or provider endpoints, and a fake-control-server run
     performs no paid generation.
   - Current evidence: no architecture enforcement test, no-spend smoke, or
     deployment guide exists.
   - Focused proof:
     `PYTHONPATH=. venv/bin/python -m pytest tests/architecture/test_toonflow_control_boundary.py tests/integration/test_toonflow_control_no_spend.py -q`

Final required proof:

`PYTHONPATH=. venv/bin/python -m pytest tests/plugins/toonflow_control tests/architecture/test_toonflow_control_boundary.py tests/integration/test_toonflow_control_no_spend.py -q`

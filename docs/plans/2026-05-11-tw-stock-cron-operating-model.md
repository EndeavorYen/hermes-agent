# TW Stock Cron Operating Model

Date: 2026-05-11

Goal: keep the Taiwan stock system useful without paying agent cost for fixed
operator work. Every scheduled job should have one owner lane, one measurable
output, and a clear reason to wake the user or spend an agent run.

## Lanes

| Lane | Job type | Agent policy | Primary value |
| --- | --- | --- | --- |
| Market judgment | preopen, midday, postclose committee, shadow open/close review, alpha hunt | Agent | Reason over fresh market context and produce accountable decisions or structured review blocks. |
| State operators | state-sync, runtime pipeline, survival, invalid remediation, spawn variant | No-agent script | Apply deterministic helpers, gate freshness, write artifacts, and alert only on applied/blocked/failed states. |
| Prediction ledger | capture plus deterministic sync/accounting | Mixed | Capture requires structured judgment; sync/accounting is no-agent and wake-gated. |
| Governance | weekly accountability and monthly scoreboard | Agent | Review whether the process is improving real decision quality, not just memo quality. |
| Audits | convergence/chain audits | Reduced frequency or paused when covered by wrappers | Avoid duplicate checking when the state operator already gates the same invariant. |

## Current Cleanup Decisions

| Job | Decision | Reason |
| --- | --- | --- |
| `taiwan-runtime-pipeline-local` | Convert to no-agent wrapper | Runs a fixed artifact pipeline every 10 minutes; normal all-clear ticks should be silent. |
| `taiwan-runtime-action-status-summary` | Convert to no-agent wrapper | Exception-only status card; no market reasoning needed. |
| `taiwan-shadow-open-state-sync` | Convert to no-agent wrapper | Deterministic dry-run/apply/scoreboard flow. |
| `taiwan-shadow-close-state-sync` | Convert to no-agent wrapper | Deterministic dry-run/apply/scoreboard flow. |
| `taiwan-postclose-state-sync` | Convert to no-agent wrapper | Deterministic internal pack apply flow. |
| `taiwan-shadow-survival-pipeline-local` | Convert to no-agent wrapper | Freshness gate plus derived artifacts; no market reasoning. |
| `taiwan-shadow-invalid-remediation-local` | Convert to no-agent wrapper | Deterministic remediation; silent when no updates. |
| `taiwan-shadow-spawn-variant-local` | Convert to no-agent wrapper | Deterministic spawn/repair; silent when fresh no-op. |
| `taiwan-watch-upstream-shadow` | Convert to no-agent wrapper | Runs the existing Watch orchestrator and summary extractor; Hermes agent adds little value. |
| `taiwan-shadow-open-convergence-audit` | Pause | The open state-sync wrapper now reports applied/blocked and checks scoreboard output. |
| `taiwan-shadow-close-convergence-audit` | Pause | The close state-sync and survival wrappers now gate same-day scoreboard freshness. |
| `taiwan-alpha-high-risk-chain-audit` | Reduce to Mon/Wed/Fri | Useful quality audit, but daily cadence overlaps alpha hunt and preopen committee. |
| `taiwan-alpha-high-risk-chain-status-summary` | Keep disabled | Existing disabled status summary remains redundant. |

## Operating Rules

1. Agent jobs must create judgment, not merely run commands.
2. No-agent jobs must be silent on healthy no-op ticks.
3. State-changing no-agent jobs must dry-run before apply where helpers support it.
4. Stale ledger, stale survival, or stale scoreboard should be reported as blocked, not disguised as failure or success.
5. Duplicate audits are disabled when the operator wrapper enforces the same invariant.
6. Prediction and shadow artifacts remain local authority; they do not create live trading authority by themselves.

# Raphael LLM-Only Public Slice

> **TL;DR** — This is the first scoped LLM-only Raphael public slice. It can
> pass the LLM release gate, but it does not ship a full media, "Sage King",
> "wow", or "big evolution" launch claim.

## Release Boundary

| Include | Paths | Reason |
| --- | --- | --- |
| Core control | `agent/raphael/appraisal.py`, `control.py`, `mission.py`, `proof.py`, `strategy.py`, `state.py`, `artifacts.py`, `labels.py` | Keeps intent, goal state, blockers, evidence, and follow-up continuity structured |
| Summon UX | `agent/raphael/observer.py`, `prompt.py`, `governor.py`, `wow_score.py`, `agent/prompt_builder.py`, `agent/conversation_loop.py`, `agent/turn_finalizer.py` | Makes `拉斐爾？` behave as a controlled readiness/sage summon rather than a prompt persona |
| Evolution audit | `agent/raphael/evolution.py`, `skill_trace.py`, `status.py`, `agent/background_review.py` | Records learning signals, prioritizes repeated self-correction patterns, and creates deduplicated approval-gated skill-patch proposals without silently mutating policy |
| Lifecycle CLI | `hermes_cli/raphael_cmd.py`, `hermes_cli/subcommands/raphael.py`, `hermes_cli/config.py`, `plugins/raphael/*` | Provides install, enable, disable, uninstall, status, doctor, readiness, and release-gate |
| Release evidence | `scripts/raphael_completion_audit.py`, `scripts/raphael_package_install_smoke.py`, `scripts/raphael_release_slice_boundary.py`, `scripts/raphael_release_slice_manifest.py`, `docs/raphael-mode.md`, `docs/raphael-release-slice-audit.md` | Keeps public readiness reproducible, blocks overbroad ultimate claims, and documents which changed paths belong to this slice |
| LLM tests | `tests/agent/test_raphael_*.py`, `tests/hermes_cli/test_raphael_*.py`, `tests/plugins/test_raphael_plugin.py`, `tests/run_agent/test_*` | Proves the LLM slice without visual quota |

## Explicit Exclusions

| Exclude from this slice | Why |
| --- | --- |
| `plugins/image_gen/grok_web_imagine/*` | Full media release still needs live Grok proof |
| `scripts/grok_web_imagine_live_e2e.py` and `scripts/openai_visual_live_e2e.py` | Provider evidence belongs to the media slice |
| `agent/visual/*`, `tools/visual_*`, `gateway/*` media delivery changes | Keep visual routing and delivery review separate from LLM-only release |
| Generated media, provider logs, cache files, Slack artifacts | Must remain local unless sanitized as fixtures |

## Required Evidence

The slice is mechanically reviewable when the scoped non-hostile commands pass
from the current worktree. Public release additionally requires
`hermes raphael readiness --readiness-profile llm --check` to pass with
`Release scope: llm_only`; that gate does not cover media, Grok, video, or full
Sage King claims.

- Quota-free production replay passes through the canonical turn kernel and
  shared finalizer for summon routing, mission follow-up continuity,
  proof-gated success claims, and auditable evolution proposals. Readiness
  rejects evidence whose producer is not `production_replay`.
- Live model identity is capability-based: the log and transcript must agree,
  the provider must be OpenAI-family, and the model must declare the supported
  GPT-5 family. Readiness does not pin one historical versioned model.
- At least one LLM-only live smoke is recorded in a JSON evidence file and
  classified as passed after matching the expected session id.
- Public wording says "Raphael LLM control-layer slice is ready".
- Public wording keeps media, visual, video, Grok, and full release claims
  outside that sentence.
- OpenAI image generation readiness remains scoped to a separate media gate.
- Grok Web Imagine readiness remains blocked.
- Video generation readiness remains blocked.
- Slack/native media delivery readiness remains blocked.
- Artifact beauty, face fidelity, pose, wardrobe, geometry, or selected-media
  quality readiness remains blocked.
- Full "ultimate Raphael" release-candidate readiness remains blocked.

## Verification Commands

```bash
venv/bin/hermes raphael status
venv/bin/hermes raphael doctor
venv/bin/python scripts/raphael_completion_audit.py --target scoped
venv/bin/python scripts/raphael_release_docs_audit.py
venv/bin/python scripts/raphael_release_slice_boundary.py --from-git-status
venv/bin/python scripts/raphael_release_slice_manifest.py --from-git-status
venv/bin/python -m pytest tests/scripts/test_raphael_package_install_smoke.py -q
venv/bin/python -m pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py tests/plugins/test_raphael_plugin.py tests/run_agent/test_background_review.py tests/scripts/test_raphael_*.py -q
venv/bin/ruff check agent/raphael hermes_cli/raphael_cmd.py hermes_cli/subcommands/raphael.py plugins/raphael scripts/raphael_completion_audit.py scripts/raphael_release_docs_audit.py scripts/raphael_release_slice_boundary.py scripts/raphael_release_slice_manifest.py scripts/raphael_package_install_smoke.py tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py tests/plugins/test_raphael_plugin.py tests/scripts/test_raphael_completion_audit.py tests/scripts/test_raphael_release_docs_audit.py tests/scripts/test_raphael_release_slice_boundary.py tests/scripts/test_raphael_release_slice_manifest.py tests/scripts/test_raphael_package_install_smoke.py
git diff --check
```

On a clean committed checkout, the bare boundary `--from-git-status` command
fails closed. Re-run it with the explicit release base, for example
`--from-git-status --diff-base <release-base>`, so committed paths from
`<release-base>...HEAD` are inspected.

Historical slice evidence (not a substitute for the current gate):

- The archived `hermes raphael readiness --readiness-profile llm --check`
  record reported `ready_for_llm_only_release` with `Release scope: llm_only`.
  It is historical evidence; run the command again for a current verdict.
- The archived scoped completion audit reported `Raphael completion audit:
  partial`, `Scoped release ready: yes`, and `Ultimate Sage King ready: no`.
- The archived release-docs audit returned pass for its matching gate
  artifacts. Documentation never extends their freshness.
- Boundary results are run-specific and are not checked-in release evidence. The canonical packaged policy deliberately leaves unrelated CI, old implementation plans, generic release automation, and generic tests/utilities unclassified instead of absorbing them into the Raphael slice.
- The archived release-slice manifest recorded `split_required`,
  `allowed_public_claims: ["llm_only"]`, one `llm_scoped_release` slice, and one
  deferred media slice.
- Historical LLM-only live summon smoke `20260701_131600_93f518` recorded
  same-session follow-up continuity with the then-current `gpt-5.5`, zero tool
  calls, and text-only output. Current acceptance must use the effective model
  reported by runtime and matching log/transcript evidence.
- Hostile-shaped text-only smoke `20260701_130957_137750` proves public Raphael wording with `不要產圖` stays out of visual handoff and ends with zero tool calls.
- Archived package install smoke `package-install-20260701-fresh-home-fail-closed-v1.json` recorded wheel install, lifecycle, audit-only default, fail-closed readiness, and approval-gated proposal commands.
- Archived non-visual regression evidence `non-visual-regression-20260701-openai-quality-attachment-gate.json` recorded `1529` passing tests, no failures, no visual quota usage, and broad Raphael/media regression coverage.
- Hostile review evidence `hostile-review-20260701-fresh-home-fail-closed-v1` explicitly disallows `sage_king`, `wow`, and `big_evolution` public claims while allowing only the scoped LLM-only slice and the separate OpenAI image-only media scope. The current readiness gate also requires all six quota-free user simulation cases to include `user_prompt`, `expected_visible_behavior`, `critical_assertions`, `next_action`, `proof_layer`, and `visual_quota_used:false`.
- OpenAI media readiness is separate from this LLM-only slice. The historical
  OpenAI image-only report has been revalidated as a limited
  `media_openai_image_only` public scope. It does not prove default Grok,
  xAI, video, or full image-first media readiness.

## Release Risks

- Public defaults must keep evolution writes audit-only unless `--evolve` is explicit. This host may enable durable writes locally, but fresh install evidence must stay audit-only.
- Any publication diff must be reviewed by slice; an older mixed worktree snapshot was not a single coherent public release.
- A hostile review must judge summon experience, goal continuity, and public-claim wording; schema correctness alone is insufficient.
- Full media claims are out of scope until Grok live E2E and image-first video evidence pass.

## Next Gate

1. Confirm audit-only defaults in fresh install and package-install smoke.
2. Run the required evidence commands above.
3. Keep public wording scoped to `llm_only`.
4. Defer full Sage King, wow, Grok, and video claims until separate hostile review and live evidence allow them.

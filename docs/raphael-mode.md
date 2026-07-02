# Raphael Mode

Raphael mode is Hermes' Sage King control layer. It is not a persona prompt and
not a passive advisor. When enabled, Raphael watches each turn for durable
learning evidence, routes specialist modes, checks proof requirements, classifies
failure layers, and can trigger a gated background evolution review to improve
skills or memory.

## Enable Or Disable

Use the first-class lifecycle command:

```bash
hermes raphael status
hermes raphael install
hermes raphael doctor
hermes raphael enable
hermes raphael disable
hermes raphael uninstall
hermes raphael readiness
hermes raphael release-gate --readiness-profile llm
```

`hermes raphael install` is an alias-like lifecycle action for first-time setup:
it enables the bundled `raphael` plugin and turns on default conversation-mode
injection. Enable writes `raphael.mode: sage_king` and turns on the gated
Raphael evolution policy. By default, install/enable runs in audit-only
evolution mode; use `--evolve` only when durable skill/memory writes should be
allowed.

After install/enable, the CLI tells operators whether durable skill/memory
writes are still audit-only or explicitly enabled with `--evolve`, and points
to `hermes raphael doctor` for a quota-free local setup check before release
readiness evidence is collected.

`hermes raphael doctor` verifies only local setup: bundled plugin state,
Raphael mode, conversation-mode injection, and whether evolution writes are
audit-only or durable. It also confirms the bundled Raphael slash-command
manifest is present without initializing runtime state. It does not call
providers, does not create media, and does not claim public release readiness.
When local setup is healthy it points to
`hermes raphael readiness --readiness-profile llm` for the first audited release
check.

`hermes raphael status` is the quick user-facing control panel: mode, plugin
state, conversation injection, bundled slash-command availability,
evolution-write posture, and the next verification command. Enabled installs
point to `doctor` plus LLM/media readiness checks; disabled installs point back
to `hermes raphael enable` when the bundled plugin and slash commands remain
available. Plugin-disabled or slash-unavailable installs point to
`hermes raphael install` for repair.

Disable keeps the plugin available so `/raphael-status` and `/raphael-enable`
can still work when the plugin is currently installed. Running `disable` after
`uninstall` does not reinstall or re-enable the plugin.

`hermes raphael uninstall` disables both the mode and bundled plugin. Use it
when Raphael should be removable for distribution tests or user opt-out flows.
Runtime state and audit history are preserved by default; remove local Raphael
state manually only when that audit trail is no longer needed.

`hermes raphael readiness` is the media public-release gate. It treats the
offline demo as non-evidence and blocks public-ready claims until local audited
evidence exists for lifecycle install/disable/uninstall, LLM-only live smoke,
slash-command surface availability, the deterministic Raphael wow score,
hostile review, non-visual regression, and visual live E2E artifact quality.
The wow score includes both an explicit task
summon and a standalone standby summon, so `拉斐爾？` must produce a ready state
that asks for the mission target instead of treating the summon word as the
goal. When visual generation quota has not been approved, the expected media
result is `blocked_visual_live_e2e_pending` unless an explicit fallback media
readiness scope has been approved, such as OpenAI/Codex image-only evidence
while Grok quota is deferred.

Use `hermes raphael readiness --readiness-profile llm` for quota-preserving
LLM-only release checks. That profile still requires lifecycle and live LLM smoke
evidence plus hostile review and non-visual regression evidence, but it does not
require visual/media generation evidence.

Use `hermes raphael release-gate` to write the trusted readiness evidence file.
The command runs both an in-process lifecycle smoke and a public CLI subprocess
smoke in isolated temp `HERMES_HOME` directories. The CLI smoke must resolve and
execute the actual `hermes` console-script entrypoint; `python -m
hermes_cli.main` is not accepted as proof of the packaged public command. It
exercises `hermes raphael install`, `status`, `disable`, `enable`, and
`uninstall` through the same command surface an operator would use, without
writing to the user's real runtime home. It also runs a quota-free slash-command
surface smoke for the bundled Raphael plugin, runs the offline demo as a
deterministic wow-score check, verifies the standalone standby summon surface,
then records audited LLM smoke fields
with matching fresh Hermes `agent.log` turn-end evidence and a transcript report
that proves the same live session preserved a Raphael summon plus same-mission
follow-up continuity. The wow check also carries a quota-free user simulation
matrix for the first public LLM surface: standby summon, vague takeover mission
continuity, runtime log attachment routing, blank-screen repair routing,
prompt-builder code-question routing, and negated media summon routing. Every
case must pass with a concrete `user_prompt`, `expected_visible_behavior`,
non-empty `critical_assertions`, `visual_quota_used: false`, a concrete
`next_action`, and a bounded `proof_layer`, or readiness rejects the offline
shape as unverified.
This keeps the wow score tied to actionable Sage King behavior rather than a
passive transcript demo. It also records hostile review and non-visual
regression evidence as first-class checks from source report files. Readiness re-reads the
referenced Hermes log, transcript, hostile-review report, and non-visual
regression report, so copied JSON fields alone cannot prove a release. For
media, readiness also re-reads the referenced visual report and requires its
current `run_id`, fresh `generated_at`, result-surface provenance, artifact
path, operation, and durability fields to match the stored release claim. The
command writes profile-specific readiness evidence
(`release_readiness.llm.json` or `release_readiness.media.json`) plus a latest
legacy snapshot for operators. Evidence writes are atomic, and refreshing the
LLM profile does not overwrite the media profile. When media evidence is not yet
present, media readiness can reuse LLM-profile common checks and remain blocked
only on the missing visual live E2E proof. It does not perform live visual
generation by itself.

The slash-command surface check verifies that the bundled plugin registers
`/raphael-status`, `/raphael-skills`, `/raphael-doctor`, `/raphael-enable`, and
`/raphael-disable`, that `/raphael-status` renders the Sage King brief, that
`/raphael-skills` renders the Skill Evolution Brief, that gateway dispatch
recognizes `/raphael-skills`, and that Telegram menu surfacing exposes the
underscore-safe `raphael_skills` command. This keeps the first user-facing
entrypoints in the release gate instead of relying only on code shape.
The lifecycle release gate also proves that slash commands remain available
after `hermes raphael disable` and that status guides users back to
`hermes raphael enable`. It also requires the public CLI smoke to prove install,
disable, re-enable, uninstall, post-uninstall repair guidance, and the resolved
`hermes` entrypoint identity. Legacy lifecycle evidence without the
disabled-state proof, without public CLI smoke proof, or without the executable
entrypoint identity is rejected.

## Slash Commands

When the bundled plugin is enabled:

- `/raphael-status` opens with a Sage King brief, then shows status cards,
  current mission state, active self-correction, pending action proposals, and
  approved manual rollouts, and recent evolution records. Pending skill-patch
  proposals show their rollout status, verification commands, promotion gate,
  and rollback condition without exposing proposal ids or raw metadata keys.
  Approved proposals remain visible as manual rollouts until an operator
  verifies and applies them outside the approval action.
- `/raphael-skills` opens with a Skill Evolution Brief, then summarizes skill
  usage and evolution traces in user-readable rows.
- `/raphael-doctor` runs the same quota-free local setup check as
  `hermes raphael doctor`.
- `/raphael-enable` enables Raphael mode.
- `/raphael-disable` disables Raphael mode while keeping commands available.

The bundled `plugins/raphael/plugin.yaml` manifest declares the same public
slash-command surface in `provides_commands` so install, packaging, and
distribution checks can inspect the module without importing plugin code.

## Sage King Contract

Raphael control and evolution decisions are privacy-safe by default. They track:

- current mode: general conversation, tool task, visual generation, visual edit,
  visual feedback, prompt disclosure, or clarification;
- target artifact: answer, runtime state, new visual package, current visual
  artifact, or latest visual prompt trace;
- provider route: base LLM, visual-agent LLM, visual media provider, and
  direct handoff policy;
- evidence gate: proof requirements, failure layer, and next repair action;
- reference resolution: semantic roles, collective reference set,
  multi-candidate validation, or precise clarification.
- evolution signal: user correction, failed proof, visual/provider failure,
  workflow pitfall, or high-risk mutation proposal.

Visual requests should route through `visual_agent_generate`; prompt disclosure
and visual feedback must not regenerate media. Direct pre-LLM visual handoff
records Raphael control metadata in the tool-result audit payload without
showing internal paths or candidate details to the user.

After the user-facing response is complete, Raphael can schedule a background
`Raphael evolution review`. That review uses the existing memory and
`skill_manage` tool gates, writes an audit record under Hermes runtime state, and
must keep durable changes scoped, auditable, and rollbackable. High-risk actions
such as cron changes, tool installation, provider configuration, or public
delivery stay proposal-only unless the user explicitly authorizes them.
The status surface turns the strongest recent evolution pattern into an active
self-correction plan. Repeated proof, provider, quality, or user-correction
signals outrank a single later unrelated lesson, and the plan shows affected
capability, audit/durable posture, proposed repair, promotion gate, rollback
condition, and next verifiable action.
When a repeated active evolution pattern reaches the promotion threshold,
Raphael also creates one deduplicated pending `skill_patch` action proposal.
That proposal is approval-gated (`R2`) and carries evidence references plus a
machine-readable rollout plan: pending-approval status, verification commands,
promotion gate, and rollback condition. Release readiness rejects stale
evolution evidence that proves only "a proposal exists" without proving this
rollout plan, so Raphael can recommend a skill improvement without silently
mutating durable policy. Approving a proposal records the audit decision and
surfaces the manual rollout steps in both CLI output and status; it does not
apply skills, memory, cron, tools, providers, or delivery policy automatically.

If Raphael's mission-state writer or control-decision builder fails during
observation, the turn should continue but inject a compact internal
`Raphael Control Layer Degraded` marker with the failure layer, error class, and
next repair action. Do not silently treat a degraded control layer as healthy.
If a final answer is blocked by the Raphael proof gate, that failed proof becomes
an evolution signal for the `raphael.proof_gate` capability rather than a normal
low-risk observation.

## Verification

Before calling a Raphael change ready, run focused tests for:

```bash
venv/bin/python -m pytest \
  tests/agent/test_raphael_control.py \
  tests/agent/test_raphael_evolution.py \
  tests/hermes_cli/test_raphael_cmd.py \
  tests/agent/test_raphael_observer.py \
  tests/agent/test_raphael_status.py \
  tests/visual/test_agent_mode_handoff.py \
  tests/plugins/test_raphael_plugin.py
```

For visual routing and evidence smoke:

```bash
venv/bin/python scripts/visual_agent_mode_regression_report.py --json
venv/bin/python scripts/visual_evidence_self_smoke.py --json
```

Public release readiness also requires a local audited evidence file produced by
the release gate command. For an LLM-only release after a live smoke, use:

```bash
venv/bin/python scripts/raphael_package_install_smoke.py \
  --output /path/to/package-install.json

hermes raphael release-gate \
  --readiness-profile llm \
  --llm-smoke-session-id session-id-from-current-run \
  --llm-smoke-command "rtk hermes chat -Q --max-turns 3" \
  --llm-smoke-transcript /path/to/llm-smoke-transcript.json \
  --package-install-report /path/to/package-install.json \
  --hostile-review-command "subagent hostile review" \
  --hostile-review-run-id review-id-from-current-run \
  --hostile-review-report /path/to/hostile-review.json \
  --non-visual-regression-command "pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py" \
  --non-visual-regression-run-id regression-id-from-current-run \
  --non-visual-regression-report /path/to/non-visual-regression.json
```

The LLM transcript report must be fresh JSON with
`kind: raphael_llm_smoke_transcript`, the matching `session_id`, zero tool
calls, `model: gpt-5.5`, an OpenAI-family `model_provider`, summon-section,
full-body, and no-visual-failure checks set to true, and a same-mission
follow-up turn with both `mission_followup_verified` and
`same_mission_continuity_verified` true. The agent log must independently show
the same session using `model=gpt-5.5` and an OpenAI-family provider. A
single-turn `RAPHAEL_OK` smoke is not release evidence.

The hostile-review and non-visual-regression gates are report-backed. A stored
`verdict: pass` or count is not trusted unless the source report is fresh,
matches the run id, and revalidates to the same claim. Hostile review reports
must come from a `subagent` reviewer; the main agent cannot self-sign this gate.
For the current scoped LLM-only and limited media release profiles, the hostile
review must explicitly deny public `sage_king`, `wow`, and `big_evolution`
launch claims. A hostile review that marks any of those broad claims as allowed
fails closed even when its verdict is otherwise `pass`.
The same claim review must exercise the adversarial UX scenarios
`constrained_summon`, `same_mission_followup`, `negated_media_request`,
`public_wording_review`, `video_claim_boundary`, and
`openai_image_only_claim_boundary`, so a scoped LLM or image-only release cannot
silently expand into unproven video, Grok, or full Sage King claims.
They must also declare full-scope `coverage` tags for
`setup_doctor_no_scaffold`, `lifecycle_install_disable_uninstall`,
`llm_live_smoke_followup`, `release_gate_evidence_provenance`,
`hostile_review_independence`, `readiness_next_action`,
`slash_command_surface_gate`, `non_visual_regression`,
`mode_router_contract_gate`, `goal_state_contract_gate`,
`evolution_contract_gate`, `visual_preflight_provenance_gate`,
`visual_live_e2e_gate`, and
`independent_visual_quality_review_gate`. Narrow reports, such as a doctor-only
recheck, fail closed even when their verdict is pass. The report must also carry
an audit trail: non-empty `scope`, non-empty `evidence`, and a `residual_risk`
statement. A coverage-only report is treated as an empty review, not release
evidence.

Every release-gate evidence file must carry a machine-readable readiness
verdict, not only human-facing prose: `public_release_ready`, `release_state`,
`blocking_reasons`, `blocking_layers`, `readiness_next_action`, and
`readiness_blocking_actions`, plus a quota-aware `readiness_repair_plan` and
`readiness_proof_requirements`. LLM-only release evidence must also carry
`public_claim_scope: llm_only` and explicit `public_claim_exclusions` for media,
Grok, video, and full Sage King claims, so automation cannot treat
`public_release_ready: true` as a full Raphael launch. Each blocking action must
name the original
reason, failure layer, scoped next action, and command when one exists. The
repair plan is the automation surface: it orders preflight, live-proof, and
final release-gate verification steps so a follow-up agent can repair the
release state without parsing the rendered readiness message. The proof
requirements define the acceptance criteria each live-proof step must satisfy.
For provider gaps with `quota_policy: preflight_first`, the first repair step
must be quota-free preflight before any live generation proof. The release gate
must publish only a complete evidence payload with these fields already present;
readers fail closed when the verdict fields are missing, contradict the
underlying check blockers, omit repair steps for blockers, or omit proof
requirements for live-proof blockers.

Non-visual regression reports must also declare `suite_coverage` for the
minimum quota-free release surface: `raphael_agent`, `raphael_cli`,
`raphael_plugin`, `visual_handoff`, `visual_agent_tool`, and
`visual_package_tool`, plus `gateway_delivery` for the platform delivery filter
that strips rejected, stale, cross-request, or unuploadable visual package
artifacts before native upload. A narrow report, such as CLI-only tests, does
not prove the LLM release profile because Raphael still coordinates visual
handoff and delivery policy even when media generation is not exercised.
The report must include a canonical `report_digest` over the report body with
`report_digest` itself omitted; stale or hand-edited reports fail closed when the
digest no longer matches.

For media public release, add visual evidence only after an approved live visual
E2E. The live run creates the artifact first; the quality review is recorded
after an independent human or vision-backed reviewer inspects that artifact.
The review CLI records and validates that source report. It is not by itself a
vision judge.

OpenAI/Codex image-only E2E can be used as a quota-preserving media evidence
slice when Grok quota is intentionally deferred. It validates OpenAI
response-surface provenance, artifact freshness, and independent quality-review
plumbing without spending Grok quota, and it can be released as a limited
public media slice only when the current source report still passes script,
digest, result-surface, artifact, and quality-review provenance checks. In that
mode, readiness records
`media_release_scope: media_openai_image_only`, records
`verified_media_capabilities` with `openai_image_generation`, and discloses
remaining full-media gaps for `xai_grok_generation` and `video_generation`.
The verified capability is a machine-readable handoff surface for "OpenAI image
generation has current release evidence"; it is not a full media release
verdict. Readers fail closed if
`verified_media_capabilities` is missing, forged, inconsistent with the
derived `media_release_scope` and `remaining_media_gaps`, if `public_claim_scope`,
`public_claim_capabilities`, `public_claim_exclusions`, or `public_claim_summary`
drift from the same scope/gap/capability derivation, or if the claim is backed
by stale source-report provenance. When that proof is current, it reports
`ready_for_limited_media_public_release` for the public media gate and readiness
output must say `Verified media capabilities: openai_image_generation`,
`Limited media release ready: yes`, `Full media release ready: no`, and
`Public release ready: limited (scope: media_openai_image_only; full media gaps remain)`.
When source-report provenance drifts after script changes, media readiness must
block until the visual E2E report is regenerated. Full default-provider media
release requires Grok live E2E evidence with no
remaining media scope gaps. Video evidence is not complete merely because a
video file exists: it
must also prove the image-first source-image selection path used to create the
video. The release gate accepts that proof only when the live report records a
single ranked selected source image with a source artifact id, materialized
source image path, and matching source-image policy. A self-attested
`source_image_exists: true` flag is not sufficient if the source image file is
not present. When full-media scope gaps remain, the next action must name the
missing layer: run Grok Web Imagine live E2E for `xai_grok_generation`, add
video generation E2E evidence for `video_generation`, add source-image selection
evidence for `image_first_source_image`, then rerun the media release gate. The
same remediation must be present in `media_release_gap_actions` and
`media_full_release_gap_actions` so automation and follow-up agents do not have
to parse prose. The same gaps must emit `media_full_release_proof_requirements`
so the next agent can see the exact acceptance criteria, such as fresh Grok
result-surface evidence for `xai_grok_generation` and a single ranked source
image for image-first video.

```bash
HERMES_VISUAL_LIVE_E2E=1 \
HERMES_OPENAI_VISUAL_LIVE_E2E=1 \
OPENAI_IMAGE_MODEL=gpt-image-2-low \
python scripts/openai_visual_live_e2e.py \
  --prompt "..." \
  --aspect-ratio square \
  --output /path/to/openai-visual-live.raw.json
```

```bash
python scripts/raphael_visual_quality_review.py \
  --artifact /path/to/artifact-from-openai-live-report.png \
  --reviewer independent-vision-release-review \
  --verdict pass \
  --dimension composition=pass \
  --dimension prompt_adherence=pass \
  --dimension geometry=pass \
  --dimension subject_quality=pass \
  --evidence "artifact was reviewed directly" \
  --output /path/to/raphael-visual-quality-review.json
```

```bash
python scripts/openai_visual_live_e2e.py \
  --input-report /path/to/openai-visual-live.raw.json \
  --quality-review-report /path/to/raphael-visual-quality-review.json \
  --output /path/to/openai-visual-live.reviewed.json
```

Run the quota-free Grok preflight before spending Grok visual quota. This checks
opt-in flags, provider construction, and the Grok Web Imagine browser/CDP
readiness probe. When the Imagine composer is available, the preflight fills a
short Raphael probe prompt and verifies that the prompt text is present and the
submit button is enabled, but it does not click submit or generate media. It
classifies setup blockers such as login, subscription, Cloudflare, or
unreachable debug Chrome without using visual quota:

```bash
python scripts/grok_web_imagine_live_e2e.py --preflight-only
```

When a preflight report exists, pass it to the media release gate as setup
evidence:

```bash
hermes raphael release-gate \
  --readiness-profile media \
  --visual-preflight-report /path/to/grok-web-preflight.json \
  --visual-e2e-report /path/to/grok-web-live-report.json
```

`--visual-preflight-report` can prove the browser path is blocked or ready, but
it does not count as visual live E2E success. Media public release still
requires `--visual-e2e-report` with a fresh selected artifact and independent
artifact-quality evidence. The release gate only accepts preflight evidence that
proves no prompt was submitted, no visual quota was used, a browser/CDP
preflight actually ran, the prompt probe succeeded, and the report timestamp is
still fresh.

```bash
python scripts/grok_web_imagine_live_e2e.py \
  --prompt "..." \
  > /path/to/grok-web-live-report.raw.json
```

```bash
python scripts/raphael_visual_quality_review.py \
  --artifact /path/to/artifact-from-grok-web-live-report.png \
  --reviewer vision-backed-artifact-review \
  --verdict pass \
  --dimension composition=pass \
  --dimension prompt_adherence=pass \
  --dimension geometry=pass \
  --dimension subject_quality=pass \
  --evidence "artifact was reviewed directly" \
  --output /path/to/raphael-visual-quality-review.json
```

```bash
python scripts/grok_web_imagine_live_e2e.py \
  --input-report /path/to/grok-web-live-report.raw.json \
  --quality-review-report /path/to/raphael-visual-quality-review.json \
  --output /path/to/grok-web-live-report.reviewed.json
```

```bash
hermes raphael release-gate \
  --readiness-profile media \
  --llm-smoke-session-id session-id-from-current-run \
  --llm-smoke-command "rtk hermes chat -Q --max-turns 3" \
  --llm-smoke-transcript /path/to/llm-smoke-transcript.json \
  --package-install-report /path/to/package-install.json \
  --hostile-review-command "subagent hostile review" \
  --hostile-review-run-id review-id-from-current-run \
  --hostile-review-report /path/to/hostile-review.json \
  --non-visual-regression-command "pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py" \
  --non-visual-regression-run-id regression-id-from-current-run \
  --non-visual-regression-report /path/to/non-visual-regression.json \
  --visual-command scripts/grok_web_imagine_live_e2e.py \
  --visual-preflight-report /path/to/grok-web-preflight.json \
  --visual-e2e-report /path/to/grok-web-live-report.reviewed.json
```

Do not populate the visual check from an offline fixture, stale artifact,
provider success flag, provider/live-harness `self_review`, or old gallery item;
it must represent a current selected artifact with independent `quality_review`
evidence recorded in the source report. The `quality_review` block must point to
a separate fresh source report with `source_report_path`; inline-only quality
claims fail closed. The source report must use
`kind: raphael_visual_quality_review`, identify the reviewed artifact path, use
a non-provider reviewer, pass composition, prompt adherence, geometry, and
subject-quality dimensions, include non-empty `producer`, `command`, `run_id`,
`evidence`, and `residual_risk` audit fields, and produce an accepted quality
verdict. Reviewer names that identify the provider path, such as OpenAI,
OpenAI Codex, GPT Image, image2, Grok Web Imagine, provider, self-review, or
live harness, are not independent quality review. OpenAI live evidence must use
a verified OpenAI response surface such as `openai-response:*`, `resp_*`, or
`response_*`; generic URLs or hand-written `history_entry_id` values do not
prove the current OpenAI result. The selected artifact file must still exist,
have a fresh modification time, and match the live report timestamp closely
enough to prove it is not a stale artifact being reattached. The readiness
command fails closed when evidence
has an unknown producer, missing command/run id, malformed JSON, missing or weak
wow-score evidence, a mismatched readiness profile, stale release evidence
(older than 24 hours), stale LLM log evidence, missing LLM transcript report,
single-turn LLM smoke without mission follow-up continuity, missing visual live
report provenance, missing or mismatched visual report `run_id`, stale
visual report `generated_at`, mismatched source-report contents, missing
history/post/result-surface evidence, stale or mismatched visual artifact mtime,
missing audited LLM execution data, missing Hermes log provenance for the LLM
smoke session, missing hostile-review report evidence, unresolved
hostile-review blockers, incomplete hostile-review coverage, missing non-visual
regression report evidence, visual quota use during the non-visual regression,
or a visual artifact without independent pass/accepted quality review evidence.
A
failed visual live report that declares operator setup or quota requirements
must surface as `visual_live_e2e_setup_required` with a setup/quota next action
instead of a generic artifact-quality failure.

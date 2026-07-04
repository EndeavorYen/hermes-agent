import json
import argparse
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from hermes_cli.subcommands.raphael import build_raphael_parser


def _write_config(home, payload):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def _read_config(home):
    return yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))


def _relative_paths(root):
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
    )


def _build_raphael_test_parser():
    from hermes_cli.raphael_cmd import raphael_command

    parser = argparse.ArgumentParser(prog="hermes")
    subparsers = parser.add_subparsers(dest="command")
    build_raphael_parser(subparsers, cmd_raphael=raphael_command)
    return parser


def _fresh_generated_at():
    return datetime.now(timezone.utc).isoformat()


def _grok_prompt_probe_ready():
    return {
        "attempted": True,
        "prompt_text_present": True,
        "submit_enabled": True,
        "reason": "",
        "tag": "TEXTAREA",
        "filled_text_preview": "Hermes Raphael preflight browser readiness probe.",
    }


def _grok_provider_report_fields(result_surface="https://grok.com/imagine/history/current"):
    return {
        "provider": {
            "name": "grok-web-imagine",
            "model": "grok-web-imagine",
        },
        "provider_result": {
            "provider": "grok-web-imagine",
            "model": "grok-web-imagine",
            "page_url": result_surface,
        },
    }


def _visual_quality_review(
    artifact,
    *,
    reviewer="vision-backed-artifact-review",
    run_id="visual-quality-review-1",
    review_source_type="vision_model",
):
    report_path = artifact.with_name(f"{artifact.stem}.quality-review.json")
    generated_at = _fresh_generated_at()
    artifact_bytes = artifact.read_bytes()
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    artifact_mtime = artifact.stat().st_mtime
    review_evidence = [
        "artifact path reviewed",
        "required visual quality dimensions passed",
    ]
    is_human_review = review_source_type == "human_independent"
    review_model_provider = "" if is_human_review else "openai"
    review_model = "" if is_human_review else "gpt-5.5-vision"
    review_response_id = "" if is_human_review else f"resp_{run_id}"
    transcript_path = artifact.with_name(f"{artifact.stem}.model-review.json")
    transcript_text = ""
    if not is_human_review:
        review_transcript = {
            "schema_version": 1,
            "kind": "raphael_visual_quality_model_review",
            "producer": "openai-gpt-vision-review",
            "response_id": review_response_id,
            "review_model_provider": review_model_provider,
            "review_model": review_model,
            "artifact_path": str(artifact),
            "artifact_sha256": artifact_sha256,
            "artifact_size_bytes": len(artifact_bytes),
            "artifact_quality_verdict": "pass",
            "dimensions": {
                "composition": "pass",
                "prompt_adherence": "pass",
                "geometry": "pass",
                "subject_quality": "pass",
            },
            "evidence": review_evidence,
        }
        transcript_text = json.dumps(review_transcript, sort_keys=True)
        transcript_path.write_text(transcript_text, encoding="utf-8")
    transcript_digest = (
        hashlib.sha256(transcript_text.encode("utf-8")).hexdigest()
        if transcript_text
        else ""
    )
    review_digest = _json_digest(
        {
            "artifact_sha256": artifact_sha256,
            "dimensions": {
                "composition": "pass",
                "prompt_adherence": "pass",
                "geometry": "pass",
                "subject_quality": "pass",
            },
            "evidence": review_evidence,
            "review_model": review_model,
            "review_model_provider": review_model_provider,
        }
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_visual_quality_review",
                "generated_at": generated_at,
                "command": "vision-backed artifact quality review",
                "run_id": run_id,
                "producer": "hermes-visual-quality-review",
                "reviewer": reviewer,
                "artifact_path": str(artifact),
                "artifact_sha256": artifact_sha256,
                "artifact_size_bytes": len(artifact_bytes),
                "artifact_mtime": artifact_mtime,
                "artifact_identity_verified": True,
                "review_source_type": review_source_type,
                "review_model_provider": review_model_provider,
                "review_model": review_model,
                "review_evidence_digest": review_digest,
                "review_response_id": review_response_id,
                "review_transcript_report_path": str(transcript_path)
                if transcript_text
                else "",
                "review_transcript_digest": transcript_digest,
                "review_provenance_verified": True,
                "artifact_quality_verdict": "pass",
                "dimensions": {
                    "composition": "pass",
                    "prompt_adherence": "pass",
                    "geometry": "pass",
                    "subject_quality": "pass",
                },
                "evidence": review_evidence,
                "residual_risk": "human or vision-backed reviewer remains responsible for subjective quality.",
            }
        ),
        encoding="utf-8",
    )
    return {
        "producer": "hermes-visual-quality-review",
        "reviewer": reviewer,
        "run_id": run_id,
        "generated_at": generated_at,
        "artifact_path": str(artifact),
        "artifact_sha256": artifact_sha256,
        "artifact_size_bytes": len(artifact_bytes),
        "artifact_mtime": artifact_mtime,
        "artifact_identity_verified": True,
        "review_source_type": review_source_type,
        "review_model_provider": review_model_provider,
        "review_model": review_model,
        "review_evidence_digest": review_digest,
        "review_response_id": review_response_id,
        "review_transcript_report_path": str(transcript_path) if transcript_text else "",
        "review_transcript_digest": transcript_digest,
        "review_provenance_verified": True,
        "artifact_quality_verdict": "pass",
        "dimensions": {
            "composition": "pass",
            "prompt_adherence": "pass",
            "geometry": "pass",
            "subject_quality": "pass",
        },
        "source_report_path": str(report_path),
    }


def _package_install_smoke_report(
    home,
    *,
    run_id="package-install-20260701-fresh-home-fail-closed-v1",
    generated_at=None,
    success=True,
    installed_llm_fail_closed=False,
):
    report_dir = home / "raphael" / "release_quality"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"package-install-{run_id}.json"
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "raphael_package_install_smoke.py"
    )
    commands = (
        _package_install_smoke_commands(
            home,
            installed_llm_fail_closed=installed_llm_fail_closed,
        )
        if success
        else []
    )
    installed_llm_gate_lines = []
    installed_llm_gate_stdout = ""
    if success:
        installed_llm_gate_lines = [
            *(
                [
                    "Release docs: missing",
                    "Completion audit: missing",
                    "Release slice manifest: missing",
                ]
                if installed_llm_fail_closed
                else [
                    "Release docs: pass",
                    "Completion audit: partial (scoped=yes, ultimate=no)",
                    "Release slice manifest: reviewable (split_required)",
                ]
            ),
            "Release scope: llm_only",
            "Public claim scope: llm_only (does not cover media/Grok/video/full Sage King claims)",
            (
                "Public release ready: no"
                if installed_llm_fail_closed
                else "Public release ready: yes"
            ),
            (
                "Release state: blocked_release_evidence_pending"
                if installed_llm_fail_closed
                else "Release state: ready_for_llm_only_release"
            ),
        ]
        installed_llm_gate_stdout = (
            "Raphael Release Readiness\n"
            "Profile: llm\n"
            + "\n".join(installed_llm_gate_lines)
            + "\n"
        )
    report = {
        "schema_version": 1,
        "kind": "raphael_package_install_smoke",
        "generated_at": generated_at or _fresh_generated_at(),
        "command": "scripts/raphael_package_install_smoke.py",
        "run_id": run_id,
        "script_path": str(script_path),
        "script_sha256": _sha256_text(script_path.read_bytes()),
        "script_identity_verified": success,
        "success": success,
        "status": "pass" if success else "fail",
        "exit_code": 0 if success else 1,
        "wheel_built": success,
        "wheel_installed": success,
        "venv_fallback_used": False,
        "venv_error": "",
        "source_tree_cwd_used": False,
        "source_tree_hygiene_checked": True,
        "source_tree_hygiene_clean": True,
        "source_tree_generated_artifacts": [],
        "source_tree_post_build_hygiene_clean": True,
        "source_tree_post_build_generated_artifacts": [],
        "pythonpath_clean": True,
        "installed_media_slice_ready": False if success else success,
        "installed_media_fail_closed": success,
        "installed_media_gate_lines": [
            "Full media release ready: no",
            "Public release ready: no",
        ]
        if success
        else [],
        "installed_media_gate_probe": {
            "label": "media_readiness_after_install",
            "exit_code": 1,
            "stdout": (
                "Raphael Release Readiness\n"
                "Profile: media\n"
                "Full media release ready: no\n"
                "Public release ready: no\n"
            ),
        }
        if success
        else {},
        "installed_llm_release_ready": success and not installed_llm_fail_closed,
        "installed_llm_manifest_gate_verified": success and not installed_llm_fail_closed,
        "installed_llm_fresh_home_fail_closed": success and installed_llm_fail_closed,
        "installed_llm_readiness_exit_code": (
            1 if success and installed_llm_fail_closed else 0 if success else None
        ),
        "installed_llm_gate_lines": installed_llm_gate_lines,
        "installed_llm_gate_probe": {
            "label": "llm_readiness_after_install",
            "exit_code": 1 if installed_llm_fail_closed else 0,
            "stdout": installed_llm_gate_stdout,
        }
        if success
        else {},
        "hermes_entrypoint": "hermes",
        "hermes_entrypoint_found": success,
        "hermes_entrypoint_path": str(home / "package-venv" / "bin" / "hermes")
        if success
        else "",
        "cli_command_count": 10 if success else 0,
        "cli_exit_codes": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] if success else [],
        "cli_status_after_install_enabled": success,
        "cli_install_enabled": success,
        "cli_disable_keeps_plugin": success,
        "cli_status_after_disable_guides_enable": success,
        "cli_status_after_enable_enabled": success,
        "cli_enable_restores_mode": success,
        "cli_proposal_status_safe_refs": success,
        "cli_proposal_approve_audited": success,
        "cli_proposal_approve_rollout_guidance": success,
        "cli_proposal_reject_audited": success,
        "cli_proposal_resolutions_persisted": success,
        "cli_proposal_raw_ids_hidden": success,
        "cli_proposal_no_durable_apply_warning": success,
        "cli_uninstall_disables_plugin": success,
        "cli_status_after_uninstall_guides_install": success,
        "commands_verified": success,
        "commands_digest": _json_digest(commands) if success else "",
        "commands": commands,
        "evidence": [
            "built wheel from current checkout",
            "installed wheel into fresh virtual environment",
            "ran Raphael lifecycle through installed hermes entrypoint",
        ],
        "residual_risk": "Does not exercise live providers or network installer scripts.",
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path


def _package_install_smoke_check(report_path):
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return {
        "status": "pass",
        "evidence": "package install smoke report verified",
        "command": report["command"],
        "run_id": report["run_id"],
        "source_report_path": str(report_path),
        "report_generated_at": report["generated_at"],
        "report_identity_verified": True,
        "exit_code": 0,
        "script_path": report["script_path"],
        "script_sha256": report["script_sha256"],
        "script_identity_verified": True,
        "wheel_built": True,
        "wheel_installed": True,
        "venv_fallback_used": False,
        "venv_error": "",
        "source_tree_cwd_used": False,
        "source_tree_hygiene_checked": report["source_tree_hygiene_checked"],
        "source_tree_hygiene_clean": report["source_tree_hygiene_clean"],
        "source_tree_generated_artifacts": report["source_tree_generated_artifacts"],
        "source_tree_post_build_hygiene_clean": report[
            "source_tree_post_build_hygiene_clean"
        ],
        "source_tree_post_build_generated_artifacts": report[
            "source_tree_post_build_generated_artifacts"
        ],
        "pythonpath_clean": True,
        "installed_media_slice_ready": report["installed_media_slice_ready"],
        "installed_media_fail_closed": report["installed_media_fail_closed"],
        "installed_media_gate_lines": report["installed_media_gate_lines"],
        "installed_llm_release_ready": report["installed_llm_release_ready"],
        "installed_llm_manifest_gate_verified": report[
            "installed_llm_manifest_gate_verified"
        ],
        "installed_llm_fresh_home_fail_closed": report[
            "installed_llm_fresh_home_fail_closed"
        ],
        "installed_llm_gate_lines": report["installed_llm_gate_lines"],
        "hermes_entrypoint": "hermes",
        "hermes_entrypoint_found": True,
        "hermes_entrypoint_path": report["hermes_entrypoint_path"],
        "cli_command_count": 10,
        "cli_exit_codes": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "cli_status_after_install_enabled": True,
        "cli_install_enabled": True,
        "cli_disable_keeps_plugin": True,
        "cli_status_after_disable_guides_enable": True,
        "cli_status_after_enable_enabled": True,
        "cli_enable_restores_mode": True,
        "cli_proposal_status_safe_refs": True,
        "cli_proposal_approve_audited": True,
        "cli_proposal_approve_rollout_guidance": True,
        "cli_proposal_reject_audited": True,
        "cli_proposal_resolutions_persisted": True,
        "cli_proposal_raw_ids_hidden": True,
        "cli_proposal_no_durable_apply_warning": True,
        "cli_uninstall_disables_plugin": True,
        "cli_status_after_uninstall_guides_install": True,
        "commands_verified": True,
        "commands_digest": report["commands_digest"],
        "commands_digest_verified": True,
    }


def _sha256_text(data):
    return hashlib.sha256(data).hexdigest()


def _json_digest(payload):
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stamp_visual_live_report(
    report,
    *,
    script_name="grok_web_imagine_live_e2e.py",
    producer="grok-web-imagine-live-e2e",
):
    script_path = Path(__file__).resolve().parents[2] / "scripts" / script_name
    report.update(
        {
            "schema_version": 1,
            "kind": "raphael_visual_live_e2e",
            "producer": producer,
            "command": f"scripts/{script_name}",
            "script_path": str(script_path),
            "script_sha256": _sha256_text(script_path.read_bytes()),
            "script_identity_verified": True,
        }
    )
    digest_source = dict(report)
    digest_source.pop("report_digest", None)
    report["report_digest"] = _json_digest(digest_source)
    return report


def _package_install_smoke_commands(home, *, installed_llm_fail_closed=False):
    wheel_dir = home / "wheel"
    venv_dir = home / "package-venv"
    runtime_cwd = home / "runtime-cwd"
    hermes = venv_dir / "bin" / "hermes"
    python = venv_dir / "bin" / "python"
    approve_proposal_id = "package-install-approve-proposal"
    reject_proposal_id = "package-install-reject-proposal"
    approve_ref = hashlib.sha256(approve_proposal_id.encode("utf-8")).hexdigest()[:12]
    reject_ref = hashlib.sha256(reject_proposal_id.encode("utf-8")).hexdigest()[:12]
    lifecycle_stdout = {
        "install": "Raphael mode enabled",
        "status_after_install": (
            "Raphael Status\n"
            "Mode: enabled (plugin enabled, mode=sage_king)\n"
            "Conversation injection: enabled\n"
            "Slash commands: available\n"
            "Next action: hermes raphael doctor"
        ),
        "disable": "Raphael mode disabled; plugin remains enabled",
        "status_after_disable": (
            "Raphael Status\n"
            "Mode: disabled (plugin enabled, mode=sage_king)\n"
            "Conversation injection: disabled\n"
            "Slash commands: available\n"
            "Next action: hermes raphael enable"
        ),
        "enable": "Raphael mode enabled",
        "status_after_enable": (
            "Raphael Status\n"
            "Mode: enabled (plugin enabled, mode=sage_king)\n"
            "Conversation injection: enabled\n"
            "Slash commands: available\n"
            "Next action: hermes raphael doctor"
        ),
        "uninstall": "Raphael mode uninstalled/disabled",
        "status_after_uninstall": (
            "Raphael Status\n"
            "Mode: disabled (plugin disabled, mode=sage_king)\n"
            "Conversation injection: disabled\n"
            "Slash commands: unavailable\n"
            "Next action: hermes raphael install"
        ),
    }
    installed_llm_gate_lines = [
        *(
            [
                "Release docs: missing",
                "Completion audit: missing",
                "Release slice manifest: missing",
            ]
            if installed_llm_fail_closed
            else [
                "Release docs: pass",
                "Completion audit: partial (scoped=yes, ultimate=no)",
                "Release slice manifest: reviewable (split_required)",
            ]
        ),
        "Release scope: llm_only",
        "Public claim scope: llm_only (does not cover media/Grok/video/full Sage King claims)",
        (
            "Public release ready: no"
            if installed_llm_fail_closed
            else "Public release ready: yes"
        ),
        (
            "Release state: blocked_release_evidence_pending"
            if installed_llm_fail_closed
            else "Release state: ready_for_llm_only_release"
        ),
    ]
    return [
        {
            "label": "build_wheel",
            "command": ["uv", "build", "--wheel", "--out-dir", str(wheel_dir), "."],
            "cwd": "/repo",
            "exit_code": 0,
            "stdout": "built wheel",
            "stderr": "",
        },
        {
            "label": "install_wheel",
            "command": [
                str(python),
                "-m",
                "pip",
                "install",
                "-q",
                "--force-reinstall",
                str(wheel_dir / "hermes_agent-0.17.0-py3-none-any.whl"),
            ],
            "cwd": str(home),
            "exit_code": 0,
            "stdout": "installed wheel",
            "stderr": "",
        },
        {
            "label": "pythonpath_probe",
            "command": [str(python), "-c", "import json, sys; print(json.dumps(sys.path))"],
            "cwd": str(runtime_cwd),
            "exit_code": 0,
            "stdout": "[]",
            "stderr": "",
        },
        *[
            {
                "label": label,
                "command": [str(hermes), "raphael", step],
                "cwd": str(runtime_cwd),
                "exit_code": 0,
                "stdout": lifecycle_stdout[label],
                "stderr": "",
            }
            for label, step in (
                ("install", "install"),
                ("status_after_install", "status"),
            )
        ],
        {
            "label": "media_readiness_after_install",
            "command": [
                str(hermes),
                "raphael",
                "readiness",
                "--readiness-profile",
                "media",
                "--check",
            ],
            "cwd": str(runtime_cwd),
            "exit_code": 1,
            "stdout": (
                "Raphael Release Readiness\n"
                "Profile: media\n"
                "Full media release ready: no\n"
                "Public release ready: no\n"
            ),
            "stderr": "",
        },
        {
            "label": "llm_readiness_after_install",
            "command": [
                str(hermes),
                "raphael",
                "readiness",
                "--readiness-profile",
                "llm",
                "--check",
            ],
            "cwd": str(runtime_cwd),
            "exit_code": 1 if installed_llm_fail_closed else 0,
            "stdout": (
                "Raphael Release Readiness\n"
                "Profile: llm\n"
                + "\n".join(installed_llm_gate_lines)
                + "\n"
            ),
            "stderr": "",
        },
        *[
            {
                "label": label,
                "command": [str(hermes), "raphael", step],
                "cwd": str(runtime_cwd),
                "exit_code": 0,
                "stdout": lifecycle_stdout[label],
                "stderr": "",
            }
            for label, step in (
                ("disable", "disable"),
                ("status_after_disable", "status"),
                ("enable", "enable"),
                ("status_after_enable", "status"),
            )
        ],
        {
            "label": "seed_action_proposals",
            "command": [
                str(python),
                "-c",
                "print('package_install_seed_action_proposals')",
            ],
            "cwd": str(runtime_cwd),
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "seeded": True,
                    "approve_ref": approve_ref,
                    "reject_ref": reject_ref,
                }
            ),
            "stderr": "",
        },
        {
            "label": "render_action_proposals",
            "command": [
                str(python),
                "-c",
                "print('package_install_render_action_proposals')",
            ],
            "cwd": str(runtime_cwd),
            "exit_code": 0,
            "stdout": (
                "Pending Action Proposals:\n"
                f"  Approve: hermes raphael proposal approve {approve_ref}\n"
                f"  Reject: hermes raphael proposal reject {reject_ref}\n"
            ),
            "stderr": "",
        },
        {
            "label": "proposal_approve",
            "command": [str(hermes), "raphael", "proposal", "approve", approve_ref],
            "cwd": str(runtime_cwd),
            "exit_code": 0,
            "stdout": (
                f"Raphael action proposal approved: {approve_ref}\n"
                "No durable change applied automatically; run the proposal "
                "verification commands before applying any skill, memory, cron, "
                "tool, or delivery change.\n"
                "Next manual rollout:\n"
                "  Rollout: approved\n"
                "  Verify: pytest tests/agent/test_raphael_evolution.py -q; "
                "hermes raphael readiness --readiness-profile llm --check\n"
                "  Promote: focused tests plus runtime, replay, or LLM smoke\n"
                "  Rollback: next evidence or user feedback shows worse behavior\n"
                "  Apply: manual only after verification; approval did not mutate durable policy.\n"
            ),
            "stderr": "",
        },
        {
            "label": "proposal_reject",
            "command": [str(hermes), "raphael", "proposal", "reject", reject_ref],
            "cwd": str(runtime_cwd),
            "exit_code": 0,
            "stdout": (
                f"Raphael action proposal rejected: {reject_ref}\n"
                "No durable change applied automatically; run the proposal "
                "verification commands before applying any skill, memory, cron, "
                "tool, or delivery change.\n"
            ),
            "stderr": "",
        },
        {
            "label": "inspect_action_proposals",
            "command": [
                str(python),
                "-c",
                "print('package_install_inspect_action_proposals')",
            ],
            "cwd": str(runtime_cwd),
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "statuses": {
                        approve_proposal_id: "approved",
                        reject_proposal_id: "rejected",
                    },
                    "approve_status": "approved",
                    "reject_status": "rejected",
                }
            ),
            "stderr": "",
        },
        *[
            {
                "label": label,
                "command": [str(hermes), "raphael", step],
                "cwd": str(runtime_cwd),
                "exit_code": 0,
                "stdout": lifecycle_stdout[label],
                "stderr": "",
            }
            for label, step in (
                ("uninstall", "uninstall"),
                ("status_after_uninstall", "status"),
            )
        ],
    ]


def _write_readiness_evidence(
    home,
    payload,
    *,
    profile="media",
    include_release_quality=True,
    include_verdict=True,
):
    if isinstance(payload, dict) and payload.get("schema_version") == 1:
        payload = dict(payload)
        payload.setdefault("generated_at", _fresh_generated_at())
        payload.setdefault("profile", profile)
        checks = payload.get("checks")
        if isinstance(checks, dict) and isinstance(checks.get("llm_live_smoke"), dict):
            llm_check = dict(checks["llm_live_smoke"])
            if llm_check.get("log_verified") is True:
                session_id = str(llm_check.get("session_id") or "20260701_131600_93f518")
                log_path, log_line = _write_llm_smoke_log(home, session_id=session_id)
                transcript_path = _write_llm_smoke_transcript(
                    home,
                    session_id=session_id,
                )
                llm_check["source_log_path"] = str(log_path)
                llm_check["log_line"] = log_line
                llm_check["source_transcript_path"] = str(transcript_path)
                checks = dict(checks)
                checks["llm_live_smoke"] = llm_check
                payload["checks"] = checks
        checks = payload.get("checks")
        if include_release_quality and isinstance(checks, dict):
            checks = dict(checks)
            lifecycle_check = checks.get("install_disable_uninstall")
            if isinstance(lifecycle_check, dict):
                lifecycle_check = dict(lifecycle_check)
                lifecycle_check.setdefault("disabled_slash_commands_available", True)
                lifecycle_check.setdefault("disabled_status_guides_enable", True)
                lifecycle_check.setdefault("cli_smoke_verified", True)
                lifecycle_check.setdefault("cli_entrypoint", "hermes")
                lifecycle_check.setdefault("cli_entrypoint_found", True)
                lifecycle_check.setdefault("cli_entrypoint_path", "/tmp/hermes")
                lifecycle_check.setdefault("cli_install_enabled", True)
                lifecycle_check.setdefault("cli_disable_keeps_plugin", True)
                lifecycle_check.setdefault(
                    "cli_status_after_disable_guides_enable",
                    True,
                )
                lifecycle_check.setdefault("cli_enable_restores_mode", True)
                lifecycle_check.setdefault("cli_uninstall_disables_plugin", True)
                lifecycle_check.setdefault(
                    "cli_status_after_uninstall_guides_install",
                    True,
                )
                checks["install_disable_uninstall"] = lifecycle_check
            checks.setdefault("mode_router_contract", _mode_router_contract_check())
            checks.setdefault("goal_state_contract", _goal_state_contract_check())
            checks.setdefault("evolution_contract", _evolution_contract_check())
            package_install_report = _package_install_smoke_report(home)
            checks.setdefault(
                "package_install_smoke",
                _package_install_smoke_check(package_install_report),
            )
            hostile_report = _write_hostile_review_report(home)
            regression_report = _write_non_visual_regression_report(home)
            checks.setdefault("slash_command_surface", _slash_command_surface_check())
            checks.setdefault("hostile_review", _hostile_review_check(hostile_report))
            checks.setdefault(
                "non_visual_regression",
                _non_visual_regression_check(regression_report),
            )
            checks.setdefault("release_docs_audit", _release_docs_audit_check(home=home))
            checks.setdefault("completion_audit", _completion_audit_check())
            normalized_profile = str(payload.get("profile") or profile).strip().lower()
            if normalized_profile == "llm":
                checks.setdefault(
                    "release_slice_manifest",
                    _release_slice_manifest_check(),
                )
            payload["checks"] = checks
        if include_verdict:
            _write_release_docs_audit_readiness_sources(home, payload)
            payload = _payload_with_readiness_verdict(payload, profile=profile)
    evidence_dir = home / "raphael"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload)
    targets = [evidence_dir / "release_readiness.json"]
    normalized_profile = str(payload.get("profile") or profile).strip().lower()
    if normalized_profile in {"llm", "media"}:
        targets.insert(0, evidence_dir / f"release_readiness.{normalized_profile}.json")
    for target in targets:
        target.write_text(text, encoding="utf-8")


def _write_raw_readiness_evidence(
    home,
    payload,
    *,
    profile=None,
    include_verdict=True,
):
    evidence_dir = home / "raphael"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if include_verdict and isinstance(payload, dict):
        _write_release_docs_audit_readiness_sources(home, payload)
        payload = _payload_with_readiness_verdict(payload, profile=profile)
    text = json.dumps(payload)
    targets = [evidence_dir / "release_readiness.json"]
    normalized_profile = str(profile or payload.get("profile") or "").strip().lower()
    if normalized_profile in {"llm", "media"}:
        targets.insert(0, evidence_dir / f"release_readiness.{normalized_profile}.json")
    for target in targets:
        target.write_text(text, encoding="utf-8")


def _payload_with_readiness_verdict(payload, *, profile=None):
    verdict_fields = {
        "public_release_ready",
        "release_state",
        "blocking_reasons",
        "blocking_layers",
        "readiness_next_action",
        "readiness_blocking_actions",
    }
    if verdict_fields & set(payload):
        return payload
    from hermes_cli import raphael_cmd

    payload = dict(payload)
    readiness_profile = raphael_cmd._normalize_readiness_profile(
        str(payload.get("profile") or profile or "media")
    )
    evidence = raphael_cmd._read_release_readiness_evidence_payload(
        readiness_profile,
        payload,
        require_verdict=False,
    )
    readiness = raphael_cmd._raphael_release_readiness_from_evidence(
        readiness_profile,
        lifecycle=raphael_cmd.raphael_lifecycle_status(),
        evidence=evidence,
    )
    payload.update(raphael_cmd._release_readiness_verdict_payload(readiness))
    return payload


def _write_llm_smoke_log(
    home,
    session_id="20260701_131600_93f518",
    *,
    tool_turns=0,
    model="gpt-5.5",
    provider="openai-codex",
    timestamp=None,
    include_followup=True,
):
    log_dir = home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logged_at = timestamp or datetime.now(timezone.utc)
    timestamp_text = logged_at.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    followup_time = logged_at + timedelta(seconds=12)
    followup_timestamp_text = followup_time.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    initial_context_line = (
        f"{timestamp_text} INFO "
        f"[{session_id}] agent.turn_context: conversation turn: "
        f"session={session_id} model={model} provider={provider} "
        "platform=cli history=0 msg='拉斐爾，請接管 LLM-only 任務'"
    )
    log_line = (
        f"{timestamp_text} INFO "
        f"[{session_id}] agent.conversation_loop: Turn ended: "
        f"reason=text_response(finish_reason=stop) model={model} "
        f"api_calls=1/3 budget=1/3 tool_turns={tool_turns} "
        f"last_msg_role=assistant response_len=713 session={session_id}"
    )
    lines = [initial_context_line, log_line]
    if include_followup:
        lines.extend(
            [
                (
                    f"{followup_timestamp_text} INFO "
                    f"[{session_id}] agent.turn_context: conversation turn: "
                    f"session={session_id} model={model} provider={provider} "
                    "platform=cli history=2 msg='同一個任務，改成先補證據'"
                ),
                (
                    f"{followup_timestamp_text} INFO "
                    f"[{session_id}] agent.conversation_loop: Turn ended: "
                    f"reason=text_response(finish_reason=stop) model={model} "
                    f"api_calls=1/3 budget=1/3 tool_turns={tool_turns} "
                    f"last_msg_role=assistant response_len=206 session={session_id}"
                ),
            ]
        )
    (log_dir / "agent.log").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return log_dir / "agent.log", log_line


def _write_llm_smoke_transcript(home, session_id="20260701_131600_93f518"):
    report_dir = home / "raphael" / "release_quality"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"llm-smoke-{session_id}.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_llm_smoke_transcript",
                "generated_at": _fresh_generated_at(),
                "session_id": session_id,
                "model": "gpt-5.5",
                "model_provider": "openai-codex",
                "command": "rtk hermes chat -Q --max-turns 3",
                "user_message": (
                    "拉斐爾？請用「狀態 / 風險 / 下一步」回答。"
                    "不要呼叫工具，不要產圖，只測試 LLM-only Raphael summon。"
                ),
                "final_response": (
                    "狀態：Raphael 已待命。\n"
                    "風險：目前只是 LLM-only smoke。\n"
                    "下一步：等待任務目標。"
                ),
                "followup_user_message": "同一個任務，改成先補證據，不要宣稱完成。",
                "followup_response": (
                    "狀態：沿用同一個 Raphael 任務。\n"
                    "風險：仍缺 runtime smoke 證據。\n"
                    "下一步：先補證據再更新完成狀態。"
                ),
                "tool_call_count": 0,
                "no_tool_calls": True,
                "summon_sections_verified": True,
                "full_body_preserved": True,
                "no_visual_failure_trace": True,
                "mission_followup_verified": True,
                "same_mission_continuity_verified": True,
            }
        ),
        encoding="utf-8",
    )
    return report_path


def _write_single_turn_llm_smoke_transcript(
    home,
    session_id="20260701_131600_93f518",
):
    report_dir = home / "raphael" / "release_quality"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"llm-smoke-single-turn-{session_id}.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_llm_smoke_transcript",
                "generated_at": _fresh_generated_at(),
                "session_id": session_id,
                "model": "gpt-5.5",
                "model_provider": "openai-codex",
                "command": "rtk hermes chat -Q --max-turns 3",
                "user_message": "Raphael, reply with status, risk, next step.",
                "final_response": (
                    "狀態：Raphael 已待命。\n"
                    "風險：目前只是 single-turn smoke。\n"
                    "下一步：等待任務目標。"
                ),
                "tool_call_count": 0,
                "no_tool_calls": True,
                "summon_sections_verified": True,
                "full_body_preserved": True,
                "no_visual_failure_trace": True,
            }
        ),
        encoding="utf-8",
    )
    return report_path


def _trusted_llm_smoke_check(home, session_id="20260701_131600_93f518"):
    log_path, log_line = _write_llm_smoke_log(home, session_id=session_id)
    transcript_path = _write_llm_smoke_transcript(home, session_id=session_id)
    check = _llm_smoke_check(session_id)
    check["source_log_path"] = str(log_path)
    check["log_line"] = log_line
    check["source_transcript_path"] = str(transcript_path)
    return check


def _llm_smoke_check(session_id="20260701_131600_93f518"):
    return {
        "status": "pass",
        "evidence": "LLM-only Raphael invocation and text-only visual route smoke passed",
        "command": "rtk hermes chat",
        "run_id": "llm-smoke-1",
        "session_id": session_id,
        "tool_call_count": 0,
        "no_tool_calls": True,
        "summon_sections_verified": True,
        "full_body_preserved": True,
        "no_visual_failure_trace": True,
        "log_verified": True,
        "source_log_path": "/tmp/hermes-agent.log",
        "log_line": (
            "Turn ended: reason=text_response(finish_reason=stop) "
            f"model=gpt-5.5 tool_turns=0 session={session_id}"
        ),
        "model": "gpt-5.5",
        "model_provider": "openai-codex",
    }


def _wow_experience_check():
    return {
        "status": "pass",
        "evidence": "deterministic Raphael wow score passed",
        "command": "hermes raphael demo",
        "run_id": "wow-1",
        "score": 10,
        "threshold": 8,
        "signals": {
            "summon_appraisal": True,
            "standby_summon": True,
            "mission_followup": True,
            "proof_gate": True,
            "evolution_feedback": True,
            "lifecycle_reversible": True,
            "demo_under_one_minute": True,
            "clean_output": True,
        },
        "missing": [],
        "user_simulation_cases": _wow_user_simulation_cases(),
    }


def _wow_user_simulation_cases():
    return [
        {
            "case": "standby_summon",
            "user_prompt": "拉斐爾？",
            "expected_visible_behavior": "待命並請使用者給任務目標",
            "critical_assertions": [
                "standby_state_visible",
                "asks_for_mission_target",
            ],
            "status": "pass",
            "visual_quota_used": False,
            "evidence": "standalone summon renders standby state",
            "next_action": "ask for the mission target before planning",
            "proof_layer": "runtime_smoke",
        },
        {
            "case": "vague_takeover_preserves_mission",
            "user_prompt": "拉斐爾，接管這個任務",
            "expected_visible_behavior": "延續既有任務，不重新開新目標",
            "critical_assertions": [
                "mission_id_preserved",
                "goal_preserved",
            ],
            "status": "pass",
            "visual_quota_used": False,
            "evidence": "vague takeover preserves mission continuity",
            "next_action": "continue the preserved mission instead of starting over",
            "proof_layer": "goal_state_contract",
        },
        {
            "case": "runtime_log_attachment_routes_tool_task",
            "user_prompt": "拉斐爾，接管這個 runtime bug，檢查這個 log",
            "expected_visible_behavior": "把 log 視為工具任務證據，不轉成視覺生成",
            "critical_assertions": [
                "routes_tool_task",
                "no_visual_handoff",
            ],
            "status": "pass",
            "visual_quota_used": False,
            "evidence": "runtime log attachment routes to tool task",
            "next_action": "plan, execute, and verify the runtime repair",
            "proof_layer": "mode_router_contract",
        },
        {
            "case": "blank_screen_repair_routes_tool_task",
            "user_prompt": "拉斐爾，接管這個任務：畫面空白，請修復",
            "expected_visible_behavior": "把畫面空白視為 runtime/UI repair，不產圖",
            "critical_assertions": [
                "classified_runtime_repair",
                "requires_runtime_evidence",
            ],
            "status": "pass",
            "visual_quota_used": False,
            "evidence": "blank screen repair routes to runtime task",
            "next_action": "inspect runtime/UI evidence before claiming repair",
            "proof_layer": "intent_appraisal_contract",
        },
        {
            "case": "prompt_builder_question_not_prompt_disclosure",
            "user_prompt": "檢查 agent/prompt_builder.py 使用哪個 prompt",
            "expected_visible_behavior": "回答 repo code 問題，不當成 prompt disclosure",
            "critical_assertions": [
                "not_prompt_disclosure",
                "uses_repository_context",
            ],
            "status": "pass",
            "visual_quota_used": False,
            "evidence": "prompt_builder code question is not prompt disclosure",
            "next_action": "answer from repository code without hidden prompt disclosure",
            "proof_layer": "prompt_safety_contract",
        },
        {
            "case": "negated_media_summon_stays_text_only",
            "user_prompt": "拉斐爾？不要呼叫工具，不要產圖，只測試 LLM-only Raphael summon。",
            "expected_visible_behavior": "用文字回覆狀態、目標、下一步，不用工具或 media",
            "critical_assertions": [
                "no_tool_call",
                "no_media_generation",
                "text_only_status_goal_next_step",
            ],
            "status": "pass",
            "visual_quota_used": False,
            "evidence": "negated media summon stays text-only",
            "next_action": "reply with status, current goal, and next step without media",
            "proof_layer": "quota_guard_contract",
        },
    ]


def _release_docs_audit_check(
    *,
    status="pass",
    violations=None,
    source_readiness_paths=None,
    home=None,
):
    if source_readiness_paths is None:
        if home is not None:
            source_readiness_paths = _release_docs_audit_readiness_source_paths(home)
        else:
            source_readiness_paths = [
                str(Path.home() / ".hermes" / "raphael" / "release_readiness.llm.json"),
                str(Path.home() / ".hermes" / "raphael" / "release_readiness.media.json"),
            ]
    return {
        "status": status,
        "evidence": "release docs audit passed",
        "command": "scripts/raphael_release_docs_audit.py",
        "run_id": "release-docs-audit-1",
        "violations": list(violations or []),
        "source_readiness_paths": list(source_readiness_paths),
    }


def _release_docs_audit_readiness_source_paths(home):
    evidence_dir = home / "raphael" / "release_quality"
    return [
        str(evidence_dir / "docs-audit-readiness.llm.json"),
        str(evidence_dir / "docs-audit-readiness.media.json"),
    ]


def _write_release_docs_audit_readiness_sources(home, payload):
    if not isinstance(payload, dict):
        return
    checks = payload.get("checks")
    if not isinstance(checks, dict) or "release_docs_audit" not in checks:
        return
    evidence_dir = home / "raphael" / "release_quality"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "docs-audit-readiness.llm.json").write_text(
        json.dumps(_release_docs_audit_llm_source()),
        encoding="utf-8",
    )
    (evidence_dir / "docs-audit-readiness.media.json").write_text(
        json.dumps(_release_docs_audit_media_source()),
        encoding="utf-8",
    )


def _release_docs_audit_llm_source():
    return {
        "schema_version": 1,
        "profile": "llm",
        "public_claim_scope": "llm_only",
        "checks": {
            "package_install_smoke": {
                "run_id": "package-install-20260701-fresh-home-fail-closed-v1",
            },
            "hostile_review": {
                "run_id": "hostile-review-20260701-fresh-home-fail-closed-v1",
            },
            "llm_live_smoke": {"session_id": "20260701_131600_93f518"},
            "non_visual_regression": {
                "run_id": "non-visual-regression-20260701-openai-quality-attachment-gate",
                "passed_count": 1529,
            },
        },
    }


def _release_docs_audit_media_source():
    return {
        "schema_version": 1,
        "profile": "media",
        "public_claim_scope": "media_openai_image_only",
        "media_release_scope": "media_openai_image_only",
        "remaining_media_gaps": ["xai_grok_generation", "video_generation"],
        "checks": {
            "package_install_smoke": {
                "run_id": "package-install-20260701-fresh-home-fail-closed-v1",
            },
            "hostile_review": {
                "run_id": "hostile-review-20260701-fresh-home-fail-closed-v1",
            },
            "llm_live_smoke": {"session_id": "20260701_163247_d9b87d"},
            "non_visual_regression": {
                "run_id": "non-visual-regression-20260701-wow-user-simulation-proof-v1",
                "passed_count": 1541,
            },
        },
    }


def _completion_audit_check(*, status="pass", scoped_release_ready=True):
    return {
        "status": status,
        "evidence": "completion audit verified scoped release boundary",
        "command": "scripts/raphael_completion_audit.py --target scoped",
        "run_id": "completion-audit-1",
        "audit_status": "partial",
        "scoped_release_ready": scoped_release_ready,
        "ultimate_ready": False,
        "blockers": [
            "ultimate_claim:sage_king_denied",
            "ultimate_claim:wow_denied",
            "ultimate_claim:big_evolution_denied",
            "full_media:xai_grok_generation_missing",
            "full_media:video_generation_missing",
            "full_media:release_not_ready",
        ],
    }


def _release_slice_manifest_check(
    *,
    status="pass",
    manifest_status="reviewable",
    review_strategy="split_required",
):
    return {
        "status": status,
        "evidence": "release slice manifest verified reviewer handoff",
        "command": "scripts/raphael_release_slice_manifest.py --from-git-status",
        "run_id": "release-slice-manifest-1",
        "manifest_status": manifest_status,
        "review_strategy": review_strategy,
        "allowed_public_claims": ["llm_only"],
        "blocked_public_claims": [
            "sage_king",
            "wow",
            "big_evolution",
            "full_media",
            "xai_grok_generation",
            "video_generation",
        ],
        "counts": {
            "llm_slice_paths": 68,
            "deferred_media_paths": 45,
            "unclassified_paths": 0,
            "content_violations": 0,
        },
        "slices": [
            {"id": "llm_scoped_release", "release_ready": True},
            {"id": "deferred_media", "release_ready": False},
        ],
        "blockers": [],
    }


def _install_disable_uninstall_check():
    return {
        "status": "pass",
        "evidence": "lifecycle smoke passed through API and public CLI in temp HERMES_HOME",
        "command": "hermes raphael install && hermes raphael status && hermes raphael disable && hermes raphael status && hermes raphael enable && hermes raphael status && hermes raphael uninstall && hermes raphael status",
        "run_id": "lifecycle-1",
        "disabled_slash_commands_available": True,
        "disabled_status_guides_enable": True,
        "cli_smoke_verified": True,
        "cli_entrypoint": "hermes",
        "cli_entrypoint_found": True,
        "cli_entrypoint_path": "/tmp/hermes",
        "cli_install_enabled": True,
        "cli_disable_keeps_plugin": True,
        "cli_status_after_disable_guides_enable": True,
        "cli_enable_restores_mode": True,
        "cli_uninstall_disables_plugin": True,
        "cli_status_after_uninstall_guides_install": True,
    }


def _llm_release_ready_checks(home, *, release_docs_audit=True):
    hostile_report = _write_hostile_review_report(home)
    regression_report = _write_non_visual_regression_report(home)
    package_report = _package_install_smoke_report(home)
    checks = {
        "install_disable_uninstall": _install_disable_uninstall_check(),
        "package_install_smoke": _package_install_smoke_check(package_report),
        "slash_command_surface": _slash_command_surface_check(),
        "mode_router_contract": _mode_router_contract_check(),
        "goal_state_contract": _goal_state_contract_check(),
        "evolution_contract": _evolution_contract_check(),
        "llm_live_smoke": _trusted_llm_smoke_check(home),
        "wow_experience": _wow_experience_check(),
        "hostile_review": _hostile_review_check(hostile_report),
        "non_visual_regression": _non_visual_regression_check(regression_report),
        "completion_audit": _completion_audit_check(),
        "release_slice_manifest": _release_slice_manifest_check(),
    }
    if release_docs_audit is not False:
        checks["release_docs_audit"] = (
            release_docs_audit
            if isinstance(release_docs_audit, dict)
            else _release_docs_audit_check(home=home)
        )
    return checks


_MODE_ROUTER_REQUIRED_CASES = (
    "general_conversation",
    "tool_task",
    "visual_agent_generation",
    "visual_agent_edit",
    "prompt_disclosure",
    "needs_clarification",
)
_MODE_ROUTER_DEFAULT_CASE_FIELDS = {
    "visual_agent_llm_provider": None,
    "visual_agent_llm_model": None,
    "visual_media_provider": None,
    "visual_media_model": None,
    "reference_resolution": "not_applicable",
    "active_artifact_continuity": False,
}
_MODE_ROUTER_CASE_FIXTURES = {
    "general_conversation": {
        **_MODE_ROUTER_DEFAULT_CASE_FIELDS,
        "mode": "general_conversation",
        "target_artifact": "answer",
        "phase": "answer",
        "next_action": "answer_directly",
        "handoff_tool": None,
        "bypass_base_llm": False,
    },
    "tool_task": {
        **_MODE_ROUTER_DEFAULT_CASE_FIELDS,
        "mode": "tool_task",
        "target_artifact": "runtime_or_repo_state",
        "phase": "plan_execute_verify",
        "next_action": "plan_execute_verify",
        "handoff_tool": None,
        "bypass_base_llm": False,
    },
    "visual_agent_generation": {
        **_MODE_ROUTER_DEFAULT_CASE_FIELDS,
        "mode": "visual_agent_generation",
        "target_artifact": "new_visual_package",
        "phase": "route_and_handoff",
        "next_action": "call_visual_agent_generate",
        "handoff_tool": "visual_agent_generate",
        "bypass_base_llm": True,
        "visual_agent_llm_provider": "xai-oauth",
        "visual_agent_llm_model": "grok-4.3",
        "visual_media_provider": "xai",
        "visual_media_model": "grok-imagine-image-quality",
        "reference_resolution": "not_applicable",
    },
    "visual_agent_edit": {
        **_MODE_ROUTER_DEFAULT_CASE_FIELDS,
        "mode": "visual_agent_edit",
        "target_artifact": "current_visual_artifact",
        "phase": "route_and_handoff",
        "next_action": "call_visual_agent_generate",
        "handoff_tool": "visual_agent_generate",
        "bypass_base_llm": True,
        "visual_agent_llm_provider": "xai-oauth",
        "visual_agent_llm_model": "grok-4.3",
        "visual_media_provider": "xai",
        "visual_media_model": "grok-imagine-image-quality",
        "active_artifact_continuity": True,
    },
    "prompt_disclosure": {
        **_MODE_ROUTER_DEFAULT_CASE_FIELDS,
        "mode": "prompt_disclosure",
        "target_artifact": "latest_visual_prompt_trace",
        "phase": "prompt_trace_lookup",
        "next_action": "answer_from_latest_visual_prompt_trace",
        "handoff_tool": None,
        "bypass_base_llm": False,
    },
    "needs_clarification": {
        **_MODE_ROUTER_DEFAULT_CASE_FIELDS,
        "mode": "needs_clarification",
        "target_artifact": "pending_visual_artifact",
        "phase": "clarify_reference_mapping",
        "next_action": "ask_precise_clarification",
        "handoff_tool": None,
        "bypass_base_llm": False,
        "reference_resolution": "clarify_missing_reference",
    },
}


def _mode_router_contract_check(cases=None):
    case_names = tuple(cases or _MODE_ROUTER_REQUIRED_CASES)
    return {
        "status": "pass",
        "evidence": "deterministic Raphael mode router contract passed",
        "command": "deterministic Raphael control decision mode-router contract",
        "run_id": "mode-router-1",
        "route_provenance": "deterministic_raphael_control_decision",
        "cases": [
            {
                "case": case_name,
                "status": "pass",
                "mismatches": [],
                **_MODE_ROUTER_CASE_FIXTURES[case_name],
            }
            for case_name in case_names
        ],
        "mismatches": [],
    }


_GOAL_STATE_REQUIRED_CASES = (
    "new_tool_mission",
    "followup_preserves_mission",
    "casual_summon_preserves_mission",
    "visual_edit_targets_current_artifact",
    "missing_reference_blocks",
)
_GOAL_STATE_CASE_FIXTURES = {
    "new_tool_mission": {
        "phase": "strategy_selected",
        "next_action": "plan_execute_verify",
        "proof_status": "pending",
        "mission_continuity": False,
        "casual_turn_preserved": None,
        "active_artifact_id": None,
        "blockers": [],
        "required_proofs": ["focused_tests", "runtime_smoke_when_live_wiring"],
    },
    "followup_preserves_mission": {
        "phase": "strategy_selected",
        "next_action": "plan_execute_verify",
        "proof_status": "pending",
        "mission_continuity": True,
        "casual_turn_preserved": None,
        "active_artifact_id": None,
        "blockers": [],
        "required_proofs": ["focused_tests", "runtime_smoke_when_live_wiring"],
    },
    "casual_summon_preserves_mission": {
        "phase": "strategy_selected",
        "next_action": "plan_execute_verify",
        "proof_status": "pending",
        "mission_continuity": True,
        "casual_turn_preserved": True,
        "active_artifact_id": None,
        "blockers": [],
        "required_proofs": ["focused_tests", "runtime_smoke_when_live_wiring"],
    },
    "visual_edit_targets_current_artifact": {
        "phase": "strategy_selected",
        "next_action": "multi_pass_review_and_repair",
        "proof_status": "pending",
        "mission_continuity": False,
        "casual_turn_preserved": None,
        "active_artifact_id": "artifact-current",
        "blockers": [],
        "required_proofs": ["artifact_continuity", "quality_gate_passed", "hostile_review"],
    },
    "missing_reference_blocks": {
        "phase": "blocked",
        "next_action": "ask_precise_clarification",
        "proof_status": "blocked",
        "mission_continuity": False,
        "casual_turn_preserved": None,
        "active_artifact_id": None,
        "blockers": ["missing_ref3"],
        "required_proofs": ["reference_mapping_confirmed"],
    },
}


def _goal_state_contract_check(cases=None):
    case_names = tuple(cases or _GOAL_STATE_REQUIRED_CASES)
    return {
        "status": "pass",
        "evidence": "deterministic Raphael goal-state contract passed",
        "command": "deterministic Raphael mission goal-state contract",
        "run_id": "goal-state-1",
        "state_provenance": "deterministic_raphael_goal_state_manager",
        "temp_home": "isolated",
        "cases": [
            {
                "case": case_name,
                "status": "pass",
                "mismatches": [],
                **_GOAL_STATE_CASE_FIXTURES[case_name],
            }
            for case_name in case_names
        ],
        "mismatches": [],
    }


_EVOLUTION_REQUIRED_CASES = (
    "audit_only_user_correction",
    "active_writes_require_explicit_enable",
    "high_risk_mutation_proposal_only",
    "visual_failure_learning_signal",
    "privacy_sanitized_evolution_record",
    "repeated_failure_self_correction_priority",
)
_EVOLUTION_CASE_FIXTURES = {
    "audit_only_user_correction": {
        "mode": "proposal_only",
        "should_review": False,
        "review_skills": False,
        "review_memory": False,
        "proposal_only": True,
        "reason_codes": ["user_correction"],
        "affected_capability": "raphael.skill_evolution",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "active_writes_require_explicit_enable": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": True,
        "proposal_only": False,
        "reason_codes": ["user_correction"],
        "affected_capability": "raphael.skill_evolution",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "high_risk_mutation_proposal_only": {
        "mode": "proposal_only",
        "should_review": False,
        "review_skills": False,
        "review_memory": False,
        "proposal_only": True,
        "reason_codes": ["high_risk_mutation"],
        "affected_capability": "raphael.approval_policy",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "visual_failure_learning_signal": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": False,
        "proposal_only": False,
        "reason_codes": ["visual_or_provider_failure"],
        "affected_capability": "visual.agent_mode",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
    },
    "privacy_sanitized_evolution_record": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": True,
        "proposal_only": False,
        "reason_codes": ["user_correction"],
        "affected_capability": "raphael.skill_evolution",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": True,
    },
    "repeated_failure_self_correction_priority": {
        "mode": "active_evolution",
        "should_review": True,
        "review_skills": True,
        "review_memory": False,
        "proposal_only": False,
        "reason_codes": ["failed_proof"],
        "affected_capability": "raphael.proof_gate",
        "metadata_has_promotion_gate": True,
        "metadata_has_rollback_condition": True,
        "record_private_data_redacted": None,
        "self_correction_prioritized": True,
        "self_correction_pattern_count": 2,
        "action_proposal_created": True,
        "action_proposal_requires_approval": True,
        "action_proposal_rollout_plan_verified": True,
        "action_proposal_rollout_status": "pending_approval",
        "action_proposal_rollout_verification_commands": [
            "pytest tests/agent/test_raphael_evolution.py -q",
            "hermes raphael readiness --readiness-profile llm --check",
        ],
        "action_proposal_rollout_promotion_gate": (
            "focused tests plus runtime, replay, or LLM smoke"
        ),
        "action_proposal_rollout_rollback_condition": (
            "next evidence or user feedback shows worse behavior"
        ),
    },
}


def _evolution_contract_check(cases=None):
    case_names = tuple(cases or _EVOLUTION_REQUIRED_CASES)
    return {
        "status": "pass",
        "evidence": "deterministic Raphael evolution contract passed",
        "command": "deterministic Raphael auditable evolution contract",
        "run_id": "evolution-1",
        "evolution_provenance": "deterministic_raphael_evolution_manager",
        "temp_home": "isolated",
        "cases": [
            {
                "case": case_name,
                "status": "pass",
                "mismatches": [],
                **_EVOLUTION_CASE_FIXTURES[case_name],
            }
            for case_name in case_names
        ],
        "mismatches": [],
    }


def _write_hostile_review_report(home, run_id="hostile-review-20260701-fresh-home-fail-closed-v1"):
    report_dir = home / "raphael" / "release_quality"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{run_id}.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "raphael_hostile_review",
                "generated_at": _fresh_generated_at(),
                "command": "subagent hostile review",
                "run_id": run_id,
                "reviewer": "subagent",
                "verdict": "pass",
                "blockers": 0,
                "coverage": [
                    "setup_doctor_no_scaffold",
                    "lifecycle_install_disable_uninstall",
                    "llm_live_smoke_followup",
                    "llm_summon_ux_hostile_review",
                    "adversarial_prompt_matrix",
                    "sage_king_claim_verdict",
                    "wow_claim_verdict",
                    "big_evolution_claim_verdict",
                    "release_gate_evidence_provenance",
                    "hostile_review_independence",
                    "readiness_next_action",
                    "slash_command_surface_gate",
                    "non_visual_regression",
                    "mode_router_contract_gate",
                    "goal_state_contract_gate",
                    "evolution_contract_gate",
                    "visual_preflight_provenance_gate",
                    "visual_live_e2e_gate",
                    "independent_visual_quality_review_gate",
                ],
                "scope": [
                    "setup doctor no-scaffold behavior",
                    "lifecycle install/enable/disable/uninstall",
                    "LLM smoke follow-up continuity",
                    "release evidence provenance",
                    "visual E2E and independent quality-review gates",
                ],
                "llm_ux_claims": {
                    "public_claims_reviewed": True,
                    "sage_king_claim_allowed": False,
                    "wow_claim_allowed": False,
                    "big_evolution_claim_allowed": False,
                    "adversarial_scenarios": [
                        "constrained_summon",
                        "same_mission_followup",
                        "negated_media_request",
                        "public_wording_review",
                        "video_claim_boundary",
                        "openai_image_only_claim_boundary",
                    ],
                    "multi_turn_transcript_ids": ["20260701_131600_93f518"],
                },
                "evidence": [
                    "focused Raphael CLI regression passed",
                    "subagent hostile review found no release blockers",
                ],
                "residual_risk": "Media public release still requires visual live E2E.",
            }
        ),
        encoding="utf-8",
    )
    return report_path


def _write_non_visual_regression_report(
    home,
    run_id="non-visual-regression-20260701-openai-quality-attachment-gate",
):
    report_dir = home / "raphael" / "release_quality"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{run_id}.json"
    report = {
        "schema_version": 1,
        "kind": "raphael_non_visual_regression",
        "generated_at": _fresh_generated_at(),
        "command": (
            "pytest tests/agent/test_raphael_*.py "
            "tests/hermes_cli/test_raphael_*.py"
        ),
        "run_id": run_id,
        "exit_code": 0,
        "passed_count": 1529,
        "failed_count": 0,
        "suite_coverage": [
            "raphael_agent",
            "raphael_cli",
            "raphael_plugin",
            "visual_handoff",
            "visual_agent_tool",
            "visual_package_tool",
            "gateway_delivery",
        ],
        "visual_quota_used": False,
    }
    report["report_digest"] = _json_digest(report)
    report_path.write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    return report_path


def _hostile_review_check(source_report_path=None):
    return {
        "status": "pass",
        "evidence": "hostile review found no release blockers",
        "command": "subagent hostile review",
        "run_id": "hostile-review-20260701-fresh-home-fail-closed-v1",
        "reviewer": "subagent",
        "verdict": "pass",
        "blockers": 0,
        "coverage": [
            "setup_doctor_no_scaffold",
            "lifecycle_install_disable_uninstall",
            "llm_live_smoke_followup",
            "llm_summon_ux_hostile_review",
            "adversarial_prompt_matrix",
            "sage_king_claim_verdict",
            "wow_claim_verdict",
            "big_evolution_claim_verdict",
            "release_gate_evidence_provenance",
            "hostile_review_independence",
            "readiness_next_action",
            "slash_command_surface_gate",
            "non_visual_regression",
            "mode_router_contract_gate",
            "goal_state_contract_gate",
            "evolution_contract_gate",
            "visual_preflight_provenance_gate",
            "visual_live_e2e_gate",
            "independent_visual_quality_review_gate",
        ],
        "review_scope": [
            "setup doctor no-scaffold behavior",
            "lifecycle install/enable/disable/uninstall",
            "LLM smoke follow-up continuity",
            "release evidence provenance",
            "visual E2E and independent quality-review gates",
        ],
        "llm_ux_claims": {
            "public_claims_reviewed": True,
            "claim_verdicts_present": True,
            "sage_king_claim_allowed": False,
            "wow_claim_allowed": False,
            "big_evolution_claim_allowed": False,
            "adversarial_scenarios": [
                "constrained_summon",
                "same_mission_followup",
                "negated_media_request",
                "public_wording_review",
                "video_claim_boundary",
                "openai_image_only_claim_boundary",
            ],
            "multi_turn_transcript_ids": ["20260701_131600_93f518"],
        },
        "review_evidence": [
            "focused Raphael CLI regression passed",
            "subagent hostile review found no release blockers",
        ],
        "residual_risk": "Media public release still requires visual live E2E.",
        **({"source_report_path": str(source_report_path)} if source_report_path else {}),
    }


def _non_visual_regression_check(source_report_path=None):
    digest_fields = {}
    if source_report_path:
        try:
            report = json.loads(Path(source_report_path).read_text(encoding="utf-8"))
            digest_fields = {
                "report_digest": str(report.get("report_digest") or ""),
                "report_digest_verified": True,
            }
        except Exception:
            digest_fields = {}
    return {
        "status": "pass",
        "evidence": "non-visual Raphael regression suite passed without media quota",
        "command": "pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py",
        "run_id": "non-visual-regression-20260701-openai-quality-attachment-gate",
        "exit_code": 0,
        "passed_count": 1529,
        "failed_count": 0,
        "suite_coverage": [
            "raphael_agent",
            "raphael_cli",
            "raphael_plugin",
            "visual_handoff",
            "visual_agent_tool",
            "visual_package_tool",
            "gateway_delivery",
        ],
        "visual_quota_used": False,
        **digest_fields,
        **({"source_report_path": str(source_report_path)} if source_report_path else {}),
    }


def _slash_command_surface_check():
    return {
        "status": "pass",
        "evidence": "Raphael slash command surface rendered in isolated HERMES_HOME",
        "command": "discover raphael plugin slash commands and render status/skills",
        "run_id": "slash-surface-1",
        "commands": [
            "raphael-status",
            "raphael-skills",
            "raphael-doctor",
            "raphael-enable",
            "raphael-disable",
        ],
        "missing_commands": [],
        "status_brief_verified": True,
        "skills_brief_verified": True,
        "gateway_known": True,
        "telegram_commands": [
            "raphael_status",
            "raphael_skills",
            "raphael_doctor",
            "raphael_enable",
            "raphael_disable",
        ],
        "temp_home": "isolated",
    }


def _release_quality_gate_kwargs(home):
    transcript_report = _write_llm_smoke_transcript(home)
    package_report = _package_install_smoke_report(home)
    hostile_report = _write_hostile_review_report(home)
    regression_report = _write_non_visual_regression_report(home)
    llm_check = _llm_smoke_check()
    log_path = home / "logs" / "agent.log"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8")
        log_line = next(
            (
                line
                for line in log_text.splitlines()
                if "Turn ended:" in line
                and "session=20260701_131600_93f518" in line
            ),
            "",
        )
        llm_check["source_log_path"] = str(log_path)
        if log_line:
            llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_report)
    _write_raw_readiness_evidence(
        home,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": _install_disable_uninstall_check(),
                "package_install_smoke": _package_install_smoke_check(package_report),
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "goal_state_contract": _goal_state_contract_check(),
                "evolution_contract": _evolution_contract_check(),
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(regression_report),
                "release_docs_audit": _release_docs_audit_check(home=home),
                "completion_audit": _completion_audit_check(),
                "release_slice_manifest": _release_slice_manifest_check(),
            },
        },
        profile="llm",
    )
    return {
        "llm_transcript_report_path": str(transcript_report),
        "package_install_report_path": str(package_report),
        "hostile_review_command": "subagent hostile review",
        "hostile_review_run_id": "hostile-review-20260701-fresh-home-fail-closed-v1",
        "hostile_review_verdict": "pass",
        "hostile_review_blockers": 0,
        "hostile_review_report_path": str(hostile_report),
        "non_visual_regression_command": (
            "pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py"
        ),
        "non_visual_regression_run_id": "non-visual-regression-20260701-openai-quality-attachment-gate",
        "non_visual_regression_passed_count": 1529,
        "non_visual_regression_visual_quota_used": False,
        "non_visual_regression_report_path": str(regression_report),
    }


def test_raphael_enable_installs_plugin_and_turns_on_default_mode(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import enable_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": [], "disabled": ["raphael"]},
            "raphael": {"enabled": False, "default_conversation_mode_enabled": False},
        },
    )

    result = enable_raphael_mode()
    config = _read_config(tmp_path)

    assert result.enabled is True
    assert result.plugin_enabled is True
    assert result.default_conversation_mode_enabled is True
    assert "raphael" in config["plugins"]["enabled"]
    assert "raphael" not in config["plugins"]["disabled"]
    assert config["raphael"]["enabled"] is True
    assert config["raphael"]["default_conversation_mode_enabled"] is True
    assert config["raphael"]["skill_writes_enabled"] is False
    assert config["raphael"]["memory_writes_enabled"] is False
    assert config["raphael"]["mode"] == "sage_king"


def test_raphael_enable_message_guides_public_install_verification(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import enable_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, {"plugins": {"enabled": [], "disabled": []}})

    result = enable_raphael_mode()

    assert "audit-only" in result.message
    assert "`hermes raphael doctor`" in result.message
    assert "`hermes raphael readiness --readiness-profile llm`" in result.message
    assert "`/raphael-status`" in result.message
    assert "durable skill/memory writes remain off" in result.message


def test_raphael_enable_evolve_message_flags_durable_writes(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import enable_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, {"plugins": {"enabled": [], "disabled": []}})

    result = enable_raphael_mode(evolve=True)

    assert "durable skill/memory writes are enabled" in result.message
    assert "audit-only" not in result.message
    assert "`hermes raphael doctor`" in result.message
    assert "`hermes raphael readiness --readiness-profile llm`" in result.message


def test_raphael_disable_turns_off_mode_but_keeps_plugin_available(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import disable_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "skill_writes_enabled": True,
                "memory_writes_enabled": True,
                "evolution": {
                    "enabled": True,
                    "skill_review_enabled": True,
                    "memory_review_enabled": True,
                },
            },
        },
    )

    result = disable_raphael_mode()
    config = _read_config(tmp_path)

    assert result.enabled is False
    assert result.plugin_enabled is True
    assert result.default_conversation_mode_enabled is False
    assert "raphael" in config["plugins"]["enabled"]
    assert config["raphael"]["enabled"] is False
    assert config["raphael"]["default_conversation_mode_enabled"] is False
    assert config["raphael"]["skill_writes_enabled"] is False
    assert config["raphael"]["memory_writes_enabled"] is False
    assert config["raphael"]["evolution"]["enabled"] is False


def test_raphael_disable_after_uninstall_keeps_plugin_disabled(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import disable_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": [], "disabled": ["raphael"]},
            "raphael": {"enabled": False, "default_conversation_mode_enabled": False},
        },
    )

    result = disable_raphael_mode()
    config = _read_config(tmp_path)

    assert result.enabled is False
    assert result.plugin_enabled is False
    assert "plugin remains enabled" not in result.message
    assert "plugin is disabled" in result.message
    assert "`hermes raphael install`" in result.message
    assert "`hermes raphael enable`" not in result.message
    assert "raphael" not in config["plugins"]["enabled"]
    assert "raphael" in config["plugins"]["disabled"]


def test_raphael_enable_after_disable_reactivates_mode_in_audit_only(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import disable_raphael_mode, enable_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "skill_writes_enabled": True,
                "memory_writes_enabled": True,
                "evolution": {
                    "enabled": True,
                    "skill_review_enabled": True,
                    "memory_review_enabled": True,
                },
            },
        },
    )

    disable_raphael_mode()
    result = enable_raphael_mode()
    config = _read_config(tmp_path)

    assert result.enabled is True
    assert config["raphael"]["enabled"] is True
    assert config["raphael"]["default_conversation_mode_enabled"] is True
    assert config["raphael"]["skill_writes_enabled"] is False
    assert config["raphael"]["memory_writes_enabled"] is False
    assert config["raphael"]["evolution"]["enabled"] is True
    assert config["raphael"]["evolution"]["skill_review_enabled"] is True
    assert config["raphael"]["evolution"]["memory_review_enabled"] is True


def test_raphael_enable_with_evolve_turns_on_durable_write_gates(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import enable_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, {"plugins": {"enabled": [], "disabled": []}})

    result = enable_raphael_mode(evolve=True)
    config = _read_config(tmp_path)

    assert result.enabled is True
    assert config["raphael"]["skill_writes_enabled"] is True
    assert config["raphael"]["memory_writes_enabled"] is True


def test_raphael_status_reports_lifecycle_state(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_lifecycle_status

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    before_paths = _relative_paths(tmp_path)

    status = raphael_lifecycle_status()

    assert status.enabled is True
    assert status.plugin_enabled is True
    assert status.default_conversation_mode_enabled is True
    assert "enabled" in status.message
    assert "Raphael Status" in status.message
    assert "Conversation injection: enabled" in status.message
    assert "Slash commands: available" in status.message
    assert "Evolution writes: audit-only" in status.message
    assert (
        "Public claim: enabled mode is not release evidence"
        in status.message
    )
    assert "Next action: hermes raphael doctor" in status.message
    assert (
        "LLM release check: hermes raphael readiness --readiness-profile llm"
        in status.message
    )
    assert (
        "Media release check: hermes raphael readiness --readiness-profile media"
        in status.message
    )
    assert _relative_paths(tmp_path) == before_paths


def test_raphael_status_labels_durable_evolution_as_local_override(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_lifecycle_status

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "skill_writes_enabled": True,
                "memory_writes_enabled": True,
            },
        },
    )

    status = raphael_lifecycle_status()

    assert (
        "Evolution writes: durable enabled (local override; public default is audit-only)"
        in status.message
    )


def test_raphael_status_includes_read_only_curator_health(
    monkeypatch,
    tmp_path,
):
    from hermes_cli import raphael_cmd

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        raphael_cmd,
        "collect_raphael_curator_health",
        lambda: {
            "enabled": True,
            "paused": False,
            "consolidate": False,
            "agent_created_skills": 9,
            "stale": 0,
            "archived": 0,
        },
    )
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    status = raphael_cmd.raphael_lifecycle_status()

    assert "Skill library: curator enabled" in status.message
    assert "agent-created skills: 9" in status.message
    assert "stale: 0" in status.message
    assert "consolidation: off" in status.message


def test_raphael_status_guides_install_when_enabled_but_slash_unavailable(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_lifecycle_status

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        "hermes_cli.raphael_cmd._bundled_raphael_slash_manifest_available",
        lambda: False,
    )
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    before_paths = _relative_paths(tmp_path)

    status = raphael_lifecycle_status()

    assert status.enabled is True
    assert status.plugin_enabled is True
    assert "Slash commands: unavailable" in status.message
    assert "Next action: hermes raphael install" in status.message
    assert "Next action: hermes raphael doctor" not in status.message
    assert "readiness --readiness-profile llm" not in status.message
    assert _relative_paths(tmp_path) == before_paths


def test_raphael_status_treats_disabled_plugin_as_inactive(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_lifecycle_status

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": ["raphael"]},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    status = raphael_lifecycle_status()

    assert status.enabled is False
    assert status.plugin_enabled is False
    assert status.default_conversation_mode_enabled is False
    assert "disabled" in status.message
    assert "Raphael Status" in status.message
    assert "Next action: hermes raphael install" in status.message
    assert "readiness --readiness-profile llm" not in status.message


def test_raphael_status_guides_enable_when_mode_disabled_but_plugin_available(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_lifecycle_status

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": False,
                "default_conversation_mode_enabled": False,
                "mode": "sage_king",
            },
        },
    )
    before_paths = _relative_paths(tmp_path)

    status = raphael_lifecycle_status()

    assert status.enabled is False
    assert status.plugin_enabled is True
    assert "Mode: disabled (plugin enabled, mode=sage_king)" in status.message
    assert "Slash commands: available" in status.message
    assert "Next action: hermes raphael enable" in status.message
    assert "Next action: hermes raphael install" not in status.message
    assert _relative_paths(tmp_path) == before_paths


def test_raphael_status_matches_runtime_plugin_default_without_plugins_section(
    monkeypatch, tmp_path
):
    from hermes_cli.raphael_cmd import raphael_lifecycle_status

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    status = raphael_lifecycle_status()

    assert status.enabled is False
    assert status.plugin_enabled is False
    assert status.default_conversation_mode_enabled is False


def test_raphael_doctor_reports_install_setup_ready_without_release_claim(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_setup_doctor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "sage_king",
                "skill_writes_enabled": False,
                "memory_writes_enabled": False,
            },
        },
    )
    before_paths = _relative_paths(tmp_path)

    doctor = raphael_setup_doctor()

    assert doctor.local_setup_ready is True
    assert doctor.blocking_reasons == ()
    assert "Raphael Setup Doctor" in doctor.message
    assert "Local setup ready: yes" in doctor.message
    assert "Plugin: enabled" in doctor.message
    assert "Slash commands: available" in doctor.message
    assert "Conversation injection: enabled" in doctor.message
    assert "Evolution writes: audit-only" in doctor.message
    assert (
        "Release claim: local setup ready is not public release evidence"
        in doctor.message
    )
    assert "Next action: hermes raphael readiness --readiness-profile llm" in doctor.message
    assert "Public release ready: yes" not in doctor.message
    assert _relative_paths(tmp_path) == before_paths


def test_raphael_doctor_labels_durable_evolution_as_local_override(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_setup_doctor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "sage_king",
                "skill_writes_enabled": True,
                "memory_writes_enabled": True,
            },
        },
    )

    doctor = raphael_setup_doctor()

    assert doctor.local_setup_ready is True
    assert (
        "Evolution writes: durable enabled (local override; public default is audit-only)"
        in doctor.message
    )


def test_raphael_doctor_blocks_enabled_mode_when_slash_unavailable(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_setup_doctor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        "hermes_cli.raphael_cmd._bundled_raphael_slash_manifest_available",
        lambda: False,
    )
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "sage_king",
            },
        },
    )
    before_paths = _relative_paths(tmp_path)

    doctor = raphael_setup_doctor()

    assert doctor.local_setup_ready is False
    assert doctor.blocking_reasons == ("raphael_slash_commands_unavailable",)
    assert "Mode: enabled (sage_king)" in doctor.message
    assert "Slash commands: unavailable" in doctor.message
    assert "Next action: hermes raphael install" in doctor.message
    assert "readiness --readiness-profile llm" not in doctor.message
    assert _relative_paths(tmp_path) == before_paths


def test_raphael_doctor_blocks_disabled_plugin_with_install_action(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_setup_doctor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": [], "disabled": ["raphael"]},
            "raphael": {"enabled": False, "default_conversation_mode_enabled": False},
        },
    )

    doctor = raphael_setup_doctor()

    assert doctor.local_setup_ready is False
    assert doctor.blocking_reasons == (
        "raphael_plugin_disabled",
        "raphael_mode_disabled",
        "raphael_conversation_injection_disabled",
    )
    assert "Local setup ready: no" in doctor.message
    assert "Blocking reasons: raphael_plugin_disabled, raphael_mode_disabled, raphael_conversation_injection_disabled" in doctor.message
    assert "Next action: hermes raphael install" in doctor.message
    assert "release-gate" not in doctor.message


def test_raphael_doctor_guides_enable_when_mode_disabled_but_plugin_available(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_setup_doctor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": False,
                "default_conversation_mode_enabled": False,
                "mode": "sage_king",
            },
        },
    )
    before_paths = _relative_paths(tmp_path)

    doctor = raphael_setup_doctor()

    assert doctor.local_setup_ready is False
    assert doctor.blocking_reasons == (
        "raphael_mode_disabled",
        "raphael_conversation_injection_disabled",
    )
    assert "Plugin: enabled" in doctor.message
    assert "Slash commands: available" in doctor.message
    assert "Next action: hermes raphael enable" in doctor.message
    assert "Next action: hermes raphael install" not in doctor.message
    assert _relative_paths(tmp_path) == before_paths


def test_raphael_doctor_does_not_backup_or_scaffold_malformed_config(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_setup_doctor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.yaml").write_text("raphael: [\n", encoding="utf-8")
    before_paths = _relative_paths(tmp_path)

    doctor = raphael_setup_doctor()

    assert doctor.local_setup_ready is False
    assert "Local setup ready: no" in doctor.message
    assert "Next action: hermes raphael install" in doctor.message
    assert _relative_paths(tmp_path) == before_paths
    assert not list(tmp_path.glob("*.corrupt.*.bak"))


def test_raphael_uninstall_disables_mode_plugin_and_clears_readiness_evidence(
    monkeypatch, tmp_path
):
    from hermes_cli.raphael_cmd import raphael_release_readiness, uninstall_raphael_mode

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "skill_writes_enabled": True,
                "memory_writes_enabled": True,
                "evolution": {"enabled": True},
            },
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    result = uninstall_raphael_mode()
    config = _read_config(tmp_path)

    assert result.enabled is False
    assert result.plugin_enabled is False
    assert "raphael" not in config["plugins"]["enabled"]
    assert "raphael" in config["plugins"]["disabled"]
    assert config["raphael"]["enabled"] is False
    assert config["raphael"]["default_conversation_mode_enabled"] is False
    assert not (tmp_path / "raphael" / "release_readiness.json").exists()
    assert "runtime state preserved" in result.message

    readiness = raphael_release_readiness(profile="llm")
    assert readiness.public_release_ready is False
    assert "raphael_plugin_disabled" in readiness.blocking_reasons
    assert "llm_live_smoke_missing" in readiness.blocking_reasons


def test_raphael_lifecycle_release_gate_smoke_exercises_public_cli_entrypoint():
    from hermes_cli.raphael_cmd import _run_lifecycle_release_gate_smoke

    result = _run_lifecycle_release_gate_smoke()

    assert result["status"] == "pass"
    assert result["cli_smoke_verified"] is True
    assert result["cli_command_count"] >= 6
    assert result["cli_exit_codes"] == [0] * result["cli_command_count"]
    assert result["cli_install_enabled"] is True
    assert result["cli_disable_keeps_plugin"] is True
    assert result["cli_status_after_disable_guides_enable"] is True
    assert result["cli_enable_restores_mode"] is True
    assert result["cli_uninstall_disables_plugin"] is True
    assert result["cli_status_after_uninstall_guides_install"] is True


def test_raphael_public_cli_lifecycle_smoke_fails_when_hermes_entrypoint_missing(
    monkeypatch,
):
    from hermes_cli.raphael_cmd import _run_public_cli_lifecycle_smoke

    monkeypatch.setenv("PATH", "/nonexistent")

    result = _run_public_cli_lifecycle_smoke()

    assert result["cli_smoke_verified"] is False
    assert result["cli_entrypoint_found"] is False
    assert result["cli_entrypoint"] == "hermes"
    assert result["cli_failure_step"] == "entrypoint_missing"
    assert result["cli_command_count"] == 0


def test_raphael_demo_renders_sage_king_control_surface():
    from hermes_cli.raphael_cmd import render_raphael_demo

    output = render_raphael_demo("拉斐爾，請修復 gateway provider fallback 並完成驗證")

    assert "Raphael Demo" in output
    assert "解析完成。" in output
    assert "局勢判讀" in output
    assert "並列推演" in output
    assert "最優路線" in output
    assert "Proof Ladder" in output
    assert "Evolution Metadata" in output
    assert "Enable/Disable" in output
    assert "Offline Demo Evidence:" in output
    assert "no provider called" in output
    assert "not public readiness" in output
    assert "Offline shape score: 10/10" in output
    assert "Public wow claim: not proven by offline demo" in output
    assert "Wow score:" not in output
    assert "Lifecycle Dry Run:" in output
    assert "Mission Transition:" in output
    assert "Proof Gate Block:" in output
    assert "Status: not complete." in output
    assert "Evolution Proposal:" in output
    assert "Cleanup:" in output
    assert "- 狀態：已選定策略 -> 已選定策略" in output
    assert "- 策略：穩定執行 -> 品質優先" in output
    assert "- 下一步：多輪檢查、修正與自我審核後再交付" in output

    assert "Offline Demo Score:" not in output
    assert "type=" not in output
    assert "risk=" not in output
    assert "phase:" not in output
    assert "selected_strategy:" not in output
    assert "next_action:" not in output
    assert "plan_execute_verify" not in output
    assert "runtime_smoke_when_live_wiring" not in output
    assert "mission-" not in output
    assert "這是工具/runtime 任務" in output
    assert "visual.agent_mode" not in output
    assert "- 能力：Raphael control layer" in output
    assert "- 改進：" in output
    assert "- 信心：0.82" in output
    assert "- 上線條件：focused tests plus live LLM smoke before public claim" in output
    assert "- 回滾條件：" in output
    assert "trigger:" not in output
    assert "proposal-" not in output
    assert "affected_capability:" not in output
    assert "proposed_change:" not in output
    assert "confidence:" not in output
    assert "promotion_gate:" not in output
    assert "rollback_condition:" not in output


def test_raphael_demo_does_not_mutate_user_config(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import render_raphael_demo

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": [], "disabled": ["raphael"]},
            "raphael": {"enabled": False, "default_conversation_mode_enabled": False},
        },
    )
    before = _read_config(tmp_path)

    output = render_raphael_demo("Raphael, demo without touching my config")
    after = _read_config(tmp_path)

    assert after == before
    assert "dry-run only; config unchanged" in output


def test_raphael_command_demo_prints_custom_prompt(capsys):
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    raphael_command(
        SimpleNamespace(
            raphael_action="demo",
            prompt=["拉斐爾，", "追蹤", "上一張圖", "並修正比例"],
        )
    )

    output = capsys.readouterr().out

    assert "Raphael Demo" in output
    assert "上一張圖" not in output
    assert "Input: redacted demo prompt" in output
    assert "Offline shape score: 10/10" in output
    assert "Public wow claim: not proven by offline demo" in output
    assert "Wow score:" not in output


def test_raphael_command_doctor_prints_setup_health(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    raphael_command(SimpleNamespace(raphael_action="doctor"))

    output = capsys.readouterr().out

    assert "Raphael Setup Doctor" in output
    assert "Local setup ready: yes" in output
    assert "readiness --readiness-profile llm" in output


def test_raphael_doctor_cli_parser_prints_setup_health(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    parser = _build_raphael_test_parser()

    args = parser.parse_args(["raphael", "doctor"])
    args.func(args)

    output = capsys.readouterr().out

    assert "Raphael Setup Doctor" in output
    assert "Local setup ready: yes" in output


def test_raphael_wow_gate_rejects_raw_demo_metadata_labels(monkeypatch):
    import hermes_cli.raphael_cmd as raphael_cmd

    leaked_demo = "\n".join(
        [
            "Raphael Demo",
            "解析完成。",
            "局勢判讀",
            "最優路線",
            "Standby Summon:",
            "狀態：Raphael 待命，請給我任務目標。",
            "Mission Transition:",
            "- 下一步：多輪檢查、修正與自我審核後再交付",
            "Proof Gate Block:",
            "Status: not complete.",
            "Evolution Metadata:",
            "- rollback_condition: raw rollback leak",
            "- proposal-only: raw state leak",
            "Enable/Disable:",
        ]
    )
    monkeypatch.setattr(
        raphael_cmd,
        "render_raphael_demo",
        lambda *_args, **_kwargs: leaked_demo,
    )

    check = raphael_cmd._wow_release_gate_check({"status": "pass"})

    assert check["status"] == "fail"
    assert check["signals"]["clean_output"] is False
    assert "clean_output" in check["missing"]


def test_raphael_readiness_blocks_public_release_without_visual_live_e2e(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_missing" in readiness.blocking_reasons
    assert "Public release ready: no" in readiness.message
    assert "Visual live E2E: missing" in readiness.message
    assert "Offline demo: not release evidence" in readiness.message
    assert "Next action:" in readiness.message
    assert "--readiness-profile media" in readiness.message
    assert "--visual-e2e-report <report.json>" in readiness.message
    assert "--readiness-profile llm" not in readiness.message


def test_raphael_llm_readiness_missing_evidence_next_action_has_full_gate_args(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "llm_live_smoke_missing" in readiness.blocking_reasons
    assert "hostile_review_missing" in readiness.blocking_reasons
    assert "--readiness-profile llm" in readiness.message
    assert "--llm-smoke-transcript" in readiness.message
    assert "--hostile-review-report" in readiness.message
    assert "--non-visual-regression-report" in readiness.message
    assert "--visual-e2e-report" not in readiness.message


def test_raphael_readiness_points_to_visual_live_e2e_report_next_action(
    monkeypatch, tmp_path
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness()

    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "preflight" in readiness.message
    assert "--preflight-only" in readiness.message
    assert "Next action: run Grok Web Imagine live E2E report" in readiness.message
    assert "scripts/grok_web_imagine_live_e2e.py" in readiness.message
    assert "hermes raphael release-gate --readiness-profile media" in readiness.message
    assert "--llm-smoke-session-id" in readiness.message
    assert "--llm-smoke-transcript" in readiness.message
    assert "--visual-e2e-report" in readiness.message


def test_raphael_readiness_media_next_action_requires_grok_visual_live_e2e(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness()

    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "scripts/openai_visual_live_e2e.py" not in readiness.message
    assert "scripts/grok_web_imagine_live_e2e.py" in readiness.message


def test_raphael_readiness_llm_profile_does_not_require_visual_live_e2e(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
                "completion_audit": _completion_audit_check(),
                "release_slice_manifest": _release_slice_manifest_check(),
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is True
    assert readiness.release_state == "ready_for_llm_only_release"
    assert "Profile: llm" in readiness.message
    assert "Visual live E2E: not required for llm profile" in readiness.message
    assert "Offline demo shape: pass" in readiness.message


def test_raphael_readiness_rejects_legacy_lifecycle_without_disabled_slash_proof(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "legacy-lifecycle-1",
                },
                "slash_command_surface": _slash_command_surface_check(),
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(regression_report),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "install_disable_uninstall_unverified" in readiness.blocking_reasons
    assert "Install/disable/uninstall: disabled_surface_unverified" in readiness.message


def test_raphael_readiness_rejects_lifecycle_without_public_cli_smoke(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "in-process-lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "goal_state_contract": _goal_state_contract_check(),
                "evolution_contract": _evolution_contract_check(),
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(regression_report),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "install_disable_uninstall_unverified" in readiness.blocking_reasons
    assert "Install/disable/uninstall: disabled_surface_unverified" in readiness.message


def test_raphael_readiness_rejects_lifecycle_without_hermes_entrypoint_identity(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed through public CLI",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "forged-cli-lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                    "cli_smoke_verified": True,
                    "cli_command_count": 8,
                    "cli_exit_codes": [0, 0, 0, 0, 0, 0, 0, 0],
                    "cli_install_enabled": True,
                    "cli_disable_keeps_plugin": True,
                    "cli_status_after_disable_guides_enable": True,
                    "cli_enable_restores_mode": True,
                    "cli_uninstall_disables_plugin": True,
                    "cli_status_after_uninstall_guides_install": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "goal_state_contract": _goal_state_contract_check(),
                "evolution_contract": _evolution_contract_check(),
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(regression_report),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "install_disable_uninstall_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_missing_package_install_smoke(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed through public CLI",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                    "cli_smoke_verified": True,
                    "cli_entrypoint": "hermes",
                    "cli_entrypoint_found": True,
                    "cli_entrypoint_path": "/tmp/hermes",
                    "cli_install_enabled": True,
                    "cli_disable_keeps_plugin": True,
                    "cli_status_after_disable_guides_enable": True,
                    "cli_enable_restores_mode": True,
                    "cli_uninstall_disables_plugin": True,
                    "cli_status_after_uninstall_guides_install": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "goal_state_contract": _goal_state_contract_check(),
                "evolution_contract": _evolution_contract_check(),
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(regression_report),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "package_install_smoke_missing" in readiness.blocking_reasons
    assert "Package install smoke: missing" in readiness.message


def test_raphael_release_gate_rejects_package_install_without_command_transcript(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    report.pop("commands")
    report.pop("commands_digest")
    report["commands_verified"] = True
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_release_evidence_pending"
    assert "package_install_smoke_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_package_install_without_installed_media_slice_proof(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    report.pop("installed_media_slice_ready", None)
    report.pop("installed_media_fail_closed", None)
    report.pop("installed_media_gate_lines", None)
    report.pop("installed_media_gate_probe", None)
    report["commands"] = [
        command
        for command in report["commands"]
        if command.get("label") != "media_readiness_after_install"
    ]
    report["commands_digest"] = _json_digest(report["commands"])
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_release_evidence_pending"
    assert "package_install_smoke_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_package_install_without_installed_llm_manifest_gate(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    report.pop("installed_llm_release_ready", None)
    report.pop("installed_llm_manifest_gate_verified", None)
    report.pop("installed_llm_gate_lines", None)
    report.pop("installed_llm_gate_probe", None)
    report["commands"] = [
        command
        for command in report["commands"]
        if command.get("label") != "llm_readiness_after_install"
    ]
    report["commands_digest"] = _json_digest(report["commands"])
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_release_evidence_pending"
    assert "package_install_smoke_unverified" in result.blocking_reasons


def test_raphael_release_gate_accepts_fail_closed_media_gate_for_llm_package_smoke(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )
    readiness = raphael_release_readiness(profile="llm")
    evidence = json.loads(
        (tmp_path / "raphael" / "release_readiness.llm.json").read_text()
    )

    assert result.public_release_ready is True
    assert result.release_state == "ready_for_llm_only_release"
    assert readiness.public_release_ready is True
    assert readiness.release_state == "ready_for_llm_only_release"
    assert evidence["checks"]["package_install_smoke"][
        "installed_media_gate_fail_closed"
    ] is True
    assert "package_install_smoke_unverified" not in readiness.blocking_reasons


def test_raphael_release_gate_accepts_fresh_home_llm_fail_closed_package_smoke(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = _package_install_smoke_report(
        tmp_path,
        installed_llm_fail_closed=True,
    )
    release_quality_kwargs["package_install_report_path"] = str(package_report)

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )
    readiness = raphael_release_readiness(profile="llm")
    evidence = json.loads(
        (tmp_path / "raphael" / "release_readiness.llm.json").read_text()
    )

    assert result.public_release_ready is True
    assert result.release_state == "ready_for_llm_only_release"
    assert readiness.public_release_ready is True
    assert readiness.release_state == "ready_for_llm_only_release"
    assert evidence["checks"]["package_install_smoke"][
        "installed_llm_fresh_home_fail_closed"
    ] is True
    assert evidence["checks"]["package_install_smoke"][
        "installed_llm_gate_verified"
    ] is True
    assert "package_install_smoke_unverified" not in readiness.blocking_reasons


def test_raphael_release_gate_rejects_package_install_without_proposal_lifecycle(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    for key in (
        "cli_proposal_status_safe_refs",
        "cli_proposal_approve_audited",
        "cli_proposal_reject_audited",
        "cli_proposal_resolutions_persisted",
        "cli_proposal_raw_ids_hidden",
        "cli_proposal_no_durable_apply_warning",
    ):
        report.pop(key, None)
    report["commands"] = [
        command
        for command in report["commands"]
        if not str(command.get("label") or "").startswith("proposal_")
        and str(command.get("label") or "")
        not in {
            "seed_action_proposals",
            "render_action_proposals",
            "inspect_action_proposals",
        }
    ]
    report["cli_command_count"] = 8
    report["cli_exit_codes"] = [0, 0, 0, 0, 0, 0, 0, 0]
    report["commands_digest"] = _json_digest(report["commands"])
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "package_install_smoke_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_package_install_without_approved_rollout_guidance(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    report.pop("cli_proposal_approve_rollout_guidance", None)
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "package_install_smoke_fail" in result.blocking_reasons


def test_raphael_release_gate_rejects_package_install_with_generated_source_artifacts(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    report["source_tree_hygiene_clean"] = False
    report["source_tree_generated_artifacts"] = ["build", "tmp", "temp_vision_images"]
    report["failure_classes"] = ["source_tree_generated_artifacts"]
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "package_install_smoke_fail" in result.blocking_reasons


def test_raphael_release_gate_rejects_package_install_without_enabled_status_proof(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    for record in report["commands"]:
        if record["label"] in {"status_after_install", "status_after_enable"}:
            record["stdout"] = "Raphael Status\nMode: unknown\n"
    report["cli_install_enabled"] = True
    report["cli_enable_restores_mode"] = True
    report["cli_status_after_install_enabled"] = False
    report["cli_status_after_enable_enabled"] = False
    report["commands_digest"] = _json_digest(report["commands"])
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "package_install_smoke_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_package_install_inconsistent_status_transcript(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    for record in report["commands"]:
        if record["label"] in {"status_after_install", "status_after_enable"}:
            record["stdout"] = (
                "Raphael Status\n"
                "Mode: disabled (plugin enabled, mode=sage_king)\n"
                "Conversation injection: disabled\n"
                "Slash commands: available\n"
                "Next action: hermes raphael enable"
            )
    report["cli_status_after_install_enabled"] = True
    report["cli_install_enabled"] = True
    report["cli_status_after_enable_enabled"] = True
    report["cli_enable_restores_mode"] = True
    report["commands_digest"] = _json_digest(report["commands"])
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "package_install_smoke_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_package_install_wrong_script_identity(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])
    report = json.loads(package_report.read_text(encoding="utf-8"))
    report["command"] = "scripts/other_package_smoke.py"
    report["script_path"] = str(tmp_path / "other_package_smoke.py")
    package_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "package_install_smoke_unverified" in result.blocking_reasons


def test_raphael_readiness_rejects_mode_router_contract_missing_cases(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(
                    regression_report
                ),
                "mode_router_contract": _mode_router_contract_check(
                    cases=("general_conversation", "tool_task")
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "mode_router_contract_unverified" in readiness.blocking_reasons
    assert "Mode router: cases_unverified" in readiness.message


def test_raphael_readiness_revalidates_mode_router_contract_against_current_runtime(
    monkeypatch,
    tmp_path,
):
    import hermes_cli.raphael_cmd as raphael_cmd

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    current_runtime_check = _mode_router_contract_check()
    current_runtime_check["run_id"] = "mode-router-current-runtime"
    for case in current_runtime_check["cases"]:
        if case["case"] == "visual_agent_generation":
            case["handoff_tool"] = "visual_agent_generate_v2"
    monkeypatch.setattr(
        raphael_cmd,
        "_mode_router_contract_release_gate_check",
        lambda: current_runtime_check,
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(
                    regression_report
                ),
                "mode_router_contract": _mode_router_contract_check(),
            },
        },
    )

    readiness = raphael_cmd.raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "mode_router_contract_unverified" in readiness.blocking_reasons
    assert "Mode router: cases_unverified" in readiness.message


def test_raphael_readiness_rejects_goal_state_contract_missing_cases(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(
                    regression_report
                ),
                "goal_state_contract": _goal_state_contract_check(
                    cases=("new_tool_mission", "followup_preserves_mission")
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "goal_state_contract_unverified" in readiness.blocking_reasons
    assert "Goal state: cases_unverified" in readiness.message


def test_raphael_readiness_revalidates_goal_state_contract_against_current_runtime(
    monkeypatch,
    tmp_path,
):
    import hermes_cli.raphael_cmd as raphael_cmd

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    current_runtime_check = _goal_state_contract_check()
    current_runtime_check["run_id"] = "goal-state-current-runtime"
    for case in current_runtime_check["cases"]:
        if case["case"] == "visual_edit_targets_current_artifact":
            case["active_artifact_id"] = "artifact-new"
    monkeypatch.setattr(
        raphael_cmd,
        "_goal_state_contract_release_gate_check",
        lambda: current_runtime_check,
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(
                    regression_report
                ),
                "goal_state_contract": _goal_state_contract_check(),
            },
        },
    )

    readiness = raphael_cmd.raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "goal_state_contract_unverified" in readiness.blocking_reasons
    assert "Goal state: cases_unverified" in readiness.message


def test_raphael_readiness_rejects_evolution_contract_missing_cases(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "goal_state_contract": _goal_state_contract_check(),
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(
                    regression_report
                ),
                "evolution_contract": _evolution_contract_check(
                    cases=("audit_only_user_correction",)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "evolution_contract_unverified" in readiness.blocking_reasons
    assert "Evolution: cases_unverified" in readiness.message


def test_raphael_readiness_rejects_evolution_contract_without_rollout_plan_details(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    package_report = _package_install_smoke_report(tmp_path)
    legacy_evolution_contract = _evolution_contract_check()
    for case in legacy_evolution_contract["cases"]:
        if case["case"] == "repeated_failure_self_correction_priority":
            case.pop("action_proposal_rollout_plan_verified", None)
            case.pop("action_proposal_rollout_status", None)
            case.pop("action_proposal_rollout_verification_commands", None)
            case.pop("action_proposal_rollout_promotion_gate", None)
            case.pop("action_proposal_rollout_rollback_condition", None)
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed through API and public CLI in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael status && hermes raphael disable && hermes raphael status && hermes raphael enable && hermes raphael status && hermes raphael uninstall && hermes raphael status",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                    "cli_smoke_verified": True,
                    "cli_entrypoint": "hermes",
                    "cli_entrypoint_found": True,
                    "cli_entrypoint_path": str(tmp_path / "bin" / "hermes"),
                    "cli_command_count": 8,
                    "cli_install_enabled": True,
                    "cli_disable_keeps_plugin": True,
                    "cli_status_after_disable_guides_enable": True,
                    "cli_enable_restores_mode": True,
                    "cli_uninstall_disables_plugin": True,
                    "cli_status_after_uninstall_guides_install": True,
                },
                "package_install_smoke": _package_install_smoke_check(package_report),
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "goal_state_contract": _goal_state_contract_check(),
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(
                    regression_report
                ),
                "evolution_contract": legacy_evolution_contract,
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "evolution_contract_unverified" in readiness.blocking_reasons
    assert "Evolution: cases_unverified" in readiness.message


def test_raphael_readiness_revalidates_evolution_contract_against_current_runtime(
    monkeypatch,
    tmp_path,
):
    import hermes_cli.raphael_cmd as raphael_cmd

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    current_runtime_check = _evolution_contract_check()
    current_runtime_check["run_id"] = "evolution-current-runtime"
    for case in current_runtime_check["cases"]:
        if case["case"] == "audit_only_user_correction":
            case["mode"] = "active_evolution"
            case["should_review"] = True
    monkeypatch.setattr(
        raphael_cmd,
        "_evolution_contract_release_gate_check",
        lambda: current_runtime_check,
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "slash_command_surface": _slash_command_surface_check(),
                "mode_router_contract": _mode_router_contract_check(),
                "goal_state_contract": _goal_state_contract_check(),
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(hostile_report),
                "non_visual_regression": _non_visual_regression_check(
                    regression_report
                ),
                "evolution_contract": _evolution_contract_check(),
            },
        },
    )

    readiness = raphael_cmd.raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "evolution_contract_unverified" in readiness.blocking_reasons
    assert "Evolution: cases_unverified" in readiness.message


def test_raphael_readiness_llm_profile_requires_review_and_regression_evidence(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
        profile="llm",
        include_release_quality=False,
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "hostile_review_missing" in readiness.blocking_reasons
    assert "non_visual_regression_missing" in readiness.blocking_reasons
    assert "Hostile review: missing" in readiness.message
    assert "Non-visual regression: missing" in readiness.message
    assert "--hostile-review-report" in readiness.message
    assert "--non-visual-regression-report" in readiness.message
    assert "--llm-smoke-transcript" in readiness.message
    assert "--hostile-review-report" in readiness.message
    assert "--non-visual-regression-report" in readiness.message


def test_raphael_media_readiness_reuses_llm_evidence_for_common_checks(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness(profile="media")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "readiness_evidence_profile_mismatch" not in readiness.blocking_reasons
    assert readiness.blocking_reasons == ("visual_live_e2e_missing",)
    assert "Install/disable/uninstall: pass" in readiness.message
    assert "LLM live smoke: pass" in readiness.message
    assert "Offline demo shape: pass" in readiness.message
    assert "Visual live E2E: missing" in readiness.message


def test_raphael_media_readiness_rejects_visual_evidence_from_llm_profile(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    quality_review = _visual_quality_review(artifact)
    report.write_text(
        json.dumps(
            {
                "run_id": "visual-live-llm-profile",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "provider": {
                    "name": "grok-web-imagine",
                    "model": "grok-web-imagine",
                },
                "provider_result": {
                    "provider": "grok-web-imagine",
                    "model": "grok-web-imagine",
                    "page_url": result_surface,
                },
                "page_url": result_surface,
                "result_surface_id": result_surface,
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": result_surface,
                },
                "request": {"operation": "generate"},
                "quality_review": quality_review,
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    package_report = _package_install_smoke_report(tmp_path)
    hostile_report = _write_hostile_review_report(tmp_path)
    non_visual_report = _write_non_visual_regression_report(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    checks = {
        "install_disable_uninstall": {
            "status": "pass",
            "evidence": "lifecycle smoke passed in temp HERMES_HOME",
            "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
            "run_id": "lifecycle-1",
        },
        "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
        "wow_experience": _wow_experience_check(),
        "hostile_review": _hostile_review_check(_write_hostile_review_report(tmp_path)),
        "non_visual_regression": _non_visual_regression_check(
            _write_non_visual_regression_report(tmp_path)
        ),
        "visual_live_e2e": {
            "status": "pass",
            "evidence": "fresh selected artifact verified after current visual submit",
            "command": "scripts/grok_web_imagine_live_e2e.py",
            "run_id": "visual-live-llm-profile",
            "fresh_artifact": True,
            "selected_artifact_id": "artifact-1",
            "artifact_quality_verdict": "pass",
            "provider_mode": "grok-web-imagine-live",
            "provider_success": True,
            "report_status": "completed",
            "artifact_path": str(artifact),
            "artifact_exists": True,
            "artifact_source": "grok_history",
            "artifact_durability": "durable_history_or_post",
            "durable_history_verified": True,
            "page_url": result_surface,
            "result_surface_id": result_surface,
            "operation": "generate",
            "source_report_path": str(report),
        },
    }
    evidence_dir = tmp_path / "raphael"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "producer": "hermes-raphael-release-gate",
        "generated_at": _fresh_generated_at(),
        "profile": "llm",
        "checks": checks,
    }
    (evidence_dir / "release_readiness.llm.json").write_text(
        json.dumps(_payload_with_readiness_verdict(payload, profile="llm")),
        encoding="utf-8",
    )

    readiness = raphael_release_readiness(profile="media")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_missing" in readiness.blocking_reasons


def test_raphael_media_visual_next_action_preserves_quality_gate_args(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
        include_release_quality=False,
    )

    readiness = raphael_release_readiness(profile="media")

    assert "visual_live_e2e_missing" in readiness.blocking_reasons
    assert "hostile_review_missing" in readiness.blocking_reasons
    assert "non_visual_regression_missing" in readiness.blocking_reasons
    assert "--visual-e2e-report <report.json>" in readiness.message
    assert "--hostile-review-report <hostile-review.json>" in readiness.message
    assert (
        "--non-visual-regression-report <non-visual-regression.json>"
        in readiness.message
    )


def test_raphael_readiness_blocks_llm_release_without_wow_experience_evidence(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "wow_experience_missing" in readiness.blocking_reasons
    assert "Offline demo shape: missing" in readiness.message
    assert "Next action: rerun hermes raphael release-gate with current smoke evidence" in readiness.message
    assert "--llm-smoke-session-id" in readiness.message


def test_raphael_readiness_rejects_wow_experience_below_release_threshold(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    weak_wow = _wow_experience_check()
    weak_wow["score"] = 7
    weak_wow["missing"] = ["proof_gate"]
    weak_wow["signals"]["proof_gate"] = False

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": weak_wow,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "wow_experience_score_unverified" in readiness.blocking_reasons
    assert "Offline demo shape: score_unverified" in readiness.message


def test_raphael_readiness_rejects_inflated_wow_score_from_false_signals(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    inflated_wow = _wow_experience_check()
    inflated_wow["score"] = 8
    inflated_wow["signals"]["evolution_feedback"] = False
    inflated_wow["signals"]["lifecycle_reversible"] = False
    inflated_wow["signals"]["demo_under_one_minute"] = False
    inflated_wow["signals"]["clean_output"] = False
    inflated_wow["missing"] = [
        "evolution_feedback",
        "lifecycle_reversible",
        "demo_under_one_minute",
        "clean_output",
    ]

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": inflated_wow,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "wow_experience_score_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_wow_score_without_standby_summon(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    weak_wow = _wow_experience_check()
    weak_wow["signals"]["standby_summon"] = False

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": weak_wow,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "wow_experience_score_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_wow_without_user_simulation_cases(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    weak_wow = _wow_experience_check()
    weak_wow.pop("user_simulation_cases", None)

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": weak_wow,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "wow_experience_score_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_wow_user_simulation_without_next_action_or_proof_layer():
    from hermes_cli.raphael_cmd import _wow_experience_has_release_score

    weak_wow = _wow_experience_check()
    weak_wow["user_simulation_cases"][0].pop("next_action", None)
    weak_wow["user_simulation_cases"][1].pop("proof_layer", None)

    assert _wow_experience_has_release_score(weak_wow) is False


def test_raphael_readiness_rejects_wow_user_simulation_without_reviewable_matrix():
    from hermes_cli.raphael_cmd import _wow_experience_has_release_score

    weak_wow = _wow_experience_check()
    weak_wow["user_simulation_cases"][0].pop("user_prompt", None)
    weak_wow["user_simulation_cases"][1].pop("expected_visible_behavior", None)
    weak_wow["user_simulation_cases"][2].pop("critical_assertions", None)

    assert _wow_experience_has_release_score(weak_wow) is False


def test_raphael_readiness_rejects_missing_release_docs_audit(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": _llm_release_ready_checks(
                tmp_path,
                release_docs_audit=False,
            ),
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "release_docs_audit_missing" in readiness.blocking_reasons
    assert "Release docs: missing" in readiness.message


def test_raphael_readiness_rejects_failed_release_docs_audit(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": _llm_release_ready_checks(
                tmp_path,
                release_docs_audit=_release_docs_audit_check(
                    status="fail",
                    violations=["release_audit_doc:grok_ready_overclaim"],
                ),
            ),
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "release_docs_audit_fail" in readiness.blocking_reasons
    assert "Release docs: fail" in readiness.message


def test_raphael_readiness_rejects_missing_completion_audit(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    checks = _llm_release_ready_checks(tmp_path)
    checks.pop("completion_audit")
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": checks,
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "completion_audit_missing" in readiness.blocking_reasons
    assert "Completion audit: missing" in readiness.message


def test_raphael_readiness_rejects_missing_release_slice_manifest(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    checks = _llm_release_ready_checks(tmp_path)
    checks.pop("release_slice_manifest")
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": checks,
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "release_slice_manifest_missing" in readiness.blocking_reasons
    assert "Release slice manifest: missing" in readiness.message


def test_raphael_readiness_rejects_failed_release_slice_manifest(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    checks = _llm_release_ready_checks(tmp_path)
    checks["release_slice_manifest"] = _release_slice_manifest_check(
        status="fail",
        manifest_status="blocked",
        review_strategy="classify_or_remove_unknown_paths",
    )
    checks["release_slice_manifest"]["blockers"] = ["boundary:unclassified_paths"]
    checks["release_slice_manifest"]["counts"]["unclassified_paths"] = 1
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": checks,
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "release_slice_manifest_fail" in readiness.blocking_reasons
    assert "Release slice manifest: fail" in readiness.message


def test_raphael_readiness_rejects_wow_with_failed_user_simulation_case(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    weak_wow = _wow_experience_check()
    weak_wow["user_simulation_cases"] = [
        {
            "case": "standby_summon",
            "status": "pass",
            "visual_quota_used": False,
        },
        {
            "case": "vague_takeover_preserves_mission",
            "status": "pass",
            "visual_quota_used": False,
        },
        {
            "case": "runtime_log_attachment_routes_tool_task",
            "status": "pass",
            "visual_quota_used": False,
        },
        {
            "case": "blank_screen_repair_routes_tool_task",
            "status": "pass",
            "visual_quota_used": False,
        },
        {
            "case": "prompt_builder_question_not_prompt_disclosure",
            "status": "pass",
            "visual_quota_used": False,
        },
        {
            "case": "negated_media_summon_stays_text_only",
            "status": "pass",
            "visual_quota_used": False,
        },
    ]
    weak_wow["user_simulation_cases"][0]["status"] = "fail"

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": weak_wow,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "wow_experience_score_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_wow_with_visual_quota_user_simulation_case(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    weak_wow = _wow_experience_check()
    weak_wow["user_simulation_cases"][0]["visual_quota_used"] = True

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": weak_wow,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "wow_experience_score_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_stale_release_evidence(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_stale" in readiness.blocking_reasons


def test_raphael_readiness_rejects_missing_generated_at_release_evidence(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_timestamp_missing" in readiness.blocking_reasons


def test_raphael_readiness_rejects_missing_profile_release_evidence(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_profile_mismatch" in readiness.blocking_reasons


def test_raphael_readiness_rejects_forged_llm_log_line_not_in_agent_log(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    session_id = "20260701_131600_93f518"
    forged_line = (
        "2026-06-30 18:13:20,443 INFO "
        f"[{session_id}] agent.conversation_loop: Turn ended: "
        "reason=text_response(finish_reason=stop) model=gpt-5.5 "
        "api_calls=1/3 budget=1/3 tool_turns=0 "
        f"last_msg_role=assistant response_len=713 session={session_id}"
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    evidence_dir = tmp_path / "raphael"
    evidence_dir.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "producer": "hermes-raphael-release-gate",
        "generated_at": _fresh_generated_at(),
        "profile": "llm",
        "checks": {
            "install_disable_uninstall": {
                "status": "pass",
                "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                "run_id": "lifecycle-1",
            },
            "llm_live_smoke": {
                **_llm_smoke_check(session_id),
                "source_log_path": str(tmp_path / "config.yaml"),
                "log_line": forged_line,
            },
            "wow_experience": _wow_experience_check(),
        },
    }
    (evidence_dir / "release_readiness.json").write_text(
        json.dumps(_payload_with_readiness_verdict(payload, profile="llm")),
        encoding="utf-8",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: smoke_unverified" in readiness.message


def test_raphael_readiness_rejects_stale_llm_smoke_log(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    log_path, log_line = _write_llm_smoke_log(
        tmp_path,
        timestamp=datetime.now(timezone.utc) - timedelta(days=2),
    )
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: smoke_unverified" in readiness.message


def test_raphael_readiness_media_wow_next_action_preserves_visual_report_args(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    artifact_mtime = datetime.fromtimestamp(
        artifact.stat().st_mtime,
        timezone.utc,
    ).isoformat()
    report = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    quality_review = _visual_quality_review(artifact)
    report_generated_at = _fresh_generated_at()
    visual_report = _stamp_visual_live_report(
        {
            "run_id": "visual-live-1",
            "generated_at": report_generated_at,
            "success": True,
            "status": "completed",
            "provider_mode": "grok-web-imagine-live",
            "provider": {
                "name": "grok-web-imagine",
                "model": "grok-web-imagine",
            },
            "provider_result": {
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "page_url": result_surface,
            },
            "page_url": result_surface,
            "result_surface_id": result_surface,
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "grok_history",
                "durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": result_surface,
            },
            "request": {"operation": "generate"},
            "quality_review": quality_review,
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        }
    )
    report.write_text(
        json.dumps(visual_report),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                    "llm_live_smoke": _llm_smoke_check(),
                    "visual_live_e2e": {
                    "status": "pass",
                    "evidence": "fresh selected artifact verified after current visual submit",
                    "command": "scripts/grok_web_imagine_live_e2e.py",
                    "run_id": "visual-live-1",
                    "report_run_id": "visual-live-1",
                    "report_generated_at": report_generated_at,
                    "report_identity_verified": True,
                    "fresh_artifact": True,
                    "selected_artifact_id": "artifact-1",
                    "artifact_quality_verdict": "pass",
                    "quality_review_source": "quality_review",
                    "quality_review_reviewer": "vision-backed-artifact-review",
                    "quality_review_run_id": quality_review["run_id"],
                    "quality_review_generated_at": quality_review["generated_at"],
                    "quality_review_source_report_path": quality_review[
                        "source_report_path"
                    ],
                    "quality_review_artifact_match": True,
                    "quality_review_artifact_sha256": quality_review[
                        "artifact_sha256"
                    ],
                    "quality_review_artifact_size_bytes": quality_review[
                        "artifact_size_bytes"
                    ],
                    "quality_review_artifact_mtime": quality_review["artifact_mtime"],
                    "quality_review_artifact_identity_verified": True,
                    "quality_review_source_type": quality_review[
                        "review_source_type"
                    ],
                    "quality_review_model_provider": quality_review[
                        "review_model_provider"
                    ],
                    "quality_review_model": quality_review["review_model"],
                    "quality_review_evidence_digest": quality_review[
                        "review_evidence_digest"
                    ],
                    "quality_review_response_id": quality_review["review_response_id"],
                    "quality_review_transcript_report_path": quality_review[
                        "review_transcript_report_path"
                    ],
                    "quality_review_transcript_digest": quality_review[
                        "review_transcript_digest"
                    ],
                        "quality_review_provenance_verified": True,
                        "quality_review_dimensions_verified": True,
                        "provider_mode": "grok-web-imagine-live",
                        "provider_name": "grok-web-imagine",
                        "provider_model": "grok-web-imagine",
                        "provider_result_provider": "grok-web-imagine",
                        "provider_result_model": "grok-web-imagine",
                        "provider_result_response_id": "",
                        "provider_success": True,
                        "report_status": "completed",
                        "artifact_path": str(artifact),
                        "artifact_exists": True,
                        "artifact_mtime_verified": True,
                        "artifact_mtime": artifact_mtime,
                        "artifact_source": "grok_history",
                        "artifact_durability": "durable_history_or_post",
                        "durable_history_verified": True,
                        "history_entry_id": "",
                        "page_url": "https://grok.com/imagine/history/current",
                    "result_surface_id": "https://grok.com/imagine/history/current",
                    "operation": "generate",
                    "source_report_path": str(report),
                },
            },
        },
        profile="media",
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert "wow_experience_missing" in readiness.blocking_reasons
    assert "--llm-smoke-session-id" in readiness.message
    assert "--visual-e2e-report" in readiness.message


def test_raphael_readiness_media_profile_with_llm_evidence_points_to_visual_gate(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="media")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "readiness_evidence_profile_mismatch" not in readiness.blocking_reasons
    assert readiness.blocking_reasons == ("visual_live_e2e_missing",)
    assert "Next action: run Grok Web Imagine live E2E report" in readiness.message
    assert "--llm-smoke-session-id" in readiness.message
    assert "--visual-e2e-report" in readiness.message


def test_raphael_release_gate_rejects_llm_smoke_without_log_provenance(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
    )

    assert result.public_release_ready is False
    assert "llm_live_smoke_log_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_llm_smoke_without_transcript_report(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    release_quality_kwargs.pop("llm_transcript_report_path")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "llm_live_smoke_unverified" in result.blocking_reasons
    assert "LLM live smoke: transcript_missing" in result.message


def test_raphael_release_gate_rejects_llm_smoke_with_internal_trace_leak(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    transcript_path = Path(release_quality_kwargs["llm_transcript_report_path"])
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript["final_response"] = (
        "狀態：chosen route = 純文字判讀。\n"
        "風險：visual_generation_requested 被封鎖。\n"
        "下一步：不要 call_visual_agent_generate。"
    )
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "llm_live_smoke_internal_trace_leak" in result.blocking_reasons
    assert "LLM live smoke: internal_trace_leak" in result.message


def test_raphael_release_gate_rejects_llm_smoke_with_context_truncation_warning(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    transcript_path = Path(release_quality_kwargs["llm_transcript_report_path"])
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript["terminal_output"] = (
        "Context file AGENTS.md TRUNCATED: 79816 chars exceeds limit of 65280"
    )
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "llm_live_smoke_context_truncated" in result.blocking_reasons
    assert "LLM live smoke: context_truncated" in result.message


def test_raphael_release_gate_rejects_llm_smoke_without_model_identity(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    transcript_path = Path(release_quality_kwargs["llm_transcript_report_path"])
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript.pop("model", None)
    transcript.pop("model_provider", None)
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "llm_live_smoke_model_identity_unverified" in result.blocking_reasons
    assert "LLM live smoke: model_identity_unverified" in result.message


def test_raphael_release_gate_rejects_llm_smoke_with_wrong_log_model(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path, model="gpt-4.1")
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "llm_live_smoke_model_identity_unverified" in result.blocking_reasons
    assert "LLM live smoke: model_identity_unverified" in result.message


def test_raphael_readiness_rejects_self_attested_quality_evidence_without_reports(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(),
                "non_visual_regression": _non_visual_regression_check(),
            },
        },
        profile="llm",
        include_release_quality=False,
    )

    result = raphael_release_readiness(profile="llm")

    assert result.public_release_ready is False
    assert "hostile_review_unverified" in result.blocking_reasons
    assert "non_visual_regression_unverified" in result.blocking_reasons
    assert "Hostile review: review_unverified" in result.message
    assert "Non-visual regression: regression_unverified" in result.message


def test_raphael_release_gate_rejects_hostile_review_older_than_release_evidence(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    hostile_report = Path(release_quality_kwargs["hostile_review_report_path"])
    report = json.loads(hostile_report.read_text(encoding="utf-8"))
    report["generated_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()
    hostile_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "hostile_review_outdated" in result.blocking_reasons
    assert "Hostile review: review_outdated" in result.message
    assert "Next action: run a fresh independent hostile review" in result.message
    assert "mode-router contract, goal-state contract" not in result.message


def test_raphael_release_gate_rejects_hostile_review_without_llm_ux_claims(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    hostile_report = Path(release_quality_kwargs["hostile_review_report_path"])
    report = json.loads(hostile_report.read_text(encoding="utf-8"))
    report.pop("llm_ux_claims", None)
    hostile_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "hostile_review_ux_claims_unverified" in result.blocking_reasons
    assert "Hostile review: ux_claims_unverified" in result.message


def test_raphael_release_gate_rejects_hostile_review_that_allows_broad_claims(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    hostile_report = Path(release_quality_kwargs["hostile_review_report_path"])
    report = json.loads(hostile_report.read_text(encoding="utf-8"))
    report["llm_ux_claims"] = {
        "public_claims_reviewed": True,
        "sage_king_claim_allowed": True,
        "wow_claim_allowed": True,
        "big_evolution_claim_allowed": True,
        "adversarial_scenarios": [
            "constrained_summon",
            "same_mission_followup",
            "negated_media_request",
            "public_wording_review",
        ],
        "multi_turn_transcript_ids": ["20260701_131600_93f518"],
    }
    hostile_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "hostile_review_ux_claims_unverified" in result.blocking_reasons
    assert "Hostile review: ux_claims_unverified" in result.message


def test_raphael_release_gate_rejects_hostile_review_missing_media_claim_boundary_scenarios(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    hostile_report = Path(release_quality_kwargs["hostile_review_report_path"])
    report = json.loads(hostile_report.read_text(encoding="utf-8"))
    report["llm_ux_claims"] = {
        "public_claims_reviewed": True,
        "sage_king_claim_allowed": False,
        "wow_claim_allowed": False,
        "big_evolution_claim_allowed": False,
        "adversarial_scenarios": [
            "constrained_summon",
            "same_mission_followup",
            "negated_media_request",
            "public_wording_review",
        ],
        "multi_turn_transcript_ids": ["20260701_131600_93f518"],
    }
    hostile_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert "hostile_review_ux_claims_unverified" in result.blocking_reasons
    assert "Hostile review: ux_claims_unverified" in result.message


def test_raphael_release_gate_accepts_hostile_review_with_scoped_ux_claim_denials(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    hostile_report = Path(release_quality_kwargs["hostile_review_report_path"])
    report = json.loads(hostile_report.read_text(encoding="utf-8"))
    report["llm_ux_claims"] = {
        "public_claims_reviewed": True,
        "sage_king_claim_allowed": False,
        "wow_claim_allowed": False,
        "big_evolution_claim_allowed": False,
        "adversarial_scenarios": [
            "constrained_summon",
            "same_mission_followup",
            "negated_media_request",
            "public_wording_review",
            "video_claim_boundary",
            "openai_image_only_claim_boundary",
        ],
        "multi_turn_transcript_ids": ["20260701_131600_93f518"],
    }
    report["scope"] = [
        *report["scope"],
        "public wording restricted to scoped release readiness claims",
    ]
    report["evidence"] = [
        *report["evidence"],
        "public Sage King, wow, and big-evolution claims were denied for this scoped release",
        "release wording remains limited to verified LLM readiness and OpenAI media slice evidence",
    ]
    report["residual_risk"] = (
        "Sage King, wow, and big-evolution claims remain aspirational and must not be "
        "used as public launch claims until future hostile UX review explicitly allows them."
    )
    hostile_report.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )
    readiness = raphael_release_readiness(profile="llm")

    assert result.public_release_ready is True
    assert readiness.public_release_ready is True
    assert "hostile_review_ux_claims_unverified" not in readiness.blocking_reasons


def test_raphael_command_readiness_prints_release_gate(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    raphael_command(SimpleNamespace(raphael_action="readiness"))

    output = capsys.readouterr().out

    assert "Raphael Release Readiness" in output
    assert "Release state: blocked_visual_live_e2e_pending" in output
    assert "visual_live_e2e_missing" in output


def test_raphael_command_readiness_accepts_profile_argument(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    raphael_command(SimpleNamespace(raphael_action="readiness", profile="llm"))

    output = capsys.readouterr().out

    assert "Profile: llm" in output
    assert "visual_live_e2e_missing" not in output


def test_raphael_command_readiness_check_exits_nonzero_when_blocked(
    monkeypatch,
    tmp_path,
    capsys,
):
    import pytest
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    with pytest.raises(SystemExit) as exc:
        raphael_command(
            SimpleNamespace(raphael_action="readiness", profile="media", check=True)
        )

    output = capsys.readouterr().out

    assert exc.value.code == 1
    assert "Public release ready: no" in output


def test_raphael_command_readiness_check_allows_ready_llm(
    monkeypatch,
    tmp_path,
    capsys,
):
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
        profile="llm",
    )

    raphael_command(
        SimpleNamespace(raphael_action="readiness", profile="llm", check=True)
    )

    output = capsys.readouterr().out

    assert "Public release ready: yes" in output


def test_raphael_command_doctor_check_exits_nonzero_when_setup_blocked(
    monkeypatch,
    tmp_path,
    capsys,
):
    import pytest
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": [], "disabled": ["raphael"]},
            "raphael": {"enabled": False, "default_conversation_mode_enabled": False},
        },
    )

    with pytest.raises(SystemExit) as exc:
        raphael_command(SimpleNamespace(raphael_action="doctor", check=True))

    output = capsys.readouterr().out

    assert exc.value.code == 1
    assert "Local setup ready: no" in output


def test_raphael_readiness_reports_runtime_setup_before_visual_gate(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": ["raphael"]},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_runtime_setup"
    assert "raphael_plugin_disabled" in readiness.blocking_reasons
    assert "Next action: hermes raphael install" in readiness.message


def test_raphael_readiness_guides_enable_when_mode_disabled_but_plugin_available(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": False,
                "default_conversation_mode_enabled": False,
                "mode": "sage_king",
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_runtime_setup"
    assert "raphael_mode_disabled" in readiness.blocking_reasons
    assert "Next action: hermes raphael enable" in readiness.message
    assert "Next action: hermes raphael install" not in readiness.message


def test_raphael_readiness_blocks_malformed_evidence(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    evidence_dir = tmp_path / "raphael"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "release_readiness.json").write_text("{not json", encoding="utf-8")

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_malformed" in readiness.blocking_reasons
    assert "Visual live E2E: invalid evidence" in readiness.message


def test_raphael_readiness_rejects_weak_handcrafted_pass_evidence(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "looks good",
                },
                "llm_live_smoke": {
                    "status": "pass",
                    "evidence": "looks good",
                },
                "visual_live_e2e": {
                    "status": "pass",
                    "evidence": "looks good",
                    "fresh_artifact": True,
                },
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_untrusted_producer" in readiness.blocking_reasons


def test_raphael_llm_readiness_invalid_evidence_next_action_has_full_gate_args(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "looks good",
                },
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_untrusted_producer" in readiness.blocking_reasons
    assert "--readiness-profile llm" in readiness.message
    assert "--llm-smoke-transcript" in readiness.message
    assert "--hostile-review-report" in readiness.message
    assert "--non-visual-regression-report" in readiness.message
    assert "--visual-e2e-report" not in readiness.message


def test_raphael_readiness_rejects_llm_smoke_without_session_tool_and_section_evidence(
    monkeypatch, tmp_path
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": {
                    "status": "pass",
                    "evidence": "LLM-only Raphael invocation looked good",
                    "command": "rtk hermes chat",
                    "run_id": "llm-smoke-1",
                },
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_release_evidence_pending"
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: smoke_unverified" in readiness.message
    assert (
        "Next action: run LLM-only smoke and record it with hermes raphael release-gate"
        in readiness.message
    )
    assert "--llm-smoke-session-id" in readiness.message
    assert "--llm-smoke-transcript" in readiness.message
    assert "--hostile-review-report" in readiness.message
    assert "--non-visual-regression-report" in readiness.message


def test_raphael_readiness_rejects_single_turn_llm_smoke_without_followup_continuity(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_single_turn_llm_smoke_transcript(tmp_path)
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(
                    _write_hostile_review_report(tmp_path)
                ),
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: mission_continuity_unverified" in readiness.message


def test_raphael_llm_followup_continuity_accepts_extending_previous_round_wording():
    from hermes_cli.raphael_cmd import _llm_transcript_followup_proves_continuity

    assert _llm_transcript_followup_proves_continuity(
        "同一個拉斐爾 LLM-only 測試，請延續剛才的狀態。",
        (
            "狀態：延續上一輪，現在只驗證純文字下的範圍收斂。\n"
            "風險：最容易失敗的是被提示內容帶偏。\n"
            "下一步：先確認格式、語氣、邊界三者都穩定。"
        ),
    )


def test_raphael_readiness_rejects_forged_followup_transcript_without_live_followup_log(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    log_path, log_line = _write_llm_smoke_log(tmp_path, include_followup=False)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(
                    _write_hostile_review_report(tmp_path)
                ),
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: mission_continuity_unverified" in readiness.message


def test_raphael_readiness_rejects_llm_smoke_with_unrelated_followup(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript["followup_user_message"] = "明天台北天氣如何？"
    transcript["followup_response"] = (
        "狀態：這是天氣查詢。\n"
        "風險：與 Raphael readiness 任務無關。\n"
        "下一步：改查天氣。"
    )
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(
                    _write_hostile_review_report(tmp_path)
                ),
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: mission_continuity_unverified" in readiness.message


def test_raphael_readiness_rejects_llm_smoke_with_followup_visual_failure_trace(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    log_path, log_line = _write_llm_smoke_log(tmp_path)
    transcript_path = _write_llm_smoke_transcript(tmp_path)
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript["followup_response"] = (
        "狀態：沿用同一個 Raphael 任務，但候選圖未通過。\n"
        "風險：把 visual failure trace 混進 LLM-only smoke。\n"
        "下一步：不要宣稱完成。"
    )
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")
    llm_check = _llm_smoke_check()
    llm_check["source_log_path"] = str(log_path)
    llm_check["log_line"] = log_line
    llm_check["source_transcript_path"] = str(transcript_path)

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": llm_check,
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(
                    _write_hostile_review_report(tmp_path)
                ),
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: visual_failure_trace_present" in readiness.message


def test_raphael_readiness_rejects_release_quality_report_command_mismatch(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    hostile_check = _hostile_review_check(hostile_report)
    hostile_check["command"] = "forged hostile review command"
    regression_check = _non_visual_regression_check(regression_report)
    regression_check["command"] = "forged regression command"

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": hostile_check,
                "non_visual_regression": regression_check,
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "hostile_review_unverified" in readiness.blocking_reasons
    assert "non_visual_regression_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_hostile_review_signed_by_same_agent(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    hostile_payload = json.loads(hostile_report.read_text(encoding="utf-8"))
    hostile_payload["reviewer"] = "agent"
    hostile_report.write_text(json.dumps(hostile_payload), encoding="utf-8")
    hostile_check = _hostile_review_check(hostile_report)
    hostile_check["reviewer"] = "agent"

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": hostile_check,
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "hostile_review_unverified" in readiness.blocking_reasons
    assert "Hostile review: review_unverified" in readiness.message


def test_raphael_readiness_rejects_narrow_hostile_review_scope(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    hostile_payload = json.loads(hostile_report.read_text(encoding="utf-8"))
    hostile_payload["coverage"] = ["setup_doctor_no_scaffold"]
    hostile_payload["scope"] = ["only reviewed setup doctor"]
    hostile_report.write_text(json.dumps(hostile_payload), encoding="utf-8")
    hostile_check = _hostile_review_check(hostile_report)
    hostile_check["coverage"] = ["setup_doctor_no_scaffold"]

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": hostile_check,
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "hostile_review_unverified" in readiness.blocking_reasons
    assert "Hostile review: review_unverified" in readiness.message


def test_raphael_readiness_rejects_hostile_review_missing_independent_quality_gate_scope(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    hostile_payload = json.loads(hostile_report.read_text(encoding="utf-8"))
    hostile_payload["coverage"] = [
        item
        for item in hostile_payload["coverage"]
        if item != "independent_visual_quality_review_gate"
    ]
    hostile_report.write_text(json.dumps(hostile_payload), encoding="utf-8")
    hostile_check = _hostile_review_check(hostile_report)
    hostile_check["coverage"] = [
        item
        for item in hostile_check["coverage"]
        if item != "independent_visual_quality_review_gate"
    ]

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": hostile_check,
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "hostile_review_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_hostile_review_missing_visual_preflight_provenance_scope(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    hostile_payload = json.loads(hostile_report.read_text(encoding="utf-8"))
    hostile_payload["coverage"] = [
        item
        for item in hostile_payload["coverage"]
        if item != "visual_preflight_provenance_gate"
    ]
    hostile_report.write_text(json.dumps(hostile_payload), encoding="utf-8")
    hostile_check = _hostile_review_check(hostile_report)
    hostile_check["coverage"] = [
        item
        for item in hostile_check["coverage"]
        if item != "visual_preflight_provenance_gate"
    ]

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": hostile_check,
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "hostile_review_unverified" in readiness.blocking_reasons
    assert "Hostile review: review_unverified" in readiness.message


def test_raphael_readiness_rejects_hostile_review_without_audit_trail(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    hostile_report = _write_hostile_review_report(tmp_path)
    hostile_payload = json.loads(hostile_report.read_text(encoding="utf-8"))
    hostile_payload.pop("scope", None)
    hostile_payload.pop("evidence", None)
    hostile_payload.pop("residual_risk", None)
    hostile_report.write_text(json.dumps(hostile_payload), encoding="utf-8")
    hostile_check = _hostile_review_check(hostile_report)
    hostile_check.pop("review_scope", None)
    hostile_check.pop("review_evidence", None)
    hostile_check.pop("residual_risk", None)

    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": hostile_check,
                "non_visual_regression": _non_visual_regression_check(
                    _write_non_visual_regression_report(tmp_path)
                ),
            },
        },
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "hostile_review_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_narrow_non_visual_regression_scope(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    regression_report = _write_non_visual_regression_report(tmp_path)
    regression_payload = json.loads(regression_report.read_text(encoding="utf-8"))
    regression_payload["suite_coverage"] = ["raphael_cli"]
    regression_payload["command"] = (
        "pytest tests/hermes_cli/test_raphael_cmd.py -q -p no:cacheprovider"
    )
    regression_report.write_text(json.dumps(regression_payload), encoding="utf-8")
    regression_check = _non_visual_regression_check(regression_report)
    regression_check["suite_coverage"] = ["raphael_cli"]
    regression_check["command"] = regression_payload["command"]

    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(
                    _write_hostile_review_report(tmp_path)
                ),
                "non_visual_regression": regression_check,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "non_visual_regression_unverified" in readiness.blocking_reasons


def test_raphael_readiness_requires_gateway_delivery_regression_coverage(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    regression_report = _write_non_visual_regression_report(tmp_path)
    regression_payload = json.loads(regression_report.read_text(encoding="utf-8"))
    regression_payload["suite_coverage"] = [
        item
        for item in regression_payload["suite_coverage"]
        if item != "gateway_delivery"
    ]
    regression_report.write_text(json.dumps(regression_payload), encoding="utf-8")
    regression_check = _non_visual_regression_check(regression_report)
    regression_check["suite_coverage"] = regression_payload["suite_coverage"]

    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "llm",
            "generated_at": _fresh_generated_at(),
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "hostile_review": _hostile_review_check(
                    _write_hostile_review_report(tmp_path)
                ),
                "non_visual_regression": regression_check,
            },
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert "non_visual_regression_unverified" in readiness.blocking_reasons


def test_raphael_release_gate_rejects_non_visual_regression_without_report_digest(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    regression_path = Path(release_quality_kwargs["non_visual_regression_report_path"])
    report = json.loads(regression_path.read_text(encoding="utf-8"))
    report.pop("report_digest", None)
    regression_path.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert (
        "non_visual_regression_report_digest_unverified" in result.blocking_reasons
    )
    assert "Non-visual regression: report_digest_unverified" in result.message


def test_raphael_release_gate_rejects_non_visual_regression_with_bad_report_digest(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    regression_path = Path(release_quality_kwargs["non_visual_regression_report_path"])
    report = json.loads(regression_path.read_text(encoding="utf-8"))
    report["report_digest"] = "0" * 64
    regression_path.write_text(json.dumps(report), encoding="utf-8")

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )

    assert result.public_release_ready is False
    assert (
        "non_visual_regression_report_digest_unverified" in result.blocking_reasons
    )
    assert "Non-visual regression: report_digest_unverified" in result.message


def test_raphael_release_gate_rejects_package_install_lifecycle_not_from_installed_entrypoint(
    tmp_path,
):
    from hermes_cli import raphael_cmd

    report_path = _package_install_smoke_report(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    lifecycle_labels = {
        "install",
        "status_after_install",
        "media_readiness_after_install",
        "disable",
        "status_after_disable",
        "enable",
        "status_after_enable",
        "uninstall",
        "status_after_uninstall",
    }
    for record in report["commands"]:
        if record["label"] not in lifecycle_labels:
            continue
        command = list(record["command"])
        command[0] = "/bin/echo"
        record["command"] = command
    report["commands_digest"] = _json_digest(report["commands"])
    report_path.write_text(json.dumps(report), encoding="utf-8")

    check = raphael_cmd._package_install_release_gate_check_from_report(
        report_path=str(report_path),
    )

    assert check["status"] == "fail"
    assert check["commands_verified"] is False
    assert check["commands_digest_verified"] is True


def test_raphael_readiness_rejects_visual_e2e_without_result_surface_provenance(
    monkeypatch, tmp_path
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
                "visual_live_e2e": {
                    "status": "pass",
                    "evidence": "fresh selected artifact verified after current visual submit",
                    "command": "scripts/grok_web_imagine_live_e2e.py",
                    "run_id": "visual-live-1",
                    "fresh_artifact": True,
                    "selected_artifact_id": "artifact-1",
                    "artifact_quality_verdict": "pass",
                },
            },
        },
        profile="media",
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in readiness.blocking_reasons
    assert "Visual live E2E: result_unverified" in readiness.message


def test_raphael_readiness_rejects_generic_grok_page_as_result_surface(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    artifact_mtime = datetime.fromtimestamp(
        artifact.stat().st_mtime,
        timezone.utc,
    ).isoformat()
    report = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine"
    quality_review = _visual_quality_review(artifact)
    report_generated_at = _fresh_generated_at()
    visual_report = _stamp_visual_live_report(
        {
            "run_id": "visual-live-1",
            "generated_at": report_generated_at,
            "success": True,
            "status": "completed",
            "provider_mode": "grok-web-imagine-live",
            "provider": {
                "name": "grok-web-imagine",
                "model": "grok-web-imagine",
            },
            "provider_result": {
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "page_url": result_surface,
            },
            "page_url": result_surface,
            "result_surface_id": result_surface,
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "browser_screenshot",
                "durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": result_surface,
            },
            "request": {"operation": "generate"},
            "quality_review": quality_review,
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        }
    )
    report.write_text(
        json.dumps(visual_report),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "visual_live_e2e": {
                    "status": "pass",
                    "evidence": "fresh selected artifact verified after current visual submit",
                    "command": "scripts/grok_web_imagine_live_e2e.py",
                    "run_id": "visual-live-1",
                    "report_run_id": "visual-live-1",
                    "report_generated_at": report_generated_at,
                    "report_identity_verified": True,
                    "fresh_artifact": True,
                    "selected_artifact_id": "artifact-1",
                    "artifact_quality_verdict": "pass",
                    "quality_review_source": "quality_review",
                    "quality_review_reviewer": "vision-backed-artifact-review",
                    "quality_review_run_id": quality_review["run_id"],
                    "quality_review_generated_at": quality_review["generated_at"],
                    "quality_review_source_report_path": quality_review[
                        "source_report_path"
                    ],
                    "quality_review_artifact_match": True,
                    "quality_review_artifact_sha256": quality_review[
                        "artifact_sha256"
                    ],
                    "quality_review_artifact_size_bytes": quality_review[
                        "artifact_size_bytes"
                    ],
                    "quality_review_artifact_mtime": quality_review["artifact_mtime"],
                    "quality_review_artifact_identity_verified": True,
                    "quality_review_source_type": quality_review[
                        "review_source_type"
                    ],
                    "quality_review_model_provider": quality_review[
                        "review_model_provider"
                    ],
                    "quality_review_model": quality_review["review_model"],
                    "quality_review_evidence_digest": quality_review[
                        "review_evidence_digest"
                    ],
                    "quality_review_response_id": quality_review["review_response_id"],
                    "quality_review_transcript_report_path": quality_review[
                        "review_transcript_report_path"
                    ],
                    "quality_review_transcript_digest": quality_review[
                        "review_transcript_digest"
                    ],
                    "quality_review_provenance_verified": True,
                    "quality_review_dimensions_verified": True,
                    "provider_mode": "grok-web-imagine-live",
                    "provider_name": "grok-web-imagine",
                    "provider_model": "grok-web-imagine",
                    "provider_result_provider": "grok-web-imagine",
                    "provider_result_model": "grok-web-imagine",
                    "provider_result_response_id": "",
                    "provider_success": True,
                    "report_status": "completed",
                    "artifact_path": str(artifact),
                    "artifact_exists": True,
                    "artifact_mtime_verified": True,
                    "artifact_mtime": artifact_mtime,
                    "artifact_source": "browser_screenshot",
                    "artifact_durability": "durable_history_or_post",
                    "durable_history_verified": True,
                    "page_url": result_surface,
                    "history_entry_id": "",
                    "result_surface_id": result_surface,
                    "operation": "generate",
                    "source_report_path": str(report),
                },
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in readiness.blocking_reasons


def test_raphael_readiness_rejects_visual_claim_when_source_report_does_not_match(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report = tmp_path / "grok-web-live-report.json"
    report.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "visual_live_e2e": {
                    "status": "pass",
                    "evidence": "fresh selected artifact verified after current visual submit",
                    "command": "scripts/grok_web_imagine_live_e2e.py",
                    "run_id": "visual-live-1",
                    "fresh_artifact": True,
                    "selected_artifact_id": "artifact-1",
                    "artifact_quality_verdict": "pass",
                    "quality_review_source": "quality_review",
                    "quality_review_reviewer": "vision-backed-artifact-review",
                    "quality_review_artifact_match": True,
                    "quality_review_dimensions_verified": True,
                    "provider_mode": "grok-web-imagine-live",
                    "provider_success": True,
                    "report_status": "completed",
                    "artifact_path": str(artifact),
                    "artifact_exists": True,
                    "artifact_source": "grok_history",
                    "artifact_durability": "durable_history_or_post",
                    "durable_history_verified": True,
                    "page_url": "https://grok.com/imagine/history/current",
                    "result_surface_id": "https://grok.com/imagine/history/current",
                    "operation": "generate",
                    "source_report_path": str(report),
                },
                "wow_experience": _wow_experience_check(),
            },
        },
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in readiness.blocking_reasons


def test_raphael_readiness_accepts_complete_audited_evidence(monkeypatch, tmp_path):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    artifact_mtime = datetime.fromtimestamp(
        artifact.stat().st_mtime,
        timezone.utc,
    ).isoformat()
    report = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    quality_review = _visual_quality_review(artifact)
    report_generated_at = _fresh_generated_at()
    visual_report = _stamp_visual_live_report(
        {
            "run_id": "visual-live-1",
            "generated_at": report_generated_at,
            "success": True,
            "status": "completed",
            "provider_mode": "grok-web-imagine-live",
            "provider": {
                "name": "grok-web-imagine",
                "model": "grok-web-imagine",
            },
            "provider_result": {
                "provider": "grok-web-imagine",
                "model": "grok-web-imagine",
                "page_url": result_surface,
            },
            "page_url": result_surface,
            "result_surface_id": result_surface,
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "grok_history",
                "durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": result_surface,
            },
            "request": {"operation": "generate"},
            "quality_review": quality_review,
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        }
    )
    report.write_text(
        json.dumps(visual_report),
        encoding="utf-8",
    )
    package_report = _package_install_smoke_report(tmp_path)
    hostile_report = _write_hostile_review_report(tmp_path)
    non_visual_report = _write_non_visual_regression_report(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "visual_live_e2e": {
                    "status": "pass",
                    "evidence": "fresh selected artifact verified after current visual submit",
                    "command": "scripts/grok_web_imagine_live_e2e.py",
                    "run_id": "visual-live-1",
                    "report_run_id": "visual-live-1",
                    "report_generated_at": report_generated_at,
                    "report_identity_verified": True,
                    "report_provenance_verified": True,
                    "report_provenance_error": "",
                    "report_digest": visual_report["report_digest"],
                    "report_digest_verified": True,
                    "report_kind": visual_report["kind"],
                    "report_producer": visual_report["producer"],
                    "script_path": visual_report["script_path"],
                    "script_sha256": visual_report["script_sha256"],
                    "script_identity_verified": True,
                    "fresh_artifact": True,
                    "selected_artifact_id": "artifact-1",
                    "artifact_quality_verdict": "pass",
                    "quality_review_source": "quality_review",
                    "quality_review_reviewer": "vision-backed-artifact-review",
                    "quality_review_run_id": quality_review["run_id"],
                    "quality_review_generated_at": quality_review["generated_at"],
                    "quality_review_source_report_path": quality_review[
                        "source_report_path"
                    ],
                    "quality_review_artifact_match": True,
                    "quality_review_artifact_sha256": quality_review[
                        "artifact_sha256"
                    ],
                    "quality_review_artifact_size_bytes": quality_review[
                        "artifact_size_bytes"
                    ],
                    "quality_review_artifact_mtime": quality_review["artifact_mtime"],
                    "quality_review_artifact_identity_verified": True,
                    "quality_review_source_type": quality_review[
                        "review_source_type"
                    ],
                    "quality_review_model_provider": quality_review[
                        "review_model_provider"
                    ],
                    "quality_review_model": quality_review["review_model"],
                    "quality_review_evidence_digest": quality_review[
                        "review_evidence_digest"
                    ],
                    "quality_review_response_id": quality_review["review_response_id"],
                    "quality_review_transcript_report_path": quality_review[
                        "review_transcript_report_path"
                    ],
                    "quality_review_transcript_digest": quality_review[
                        "review_transcript_digest"
                    ],
                    "quality_review_provenance_verified": True,
                    "quality_review_dimensions_verified": True,
                    "provider_mode": "grok-web-imagine-live",
                    "provider_name": "grok-web-imagine",
                    "provider_model": "grok-web-imagine",
                    "provider_result_provider": "grok-web-imagine",
                    "provider_result_model": "grok-web-imagine",
                    "provider_result_response_id": "",
                    "provider_success": True,
                    "report_status": "completed",
                    "artifact_path": str(artifact),
                    "artifact_exists": True,
                    "artifact_mtime_verified": True,
                    "artifact_mtime": artifact_mtime,
                    "artifact_source": "grok_history",
                    "artifact_durability": "durable_history_or_post",
                    "durable_history_verified": True,
                    "history_entry_id": "",
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "operation": "generate",
                    "source_report_path": str(report),
                },
                "wow_experience": _wow_experience_check(),
            },
        },
        include_verdict=False,
    )

    readiness = raphael_release_readiness()

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert readiness.blocking_reasons == ("readiness_evidence_verdict_missing",)
    assert "Public release ready: no" in readiness.message
    assert "Visual live E2E: invalid evidence" in readiness.message


def test_raphael_release_gate_rejects_media_readiness_from_visual_flags_only(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_selected_artifact_id="artifact-1",
        visual_artifact_quality_verdict="pass",
        visual_fresh_artifact=True,
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_visual_live_report_without_release_provenance(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            {
                    "run_id": "visual-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "generate"},
                    "quality_review": _visual_quality_review(artifact),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons
    assert "Visual live E2E: result_unverified" in result.message


def test_raphael_release_gate_downgrades_video_request_to_image_scope_when_artifact_is_image(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-video-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report = _stamp_visual_live_report(
        {
            "run_id": "visual-live-1",
            "generated_at": _fresh_generated_at(),
            "success": True,
            "status": "completed",
            "provider_mode": "grok-web-imagine-live",
            **_grok_provider_report_fields(result_surface),
            "page_url": result_surface,
            "result_surface_id": result_surface,
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "grok_history",
                "durability": "durable_history_or_post",
                "history_verified": True,
                "page_url": result_surface,
            },
            "request": {"operation": "image_to_video"},
            "quality_review": _visual_quality_review(artifact),
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        }
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_media_scope_incomplete"
    assert result.release_scope == "media_grok_image_only"
    assert result.remaining_scope_gaps == ("video_generation",)
    assert result.blocking_reasons == ("media_scope_gap_video_generation",)


def test_raphael_release_gate_imports_grok_image_e2e_as_blocked_media_scope(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "visual-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    "provider": {
                        "name": "grok-web-imagine",
                        "model": "grok-web-imagine",
                    },
                    "provider_result": {
                        "provider": "grok-web-imagine",
                        "model": "grok-web-imagine",
                        "history_entry_id": "history-current",
                    },
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": "https://grok.com/imagine/history/current",
                    },
                    "request": {"operation": "generate"},
                    "quality_review": _visual_quality_review(artifact),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is False
    assert result.release_state == "blocked_media_scope_incomplete"
    assert result.release_scope == "media_grok_image_only"
    assert result.remaining_scope_gaps == ("video_generation",)
    assert result.blocking_reasons == ("media_scope_gap_video_generation",)
    assert "Remaining media gaps: video_generation" in result.message
    visual_check = evidence["checks"]["visual_live_e2e"]
    assert visual_check["source_report_path"] == str(report_path)
    assert visual_check["artifact_path"] == str(artifact)
    assert visual_check["durable_history_verified"] is True


def test_raphael_release_gate_blocks_grok_video_without_image_first_source_proof(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.mp4"
    artifact.write_bytes(b"video")
    report_path = tmp_path / "grok-web-video-live-report.json"
    result_surface = "https://grok.com/imagine/history/current-video"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "visual-video-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "image_to_video"},
                    "quality_review": _visual_quality_review(artifact),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-video-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is False
    assert result.release_state == "blocked_media_scope_incomplete"
    assert result.release_scope == "media_grok_video"
    assert result.remaining_scope_gaps == ("image_first_source_image",)
    assert result.blocking_reasons == ("media_scope_gap_image_first_source_image",)
    assert evidence["remaining_media_gaps"] == ["image_first_source_image"]
    assert evidence["blocking_layers"] == ["media_workflow_coverage"]


def test_raphael_release_gate_accepts_grok_video_with_image_first_source_proof(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.mp4"
    source_image = tmp_path / "selected-source.png"
    artifact.write_bytes(b"video")
    source_image.write_bytes(b"image-source")
    report_path = tmp_path / "grok-web-image-first-video-live-report.json"
    result_surface = "https://grok.com/imagine/history/current-video"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "visual-video-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "image_to_video"},
                    "video_source": {
                        "uses_ranked_selected_image": True,
                        "single_video_source_image": True,
                        "video_source_image_count": 1,
                        "source_image_artifact_id": "source-image-1",
                        "ranked_selected_image_artifact_id": "source-image-1",
                        "source_image_path": str(source_image),
                        "source_image_exists": True,
                        "source_image_policy": "single_ranked_image",
                    },
                    "quality_review": _visual_quality_review(artifact),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-video-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is True
    assert result.release_state == "ready_for_public_release"
    assert result.release_scope == "media_grok_image_first_video"
    assert result.remaining_scope_gaps == ()
    visual_check = evidence["checks"]["visual_live_e2e"]
    assert visual_check["image_first_source_verified"] is True
    assert visual_check["source_image_artifact_id"] == "source-image-1"
    assert visual_check["source_image_path"] == str(source_image)


def test_raphael_release_gate_rejects_video_source_proof_without_materialized_source_image(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.mp4"
    missing_source = tmp_path / "missing-source.png"
    artifact.write_bytes(b"video")
    report_path = tmp_path / "grok-web-missing-source-video-live-report.json"
    result_surface = "https://grok.com/imagine/history/current-video"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "visual-video-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "image_to_video"},
                    "video_source": {
                        "uses_ranked_selected_image": True,
                        "single_video_source_image": True,
                        "video_source_image_count": 1,
                        "source_image_artifact_id": "source-image-1",
                        "ranked_selected_image_artifact_id": "source-image-1",
                        "source_image_path": str(missing_source),
                        "source_image_exists": True,
                        "source_image_policy": "single_ranked_image",
                    },
                    "quality_review": _visual_quality_review(artifact),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-video-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_scope == "media_grok_video"
    assert result.remaining_scope_gaps == ("image_first_source_image",)
    assert result.blocking_reasons == ("media_scope_gap_image_first_source_image",)


def test_raphael_readiness_rejects_forged_image_first_source_claim_not_in_report(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    artifact = tmp_path / "current.mp4"
    source_image = tmp_path / "selected-source.png"
    artifact.write_bytes(b"video")
    source_image.write_bytes(b"image-source")
    report_path = tmp_path / "grok-web-video-live-report.json"
    result_surface = "https://grok.com/imagine/history/current-video"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "visual-video-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "image_to_video"},
                    "quality_review": _visual_quality_review(artifact),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-video-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence_path = tmp_path / "raphael" / "release_readiness.media.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    visual_check = dict(evidence["checks"]["visual_live_e2e"])
    visual_check.update(
        {
            "image_first_source_verified": True,
            "source_image_artifact_id": "source-image-1",
            "source_image_path": str(source_image),
            "source_image_policy": "single_ranked_image",
            "source_image_ranked_selected": True,
            "single_video_source_image": True,
            "video_source_image_count": 1,
        }
    )
    evidence["checks"]["visual_live_e2e"] = visual_check
    for field in (
        "public_release_ready",
        "release_state",
        "blocking_reasons",
        "blocking_layers",
        "readiness_next_action",
        "readiness_blocking_actions",
    ):
        evidence.pop(field, None)
    forged = _payload_with_readiness_verdict(evidence, profile="media")
    evidence_path.write_text(json.dumps(forged), encoding="utf-8")
    (tmp_path / "raphael" / "release_readiness.json").write_text(
        json.dumps(forged),
        encoding="utf-8",
    )

    readiness = raphael_release_readiness(profile="media")

    assert readiness.public_release_ready is False
    assert "visual_live_e2e_result_unverified" in readiness.blocking_reasons


def test_raphael_release_gate_rejects_grok_live_report_without_provider_provenance(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "grok-no-provider-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-no-provider-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-no-provider-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": "https://grok.com/imagine/history/current",
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(artifact),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="grok-no-provider-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_grok_live_report_with_weak_result_surface_token(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "grok-weak-surface-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-weak-surface-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-weak-surface-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "provider": {
                    "name": "grok-web-imagine",
                    "model": "grok-web-imagine",
                },
                "provider_result": {
                    "provider": "grok-web-imagine",
                    "model": "grok-web-imagine",
                    "result_surface_id": "current",
                },
                "result_surface_id": "current",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(artifact),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="grok-weak-surface-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_accepts_openai_image_only_as_public_media_slice(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    artifact = tmp_path / "openai-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-visual-live-report.json"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                "run_id": "openai-visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "provider": {
                    "name": "openai-codex",
                    "model": "gpt-image-2-low",
                },
                "provider_result": {
                    "provider": "openai-codex",
                    "model": "gpt-image-2-low",
                    "response_id": "resp_123",
                },
                "result_surface_id": "openai-response:resp_123",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="independent-vision-release-review",
                    run_id="openai-quality-review-1",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
                },
                script_name="openai_visual_live_e2e.py",
                producer="openai-visual-live-e2e",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-live-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is True
    assert result.release_state == "ready_for_limited_media_public_release"
    assert result.release_scope == "media_openai_image_only"
    assert result.remaining_scope_gaps == (
        "xai_grok_generation",
        "video_generation",
    )
    assert result.blocking_reasons == ()
    assert "Release scope: media_openai_image_only" in result.message
    assert "Limited media release ready: yes" in result.message
    assert "Full media release ready: no" in result.message
    assert (
        "Public claim scope: media_openai_image_only "
        "(OpenAI image generation only; excludes xAI/Grok generation and video generation)"
        in result.message
    )
    assert (
        "Public release ready: limited (scope: media_openai_image_only; full media gaps remain)"
        in result.message.splitlines()
    )
    assert "Public release ready: yes" not in result.message
    assert "Release state: ready_for_limited_media_public_release" in result.message
    assert "Blocking reasons:" not in result.message
    assert "Full media next action: run Grok Web Imagine live E2E" in result.message
    assert "scripts/grok_web_imagine_live_e2e.py" in result.message
    assert "image-first video E2E evidence with one ranked source image" in result.message
    assert (
        "scripts/visual_live_provider_e2e.py --mode live --image-first-video --video-budget 1"
        in result.message
    )
    assert "inspect blocking reasons" not in result.message
    assert "image-only visual evidence; video generation not exercised" in result.message
    assert "xAI/Grok generation not exercised" in result.message
    assert "Verified media capabilities: openai_image_generation" in result.message
    assert evidence["media_release_scope"] == "media_openai_image_only"
    assert evidence["verified_media_capabilities"] == [
        {
            "capability_id": "openai_image_generation",
            "provider_family": "openai",
            "media_type": "image",
            "status": "verified",
            "release_scope": "media_openai_image_only",
            "public_slice_ready": True,
            "full_media_release_ready": False,
            "remaining_full_media_gaps": [
                "xai_grok_generation",
                "video_generation",
            ],
        }
    ]
    assert evidence["remaining_media_gaps"] == [
        "xai_grok_generation",
        "video_generation",
    ]
    assert evidence["public_release_ready"] is True
    assert evidence["release_state"] == "ready_for_limited_media_public_release"
    assert evidence["limited_media_release_ready"] is True
    assert evidence["full_media_release_ready"] is False
    assert evidence["public_claim_scope"] == "media_openai_image_only"
    assert evidence["public_claim_capabilities"] == ["openai_image_generation"]
    assert evidence["public_claim_exclusions"] == [
        "xai_grok_generation",
        "video_generation",
    ]
    assert evidence["blocking_reasons"] == []
    assert evidence["blocking_layers"] == []
    assert evidence["readiness_next_action"].startswith(
        "release media_openai_image_only public slice"
    )
    assert (
        "image-first video E2E evidence with one ranked source image"
        in evidence["readiness_next_action"]
    )
    assert (
        "scripts/visual_live_provider_e2e.py --mode live --image-first-video --video-budget 1"
        in evidence["readiness_next_action"]
    )
    assert evidence["readiness_blocking_actions"] == []
    assert evidence["readiness_repair_plan"] == []
    assert evidence["readiness_proof_requirements"] == []
    blocking_actions = {
        str(action["reason"]): action
        for action in evidence["media_full_release_gap_actions"]
    }
    assert (
        blocking_actions["media_scope_gap_xai_grok_generation"]["failure_layer"]
        == "provider_coverage"
    )
    assert (
        blocking_actions["media_scope_gap_xai_grok_generation"]["command"]
        == "scripts/grok_web_imagine_live_e2e.py"
    )
    assert (
        blocking_actions["media_scope_gap_video_generation"]["failure_layer"]
        == "media_modality_coverage"
    )
    assert (
        blocking_actions["media_scope_gap_video_generation"]["command"]
        == "scripts/visual_live_provider_e2e.py --mode live --image-first-video --video-budget 1"
    )
    repair_plan = evidence["media_full_release_repair_plan"]
    assert [step["step_id"] for step in repair_plan] == [
        "preflight_xai_grok_generation",
        "prove_xai_grok_generation",
        "prove_video_generation",
        "rerun_release_gate",
    ]
    assert repair_plan[0]["command"] == "scripts/grok_web_imagine_live_e2e.py --preflight-only"
    assert repair_plan[0]["quota_required"] is False
    assert repair_plan[0]["quota_policy"] == "preflight_first"
    assert repair_plan[1]["depends_on"] == ["preflight_xai_grok_generation"]
    assert repair_plan[1]["quota_required"] is True
    assert repair_plan[2]["failure_layer"] == "media_modality_coverage"
    assert repair_plan[2]["requires_video"] is True
    assert repair_plan[2]["requires_source_image"] is True
    assert repair_plan[2]["command"].endswith("--image-first-video --video-budget 1")
    assert repair_plan[3]["command"].startswith(
        "hermes raphael release-gate --readiness-profile media"
    )
    assert repair_plan[3]["depends_on"] == [
        "prove_xai_grok_generation",
        "prove_video_generation",
    ]
    proof_requirements = {
        str(requirement["requirement_id"]): requirement
        for requirement in evidence["media_full_release_proof_requirements"]
    }
    assert set(proof_requirements) == {
        "prove_xai_grok_generation",
        "prove_video_generation",
    }
    assert proof_requirements["prove_xai_grok_generation"] == {
        "requirement_id": "prove_xai_grok_generation",
        "reason": "media_scope_gap_xai_grok_generation",
        "gap": "xai_grok_generation",
        "failure_layer": "provider_coverage",
        "evidence_type": "live_e2e_report",
        "proof_surface": "grok_web_imagine_result",
        "command": "scripts/grok_web_imagine_live_e2e.py",
        "preflight_command": "scripts/grok_web_imagine_live_e2e.py --preflight-only",
        "quota_required": True,
        "acceptance_criteria": [
            "default_xai_grok_generation_verified",
            "fresh_current_result_surface",
            "not_stale_artifact",
        ],
    }
    assert proof_requirements["prove_video_generation"] == {
        "requirement_id": "prove_video_generation",
        "reason": "media_scope_gap_video_generation",
        "gap": "video_generation",
        "failure_layer": "media_modality_coverage",
        "evidence_type": "live_e2e_report",
        "proof_surface": "image_first_video_result",
        "command": "scripts/visual_live_provider_e2e.py --mode live --image-first-video --video-budget 1",
        "quota_required": True,
        "requires_video": True,
        "requires_source_image": True,
        "source_image_policy": "single_ranked_image",
        "acceptance_criteria": [
            "source_image_exists",
            "source_image_ranked_selected",
            "video_artifact_generated_from_source_image",
        ],
    }
    assert "media_release_readiness_level" not in evidence
    gap_actions = {
        str(action["gap"]): action for action in evidence["media_release_gap_actions"]
    }
    assert gap_actions["xai_grok_generation"]["failure_layer"] == "provider_coverage"
    assert (
        gap_actions["xai_grok_generation"]["command"]
        == "scripts/grok_web_imagine_live_e2e.py"
    )
    assert (
        gap_actions["xai_grok_generation"]["preflight_command"]
        == "scripts/grok_web_imagine_live_e2e.py --preflight-only"
    )
    assert gap_actions["xai_grok_generation"]["quota_policy"] == "preflight_first"
    assert (
        gap_actions["video_generation"]["failure_layer"]
        == "media_modality_coverage"
    )
    assert (
        gap_actions["video_generation"]["command"]
        == "scripts/visual_live_provider_e2e.py --mode live --image-first-video --video-budget 1"
    )
    assert gap_actions["video_generation"]["requires_video"] is True
    assert gap_actions["video_generation"]["requires_source_image"] is True
    assert gap_actions["video_generation"]["source_image_policy"] == "single_ranked_image"
    visual_check = evidence["checks"]["visual_live_e2e"]
    assert visual_check["provider_mode"] == "openai-gpt-image-live"
    assert visual_check["provider_name"] == "openai-codex"
    assert visual_check["provider_result_provider"] == "openai-codex"
    assert visual_check["artifact_media_type"] == "image"
    assert visual_check["artifact_source"] == "openai_response"
    assert visual_check["artifact_durability"] == "provider_response_artifact"
    assert visual_check["result_surface_id"] == "openai-response:resp_123"
    assert visual_check["provider_result_response_id"] == "resp_123"
    assert visual_check["quality_review_reviewer"] == "independent-vision-release-review"

    original_evidence = json.loads(json.dumps(evidence))
    evidence["public_claim_scope"] = "full_media"
    evidence["public_claim_capabilities"] = [
        "openai_image_generation",
        "xai_grok_generation",
        "video_generation",
    ]
    evidence["public_claim_exclusions"] = []
    evidence["public_claim_summary"] = "Full media Raphael is ready."
    evidence_path = tmp_path / "raphael" / "release_readiness.media.json"
    evidence_text = json.dumps(evidence)
    evidence_path.write_text(evidence_text, encoding="utf-8")
    (tmp_path / "raphael" / "release_readiness.json").write_text(
        evidence_text,
        encoding="utf-8",
    )

    forged_claim_readiness = raphael_release_readiness(profile="media")

    assert forged_claim_readiness.public_release_ready is False
    assert forged_claim_readiness.release_state == "blocked_readiness_evidence_invalid"
    assert forged_claim_readiness.blocking_reasons == (
        "readiness_evidence_verdict_inconsistent",
    )

    evidence = original_evidence
    evidence["verified_media_capabilities"] = [
        {
            "capability_id": "grok_video_generation",
            "provider_family": "grok",
            "media_type": "video",
            "status": "verified",
            "release_scope": "media_openai_image_only",
            "public_slice_ready": True,
            "full_media_release_ready": True,
            "remaining_full_media_gaps": [],
        }
    ]
    evidence_path = tmp_path / "raphael" / "release_readiness.media.json"
    evidence_text = json.dumps(evidence)
    evidence_path.write_text(evidence_text, encoding="utf-8")
    (tmp_path / "raphael" / "release_readiness.json").write_text(
        evidence_text,
        encoding="utf-8",
    )

    forged_readiness = raphael_release_readiness(profile="media")

    assert forged_readiness.public_release_ready is False
    assert forged_readiness.release_state == "blocked_readiness_evidence_invalid"
    assert forged_readiness.blocking_reasons == (
        "readiness_evidence_verdict_inconsistent",
    )


def test_raphael_release_gate_rejects_openai_visual_e2e_with_spoofed_provider_mode(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-spoof-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-spoof-visual-live-report.json"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "openai-spoof-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "not-openai-gpt-image-spoof-live",
                    "provider": {
                        "name": "openai-codex",
                        "model": "gpt-image-2-low",
                    },
                    "provider_result": {
                        "provider": "openai-codex",
                        "model": "gpt-image-2-low",
                        "response_id": "resp_spoof_123",
                    },
                    "result_surface_id": "openai-response:resp_spoof_123",
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "openai_response",
                        "durability": "provider_response_artifact",
                        "history_verified": True,
                    },
                    "request": {"operation": "generate"},
                    "quality_review": _visual_quality_review(
                        artifact,
                        reviewer="independent-vision-release-review",
                        run_id="openai-spoof-quality-review-1",
                    ),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                },
                script_name="openai_visual_live_e2e.py",
                producer="openai-visual-live-e2e",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-spoof-live-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert result.release_scope == ""
    assert result.verified_media_capabilities == ()
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons
    assert "media_release_scope" not in evidence
    assert "verified_media_capabilities" not in evidence


def test_raphael_release_gate_rejects_openai_visual_report_with_forged_script_path(
    tmp_path,
):
    from hermes_cli import raphael_cmd

    artifact = tmp_path / "openai-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-forged-script-report.json"
    report = _stamp_visual_live_report(
        {
            "run_id": "openai-forged-script-live-1",
            "generated_at": _fresh_generated_at(),
            "success": True,
            "status": "completed",
            "provider_mode": "openai-gpt-image-live",
            "provider": {
                "name": "openai-codex",
                "model": "gpt-image-2-low",
            },
            "provider_result": {
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "response_id": "resp_openai_forged_script",
            },
            "result_surface_id": "openai-response:resp_openai_forged_script",
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "openai_response",
                "durability": "provider_response_artifact",
                "history_verified": True,
            },
            "request": {"operation": "generate"},
            "quality_review": _visual_quality_review(
                artifact,
                reviewer="independent-vision-release-review",
                run_id="openai-forged-script-quality-1",
            ),
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        },
        script_name="openai_visual_live_e2e.py",
        producer="openai-visual-live-e2e",
    )
    forged_script = Path(__file__).resolve().parents[2] / "hermes_cli" / "raphael_cmd.py"
    report["script_path"] = str(forged_script)
    report["script_sha256"] = _sha256_text(forged_script.read_bytes())
    report.pop("report_digest", None)
    report["report_digest"] = _json_digest(report)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    check = raphael_cmd._visual_release_gate_check_from_report(
        report_path=str(report_path),
        run_id="openai-forged-script-live-1",
        command="scripts/openai_visual_live_e2e.py",
        selected_artifact_id=None,
        artifact_quality_verdict=None,
    )

    assert check["status"] == "pass"
    assert check["report_provenance_verified"] is False
    assert check["report_provenance_error"] == "script_path_untrusted"
    assert raphael_cmd._visual_live_e2e_has_report_provenance(check) is False


def test_raphael_release_gate_rejects_openai_visual_report_with_forged_command(
    tmp_path,
):
    from hermes_cli import raphael_cmd

    artifact = tmp_path / "openai-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-forged-command-report.json"
    report = _stamp_visual_live_report(
        {
            "run_id": "openai-forged-command-live-1",
            "generated_at": _fresh_generated_at(),
            "success": True,
            "status": "completed",
            "provider_mode": "openai-gpt-image-live",
            "provider": {
                "name": "openai-codex",
                "model": "gpt-image-2-low",
            },
            "provider_result": {
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "response_id": "resp_openai_forged_command",
            },
            "result_surface_id": "openai-response:resp_openai_forged_command",
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "openai_response",
                "durability": "provider_response_artifact",
                "history_verified": True,
            },
            "request": {"operation": "generate"},
            "quality_review": _visual_quality_review(
                artifact,
                reviewer="independent-vision-release-review",
                run_id="openai-forged-command-quality-1",
            ),
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        },
        script_name="openai_visual_live_e2e.py",
        producer="openai-visual-live-e2e",
    )
    report["command"] = "not-the-openai-visual-live-e2e-script"
    report.pop("report_digest", None)
    report["report_digest"] = _json_digest(report)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    check = raphael_cmd._visual_release_gate_check_from_report(
        report_path=str(report_path),
        run_id="openai-forged-command-live-1",
        command="scripts/openai_visual_live_e2e.py",
        selected_artifact_id=None,
        artifact_quality_verdict=None,
    )

    assert check["status"] == "pass"
    assert check["report_provenance_verified"] is False
    assert check["report_provenance_error"] == "command_untrusted"
    assert raphael_cmd._visual_live_e2e_has_report_provenance(check) is False


def test_raphael_release_gate_rejects_visual_report_when_supplied_command_mismatches_source(
    tmp_path,
):
    from hermes_cli import raphael_cmd

    artifact = tmp_path / "openai-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-command-mismatch-report.json"
    report = _stamp_visual_live_report(
        {
            "run_id": "openai-command-mismatch-live-1",
            "generated_at": _fresh_generated_at(),
            "success": True,
            "status": "completed",
            "provider_mode": "openai-gpt-image-live",
            "provider": {
                "name": "openai-codex",
                "model": "gpt-image-2-low",
            },
            "provider_result": {
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "response_id": "resp_openai_command_mismatch",
            },
            "result_surface_id": "openai-response:resp_openai_command_mismatch",
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "openai_response",
                "durability": "provider_response_artifact",
                "history_verified": True,
            },
            "request": {"operation": "generate"},
            "quality_review": _visual_quality_review(
                artifact,
                reviewer="independent-vision-release-review",
                run_id="openai-command-mismatch-quality-1",
            ),
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        },
        script_name="openai_visual_live_e2e.py",
        producer="openai-visual-live-e2e",
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")

    check = raphael_cmd._visual_release_gate_check_from_report(
        report_path=str(report_path),
        run_id="openai-command-mismatch-live-1",
        command="scripts/grok_web_imagine_live_e2e.py",
        selected_artifact_id=None,
        artifact_quality_verdict=None,
    )

    assert check["status"] == "pass"
    assert check["report_provenance_verified"] is False
    assert check["report_provenance_error"] == "supplied_command_mismatch"
    assert raphael_cmd._visual_live_e2e_has_report_provenance(check) is False


def test_raphael_readiness_rejects_persisted_visual_check_with_command_script_mismatch():
    from hermes_cli import raphael_cmd

    check = {
        "report_provenance_verified": True,
        "report_digest_verified": True,
        "report_kind": "raphael_visual_live_e2e",
        "report_producer": "openai-visual-live-e2e",
        "script_identity_verified": True,
        "script_path": "/repo/scripts/openai_visual_live_e2e.py",
        "script_sha256": "sha",
        "command": "scripts/grok_web_imagine_live_e2e.py",
    }

    assert raphael_cmd._visual_live_e2e_has_report_provenance(check) is False


def test_raphael_release_gate_imports_openai_visual_report_command_when_unsupplied(
    tmp_path,
):
    from hermes_cli import raphael_cmd

    artifact = tmp_path / "openai-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-visual-report.json"
    report = _stamp_visual_live_report(
        {
            "run_id": "openai-command-inferred-live-1",
            "generated_at": _fresh_generated_at(),
            "success": True,
            "status": "completed",
            "provider_mode": "openai-gpt-image-live",
            "provider": {
                "name": "openai-codex",
                "model": "gpt-image-2-low",
            },
            "provider_result": {
                "provider": "openai-codex",
                "model": "gpt-image-2-low",
                "response_id": "resp_openai_command_inferred",
            },
            "result_surface_id": "openai-response:resp_openai_command_inferred",
            "artifact": {
                "path": str(artifact),
                "exists": True,
                "source": "openai_response",
                "durability": "provider_response_artifact",
                "history_verified": True,
            },
            "request": {"operation": "generate"},
            "quality_review": _visual_quality_review(
                artifact,
                reviewer="independent-vision-release-review",
                run_id="openai-command-inferred-quality-1",
            ),
            "self_review": {
                "provider_called": True,
                "artifact_verified": True,
                "durable_history_verified": True,
                "artifact_quality_verdict": "pass",
            },
        },
        script_name="openai_visual_live_e2e.py",
        producer="openai-visual-live-e2e",
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")

    check = raphael_cmd._visual_release_gate_check_from_report(
        report_path=str(report_path),
        run_id="openai-command-inferred-live-1",
        command=None,
        selected_artifact_id=None,
        artifact_quality_verdict=None,
    )

    assert check["command"] == "scripts/openai_visual_live_e2e.py"
    assert check["report_provenance_verified"] is True
    assert raphael_cmd._visual_source_report_matches_claim(check) is True
    assert raphael_cmd._visual_live_e2e_has_result_surface_evidence(check) is True


def test_raphael_release_gate_accepts_openai_image_first_video_as_public_media_slice(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-current.mp4"
    source_image = tmp_path / "openai-selected-source.png"
    artifact.write_bytes(b"video")
    source_image.write_bytes(b"image-source")
    source_stat = source_image.stat()
    source_sha256 = hashlib.sha256(source_image.read_bytes()).hexdigest()
    report_path = tmp_path / "openai-visual-image-first-video-report.json"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "openai-visual-video-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "openai-gpt-image-live",
                    "provider": {
                        "name": "openai-codex",
                        "model": "gpt-image-2-low",
                    },
                    "provider_result": {
                        "provider": "openai-codex",
                        "model": "gpt-image-2-low",
                        "response_id": "resp_video_123",
                    },
                    "result_surface_id": "openai-response:resp_video_123",
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "openai_response",
                        "durability": "provider_response_artifact",
                        "history_verified": True,
                    },
                    "request": {"operation": "image_to_video"},
                    "video_source": {
                        "uses_ranked_selected_image": True,
                        "single_video_source_image": True,
                        "video_source_image_count": 1,
                        "source_image_artifact_id": "openai-source-image-1",
                        "ranked_selected_image_artifact_id": "openai-source-image-1",
                        "source_image_path": str(source_image),
                        "source_image_exists": True,
                        "source_image_policy": "single_ranked_image",
                        "source_image_source": "openai_response",
                        "source_image_durability": "provider_response_artifact",
                        "source_image_result_surface_id": "openai-response:resp_source_123",
                        "source_image_provider_result_response_id": "resp_source_123",
                        "source_image_artifact_identity_verified": True,
                        "source_image_artifact_sha256": source_sha256,
                        "source_image_artifact_size_bytes": source_stat.st_size,
                        "source_image_artifact_mtime": source_stat.st_mtime,
                        "source_image_quality_verdict": "pass",
                        "source_image_quality_identity_verified": True,
                    },
                    "quality_review": _visual_quality_review(
                        artifact,
                        reviewer="independent-vision-release-review",
                        run_id="openai-video-quality-review-1",
                    ),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                },
                script_name="openai_visual_live_e2e.py",
                producer="openai-visual-live-e2e",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-video-live-1",
        visual_command="scripts/openai_visual_live_e2e.py --image-first-video",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is True
    assert result.release_state == "ready_for_limited_media_public_release"
    assert result.release_scope == "media_openai_image_first_video"
    assert result.remaining_scope_gaps == ("xai_grok_generation",)
    assert result.blocking_reasons == ()
    assert "Release scope: media_openai_image_first_video" in result.message
    assert "Full media release ready: no" in result.message
    assert (
        "Verified media capabilities: "
        "openai_image_generation, openai_image_first_video_generation"
    ) in result.message
    assert evidence["media_release_scope"] == "media_openai_image_first_video"
    assert evidence["remaining_media_gaps"] == ["xai_grok_generation"]
    assert evidence["verified_media_capabilities"] == [
        {
            "capability_id": "openai_image_generation",
            "provider_family": "openai",
            "media_type": "image",
            "status": "verified",
            "release_scope": "media_openai_image_first_video",
            "public_slice_ready": True,
            "full_media_release_ready": False,
            "remaining_full_media_gaps": ["xai_grok_generation"],
        },
        {
            "capability_id": "openai_image_first_video_generation",
            "provider_family": "openai",
            "media_type": "video",
            "status": "verified",
            "release_scope": "media_openai_image_first_video",
            "public_slice_ready": True,
            "full_media_release_ready": False,
            "remaining_full_media_gaps": ["xai_grok_generation"],
            "source_image_policy": "single_ranked_image",
        },
    ]
    visual_check = evidence["checks"]["visual_live_e2e"]
    assert visual_check["artifact_media_type"] == "video"
    assert visual_check["image_first_source_verified"] is True
    assert visual_check["openai_source_image_verified"] is True
    assert visual_check["source_image_artifact_id"] == "openai-source-image-1"
    assert visual_check["source_image_path"] == str(source_image)
    assert visual_check["source_image_artifact_sha256"] == source_sha256
    assert visual_check["source_image_artifact_identity_verified"] is True
    assert visual_check["source_image_ranked_selected"] is True
    assert visual_check["single_video_source_image"] is True


def test_raphael_release_gate_rejects_openai_image_first_video_with_weak_source_proof(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-current.mp4"
    source_image = tmp_path / "local-unproven-source.png"
    artifact.write_bytes(b"video")
    source_image.write_bytes(b"local-source")
    report_path = tmp_path / "openai-weak-source-video-report.json"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "openai-visual-video-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "openai-gpt-image-live",
                    "provider": {
                        "name": "openai-codex",
                        "model": "gpt-image-2-low",
                    },
                    "provider_result": {
                        "provider": "openai-codex",
                        "model": "gpt-image-2-low",
                        "response_id": "resp_video_123",
                    },
                    "result_surface_id": "openai-response:resp_video_123",
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "openai_response",
                        "durability": "provider_response_artifact",
                        "history_verified": True,
                    },
                    "request": {"operation": "image_to_video"},
                    "video_source": {
                        "uses_ranked_selected_image": True,
                        "single_video_source_image": True,
                        "video_source_image_count": 1,
                        "source_image_artifact_id": "openai-source-image-1",
                        "ranked_selected_image_artifact_id": "openai-source-image-1",
                        "source_image_path": str(source_image),
                        "source_image_exists": True,
                        "source_image_policy": "single_ranked_image",
                    },
                    "quality_review": _visual_quality_review(
                        artifact,
                        reviewer="independent-vision-release-review",
                        run_id="openai-video-quality-review-1",
                    ),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                },
                script_name="openai_visual_live_e2e.py",
                producer="openai-visual-live-e2e",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-video-live-1",
        visual_command="scripts/openai_visual_live_e2e.py --image-first-video",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is False
    assert result.release_state == "blocked_media_scope_incomplete"
    assert result.release_scope == "media_openai_video_only"
    assert result.remaining_scope_gaps == (
        "xai_grok_generation",
        "image_first_source_image",
    )
    assert result.blocking_reasons == ("media_scope_gap_image_first_source_image",)
    visual_check = evidence["checks"]["visual_live_e2e"]
    assert visual_check["image_first_source_verified"] is True
    assert visual_check["openai_source_image_verified"] is False


def test_raphael_readiness_payload_does_not_verify_media_capabilities_from_failed_visual_check(
    tmp_path,
):
    from hermes_cli import raphael_cmd

    payload = {
        "schema_version": 1,
        "producer": "hermes-raphael-release-gate",
        "generated_at": _fresh_generated_at(),
        "profile": "media",
        "checks": {
            "install_disable_uninstall": {
                "status": "pass",
                "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                "run_id": "lifecycle-1",
                "disabled_slash_commands_available": True,
                "disabled_status_guides_enable": True,
                "cli_smoke_verified": True,
                "cli_entrypoint": "hermes",
                "cli_entrypoint_found": True,
                "cli_entrypoint_path": "/tmp/hermes",
                "cli_install_enabled": True,
                "cli_disable_keeps_plugin": True,
                "cli_status_after_disable_guides_enable": True,
                "cli_enable_restores_mode": True,
                "cli_uninstall_disables_plugin": True,
                "cli_status_after_uninstall_guides_install": True,
            },
            "package_install_smoke": _package_install_smoke_check(
                _package_install_smoke_report(tmp_path)
            ),
            "slash_command_surface": _slash_command_surface_check(),
            "mode_router_contract": _mode_router_contract_check(),
            "goal_state_contract": _goal_state_contract_check(),
            "evolution_contract": _evolution_contract_check(),
            "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
            "wow_experience": _wow_experience_check(),
            "hostile_review": _hostile_review_check(
                _write_hostile_review_report(tmp_path)
            ),
            "non_visual_regression": _non_visual_regression_check(
                _write_non_visual_regression_report(tmp_path)
            ),
            "visual_live_e2e": {
                "status": "pass",
                "evidence": "fresh selected artifact verified after current visual submit",
                "command": "scripts/openai_visual_live_e2e.py --image-first-video",
                "run_id": "stale-openai-video-1",
                "report_identity_verified": True,
                "fresh_artifact": False,
                "provider_mode": "openai-gpt-image-live",
                "artifact_media_type": "video",
                "image_first_source_verified": True,
                "openai_source_image_verified": True,
            },
        },
        "media_release_scope": "media_openai_image_first_video",
        "remaining_media_gaps": ["xai_grok_generation"],
        "verified_media_capabilities": [
            {
                "capability_id": "openai_image_generation",
                "provider_family": "openai",
                "media_type": "image",
                "status": "verified",
                "release_scope": "media_openai_image_first_video",
                "public_slice_ready": True,
                "full_media_release_ready": False,
                "remaining_full_media_gaps": ["xai_grok_generation"],
            },
            {
                "capability_id": "openai_image_first_video_generation",
                "provider_family": "openai",
                "media_type": "video",
                "status": "verified",
                "release_scope": "media_openai_image_first_video",
                "public_slice_ready": True,
                "full_media_release_ready": False,
                "remaining_full_media_gaps": ["xai_grok_generation"],
                "source_image_policy": "single_ranked_image",
            },
        ],
    }

    evidence = raphael_cmd._read_release_readiness_evidence_payload(
        "media",
        payload,
        require_verdict=False,
    )

    assert "visual_live_e2e_stale_or_unverified" in evidence.blocking_reasons
    assert evidence.release_scope == ""
    assert evidence.remaining_scope_gaps == ()
    assert evidence.verified_media_capabilities == ()


def test_raphael_release_gate_blocks_openai_video_without_image_first_source_proof(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-current.mp4"
    artifact.write_bytes(b"video")
    report_path = tmp_path / "openai-visual-video-only-report.json"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "openai-visual-video-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "openai-gpt-image-live",
                    "provider": {
                        "name": "openai-codex",
                        "model": "gpt-image-2-low",
                    },
                    "provider_result": {
                        "provider": "openai-codex",
                        "model": "gpt-image-2-low",
                        "response_id": "resp_video_123",
                    },
                    "result_surface_id": "openai-response:resp_video_123",
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "openai_response",
                        "durability": "provider_response_artifact",
                        "history_verified": True,
                    },
                    "request": {"operation": "image_to_video"},
                    "quality_review": _visual_quality_review(
                        artifact,
                        reviewer="independent-vision-release-review",
                        run_id="openai-video-quality-review-1",
                    ),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                },
                script_name="openai_visual_live_e2e.py",
                producer="openai-visual-live-e2e",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-video-live-1",
        visual_command="scripts/openai_visual_live_e2e.py --video",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is False
    assert result.release_state == "blocked_media_scope_incomplete"
    assert result.release_scope == "media_openai_video_only"
    assert result.remaining_scope_gaps == (
        "xai_grok_generation",
        "image_first_source_image",
    )
    assert result.blocking_reasons == ("media_scope_gap_image_first_source_image",)
    assert evidence["blocking_layers"] == ["media_workflow_coverage"]


def test_raphael_release_gate_rejects_openai_visual_e2e_with_synthetic_result_surface(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-synthetic-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-synthetic-visual-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "provider": {
                    "name": "openai-codex",
                    "model": "gpt-image-2-low",
                },
                "provider_result": {
                    "provider": "openai-codex",
                    "model": "gpt-image-2-low",
                },
                "result_surface_id": "openai-response:openai-visual-live-1",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="independent-vision-release-review",
                    run_id="openai-synthetic-quality-review-1",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-live-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_human_independent_quality_without_model_transcript(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "human-reviewed-openai-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "human-reviewed-openai-visual-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "human-reviewed-openai-visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "provider": {
                    "name": "openai-codex",
                    "model": "gpt-image-2-low",
                },
                "provider_result": {
                    "provider": "openai-codex",
                    "model": "gpt-image-2-low",
                    "response_id": "resp_human_reviewed",
                },
                "result_surface_id": "openai-response:resp_human_reviewed",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="independent-human-release-review",
                    run_id="human-quality-review-1",
                    review_source_type="human_independent",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="human-reviewed-openai-visual-live-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons
    assert "Visual live E2E: quality_unverified" in result.message
    visual_check = evidence["checks"]["visual_live_e2e"]
    assert visual_check["quality_review_source_type"] == ""
    assert visual_check["quality_review_reviewer"] == ""
    assert visual_check["quality_review_model_provider"] == ""
    assert visual_check["quality_review_response_id"] == ""


def test_raphael_release_gate_rejects_openai_visual_e2e_with_xai_provider_result(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-xai-provider.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-xai-provider-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-visual-xai-provider-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "provider": {"name": "xai", "model": "grok-imagine"},
                "provider_result": {"provider": "xai", "model": "grok-imagine"},
                "result_surface_id": "openai-response:resp_xai_provider",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="independent-vision-release-review",
                    run_id="openai-xai-provider-quality-review-1",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-xai-provider-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_openai_visual_e2e_without_provider_provenance(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-missing-provider.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-missing-provider-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-visual-missing-provider-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "result_surface_id": "openai-response:resp_missing_provider",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="independent-vision-release-review",
                    run_id="openai-missing-provider-quality-review-1",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-missing-provider-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_openai_visual_e2e_stale_artifact(
    monkeypatch,
    tmp_path,
):
    import os
    from datetime import datetime, timedelta, timezone

    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-stale.png"
    artifact.write_bytes(b"old image")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp()
    os.utime(artifact, (old_timestamp, old_timestamp))
    report_path = tmp_path / "openai-stale-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-visual-stale-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "result_surface_id": "openai-response:resp_stale",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="independent-vision-release-review",
                    run_id="openai-stale-quality-review-1",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-stale-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_stale_or_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_quality_review_for_overwritten_artifact(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "openai-overwritten.png"
    artifact.write_bytes(b"reviewed image")
    quality_review = _visual_quality_review(
        artifact,
        reviewer="independent-vision-release-review",
        run_id="openai-overwritten-quality-review-1",
    )
    artifact.write_bytes(b"replacement image after review")
    report_path = tmp_path / "openai-overwritten-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-visual-overwritten-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "provider": {
                    "name": "openai-codex",
                    "model": "gpt-image-2-low",
                },
                "provider_result": {
                    "provider": "openai-codex",
                    "model": "gpt-image-2-low",
                    "response_id": "resp_overwritten",
                },
                "result_surface_id": "openai-response:resp_overwritten",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": quality_review,
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-visual-overwritten-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_readiness_rejects_openai_stored_history_id_without_response_surface(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    artifact = tmp_path / "openai-current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "openai-generic-url-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-visual-generic-url-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "result_surface_id": "https://example.com/not-an-openai-response",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="independent-vision-release-review",
                    run_id="openai-generic-url-quality-review-1",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "profile": "media",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                    "disabled_slash_commands_available": True,
                    "disabled_status_guides_enable": True,
                },
                "llm_live_smoke": _trusted_llm_smoke_check(tmp_path),
                "wow_experience": _wow_experience_check(),
                "visual_live_e2e": {
                    "status": "pass",
                    "evidence": "fresh selected artifact verified after current visual submit",
                    "command": "scripts/openai_visual_live_e2e.py",
                    "run_id": "openai-visual-generic-url-1",
                    "report_run_id": "openai-visual-generic-url-1",
                    "report_generated_at": _fresh_generated_at(),
                    "report_identity_verified": True,
                    "fresh_artifact": True,
                    "selected_artifact_id": str(artifact),
                    "artifact_quality_verdict": "pass",
                    "quality_review_source": "quality_review",
                    "quality_review_reviewer": "independent-vision-release-review",
                    "quality_review_run_id": "openai-generic-url-quality-review-1",
                    "quality_review_generated_at": _fresh_generated_at(),
                    "quality_review_source_report_path": str(
                        artifact.with_name(f"{artifact.stem}.quality-review.json")
                    ),
                    "quality_review_artifact_match": True,
                    "quality_review_dimensions_verified": True,
                    "provider_mode": "openai-gpt-image-live",
                    "provider_success": True,
                    "report_status": "completed",
                    "artifact_path": str(artifact),
                    "artifact_exists": True,
                    "artifact_source": "openai_response",
                    "artifact_durability": "provider_response_artifact",
                    "durable_history_verified": True,
                    "result_surface_id": "https://example.com/not-an-openai-response",
                    "history_entry_id": "forged-history-id",
                    "operation": "generate",
                    "source_report_path": str(report_path),
                },
            },
        },
    )

    readiness = raphael_release_readiness(profile="media")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in readiness.blocking_reasons


def test_raphael_release_gate_rejects_cli_visual_quality_self_attestation(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                **_grok_provider_report_fields(result_surface),
                "page_url": result_surface,
                "result_surface_id": result_surface,
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": result_surface,
                },
                "request": {"operation": "generate"},
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons
    assert "Visual live E2E: quality_unverified" in result.message


def test_raphael_release_gate_rejects_inline_visual_quality_review_without_source_report(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                **_grok_provider_report_fields(result_surface),
                "page_url": result_surface,
                "result_surface_id": result_surface,
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": result_surface,
                },
                "request": {"operation": "generate"},
                "quality_review": {
                    "producer": "hermes-visual-quality-review",
                    "reviewer": "vision-backed-artifact-review",
                    "artifact_path": str(artifact),
                    "artifact_quality_verdict": "pass",
                    "dimensions": {
                        "composition": "pass",
                        "prompt_adherence": "pass",
                        "geometry": "pass",
                        "subject_quality": "pass",
                    },
                },
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_visual_quality_source_report_without_audit_fields(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    for missing_field in ("producer", "command", "evidence", "residual_risk"):
        artifact = tmp_path / f"{missing_field}.png"
        artifact.write_bytes(b"image")
        report_path = tmp_path / f"{missing_field}-live-report.json"
        result_surface = f"https://grok.com/imagine/history/{missing_field}"
        quality_review = _visual_quality_review(artifact)
        quality_report_path = Path(quality_review["source_report_path"])
        quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
        quality_report.pop(missing_field, None)
        quality_report_path.write_text(json.dumps(quality_report), encoding="utf-8")
        report_path.write_text(
            json.dumps(
                {
                    "run_id": f"visual-live-{missing_field}",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "generate"},
                    "quality_review": quality_review,
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                    },
                }
            ),
            encoding="utf-8",
        )

        result = raphael_release_gate(
            profile="media",
            llm_smoke_session_id="20260701_131600_93f518",
            llm_smoke_command="rtk hermes chat -Q --max-turns 3",
            llm_tool_call_count=0,
            llm_summon_sections_verified=True,
            llm_full_body_preserved=True,
            llm_no_visual_failure_trace=True,
            visual_run_id=f"visual-live-{missing_field}",
            visual_command="scripts/grok_web_imagine_live_e2e.py",
            visual_e2e_report_path=str(report_path),
            **_release_quality_gate_kwargs(tmp_path),
        )

        assert result.public_release_ready is False, missing_field
        assert result.release_state == "blocked_visual_live_e2e_pending", missing_field
        assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_visual_quality_source_report_without_review_provenance(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    quality_review = _visual_quality_review(
        artifact,
        reviewer="independent-vision-release-review",
        run_id="missing-review-provenance-quality-review-1",
    )
    quality_report_path = Path(quality_review["source_report_path"])
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    for field in (
        "review_source_type",
        "review_model_provider",
        "review_model",
        "review_evidence_digest",
        "review_provenance_verified",
    ):
        quality_report.pop(field, None)
    quality_report_path.write_text(json.dumps(quality_report), encoding="utf-8")

    report_path = tmp_path / "openai-missing-review-provenance-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-missing-review-provenance-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "openai-gpt-image-live",
                "provider": {
                    "name": "openai-codex",
                    "model": "gpt-image-2-low",
                },
                "provider_result": {
                    "provider": "openai-codex",
                    "model": "gpt-image-2-low",
                    "response_id": "resp_missing_review_provenance",
                },
                "result_surface_id": "openai-response:resp_missing_review_provenance",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "openai_response",
                    "durability": "provider_response_artifact",
                    "history_verified": True,
                },
                "request": {"operation": "generate"},
                "quality_review": quality_review,
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="openai-missing-review-provenance-1",
        visual_command="scripts/openai_visual_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_live_harness_visual_quality_self_review(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                **_grok_provider_report_fields(result_surface),
                "page_url": result_surface,
                "result_surface_id": result_surface,
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": result_surface,
                },
                "request": {"operation": "generate"},
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_hyphenated_live_harness_quality_reviewer(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                **_grok_provider_report_fields(result_surface),
                "page_url": result_surface,
                "result_surface_id": result_surface,
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": result_surface,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(
                    artifact,
                    reviewer="live-harness",
                ),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_grok_provider_quality_reviewer_names(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    for reviewer in ("grok-web-imagine-live", "grok-web-imagine"):
        artifact = tmp_path / f"{reviewer}.png"
        artifact.write_bytes(b"image")
        report_path = tmp_path / f"{reviewer}-report.json"
        result_surface = f"https://grok.com/imagine/history/{reviewer}"
        report_path.write_text(
            json.dumps(
                {
                    "run_id": f"visual-{reviewer}",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "generate"},
                    "quality_review": _visual_quality_review(
                        artifact,
                        reviewer=reviewer,
                    ),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                    },
                }
            ),
            encoding="utf-8",
        )

        result = raphael_release_gate(
            profile="media",
            llm_smoke_session_id="20260701_131600_93f518",
            llm_smoke_command="rtk hermes chat -Q --max-turns 3",
            llm_tool_call_count=0,
            llm_summon_sections_verified=True,
            llm_full_body_preserved=True,
            llm_no_visual_failure_trace=True,
            visual_run_id=f"visual-{reviewer}",
            visual_command="scripts/grok_web_imagine_live_e2e.py",
            visual_e2e_report_path=str(report_path),
            **_release_quality_gate_kwargs(tmp_path),
        )

        assert result.public_release_ready is False, reviewer
        assert result.release_state == "blocked_visual_live_e2e_pending", reviewer
        assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_decorated_provider_quality_reviewer_names(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    for reviewer in (
        "grok-web-imagine-provider",
        "provider-grok-web-imagine",
        "openai",
        "openai-codex",
        "gpt-image-2-low",
        "image2",
        "openai-codex-provider",
        "provider-openai-codex",
        "self-reviewer",
        "live-harness-review",
    ):
        artifact = tmp_path / f"{reviewer}.png"
        artifact.write_bytes(b"image")
        report_path = tmp_path / f"{reviewer}-report.json"
        result_surface = f"https://grok.com/imagine/history/{reviewer}"
        report_path.write_text(
            json.dumps(
                {
                    "run_id": f"visual-{reviewer}",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "generate"},
                    "quality_review": _visual_quality_review(
                        artifact,
                        reviewer=reviewer,
                    ),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                    },
                }
            ),
            encoding="utf-8",
        )

        result = raphael_release_gate(
            profile="media",
            llm_smoke_session_id="20260701_131600_93f518",
            llm_smoke_command="rtk hermes chat -Q --max-turns 3",
            llm_tool_call_count=0,
            llm_summon_sections_verified=True,
            llm_full_body_preserved=True,
            llm_no_visual_failure_trace=True,
            visual_run_id=f"visual-{reviewer}",
            visual_command="scripts/grok_web_imagine_live_e2e.py",
            visual_e2e_report_path=str(report_path),
            **_release_quality_gate_kwargs(tmp_path),
        )

        assert result.public_release_ready is False, reviewer
        assert result.release_state == "blocked_visual_live_e2e_pending", reviewer
        assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_non_finite_visual_quality_dimensions(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    quality_review = _visual_quality_review(artifact)
    quality_report_path = tmp_path / "current.quality-review.json"
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    quality_report["dimensions"] = {
        "composition": float("inf"),
        "prompt_adherence": float("inf"),
        "geometry": float("inf"),
        "subject_quality": float("inf"),
    }
    quality_report_path.write_text(json.dumps(quality_report), encoding="utf-8")

    report_path = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                **_grok_provider_report_fields(result_surface),
                "page_url": result_surface,
                "result_surface_id": result_surface,
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": result_surface,
                },
                "request": {"operation": "generate"},
                "quality_review": quality_review,
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_quality_unverified" in result.blocking_reasons


def test_raphael_release_gate_persists_visual_report_path_as_absolute(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_path = report_dir / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                    "run_id": "visual-live-1",
                    "generated_at": _fresh_generated_at(),
                    "success": True,
                    "status": "completed",
                    "provider_mode": "grok-web-imagine-live",
                    **_grok_provider_report_fields(result_surface),
                    "page_url": result_surface,
                    "result_surface_id": result_surface,
                    "artifact": {
                        "path": str(artifact),
                        "exists": True,
                        "source": "grok_history",
                        "durability": "durable_history_or_post",
                        "history_verified": True,
                        "page_url": result_surface,
                    },
                    "request": {"operation": "generate"},
                    "quality_review": _visual_quality_review(artifact),
                    "self_review": {
                        "provider_called": True,
                        "artifact_verified": True,
                        "durable_history_verified": True,
                        "artifact_quality_verdict": "pass",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    monkeypatch.chdir(report_dir)
    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path="grok-web-live-report.json",
        visual_artifact_quality_verdict="pass",
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())
    visual_check = evidence["checks"]["visual_live_e2e"]

    assert result.public_release_ready is False
    assert result.release_state == "blocked_media_scope_incomplete"
    assert visual_check["source_report_path"] == str(report_path.resolve())

    monkeypatch.chdir(tmp_path.parent)
    readiness = raphael_release_readiness(profile="media")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_media_scope_incomplete"
    assert readiness.release_scope == "media_grok_image_only"
    assert readiness.remaining_scope_gaps == ("video_generation",)
    assert readiness.blocking_reasons == ("media_scope_gap_video_generation",)


def test_raphael_release_gate_keeps_media_evidence_after_llm_refresh(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    result_surface = "https://grok.com/imagine/history/current"
    report_path.write_text(
        json.dumps(
            _stamp_visual_live_report(
                {
                "run_id": "visual-live-1",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                **_grok_provider_report_fields(result_surface),
                "page_url": result_surface,
                "result_surface_id": result_surface,
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": result_surface,
                },
                "request": {"operation": "generate"},
                "quality_review": _visual_quality_review(artifact),
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                    "artifact_quality_verdict": "pass",
                },
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)

    media_result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
        **release_quality_kwargs,
    )
    llm_result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )
    media_readiness = raphael_release_readiness(profile="media")

    assert media_result.public_release_ready is False
    assert llm_result.public_release_ready is True
    assert media_readiness.public_release_ready is False
    assert media_readiness.release_state == "blocked_media_scope_incomplete"
    assert media_readiness.release_scope == "media_grok_image_only"
    assert media_readiness.remaining_scope_gaps == ("video_generation",)
    assert media_readiness.blocking_reasons == ("media_scope_gap_video_generation",)


def test_raphael_media_readiness_prefers_llm_profile_over_stale_legacy_snapshot(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    llm_result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **_release_quality_gate_kwargs(tmp_path),
    )
    legacy_path = tmp_path / "raphael" / "release_readiness.json"
    media_path = tmp_path / "raphael" / "release_readiness.media.json"
    legacy_path.write_text("{not json", encoding="utf-8")
    if media_path.exists():
        media_path.unlink()

    media_readiness = raphael_release_readiness(profile="media")

    assert llm_result.public_release_ready is True
    assert media_readiness.public_release_ready is False
    assert media_readiness.release_state == "blocked_visual_live_e2e_pending"
    assert media_readiness.blocking_reasons == ("visual_live_e2e_missing",)


def test_raphael_release_gate_rejects_visual_report_without_run_identity(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": "https://grok.com/imagine/history/current",
                },
                "request": {"operation": "generate"},
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-1",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_rejects_visual_report_run_id_mismatch(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    artifact = tmp_path / "current.png"
    artifact.write_bytes(b"image")
    report_path = tmp_path / "grok-web-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "visual-live-real",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "artifact": {
                    "path": str(artifact),
                    "exists": True,
                    "source": "grok_history",
                    "durability": "durable_history_or_post",
                    "history_verified": True,
                    "page_url": "https://grok.com/imagine/history/current",
                },
                "request": {"operation": "generate"},
                "self_review": {
                    "provider_called": True,
                    "artifact_verified": True,
                    "durable_history_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-forged",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_result_unverified" in result.blocking_reasons


def test_raphael_release_gate_surfaces_visual_setup_blocker_from_failed_report(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    report_path = tmp_path / "grok-web-live-report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "visual-live-setup",
                "generated_at": _fresh_generated_at(),
                "success": False,
                "status": "failed",
                "provider_mode": "grok-web-imagine-live",
                "requires_operator_setup": True,
                "failure_class": "quota_exhausted",
                "error": "subscription required",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_run_id="visual-live-setup",
        visual_command="scripts/grok_web_imagine_live_e2e.py",
        visual_e2e_report_path=str(report_path),
        visual_artifact_quality_verdict="pass",
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_setup_required" in result.blocking_reasons
    assert "Visual live E2E: setup_required" in result.message
    assert "quota_exhausted" in result.message
    assert "subscription required" in result.message
    assert "resolve Grok Web Imagine provider setup/quota" in result.message


def test_raphael_release_gate_surfaces_visual_setup_blocker_from_preflight_report(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-preflight-report.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-preflight-setup",
                "generated_at": _fresh_generated_at(),
                "success": False,
                "status": "browser_preflight_blocked",
                "provider_mode": "grok-web-imagine-live",
                "requires_operator_setup": True,
                "error_type": "browser_page_not_found",
                "error": "No Chrome page target contains 'grok.com,accounts.x.ai' on CDP port 9223.",
                "browser_preflight": {
                    "status": "browser_page_not_found",
                    "ready": False,
                    "safe_to_submit": False,
                    "quota_used": False,
                },
                "checks": {
                    "generation_called": False,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_setup_required" in result.blocking_reasons
    assert "Visual live E2E: setup_required" in result.message
    assert "browser_page_not_found" in result.message
    assert "visual preflight" in result.message
    assert "--visual-preflight-report" in result.message


def test_raphael_release_gate_surfaces_preflight_ready_without_counting_as_visual_e2e(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-preflight-ready.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-preflight-ready",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "preflight_ready",
                "provider_mode": "grok-web-imagine-live",
                "requires_operator_setup": False,
                "quota_used": False,
                "browser_preflight": {
                    "status": "imagine_ready",
                    "ready": True,
                    "safe_to_submit": True,
                    "quota_used": False,
                    "prompt_probe": _grok_prompt_probe_ready(),
                },
                "checks": {
                    "generation_called": False,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_ready" in result.blocking_reasons
    assert "Visual live E2E: preflight_ready" in result.message
    assert "Public release ready: no" in result.message
    assert "scripts/grok_web_imagine_live_e2e.py" in result.message
    assert "scripts/openai_visual_live_e2e.py" not in result.message


def test_raphael_release_gate_rejects_preflight_ready_without_prompt_probe(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-preflight-ready-no-prompt-probe.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-preflight-ready-no-prompt-probe",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "preflight_ready",
                "provider_mode": "grok-web-imagine-live",
                "requires_operator_setup": False,
                "quota_used": False,
                "browser_preflight": {
                    "status": "imagine_ready",
                    "ready": True,
                    "safe_to_submit": True,
                    "quota_used": False,
                },
                "checks": {
                    "generation_called": False,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_unverified" in result.blocking_reasons
    assert "Visual live E2E: preflight_unverified" in result.message
    assert "prompt_probe_missing" in result.message


def test_raphael_release_gate_rejects_preflight_from_wrong_provider_mode(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "openai-preflight-ready.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "openai-preflight-ready",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "preflight_ready",
                "provider_mode": "openai-image-live",
                "requires_operator_setup": False,
                "quota_used": False,
                "browser_preflight": {
                    "status": "imagine_ready",
                    "ready": True,
                    "safe_to_submit": True,
                    "quota_used": False,
                },
                "checks": {
                    "generation_called": False,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_unverified" in result.blocking_reasons
    assert "Visual live E2E: preflight_unverified" in result.message
    assert "provider_mode" in result.message


def test_raphael_release_gate_rejects_completed_report_passed_as_preflight(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-completed-as-preflight.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-completed-as-preflight",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "completed",
                "provider_mode": "grok-web-imagine-live",
                "requires_operator_setup": False,
                "quota_used": False,
                "browser_preflight": {
                    "status": "imagine_ready",
                    "ready": True,
                    "safe_to_submit": True,
                    "quota_used": False,
                },
                "checks": {
                    "generation_called": False,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_unverified" in result.blocking_reasons
    assert "Visual live E2E: preflight_unverified" in result.message
    assert "preflight_status_not_ready" in result.message


def test_raphael_release_gate_rejects_preflight_report_that_called_generation(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-preflight-generated.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-preflight-generated",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "preflight_ready",
                "provider_mode": "grok-web-imagine-live",
                "quota_used": False,
                "browser_preflight": {
                    "status": "imagine_ready",
                    "ready": True,
                    "safe_to_submit": True,
                    "quota_used": False,
                },
                "checks": {
                    "generation_called": True,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_unverified" in result.blocking_reasons
    assert "Visual live E2E: preflight_unverified" in result.message
    assert "generation_called" in result.message


def test_raphael_release_gate_rejects_preflight_report_that_used_quota(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-preflight-quota.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-preflight-quota",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "preflight_ready",
                "provider_mode": "grok-web-imagine-live",
                "quota_used": True,
                "browser_preflight": {
                    "status": "imagine_ready",
                    "ready": True,
                    "safe_to_submit": True,
                    "quota_used": False,
                },
                "checks": {
                    "generation_called": False,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_unverified" in result.blocking_reasons
    assert "Visual live E2E: preflight_unverified" in result.message
    assert "quota_used" in result.message


def test_raphael_release_gate_rejects_preflight_report_without_browser_probe(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-preflight-no-browser-probe.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-preflight-no-browser-probe",
                "generated_at": _fresh_generated_at(),
                "success": True,
                "status": "preflight_ready",
                "provider_mode": "grok-web-imagine-live",
                "quota_used": False,
                "checks": {
                    "generation_called": False,
                    "provider_constructed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_unverified" in result.blocking_reasons
    assert "Visual live E2E: preflight_unverified" in result.message
    assert "provider_preflight" in result.message


def test_raphael_release_gate_rejects_stale_preflight_report(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    preflight_report_path = tmp_path / "grok-web-preflight-stale.json"
    preflight_report_path.write_text(
        json.dumps(
            {
                "run_id": "grok-web-preflight-stale",
                "generated_at": "2020-01-01T00:00:00Z",
                "success": True,
                "status": "preflight_ready",
                "provider_mode": "grok-web-imagine-live",
                "quota_used": False,
                "browser_preflight": {
                    "status": "imagine_ready",
                    "ready": True,
                    "safe_to_submit": True,
                    "quota_used": False,
                },
                "checks": {
                    "generation_called": False,
                    "provider_preflight": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="media",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        visual_preflight_report_path=str(preflight_report_path),
    )

    assert result.public_release_ready is False
    assert result.release_state == "blocked_visual_live_e2e_pending"
    assert "visual_live_e2e_preflight_unverified" in result.blocking_reasons
    assert "Visual live E2E: preflight_unverified" in result.message
    assert "readiness_evidence_stale" in result.message


def test_raphael_release_gate_writes_trusted_llm_readiness_evidence(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    release_quality_kwargs = _release_quality_gate_kwargs(tmp_path)
    package_report = Path(release_quality_kwargs["package_install_report_path"])

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **release_quality_kwargs,
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.json").read_text())
    readiness = raphael_release_readiness(profile="llm")

    assert result.public_release_ready is True
    assert evidence["producer"] == "hermes-raphael-release-gate"
    assert evidence["public_claim_scope"] == "llm_only"
    assert evidence["public_claim_exclusions"] == [
        "media",
        "Grok",
        "video",
        "full Sage King",
    ]
    assert evidence["checks"]["install_disable_uninstall"]["status"] == "pass"
    assert evidence["checks"]["install_disable_uninstall"][
        "disabled_slash_commands_available"
    ] is True
    assert evidence["checks"]["install_disable_uninstall"][
        "disabled_status_guides_enable"
    ] is True
    assert evidence["checks"]["install_disable_uninstall"]["cli_smoke_verified"] is True
    assert evidence["checks"]["install_disable_uninstall"]["cli_entrypoint"] == "hermes"
    assert evidence["checks"]["install_disable_uninstall"]["cli_entrypoint_found"] is True
    assert evidence["checks"]["install_disable_uninstall"]["cli_entrypoint_path"]
    assert evidence["checks"]["install_disable_uninstall"]["cli_command_count"] >= 6
    assert evidence["checks"]["install_disable_uninstall"]["cli_install_enabled"] is True
    assert evidence["checks"]["install_disable_uninstall"][
        "cli_disable_keeps_plugin"
    ] is True
    assert evidence["checks"]["install_disable_uninstall"][
        "cli_status_after_disable_guides_enable"
    ] is True
    assert evidence["checks"]["install_disable_uninstall"][
        "cli_enable_restores_mode"
    ] is True
    assert evidence["checks"]["install_disable_uninstall"][
        "cli_uninstall_disables_plugin"
    ] is True
    assert evidence["checks"]["install_disable_uninstall"][
        "cli_status_after_uninstall_guides_install"
    ] is True
    assert evidence["checks"]["package_install_smoke"]["status"] == "pass"
    assert evidence["checks"]["package_install_smoke"]["source_report_path"] == str(
        package_report
    )
    assert evidence["checks"]["package_install_smoke"]["wheel_built"] is True
    assert evidence["checks"]["package_install_smoke"]["wheel_installed"] is True
    assert evidence["checks"]["package_install_smoke"][
        "installed_media_slice_ready"
    ] is False
    assert evidence["checks"]["package_install_smoke"][
        "installed_media_gate_fail_closed"
    ] is True
    assert evidence["checks"]["package_install_smoke"]["installed_media_gate_lines"] == [
        "Full media release ready: no",
        "Public release ready: no",
    ]
    assert evidence["checks"]["package_install_smoke"]["hermes_entrypoint"] == "hermes"
    assert evidence["checks"]["package_install_smoke"]["hermes_entrypoint_found"] is True
    assert evidence["checks"]["package_install_smoke"]["cli_command_count"] == 10
    assert evidence["checks"]["package_install_smoke"][
        "cli_proposal_status_safe_refs"
    ] is True
    assert evidence["checks"]["package_install_smoke"][
        "cli_proposal_approve_audited"
    ] is True
    assert evidence["checks"]["package_install_smoke"][
        "cli_proposal_reject_audited"
    ] is True
    assert evidence["checks"]["package_install_smoke"][
        "cli_proposal_resolutions_persisted"
    ] is True
    assert evidence["checks"]["slash_command_surface"]["status"] == "pass"
    assert evidence["checks"]["slash_command_surface"]["commands"] == [
        "raphael-status",
        "raphael-skills",
        "raphael-doctor",
        "raphael-enable",
        "raphael-disable",
    ]
    assert evidence["checks"]["slash_command_surface"]["status_brief_verified"] is True
    assert evidence["checks"]["slash_command_surface"]["skills_brief_verified"] is True
    assert evidence["checks"]["slash_command_surface"]["gateway_known"] is True
    assert "raphael_skills" in evidence["checks"]["slash_command_surface"][
        "telegram_commands"
    ]
    assert evidence["checks"]["llm_live_smoke"]["session_id"] == "20260701_131600_93f518"
    assert evidence["checks"]["wow_experience"]["status"] == "pass"
    assert evidence["checks"]["wow_experience"]["score"] >= 8
    user_simulation_cases = evidence["checks"]["wow_experience"][
        "user_simulation_cases"
    ]
    assert {case["case"] for case in user_simulation_cases} == {
        "standby_summon",
        "vague_takeover_preserves_mission",
        "runtime_log_attachment_routes_tool_task",
        "blank_screen_repair_routes_tool_task",
        "prompt_builder_question_not_prompt_disclosure",
        "negated_media_summon_stays_text_only",
    }
    assert all(case["status"] == "pass" for case in user_simulation_cases)
    assert all(case["visual_quota_used"] is False for case in user_simulation_cases)
    assert all(case["next_action"].strip() for case in user_simulation_cases)
    assert {case["proof_layer"] for case in user_simulation_cases} == {
        "runtime_smoke",
        "goal_state_contract",
        "mode_router_contract",
        "intent_appraisal_contract",
        "prompt_safety_contract",
        "quota_guard_contract",
    }
    mode_router_check = evidence["checks"]["mode_router_contract"]
    assert mode_router_check["status"] == "pass"
    assert mode_router_check["route_provenance"] == (
        "deterministic_raphael_control_decision"
    )
    assert {case["case"] for case in mode_router_check["cases"]} == set(
        _MODE_ROUTER_REQUIRED_CASES
    )
    goal_state_check = evidence["checks"]["goal_state_contract"]
    assert goal_state_check["status"] == "pass"
    assert goal_state_check["state_provenance"] == (
        "deterministic_raphael_goal_state_manager"
    )
    assert goal_state_check["temp_home"] == "isolated"
    assert {case["case"] for case in goal_state_check["cases"]} == set(
        _GOAL_STATE_REQUIRED_CASES
    )
    evolution_check = evidence["checks"]["evolution_contract"]
    assert evolution_check["status"] == "pass"
    assert evolution_check["evolution_provenance"] == (
        "deterministic_raphael_evolution_manager"
    )
    assert evolution_check["temp_home"] == "isolated"
    assert {case["case"] for case in evolution_check["cases"]} == set(
        _EVOLUTION_REQUIRED_CASES
    )
    evolution_cases = {case["case"]: case for case in evolution_check["cases"]}
    repeated_case = evolution_cases["repeated_failure_self_correction_priority"]
    assert repeated_case["self_correction_prioritized"] is True
    assert repeated_case["self_correction_pattern_count"] == 2
    assert repeated_case["action_proposal_created"] is True
    assert repeated_case["action_proposal_requires_approval"] is True
    assert repeated_case["action_proposal_rollout_plan_verified"] is True
    assert repeated_case["action_proposal_rollout_status"] == "pending_approval"
    assert repeated_case["action_proposal_rollout_verification_commands"] == [
        "pytest tests/agent/test_raphael_evolution.py -q",
        "hermes raphael readiness --readiness-profile llm --check",
    ]
    assert repeated_case["action_proposal_rollout_promotion_gate"] == (
        "focused tests plus runtime, replay, or LLM smoke"
    )
    assert repeated_case["action_proposal_rollout_rollback_condition"] == (
        "next evidence or user feedback shows worse behavior"
    )
    completion_audit = evidence["checks"]["completion_audit"]
    assert completion_audit["status"] == "pass"
    assert completion_audit["audit_status"] == "partial"
    assert completion_audit["scoped_release_ready"] is True
    assert completion_audit["ultimate_ready"] is False
    assert 50 <= completion_audit["progress_percent"] < 100
    progress_by_layer = {
        layer["id"]: layer for layer in completion_audit["progress_layers"]
    }
    assert progress_by_layer["summon_wow_ux"]["percent"] == 80
    assert "full_wow_claim_not_allowed" in progress_by_layer["summon_wow_ux"]["gaps"]
    assert progress_by_layer["visual_coordination"]["percent"] < 70
    assert "ultimate_claim:sage_king_denied" in completion_audit["blockers"]
    release_manifest = evidence["checks"]["release_slice_manifest"]
    assert release_manifest["status"] == "pass"
    assert release_manifest["manifest_status"] == "reviewable"
    assert release_manifest["review_strategy"] in {
        "split_required",
        "single_llm_slice",
    }
    assert release_manifest["allowed_public_claims"] == ["llm_only"]
    assert "full_media" in release_manifest["blocked_public_claims"]
    assert release_manifest["counts"]["unclassified_paths"] == 0
    assert release_manifest["counts"]["content_violations"] == 0
    assert "Slash commands: pass" in readiness.message
    assert "Mode router: pass" in readiness.message
    assert "Goal state: pass" in readiness.message
    assert "Evolution: pass" in readiness.message
    assert "Completion audit: partial (scoped=yes, ultimate=no)" in readiness.message
    assert "Release slice manifest: reviewable" in readiness.message
    assert "Release scope: llm_only" in readiness.message
    assert (
        "Public claim scope: llm_only "
        "(does not cover media/Grok/video/full Sage King claims)"
        in readiness.message
    )
    assert readiness.public_release_ready is True
    assert readiness.release_state == "ready_for_llm_only_release"


def test_raphael_release_gate_records_hostile_review_and_non_visual_regression(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)

    result = raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence = json.loads((tmp_path / "raphael" / "release_readiness.llm.json").read_text())

    assert result.public_release_ready is True
    assert evidence["checks"]["hostile_review"]["status"] == "pass"
    assert evidence["checks"]["hostile_review"]["blockers"] == 0
    assert evidence["checks"]["non_visual_regression"]["status"] == "pass"
    assert evidence["checks"]["non_visual_regression"]["visual_quota_used"] is False


def test_raphael_release_gate_write_failure_preserves_prior_evidence(
    monkeypatch,
    tmp_path,
):
    from pathlib import Path

    import pytest

    from hermes_cli.raphael_cmd import raphael_release_gate

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    old_payload = {
        "schema_version": 1,
        "producer": "hermes-raphael-release-gate",
        "profile": "llm",
        "generated_at": _fresh_generated_at(),
        "checks": {
            "install_disable_uninstall": {
                "status": "pass",
                "evidence": "old lifecycle evidence",
                "command": "old command",
                "run_id": "old-lifecycle",
            },
            "llm_live_smoke": _llm_smoke_check(),
            "wow_experience": _wow_experience_check(),
        },
    }
    evidence_dir = tmp_path / "raphael"
    evidence_dir.mkdir()
    for name in ("release_readiness.json", "release_readiness.llm.json"):
        (evidence_dir / name).write_text(json.dumps(old_payload), encoding="utf-8")

    def fail_replace(self, target):
        if str(target).endswith("release_readiness.llm.json"):
            raise OSError("simulated atomic replace failure")
        return original_replace(self, target)

    original_replace = Path.replace
    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated atomic replace failure"):
        raphael_release_gate(
            profile="llm",
            llm_smoke_session_id="20260701_131600_93f518",
            llm_smoke_command="rtk hermes chat -Q --max-turns 3",
            llm_tool_call_count=0,
            llm_summon_sections_verified=True,
            llm_full_body_preserved=True,
            llm_no_visual_failure_trace=True,
        )

    assert json.loads((evidence_dir / "release_readiness.llm.json").read_text()) == old_payload
    assert json.loads((evidence_dir / "release_readiness.json").read_text()) == old_payload


def test_raphael_release_gate_rolls_back_profile_write_when_legacy_write_fails(
    monkeypatch,
    tmp_path,
):
    from pathlib import Path

    import pytest

    from hermes_cli.raphael_cmd import _write_release_readiness_evidence

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    evidence_dir = tmp_path / "raphael"
    evidence_dir.mkdir()
    old_payload = {
        "schema_version": 1,
        "producer": "hermes-raphael-release-gate",
        "profile": "llm",
        "generated_at": "2026-07-01T00:00:00+00:00",
        "checks": {},
        "public_release_ready": False,
        "release_state": "old_state",
        "blocking_reasons": ["old_blocker"],
        "blocking_layers": ["old_layer"],
        "readiness_next_action": "old action",
        "readiness_blocking_actions": [],
    }
    new_payload = {
        **old_payload,
        "release_state": "new_state",
        "blocking_reasons": [],
        "blocking_layers": [],
        "readiness_next_action": "new action",
    }
    for name in ("release_readiness.json", "release_readiness.llm.json"):
        (evidence_dir / name).write_text(json.dumps(old_payload), encoding="utf-8")

    def fail_legacy_replace(self, target):
        if str(target).endswith("release_readiness.json"):
            raise OSError("simulated legacy replace failure")
        return original_replace(self, target)

    original_replace = Path.replace
    monkeypatch.setattr(Path, "replace", fail_legacy_replace)

    with pytest.raises(OSError, match="simulated legacy replace failure"):
        _write_release_readiness_evidence("llm", new_payload)

    assert json.loads((evidence_dir / "release_readiness.llm.json").read_text()) == old_payload
    assert json.loads((evidence_dir / "release_readiness.json").read_text()) == old_payload


def test_raphael_release_gate_atomic_write_uses_unique_temp_paths(
    monkeypatch,
    tmp_path,
):
    from pathlib import Path

    from hermes_cli.raphael_cmd import _write_text_atomic

    target = tmp_path / "raphael" / "release_readiness.json"
    target.parent.mkdir(parents=True)
    written_tmp_names = []
    original_write_text = Path.write_text

    def track_write_path(self, text, *args, **kwargs):
        if self.parent == target.parent and self.name.startswith(f".{target.name}."):
            written_tmp_names.append(self.name)
        return original_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", track_write_path)

    _write_text_atomic(target, "first")
    _write_text_atomic(target, "second")

    assert len(written_tmp_names) == 2
    assert len(set(written_tmp_names)) == 2
    assert target.read_text(encoding="utf-8") == "second"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_raphael_release_gate_only_publishes_complete_verdict_evidence(
    monkeypatch,
    tmp_path,
):
    import hermes_cli.raphael_cmd as raphael_cmd

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    observed_payloads = []
    required_verdict_fields = {
        "public_release_ready",
        "release_state",
        "blocking_reasons",
        "blocking_layers",
        "readiness_next_action",
        "readiness_blocking_actions",
    }
    original_write_text_atomic = raphael_cmd._write_text_atomic

    def assert_complete_evidence(path, text):
        if path.name.startswith("release_readiness"):
            payload = json.loads(text)
            observed_payloads.append(payload)
            assert required_verdict_fields <= set(payload)
        return original_write_text_atomic(path, text)

    monkeypatch.setattr(
        raphael_cmd,
        "_write_text_atomic",
        assert_complete_evidence,
    )

    result = raphael_cmd.raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **_release_quality_gate_kwargs(tmp_path),
    )

    assert result.public_release_ready is True
    assert len(observed_payloads) == 2


def test_raphael_readiness_rejects_inconsistent_verdict_evidence(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_raw_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {},
            "public_release_ready": True,
            "release_state": "ready_for_llm_only_release",
            "blocking_reasons": [],
            "blocking_layers": [],
            "readiness_next_action": "release_ready",
            "readiness_blocking_actions": [],
            "readiness_repair_plan": [{"step_id": "unexpected_repair"}],
            "readiness_proof_requirements": [],
        },
        profile="llm",
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_verdict_inconsistent" in readiness.blocking_reasons
    assert "llm_live_smoke_missing" in readiness.blocking_reasons
    assert "LLM live smoke: missing" in readiness.message
    assert "Blocking reasons: " in readiness.message


def test_raphael_readiness_rejects_llm_verdict_without_public_claim_scope(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_gate, raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    raphael_release_gate(
        profile="llm",
        llm_smoke_session_id="20260701_131600_93f518",
        llm_smoke_command="rtk hermes chat -Q --max-turns 3",
        llm_tool_call_count=0,
        llm_summon_sections_verified=True,
        llm_full_body_preserved=True,
        llm_no_visual_failure_trace=True,
        **_release_quality_gate_kwargs(tmp_path),
    )
    evidence_path = tmp_path / "raphael" / "release_readiness.llm.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload.pop("public_claim_scope", None)
    payload.pop("public_claim_exclusions", None)
    _write_raw_readiness_evidence(
        tmp_path,
        payload,
        profile="llm",
        include_verdict=False,
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_verdict_inconsistent" in readiness.blocking_reasons


def test_raphael_readiness_preserves_recomputed_blocker_when_verdict_is_inconsistent(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_readiness_evidence(
        tmp_path,
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {
                "install_disable_uninstall": {
                    "status": "pass",
                    "evidence": "lifecycle smoke passed in temp HERMES_HOME",
                    "command": "hermes raphael install && hermes raphael disable && hermes raphael uninstall",
                    "run_id": "lifecycle-1",
                },
                "llm_live_smoke": _llm_smoke_check(),
                "wow_experience": _wow_experience_check(),
            },
        },
        profile="llm",
        include_verdict=False,
    )
    evidence_path = tmp_path / "raphael" / "release_readiness.llm.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["checks"]["llm_live_smoke"]["source_log_path"] = str(
        tmp_path / "missing-agent.log"
    )
    payload.update(
        {
            "public_release_ready": True,
            "release_state": "ready_for_llm_only_release",
            "blocking_reasons": [],
            "blocking_layers": [],
            "readiness_next_action": "release_ready",
            "readiness_blocking_actions": [],
            "readiness_repair_plan": [],
            "readiness_proof_requirements": [],
        }
    )
    _write_raw_readiness_evidence(
        tmp_path,
        payload,
        profile="llm",
        include_verdict=False,
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_verdict_inconsistent" in readiness.blocking_reasons
    assert "llm_live_smoke_unverified" in readiness.blocking_reasons
    assert "llm_live_smoke_smoke_unverified" in readiness.blocking_reasons
    assert "LLM live smoke: smoke_unverified" in readiness.message


def test_raphael_readiness_rejects_verdict_without_repair_plan_for_blockers(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    payload = _payload_with_readiness_verdict(
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {},
        },
        profile="llm",
    )
    payload["readiness_repair_plan"] = []
    _write_raw_readiness_evidence(
        tmp_path,
        payload,
        profile="llm",
        include_verdict=False,
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_verdict_inconsistent" in readiness.blocking_reasons
    assert "llm_live_smoke_missing" in readiness.blocking_reasons
    assert "LLM live smoke: missing" in readiness.message


def test_raphael_readiness_rejects_verdict_without_proof_requirements_for_blockers(
    monkeypatch,
    tmp_path,
):
    from hermes_cli.raphael_cmd import raphael_release_readiness

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    payload = _payload_with_readiness_verdict(
        {
            "schema_version": 1,
            "producer": "hermes-raphael-release-gate",
            "generated_at": _fresh_generated_at(),
            "profile": "llm",
            "checks": {},
        },
        profile="llm",
    )
    payload["readiness_proof_requirements"] = []
    _write_raw_readiness_evidence(
        tmp_path,
        payload,
        profile="llm",
        include_verdict=False,
    )

    readiness = raphael_release_readiness(profile="llm")

    assert readiness.public_release_ready is False
    assert readiness.release_state == "blocked_readiness_evidence_invalid"
    assert "readiness_evidence_verdict_inconsistent" in readiness.blocking_reasons
    assert "llm_live_smoke_missing" in readiness.blocking_reasons
    assert "LLM live smoke: missing" in readiness.message


def test_raphael_command_release_gate_prints_readiness_without_handwritten_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    from types import SimpleNamespace

    from hermes_cli.raphael_cmd import raphael_command

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    transcript_report = _write_llm_smoke_transcript(tmp_path)
    package_report = _package_install_smoke_report(tmp_path)
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)

    raphael_command(
        SimpleNamespace(
            raphael_action="release-gate",
            profile="llm",
            llm_smoke_session_id="20260701_131600_93f518",
            llm_smoke_command="rtk hermes chat -Q --max-turns 3",
            llm_tool_call_count=0,
            llm_transcript_report_path=str(transcript_report),
            llm_summon_sections_verified=True,
            llm_full_body_preserved=True,
            llm_no_visual_failure_trace=True,
            package_install_report_path=str(package_report),
            hostile_review_command="subagent hostile review",
            hostile_review_run_id="hostile-review-20260701-fresh-home-fail-closed-v1",
            hostile_review_verdict="pass",
            hostile_review_blockers=0,
            hostile_review_report_path=str(hostile_report),
            non_visual_regression_command=(
                "pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py"
            ),
            non_visual_regression_run_id="non-visual-regression-20260701-openai-quality-attachment-gate",
            non_visual_regression_passed_count=1529,
            non_visual_regression_visual_quota_used=False,
            non_visual_regression_report_path=str(regression_report),
        )
    )

    output = capsys.readouterr().out

    assert "Raphael release-gate evidence written" in output
    assert "Profile: llm" in output
    assert "Public release ready: yes" in output


def test_raphael_release_gate_help_hides_self_attestation_flags(capsys):
    import pytest

    parser = _build_raphael_test_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["raphael", "release-gate", "--help"])

    output = capsys.readouterr().out

    assert exc.value.code == 0
    assert "--llm-smoke-transcript" in output
    assert "--package-install-report" in output
    assert "--hostile-review-report" in output
    assert "--non-visual-regression-report" in output
    assert "--llm-tool-call-count" not in output
    assert "--llm-summon-sections-verified" not in output
    assert "--llm-full-body-preserved" not in output
    assert "--llm-no-visual-failure-trace" not in output
    assert "--hostile-review-verdict" not in output
    assert "--hostile-review-blockers" not in output
    assert "--non-visual-regression-passed-count" not in output
    assert "--non-visual-regression-visual-quota-used" not in output
    assert "--visual-selected-artifact-id" not in output
    assert "--visual-artifact-quality-verdict" not in output
    assert "--visual-fresh-artifact" not in output


def test_raphael_readiness_and_doctor_help_show_check_flag(capsys):
    import pytest

    parser = _build_raphael_test_parser()

    with pytest.raises(SystemExit) as readiness_exc:
        parser.parse_args(["raphael", "readiness", "--help"])
    readiness_output = capsys.readouterr().out

    with pytest.raises(SystemExit) as doctor_exc:
        parser.parse_args(["raphael", "doctor", "--help"])
    doctor_output = capsys.readouterr().out

    assert readiness_exc.value.code == 0
    assert doctor_exc.value.code == 0
    assert "--check" in readiness_output
    assert "--check" in doctor_output


def test_raphael_proposal_cli_rejects_pending_action_with_audit(
    monkeypatch,
    tmp_path,
    capsys,
):
    from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel
    from agent.raphael.state import get_raphael_events_path, read_state, write_state

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_state(
        RaphaelState(
            status_cards=(),
            action_proposals=(
                ActionProposal(
                    proposal_id="proposal-1",
                    action_type="skill_patch",
                    risk=RiskLevel.R2,
                    summary="Patch Raphael proof gate after recurring signals.",
                    evidence_refs=("evolution:raphael.proof_gate",),
                    created_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
                    metadata={
                        "rollout_plan": {
                            "status": "pending_approval",
                            "verification_commands": [
                                "pytest tests/agent/test_raphael_evolution.py -q",
                            ],
                            "promotion_gate": "focused tests",
                            "rollback_condition": "worse behavior",
                        },
                    },
                ),
            ),
            updated_at=datetime(2026, 6, 16, 9, 1, tzinfo=timezone.utc),
        )
    )
    parser = _build_raphael_test_parser()

    args = parser.parse_args(
        [
            "raphael",
            "proposal",
            "reject",
            "proposal-1",
            "--reason",
            "Declined sk-secret123 /Users/simon/private/trace.json",
        ]
    )
    args.func(args)

    output = capsys.readouterr().out
    stored = read_state()
    event_text = get_raphael_events_path().read_text(encoding="utf-8")

    assert "Raphael action proposal rejected: proposal-1" in output
    assert "No durable change applied automatically" in output
    assert "sk-secret123" not in output
    assert "/Users/simon/private/trace.json" not in output
    assert stored.action_proposals[0].status == "rejected"
    assert stored.action_proposals[0].metadata["rollout_plan"]["status"] == "rejected"
    assert "action_proposal_resolved" in event_text
    assert "sk-secret123" not in event_text
    assert "/Users/simon/private/trace.json" not in event_text


def test_raphael_proposal_cli_accepts_safe_status_reference(
    monkeypatch,
    tmp_path,
    capsys,
):
    from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel
    from agent.raphael.state import read_state, write_state

    proposal_id = "proposal-private-id"
    proposal_ref = hashlib.sha256(proposal_id.encode("utf-8")).hexdigest()[:12]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_state(
        RaphaelState(
            status_cards=(),
            action_proposals=(
                ActionProposal(
                    proposal_id=proposal_id,
                    action_type="skill_patch",
                    risk=RiskLevel.R2,
                    summary="Patch Raphael proof gate after recurring signals.",
                    evidence_refs=("evolution:raphael.proof_gate",),
                    created_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
                ),
            ),
            updated_at=datetime(2026, 6, 16, 9, 1, tzinfo=timezone.utc),
        )
    )
    parser = _build_raphael_test_parser()

    args = parser.parse_args(
        [
            "raphael",
            "proposal",
            "approve",
            proposal_ref,
            "--reason",
            "Approved for manual rollout.",
        ]
    )
    args.func(args)

    output = capsys.readouterr().out
    stored = read_state()

    assert f"Raphael action proposal approved: {proposal_ref}" in output
    assert proposal_id not in output
    assert stored.action_proposals[0].status == "approved"


def test_raphael_proposal_cli_shows_approved_rollout_next_steps(
    monkeypatch,
    tmp_path,
    capsys,
):
    from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel
    from agent.raphael.state import write_state

    proposal_id = "proposal-private-id"
    proposal_ref = hashlib.sha256(proposal_id.encode("utf-8")).hexdigest()[:12]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_state(
        RaphaelState(
            status_cards=(),
            action_proposals=(
                ActionProposal(
                    proposal_id=proposal_id,
                    action_type="skill_patch",
                    risk=RiskLevel.R2,
                    summary="Patch Raphael proof gate after recurring signals.",
                    evidence_refs=("evolution:raphael.proof_gate",),
                    created_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
                    metadata={
                        "rollout_plan": {
                            "status": "pending_approval",
                            "verification_commands": [
                                "pytest tests/agent/test_raphael_evolution.py -q",
                                "hermes raphael readiness --readiness-profile llm --check",
                            ],
                            "promotion_gate": (
                                "focused tests plus runtime, replay, or LLM smoke"
                            ),
                            "rollback_condition": (
                                "next evidence or user feedback shows worse behavior"
                            ),
                        },
                    },
                ),
            ),
            updated_at=datetime(2026, 6, 16, 9, 1, tzinfo=timezone.utc),
        )
    )
    parser = _build_raphael_test_parser()

    args = parser.parse_args(
        [
            "raphael",
            "proposal",
            "approve",
            proposal_ref,
            "--reason",
            "Approved for manual rollout.",
        ]
    )
    args.func(args)

    output = capsys.readouterr().out

    assert f"Raphael action proposal approved: {proposal_ref}" in output
    assert "Next manual rollout:" in output
    assert "Rollout: approved" in output
    assert (
        "Verify: pytest tests/agent/test_raphael_evolution.py -q; "
        "hermes raphael readiness --readiness-profile llm --check"
        in output
    )
    assert "Promote: focused tests plus runtime, replay, or LLM smoke" in output
    assert "Rollback: next evidence or user feedback shows worse behavior" in output
    assert "Apply: manual only after verification; approval did not mutate durable policy." in output
    assert "rollout_plan" not in output
    assert "pending_approval" not in output
    assert proposal_id not in output


def test_raphael_release_gate_cli_infers_evidence_from_reports(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )
    _write_llm_smoke_log(tmp_path)
    transcript_report = _write_llm_smoke_transcript(tmp_path)
    package_report = _package_install_smoke_report(tmp_path)
    hostile_report = _write_hostile_review_report(tmp_path)
    regression_report = _write_non_visual_regression_report(tmp_path)
    parser = _build_raphael_test_parser()

    args = parser.parse_args(
        [
            "raphael",
            "release-gate",
            "--readiness-profile",
            "llm",
            "--llm-smoke-session-id",
            "20260701_131600_93f518",
            "--llm-smoke-command",
            "rtk hermes chat -Q --max-turns 3",
            "--llm-smoke-transcript",
            str(transcript_report),
            "--package-install-report",
            str(package_report),
            "--hostile-review-command",
            "subagent hostile review",
            "--hostile-review-run-id",
            "hostile-review-20260701-fresh-home-fail-closed-v1",
            "--hostile-review-report",
            str(hostile_report),
            "--non-visual-regression-command",
            "pytest tests/agent/test_raphael_*.py tests/hermes_cli/test_raphael_*.py",
            "--non-visual-regression-run-id",
            "non-visual-regression-20260701-openai-quality-attachment-gate",
            "--non-visual-regression-report",
            str(regression_report),
        ]
    )
    args.func(args)

    output = capsys.readouterr().out

    assert "Raphael release-gate evidence written" in output
    assert "Profile: llm" in output
    assert "LLM live smoke: pass" in output
    assert "Hostile review: pass" in output
    assert "Non-visual regression: pass" in output
    assert "Public release ready: yes" in output


def test_raphael_plugin_slash_commands_can_enable_and_disable(monkeypatch, tmp_path):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": False, "default_conversation_mode_enabled": False},
        },
    )

    plugin_dir = Path(__file__).resolve().parents[2] / "plugins" / "raphael"
    module_name = "hermes_plugins.raphael_test_lifecycle"
    spec = importlib.util.spec_from_file_location(
        module_name,
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    assert spec is not None
    assert spec.loader is not None
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    sys.modules.pop(module_name, None)
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = plugin
    spec.loader.exec_module(plugin)

    enabled = plugin.handle_enable("")
    config = _read_config(tmp_path)
    disabled = plugin.handle_disable("")
    config_after_disable = _read_config(tmp_path)

    assert "enabled" in enabled
    assert config["raphael"]["enabled"] is True
    assert config["raphael"]["default_conversation_mode_enabled"] is True
    assert "disabled" in disabled
    assert config_after_disable["raphael"]["enabled"] is False
    assert config_after_disable["raphael"]["default_conversation_mode_enabled"] is False

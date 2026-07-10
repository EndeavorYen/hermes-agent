from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


class FakeVenvCreator:
    def __call__(self, venv_dir: Path, *, with_pip: bool) -> None:
        assert with_pip is True
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "python").write_text("# fake python\n", encoding="utf-8")
        (bin_dir / "hermes").write_text("# fake hermes\n", encoding="utf-8")


class FailingVenvCreator:
    def __call__(self, venv_dir: Path, *, with_pip: bool) -> None:
        assert with_pip is True
        raise RuntimeError("ensurepip aborted")


class FakeRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        wheel_name: str = "hermes_agent-0.17.0-py3-none-any.whl",
        cli_failure_step: str | None = None,
        dirty_pythonpath: bool = False,
        lie_enabled_status_disabled: bool = False,
        create_repo_build_dir: bool = False,
        media_readiness_limited_ready: bool = False,
        llm_readiness_manifest_ready: bool = True,
        llm_readiness_evidence_missing: bool = False,
        durable_evolution_status: bool = False,
    ) -> None:
        self.repo_root = repo_root
        self.wheel_name = wheel_name
        self.cli_failure_step = cli_failure_step
        self.dirty_pythonpath = dirty_pythonpath
        self.lie_enabled_status_disabled = lie_enabled_status_disabled
        self.create_repo_build_dir = create_repo_build_dir
        self.media_readiness_limited_ready = media_readiness_limited_ready
        self.llm_readiness_manifest_ready = llm_readiness_manifest_ready
        self.llm_readiness_evidence_missing = llm_readiness_evidence_missing
        self.durable_evolution_status = durable_evolution_status
        self.calls: list[dict[str, object]] = []
        self.plugin_enabled = False
        self.mode_enabled = False
        self.approve_proposal_id = "package-install-approve-proposal"
        self.reject_proposal_id = "package-install-reject-proposal"
        self.approve_proposal_ref = hashlib.sha256(
            self.approve_proposal_id.encode("utf-8")
        ).hexdigest()[:12]
        self.reject_proposal_ref = hashlib.sha256(
            self.reject_proposal_id.encode("utf-8")
        ).hexdigest()[:12]
        self.proposal_statuses: dict[str, str] = {}

    def __call__(self, command, **kwargs):
        command = [str(item) for item in command]
        cwd = Path(str(kwargs["cwd"])).resolve()
        self.calls.append({"command": command, "cwd": cwd, "env": kwargs.get("env")})
        if command[:3] == ["uv", "build", "--wheel"]:
            if self.create_repo_build_dir:
                build_dir = self.repo_root / "build"
                build_dir.mkdir(parents=True, exist_ok=True)
                (build_dir / "generated.py").write_text("# generated\n", encoding="utf-8")
            wheel_dir = Path(command[command.index("--out-dir") + 1])
            wheel_dir.mkdir(parents=True, exist_ok=True)
            (wheel_dir / self.wheel_name).write_text("wheel", encoding="utf-8")
            return _completed(command, stdout="built wheel")
        if command[:4] == ["uv", "venv", "--clear", "--seed"]:
            bin_dir = Path(command[4]) / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "python").write_text("# fake python\n", encoding="utf-8")
            return _completed(command, stdout="created venv")
        if command[1:4] == ["-m", "pip", "install"]:
            (Path(command[0]).parent / "hermes").write_text(
                "# fake hermes\n",
                encoding="utf-8",
            )
            return _completed(command, stdout="installed wheel")
        if command[1:3] == ["-c", "import json, sys; print(json.dumps(sys.path))"]:
            paths = [str(cwd)]
            if self.dirty_pythonpath:
                paths.append(str(self.repo_root))
            return _completed(command, stdout=f"{paths!r}".replace("'", '"'))
        if len(command) >= 3 and command[1] == "-c":
            script = command[2]
            if "package_install_seed_action_proposals" in script:
                self.proposal_statuses = {
                    self.approve_proposal_id: "pending",
                    self.reject_proposal_id: "pending",
                }
                return _completed(
                    command,
                    stdout=json.dumps(
                        {
                            "seeded": True,
                            "approve_ref": self.approve_proposal_ref,
                            "reject_ref": self.reject_proposal_ref,
                        }
                    ),
                )
            if "package_install_render_action_proposals" in script:
                return _completed(
                    command,
                    stdout=(
                        "Pending Action Proposals:\n"
                        f"  Approve: hermes raphael proposal approve {self.approve_proposal_ref}\n"
                        f"  Reject: hermes raphael proposal reject {self.reject_proposal_ref}\n"
                    ),
                )
            if "package_install_inspect_action_proposals" in script:
                return _completed(
                    command,
                    stdout=json.dumps(
                        {
                            "statuses": dict(self.proposal_statuses),
                            "approve_status": self.proposal_statuses.get(
                                self.approve_proposal_id
                            ),
                            "reject_status": self.proposal_statuses.get(
                                self.reject_proposal_id
                            ),
                        }
                    ),
                )
        if (
            len(command) >= 3
            and command[1] == "-c"
            and "_media_release_readiness_lines" in command[2]
        ):
            limited_line = (
                "Limited media release ready: yes"
                if self.media_gate_limited_ready
                else "Limited media release ready: no"
            )
            return _completed(
                command,
                stdout=(
                    '{"lines":["'
                    + limited_line
                    + '","Full media release ready: no"],'
                    + '"limited_ready_no":'
                    + ("false" if self.media_gate_limited_ready else "true")
                    + ',"limited_ready_yes":'
                    + ("true" if self.media_gate_limited_ready else "false")
                    + "}\n"
                ),
            )
        if command[1:5] == ["raphael", "readiness", "--readiness-profile", "media"]:
            limited_line = (
                "Limited media release ready: yes"
                if self.media_readiness_limited_ready
                else "Limited media release ready: no"
            )
            public_line = (
                "Public release ready: limited (scope: media_openai_image_only; full media gaps remain)"
                if self.media_readiness_limited_ready
                else "Public release ready: no"
            )
            return _completed(
                command,
                returncode=0 if self.media_readiness_limited_ready else 1,
                stdout=(
                    "Raphael Release Readiness\n"
                    "Profile: media\n"
                    f"{limited_line}\n"
                    "Full media release ready: no\n"
                    f"{public_line}\n"
                ),
            )
        if command[1:5] == ["raphael", "readiness", "--readiness-profile", "llm"]:
            if self.llm_readiness_evidence_missing:
                return _completed(
                    command,
                    returncode=1,
                    stdout=(
                        "Raphael Release Readiness\n"
                        "Profile: llm\n"
                        "Release docs: missing\n"
                        "Completion audit: missing\n"
                        "Release slice manifest: missing\n"
                        "Release scope: llm_only\n"
                        "Public claim scope: llm_only "
                        "(does not cover media/Grok/video/full Sage King claims)\n"
                        "Public release ready: no\n"
                        "Release state: blocked_release_evidence_pending\n"
                    ),
                )
            manifest_line = (
                "Release slice manifest: reviewable (split_required)\n"
                if self.llm_readiness_manifest_ready
                else ""
            )
            return _completed(
                command,
                returncode=0,
                stdout=(
                    "Raphael Release Readiness\n"
                    "Profile: llm\n"
                    "Release docs: pass\n"
                    "Completion audit: partial (scoped=yes, ultimate=no)\n"
                    f"{manifest_line}"
                    "Release scope: llm_only\n"
                    "Public claim scope: llm_only "
                    "(does not cover media/Grok/video/full Sage King claims)\n"
                    "Public release ready: yes\n"
                    "Release state: ready_for_llm_only_release\n"
                ),
            )
        if command[1:3] == ["raphael", "status"]:
            if not self.plugin_enabled:
                return _completed(
                    command,
                    stdout=(
                        "Raphael plugin disabled\n"
                        "Evolution writes: audit-only\n"
                        "Next action: hermes raphael install"
                    ),
                )
            if not self.mode_enabled:
                return _completed(
                    command,
                    stdout=(
                        "Raphael Status\n"
                        "Mode: disabled (plugin enabled, mode=sage_king)\n"
                        "Conversation injection: disabled\n"
                        "Slash commands: available\n"
                        "Evolution writes: audit-only\n"
                        "Next action: hermes raphael enable"
                    ),
                )
            if self.lie_enabled_status_disabled:
                return _completed(
                    command,
                    stdout=(
                        "Raphael Status\n"
                        "Mode: disabled (plugin enabled, mode=sage_king)\n"
                        "Conversation injection: disabled\n"
                        "Slash commands: available\n"
                        "Evolution writes: audit-only\n"
                        "Next action: hermes raphael enable"
                    ),
                )
            evolution_line = (
                "Evolution writes: durable enabled"
                if self.durable_evolution_status
                else "Evolution writes: audit-only"
            )
            return _completed(
                command,
                stdout=(
                    "Raphael Status\n"
                    "Mode: enabled (plugin enabled, mode=sage_king)\n"
                    "Conversation injection: enabled\n"
                    "Slash commands: available\n"
                    f"{evolution_line}\n"
                    "Next action: hermes raphael doctor"
                ),
            )
        if command[1:3] == ["raphael", "install"]:
            self.plugin_enabled = True
            self.mode_enabled = True
            return _completed(command, stdout="Raphael mode enabled")
        if command[1:3] == ["raphael", "disable"]:
            if self.cli_failure_step == "disable":
                return _completed(command, returncode=3, stderr="disable failed")
            self.plugin_enabled = True
            self.mode_enabled = False
            return _completed(
                command,
                stdout="Raphael mode disabled; plugin remains enabled",
            )
        if command[1:3] == ["raphael", "enable"]:
            self.plugin_enabled = True
            self.mode_enabled = True
            return _completed(command, stdout="Raphael mode enabled")
        if command[1:4] == ["raphael", "proposal", "approve"]:
            if command[4] != self.approve_proposal_ref:
                return _completed(command, returncode=2, stderr="wrong proposal ref")
            self.proposal_statuses[self.approve_proposal_id] = "approved"
            return _completed(
                command,
                stdout=(
                    f"Raphael action proposal approved: {self.approve_proposal_ref}\n"
                    "Next manual rollout:\n"
                    "  Rollout: approved\n"
                    "  Verify: pytest tests/agent/test_raphael_evolution.py -q; "
                    "hermes raphael readiness --readiness-profile llm --check\n"
                    "  Promote: focused tests plus runtime, replay, or LLM smoke\n"
                    "  Rollback: next evidence or user feedback shows worse behavior\n"
                    "  Apply: manual only after verification; approval did not mutate durable policy.\n"
                    "No durable change applied automatically; run the proposal "
                    "verification commands before applying any skill, memory, cron, "
                    "tool, or delivery change.\n"
                ),
            )
        if command[1:4] == ["raphael", "proposal", "reject"]:
            if command[4] != self.reject_proposal_ref:
                return _completed(command, returncode=2, stderr="wrong proposal ref")
            self.proposal_statuses[self.reject_proposal_id] = "rejected"
            return _completed(
                command,
                stdout=(
                    f"Raphael action proposal rejected: {self.reject_proposal_ref}\n"
                    "No durable change applied automatically; run the proposal "
                    "verification commands before applying any skill, memory, cron, "
                    "tool, or delivery change.\n"
                ),
            )
        if command[1:3] == ["raphael", "uninstall"]:
            self.plugin_enabled = False
            self.mode_enabled = False
            return _completed(command, stdout="Raphael mode uninstalled/disabled")
        return _completed(command)


def _completed(
    command: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_package_install_smoke_report_proves_installed_hermes_entrypoint(tmp_path):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-test",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["schema_version"] == 1
    assert report["kind"] == "raphael_package_install_smoke"
    assert report["command"] == "scripts/raphael_package_install_smoke.py"
    assert report["run_id"] == "package-install-test"
    assert report["success"] is True
    assert report["status"] == "pass"
    assert report["exit_code"] == 0
    assert report["wheel_built"] is True
    assert report["wheel_installed"] is True
    assert report["source_tree_cwd_used"] is False
    assert report["source_tree_hygiene_checked"] is True
    assert report["source_tree_hygiene_clean"] is True
    assert report["source_tree_generated_artifacts"] == []
    assert report["pythonpath_clean"] is True
    assert report["installed_media_slice_ready"] is False
    assert report["installed_media_fail_closed"] is True
    assert report["installed_media_readiness_exit_code"] == 1
    assert report["installed_media_gate_lines"] == [
        "Limited media release ready: no",
        "Full media release ready: no",
        "Public release ready: no",
    ]
    assert report["installed_llm_release_ready"] is True
    assert report["installed_llm_manifest_gate_verified"] is True
    assert report["installed_llm_readiness_exit_code"] == 0
    assert report["installed_llm_gate_lines"] == [
        "Release docs: pass",
        "Completion audit: partial (scoped=yes, ultimate=no)",
        "Release slice manifest: reviewable (split_required)",
        "Release scope: llm_only",
        "Public claim scope: llm_only (does not cover media/Grok/video/full Sage King claims)",
        "Public release ready: yes",
        "Release state: ready_for_llm_only_release",
    ]
    assert report["hermes_entrypoint"] == "hermes"
    assert report["hermes_entrypoint_found"] is True
    assert report["hermes_entrypoint_path"].endswith("/venv/bin/hermes")
    assert report["cli_command_count"] == 10
    assert report["cli_exit_codes"] == [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert report["cli_status_after_install_enabled"] is True
    assert report["cli_status_after_install_audit_only"] is True
    assert report["cli_install_enabled"] is True
    assert report["cli_disable_keeps_plugin"] is True
    assert report["cli_status_after_disable_guides_enable"] is True
    assert report["cli_status_after_enable_enabled"] is True
    assert report["cli_status_after_enable_audit_only"] is True
    assert report["cli_enable_restores_mode"] is True
    assert report["cli_proposal_status_safe_refs"] is True
    assert report["cli_proposal_approve_audited"] is True
    assert report["cli_proposal_approve_rollout_guidance"] is True
    assert report["cli_proposal_reject_audited"] is True
    assert report["cli_proposal_resolutions_persisted"] is True
    assert report["cli_proposal_raw_ids_hidden"] is True
    assert report["cli_proposal_no_durable_apply_warning"] is True
    assert report["cli_uninstall_disables_plugin"] is True
    assert report["cli_status_after_uninstall_guides_install"] is True
    assert report["commands_verified"] is True
    assert report["script_identity_verified"] is True
    assert report["script_sha256"]
    assert report["commands_digest"]
    assert report["failure_classes"] == []
    assert report["residual_risk"]
    runtime_cwds = [call["cwd"] for call in runner.calls if call["command"][1:2] == ["raphael"]]
    assert runtime_cwds
    assert all(cwd != repo_root.resolve() for cwd in runtime_cwds)


def test_package_install_smoke_blocks_installed_media_readiness_not_fail_closed(tmp_path):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root, media_readiness_limited_ready=True)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-media-readiness-false-green",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is False
    assert report["status"] == "fail"
    assert report["installed_media_slice_ready"] is True
    assert report["installed_media_fail_closed"] is False
    assert report["installed_media_gate_lines"] == [
        "Limited media release ready: yes",
        "Full media release ready: no",
        "Public release ready: limited (scope: media_openai_image_only; full media gaps remain)",
    ]
    assert "installed_media_not_fail_closed" in report["failure_classes"]


def test_package_install_smoke_blocks_missing_installed_llm_manifest_gate(tmp_path):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root, llm_readiness_manifest_ready=False)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-llm-manifest-missing",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is False
    assert report["status"] == "fail"
    assert report["installed_llm_release_ready"] is True
    assert report["installed_llm_manifest_gate_verified"] is False
    assert "installed_llm_manifest_gate_unverified" in report["failure_classes"]


def test_package_install_smoke_accepts_installed_llm_readiness_fail_closed_without_evidence(
    tmp_path,
):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root, llm_readiness_evidence_missing=True)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-fresh-home-llm-fail-closed",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is True
    assert report["status"] == "pass"
    assert report["installed_llm_release_ready"] is False
    assert report["installed_llm_fresh_home_fail_closed"] is True
    assert report["installed_llm_gate_lines"] == [
        "Release docs: missing",
        "Completion audit: missing",
        "Release slice manifest: missing",
        "Release scope: llm_only",
        "Public claim scope: llm_only (does not cover media/Grok/video/full Sage King claims)",
        "Public release ready: no",
        "Release state: blocked_release_evidence_pending",
    ]


def test_media_readiness_result_accepts_no_scope_fail_closed_output():
    from scripts import raphael_package_install_smoke

    result = raphael_package_install_smoke._media_readiness_result(
        (
            "Raphael Release Readiness\n"
            "Profile: media\n"
            "Full media release ready: no\n"
            "Public release ready: no\n"
            "Blocking reasons: visual_live_e2e_missing\n"
        ),
        exit_code=1,
    )

    assert result == {
        "slice_ready": False,
        "fail_closed": True,
        "exit_code": 1,
        "lines": [
            "Full media release ready: no",
            "Public release ready: no",
        ],
    }


def test_package_install_smoke_blocks_durable_evolution_public_default(tmp_path):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root, durable_evolution_status=True)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-durable-evolution-default",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is False
    assert report["status"] == "fail"
    assert report["cli_status_after_install_audit_only"] is False
    assert report["cli_status_after_enable_audit_only"] is False
    assert "public_default_evolution_not_audit_only" in report["failure_classes"]


def test_package_install_smoke_report_blocks_generated_runtime_artifacts(tmp_path):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    (repo_root / "tmp").mkdir(parents=True)
    (repo_root / "tmp" / "visual-live-provider-e2e.json").write_text(
        "{}",
        encoding="utf-8",
    )
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-dirty-source-tree",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is False
    assert report["status"] == "fail"
    assert report["source_tree_hygiene_checked"] is True
    assert report["source_tree_hygiene_clean"] is False
    assert report["source_tree_generated_artifacts"] == ["tmp"]
    assert "source_tree_generated_artifacts" in report["failure_classes"]


def test_package_install_smoke_cleans_build_dir_created_by_build(tmp_path):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root, create_repo_build_dir=True)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-build-cleanup",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is True
    assert report["source_tree_hygiene_clean"] is True
    assert report["source_tree_post_build_hygiene_clean"] is True
    assert report["source_tree_generated_artifacts"] == []
    assert not (repo_root / "build").exists()


def test_package_install_smoke_report_blocks_dirty_pythonpath_and_cli_failures(
    tmp_path,
):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(
        repo_root=repo_root,
        cli_failure_step="disable",
        dirty_pythonpath=True,
    )

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-failure-test",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is False
    assert report["status"] == "fail"
    assert report["exit_code"] == 1
    assert report["wheel_built"] is True
    assert report["wheel_installed"] is True
    assert report["source_tree_cwd_used"] is False
    assert report["pythonpath_clean"] is False
    assert report["cli_exit_codes"] == [0, 0, 3, 0, 0, 0, 0, 0, 0, 0]
    assert "pythonpath_dirty" in report["failure_classes"]
    assert "cli_lifecycle_failed" in report["failure_classes"]


def test_package_install_smoke_report_uses_uv_venv_fallback_when_ensurepip_fails(
    tmp_path,
):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(repo_root=repo_root)

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-uv-venv-fallback-test",
        runner=runner,
        venv_creator=FailingVenvCreator(),
    )

    assert report["success"] is True
    assert report["venv_created"] is True
    assert report["venv_fallback_used"] is True
    assert report["venv_error"] == "RuntimeError: ensurepip aborted"
    assert any(
        call["command"][:4] == ["uv", "venv", "--clear", "--seed"]
        for call in runner.calls
    )
    assert report["cli_exit_codes"] == [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]


def test_package_install_smoke_report_blocks_enabled_command_with_disabled_status(
    tmp_path,
):
    from scripts import raphael_package_install_smoke

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    work_dir = tmp_path / "work"
    runner = FakeRunner(
        repo_root=repo_root,
        lie_enabled_status_disabled=True,
    )

    report = raphael_package_install_smoke.build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id="package-install-disabled-status-test",
        runner=runner,
        venv_creator=FakeVenvCreator(),
    )

    assert report["success"] is False
    assert report["status"] == "fail"
    assert report["cli_exit_codes"] == [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert report["cli_status_after_install_enabled"] is False
    assert report["cli_install_enabled"] is False
    assert report["cli_status_after_enable_enabled"] is False
    assert report["cli_enable_restores_mode"] is False
    assert "cli_lifecycle_failed" in report["failure_classes"]

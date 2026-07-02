from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

COMMAND_NAME = "scripts/raphael_package_install_smoke.py"
KIND = "raphael_package_install_smoke"
PYTHONPATH_PROBE = "import json, sys; print(json.dumps(sys.path))"
MEDIA_READINESS_ARGS = (
    "raphael",
    "readiness",
    "--readiness-profile",
    "media",
    "--check",
)
LLM_READINESS_ARGS = (
    "raphael",
    "readiness",
    "--readiness-profile",
    "llm",
    "--check",
)
DEFAULT_RESIDUAL_RISK = (
    "Does not exercise live providers or network installer scripts."
)
SOURCE_TREE_GENERATED_ARTIFACT_DIRS = (
    "build",
    "tmp",
    "temp_vision_images",
)
LIFECYCLE_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("install", ("install",)),
    ("status_after_install", ("status",)),
    ("disable", ("disable",)),
    ("status_after_disable", ("status",)),
    ("enable", ("enable",)),
    ("status_after_enable", ("status",)),
    ("uninstall", ("uninstall",)),
    ("status_after_uninstall", ("status",)),
)
PROPOSAL_APPROVE_ID = "package-install-approve-proposal"
PROPOSAL_REJECT_ID = "package-install-reject-proposal"
PROPOSAL_APPROVE_REF = hashlib.sha256(PROPOSAL_APPROVE_ID.encode("utf-8")).hexdigest()[
    :12
]
PROPOSAL_REJECT_REF = hashlib.sha256(PROPOSAL_REJECT_ID.encode("utf-8")).hexdigest()[
    :12
]
PROPOSAL_CLI_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("proposal_approve", ("proposal", "approve", PROPOSAL_APPROVE_REF)),
    ("proposal_reject", ("proposal", "reject", PROPOSAL_REJECT_REF)),
)

Runner = Callable[..., subprocess.CompletedProcess]
VenvCreator = Callable[..., None]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    work_dir = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else Path(tempfile.mkdtemp(prefix="hermes-raphael-package-install-"))
    )
    report = build_package_install_smoke_report(
        repo_root=repo_root,
        work_dir=work_dir,
        run_id=args.run_id,
        timeout_seconds=args.timeout,
        argv=list(argv or sys.argv[1:]),
    )
    text = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.get("success") is True else 1


def build_package_install_smoke_report(
    *,
    repo_root: str | Path,
    work_dir: str | Path,
    run_id: str | None = None,
    timeout_seconds: int = 600,
    runner: Runner = subprocess.run,
    venv_creator: VenvCreator = venv.create,
    argv: list[str] | None = None,
) -> dict[str, Any]:
    generated_at = _utc_now_text()
    repo = Path(repo_root).expanduser().resolve()
    work = Path(work_dir).expanduser().resolve()
    wheel_dir = work / "wheel"
    venv_dir = work / "venv"
    runtime_cwd = work / "runtime-cwd"
    hermes_home = work / "hermes-home"
    wheel_dir.mkdir(parents=True, exist_ok=True)
    runtime_cwd.mkdir(parents=True, exist_ok=True)
    hermes_home.mkdir(parents=True, exist_ok=True)

    evidence: list[str] = []
    failure_classes: list[str] = []
    command_records: list[dict[str, Any]] = []
    runtime_records: list[dict[str, Any]] = []
    source_tree_hygiene = _source_tree_hygiene(repo)
    build_dir_preexisting = (repo / "build").exists()
    if source_tree_hygiene["clean"]:
        evidence.append("verified source tree has no generated runtime artifacts")
    else:
        failure_classes.append("source_tree_generated_artifacts")

    build_result = _run_command(
        runner,
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir), "."],
        cwd=repo,
        env=_clean_env(),
        timeout=timeout_seconds,
        label="build_wheel",
    )
    command_records.append(build_result)
    wheel = _latest_wheel(wheel_dir)
    wheel_built = build_result["exit_code"] == 0 and wheel is not None
    if wheel_built:
        evidence.append("built wheel from current checkout")
    else:
        failure_classes.append("wheel_build_failed")
    if not build_dir_preexisting:
        _remove_generated_build_dir(repo)
    source_tree_post_build_hygiene = _source_tree_hygiene(repo)
    if source_tree_post_build_hygiene["clean"]:
        evidence.append("verified source tree remains clean after wheel build")
    else:
        failure_classes.append("source_tree_post_build_generated_artifacts")

    venv_created = False
    venv_fallback_used = False
    venv_error = ""
    if wheel_built:
        try:
            venv_creator(venv_dir, with_pip=True)
            venv_created = True
            evidence.append("created fresh virtual environment")
        except Exception as exc:
            venv_error = f"{exc.__class__.__name__}: {exc}"
            fallback_result = _run_command(
                runner,
                ["uv", "venv", "--clear", "--seed", str(venv_dir)],
                cwd=work,
                env=_clean_env(),
                timeout=timeout_seconds,
                label="create_venv_uv_fallback",
            )
            command_records.append(fallback_result)
            if fallback_result["exit_code"] == 0:
                venv_created = True
                venv_fallback_used = True
                evidence.append("created fresh virtual environment with uv fallback")
            else:
                failure_classes.append("venv_create_failed")

    python_entrypoint = _venv_executable(venv_dir, "python")
    hermes_entrypoint_path = _venv_executable(venv_dir, "hermes")
    install_result: dict[str, Any] | None = None
    wheel_installed = False
    runtime_env = _runtime_env(venv_dir=venv_dir, hermes_home=hermes_home)
    if wheel_built and venv_created and wheel is not None:
        install_result = _run_command(
            runner,
            [
                str(python_entrypoint),
                "-m",
                "pip",
                "install",
                "-q",
                "--force-reinstall",
                str(wheel),
            ],
            cwd=work,
            env=runtime_env,
            timeout=timeout_seconds,
            label="install_wheel",
        )
        command_records.append(install_result)
        wheel_installed = install_result["exit_code"] == 0
        if wheel_installed:
            evidence.append("installed wheel into fresh virtual environment")
        else:
            failure_classes.append("wheel_install_failed")

    hermes_entrypoint_found = hermes_entrypoint_path.is_file()
    if not hermes_entrypoint_found:
        failure_classes.append("cli_entrypoint_missing")

    pythonpath_probe: dict[str, Any] | None = None
    pythonpath_clean = False
    media_readiness_probe: dict[str, Any] | None = None
    installed_media_slice_ready = False
    installed_media_fail_closed = False
    installed_media_readiness_exit_code: int | None = None
    installed_media_gate_lines: list[str] = []
    llm_readiness_probe: dict[str, Any] | None = None
    installed_llm_release_ready = False
    installed_llm_manifest_gate_verified = False
    installed_llm_fresh_home_fail_closed = False
    installed_llm_readiness_exit_code: int | None = None
    installed_llm_gate_lines: list[str] = []
    cli_records: list[dict[str, Any]] = []
    if wheel_installed and hermes_entrypoint_found:
        pythonpath_probe = _run_command(
            runner,
            [str(python_entrypoint), "-c", PYTHONPATH_PROBE],
            cwd=runtime_cwd,
            env=runtime_env,
            timeout=60,
            label="pythonpath_probe",
        )
        runtime_records.append(pythonpath_probe)
        command_records.append(pythonpath_probe)
        pythonpath_clean = _pythonpath_probe_is_clean(
            pythonpath_probe.get("stdout", ""),
            repo_root=repo,
        )
        if pythonpath_clean:
            evidence.append("verified installed runtime sys.path avoids source tree")
        else:
            failure_classes.append("pythonpath_dirty")

        for label, step_args in LIFECYCLE_STEPS:
            record = _run_command(
                runner,
                [str(hermes_entrypoint_path), "raphael", *step_args],
                cwd=runtime_cwd,
                env=runtime_env,
                timeout=60,
                label=label,
            )
            cli_records.append(record)
            runtime_records.append(record)
            command_records.append(record)
            if label == "status_after_install":
                media_readiness_probe = _run_command(
                    runner,
                    [str(hermes_entrypoint_path), *MEDIA_READINESS_ARGS],
                    cwd=runtime_cwd,
                    env=runtime_env,
                    timeout=60,
                    label="media_readiness_after_install",
                )
                runtime_records.append(media_readiness_probe)
                command_records.append(media_readiness_probe)
                media_readiness = _media_readiness_result(
                    media_readiness_probe.get("stdout", ""),
                    exit_code=media_readiness_probe.get("exit_code"),
                )
                installed_media_slice_ready = media_readiness["slice_ready"]
                installed_media_fail_closed = media_readiness["fail_closed"]
                installed_media_readiness_exit_code = media_readiness["exit_code"]
                installed_media_gate_lines = media_readiness["lines"]
                if installed_media_fail_closed:
                    evidence.append(
                        "verified installed media readiness fails closed without media evidence"
                    )
                else:
                    failure_classes.append("installed_media_not_fail_closed")
                llm_readiness_probe = _run_command(
                    runner,
                    [str(hermes_entrypoint_path), *LLM_READINESS_ARGS],
                    cwd=runtime_cwd,
                    env=runtime_env,
                    timeout=60,
                    label="llm_readiness_after_install",
                )
                runtime_records.append(llm_readiness_probe)
                command_records.append(llm_readiness_probe)
                llm_readiness = _llm_readiness_result(
                    llm_readiness_probe.get("stdout", ""),
                    exit_code=llm_readiness_probe.get("exit_code"),
                )
                installed_llm_release_ready = llm_readiness["release_ready"]
                installed_llm_manifest_gate_verified = llm_readiness[
                    "manifest_gate_verified"
                ]
                installed_llm_fresh_home_fail_closed = llm_readiness["fail_closed"]
                installed_llm_readiness_exit_code = llm_readiness["exit_code"]
                installed_llm_gate_lines = llm_readiness["lines"]
                if installed_llm_manifest_gate_verified:
                    evidence.append(
                        "verified installed LLM readiness includes release slice manifest gate"
                    )
                elif installed_llm_fresh_home_fail_closed:
                    evidence.append(
                        "verified installed LLM readiness fails closed without release evidence"
                    )
                else:
                    failure_classes.append("installed_llm_manifest_gate_unverified")
            if label == "status_after_enable":
                for runtime_label, runtime_script in (
                    ("seed_action_proposals", _proposal_seed_script()),
                    ("render_action_proposals", _proposal_render_script()),
                ):
                    runtime_record = _run_command(
                        runner,
                        [str(python_entrypoint), "-c", runtime_script],
                        cwd=runtime_cwd,
                        env=runtime_env,
                        timeout=60,
                        label=runtime_label,
                    )
                    runtime_records.append(runtime_record)
                    command_records.append(runtime_record)
                for proposal_label, proposal_args in PROPOSAL_CLI_STEPS:
                    proposal_record = _run_command(
                        runner,
                        [str(hermes_entrypoint_path), "raphael", *proposal_args],
                        cwd=runtime_cwd,
                        env=runtime_env,
                        timeout=60,
                        label=proposal_label,
                    )
                    cli_records.append(proposal_record)
                    runtime_records.append(proposal_record)
                    command_records.append(proposal_record)
                inspect_record = _run_command(
                    runner,
                    [str(python_entrypoint), "-c", _proposal_inspect_script()],
                    cwd=runtime_cwd,
                    env=runtime_env,
                    timeout=60,
                    label="inspect_action_proposals",
                )
                runtime_records.append(inspect_record)
                command_records.append(inspect_record)

    cli_exit_codes = [int(record["exit_code"]) for record in cli_records]
    outputs = {
        str(record["label"]): f"{record.get('stdout', '')}\n{record.get('stderr', '')}"
        for record in cli_records
    }
    all_outputs = {
        str(record["label"]): f"{record.get('stdout', '')}\n{record.get('stderr', '')}"
        for record in command_records
    }
    exit_codes_by_label = {
        str(record["label"]): int(record["exit_code"]) for record in command_records
    }
    lifecycle_checks = _lifecycle_checks(exit_codes_by_label, outputs)
    proposal_checks = _proposal_lifecycle_checks(
        exit_codes_by_label=exit_codes_by_label,
        outputs=all_outputs,
    )
    source_tree_cwd_used = any(
        _same_or_child(Path(str(record["cwd"])).resolve(), repo)
        for record in runtime_records
    )
    if source_tree_cwd_used:
        failure_classes.append("source_tree_cwd_used")
    if cli_records and (
        not all(code == 0 for code in cli_exit_codes)
        or not all(lifecycle_checks.values())
    ):
        failure_classes.append("cli_lifecycle_failed")
    if cli_records and not (
        lifecycle_checks.get("cli_status_after_install_audit_only")
        and lifecycle_checks.get("cli_status_after_enable_audit_only")
    ):
        failure_classes.append("public_default_evolution_not_audit_only")
    if cli_records and not all(proposal_checks.values()):
        failure_classes.append("cli_proposal_lifecycle_failed")
    expected_cli_count = len(LIFECYCLE_STEPS) + len(PROPOSAL_CLI_STEPS)
    if len(cli_records) == expected_cli_count and all(lifecycle_checks.values()):
        evidence.append("ran Raphael lifecycle through installed hermes entrypoint")
    if proposal_checks and all(proposal_checks.values()):
        evidence.append(
            "ran Raphael proposal approve/reject through installed hermes entrypoint"
        )

    failure_classes = _unique(failure_classes)
    script_path = Path(__file__).resolve()
    script_sha256 = _file_sha256(script_path)
    script_identity_verified = bool(script_sha256)
    commands_digest = _command_records_digest(command_records)
    commands_verified = _command_records_verified(
        command_records,
        venv_fallback_used=venv_fallback_used,
    )
    if not script_identity_verified:
        failure_classes.append("script_identity_unverified")
    if not commands_verified:
        failure_classes.append("command_transcript_unverified")
    failure_classes = _unique(failure_classes)
    success = (
        wheel_built
        and wheel_installed
        and not source_tree_cwd_used
        and pythonpath_clean
        and hermes_entrypoint_found
        and len(cli_exit_codes) == expected_cli_count
        and all(code == 0 for code in cli_exit_codes)
        and all(lifecycle_checks.values())
        and all(proposal_checks.values())
        and installed_media_fail_closed
        and (installed_llm_manifest_gate_verified or installed_llm_fresh_home_fail_closed)
        and script_identity_verified
        and commands_verified
        and source_tree_hygiene["clean"]
        and source_tree_post_build_hygiene["clean"]
        and not failure_classes
    )
    return {
        "schema_version": 1,
        "kind": KIND,
        "generated_at": generated_at,
        "command": COMMAND_NAME,
        "arguments": list(argv or []),
        "run_id": run_id or _default_run_id(generated_at),
        "script_path": str(script_path),
        "script_sha256": script_sha256,
        "script_identity_verified": script_identity_verified,
        "success": success,
        "status": "pass" if success else "fail",
        "exit_code": 0 if success else 1,
        "repo_root": str(repo),
        "work_dir": str(work),
        "wheel_dir": str(wheel_dir),
        "wheel_path": str(wheel) if wheel else "",
        "venv_dir": str(venv_dir),
        "venv_created": venv_created,
        "venv_fallback_used": venv_fallback_used,
        "venv_error": venv_error,
        "runtime_cwd": str(runtime_cwd),
        "hermes_home": str(hermes_home),
        "wheel_built": wheel_built,
        "wheel_installed": wheel_installed,
        "source_tree_cwd_used": source_tree_cwd_used,
        "source_tree_hygiene_checked": source_tree_hygiene["checked"],
        "source_tree_hygiene_clean": source_tree_hygiene["clean"],
        "source_tree_generated_artifacts": source_tree_hygiene["generated_artifacts"],
        "source_tree_post_build_hygiene_clean": source_tree_post_build_hygiene[
            "clean"
        ],
        "source_tree_post_build_generated_artifacts": source_tree_post_build_hygiene[
            "generated_artifacts"
        ],
        "pythonpath_clean": pythonpath_clean,
        "installed_media_slice_ready": installed_media_slice_ready,
        "installed_media_fail_closed": installed_media_fail_closed,
        "installed_media_readiness_exit_code": installed_media_readiness_exit_code,
        "installed_media_gate_lines": installed_media_gate_lines,
        "installed_media_gate_probe": media_readiness_probe or {},
        "installed_llm_release_ready": installed_llm_release_ready,
        "installed_llm_manifest_gate_verified": installed_llm_manifest_gate_verified,
        "installed_llm_fresh_home_fail_closed": installed_llm_fresh_home_fail_closed,
        "installed_llm_readiness_exit_code": installed_llm_readiness_exit_code,
        "installed_llm_gate_lines": installed_llm_gate_lines,
        "installed_llm_gate_probe": llm_readiness_probe or {},
        "hermes_entrypoint": "hermes",
        "hermes_entrypoint_found": hermes_entrypoint_found,
        "hermes_entrypoint_path": str(hermes_entrypoint_path),
        "cli_command_count": len(cli_records),
        "cli_exit_codes": cli_exit_codes,
        "cli_status_after_install_enabled": lifecycle_checks[
            "cli_status_after_install_enabled"
        ],
        "cli_status_after_install_audit_only": lifecycle_checks[
            "cli_status_after_install_audit_only"
        ],
        "cli_install_enabled": lifecycle_checks["cli_install_enabled"],
        "cli_disable_keeps_plugin": lifecycle_checks["cli_disable_keeps_plugin"],
        "cli_status_after_disable_guides_enable": lifecycle_checks[
            "cli_status_after_disable_guides_enable"
        ],
        "cli_status_after_enable_enabled": lifecycle_checks[
            "cli_status_after_enable_enabled"
        ],
        "cli_status_after_enable_audit_only": lifecycle_checks[
            "cli_status_after_enable_audit_only"
        ],
        "cli_enable_restores_mode": lifecycle_checks["cli_enable_restores_mode"],
        "cli_proposal_status_safe_refs": proposal_checks[
            "cli_proposal_status_safe_refs"
        ],
        "cli_proposal_approve_audited": proposal_checks[
            "cli_proposal_approve_audited"
        ],
        "cli_proposal_approve_rollout_guidance": proposal_checks[
            "cli_proposal_approve_rollout_guidance"
        ],
        "cli_proposal_reject_audited": proposal_checks[
            "cli_proposal_reject_audited"
        ],
        "cli_proposal_resolutions_persisted": proposal_checks[
            "cli_proposal_resolutions_persisted"
        ],
        "cli_proposal_raw_ids_hidden": proposal_checks[
            "cli_proposal_raw_ids_hidden"
        ],
        "cli_proposal_no_durable_apply_warning": proposal_checks[
            "cli_proposal_no_durable_apply_warning"
        ],
        "cli_uninstall_disables_plugin": lifecycle_checks[
            "cli_uninstall_disables_plugin"
        ],
        "cli_status_after_uninstall_guides_install": lifecycle_checks[
            "cli_status_after_uninstall_guides_install"
        ],
        "commands_verified": commands_verified,
        "commands_digest": commands_digest,
        "failure_classes": failure_classes,
        "commands": command_records,
        "pythonpath_probe": pythonpath_probe or {},
        "evidence": evidence or ["package install smoke did not reach trusted runtime evidence"],
        "residual_risk": DEFAULT_RESIDUAL_RISK,
    }


def _source_tree_hygiene(repo: Path) -> dict[str, Any]:
    generated_artifacts: list[str] = []
    for relative in SOURCE_TREE_GENERATED_ARTIFACT_DIRS:
        path = repo / relative
        if _path_has_contents(path):
            generated_artifacts.append(relative)
    return {
        "checked": True,
        "clean": not generated_artifacts,
        "generated_artifacts": generated_artifacts,
    }


def _path_has_contents(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return True
    if not path.is_dir():
        return True
    try:
        next(path.iterdir())
    except StopIteration:
        return False
    except OSError:
        return True
    return True


def _remove_generated_build_dir(repo: Path) -> None:
    build_dir = repo / "build"
    if not build_dir.exists():
        return
    if build_dir.is_dir():
        shutil.rmtree(build_dir)
        return
    build_dir.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, install, and lifecycle-smoke Raphael mode from a fresh wheel."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Hermes checkout to build from",
    )
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--timeout", type=int, default=600)
    return parser


def _run_command(
    runner: Runner,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    label: str,
) -> dict[str, Any]:
    try:
        result = runner(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return {
            "label": label,
            "command": command,
            "cwd": str(cwd),
            "exit_code": 124,
            "stdout": "",
            "stderr": f"{exc.__class__.__name__}: {exc}",
        }
    return {
        "label": label,
        "command": command,
        "cwd": str(cwd),
        "exit_code": int(result.returncode),
        "stdout": str(result.stdout or ""),
        "stderr": str(result.stderr or ""),
    }


def _latest_wheel(wheel_dir: Path) -> Path | None:
    wheels = sorted(
        wheel_dir.glob("*.whl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return wheels[0].resolve() if wheels else None


def _runtime_env(*, venv_dir: Path, hermes_home: Path) -> dict[str, str]:
    env = _clean_env()
    bin_dir = _venv_bin_dir(venv_dir)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["HERMES_HOME"] = str(hermes_home)
    return env


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "PYTHONPATH",
        "HERMES_BUNDLED_LOCALES",
        "PYTHONHOME",
    ):
        env.pop(key, None)
    return env


def _venv_bin_dir(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _venv_executable(venv_dir: Path, name: str) -> Path:
    bin_dir = _venv_bin_dir(venv_dir)
    if os.name == "nt" and name != "python":
        exe = bin_dir / f"{name}.exe"
        if exe.exists():
            return exe
    if os.name == "nt" and name == "python":
        exe = bin_dir / "python.exe"
        if exe.exists():
            return exe
    return bin_dir / name


def _pythonpath_probe_is_clean(stdout: str, *, repo_root: Path) -> bool:
    try:
        paths = json.loads(str(stdout or "[]"))
    except json.JSONDecodeError:
        return False
    if not isinstance(paths, list):
        return False
    repo = repo_root.resolve()
    for item in paths:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            candidate = Path(text).expanduser().resolve()
        except OSError:
            continue
        if _same_or_child(candidate, repo):
            return False
    return True


def _media_readiness_result(stdout: str, *, exit_code: Any) -> dict[str, Any]:
    try:
        parsed_exit_code = int(exit_code)
    except (TypeError, ValueError):
        parsed_exit_code = -1
    lines = [
        line.strip()
        for line in str(stdout or "").splitlines()
        if "media release ready:" in line or line.strip().startswith("Public release ready:")
    ]
    slice_ready = (
        parsed_exit_code == 0
        and "Limited media release ready: yes" in lines
        and "Full media release ready: no" in lines
    )
    limited_no_or_absent = (
        "Limited media release ready: no" in lines
        or not any(line.startswith("Limited media release ready:") for line in lines)
    )
    fail_closed = (
        parsed_exit_code != 0
        and limited_no_or_absent
        and "Full media release ready: no" in lines
        and "Public release ready: no" in lines
    )
    return {
        "slice_ready": slice_ready,
        "fail_closed": fail_closed,
        "exit_code": parsed_exit_code,
        "lines": lines,
    }


def _llm_readiness_result(stdout: str, *, exit_code: Any) -> dict[str, Any]:
    try:
        parsed_exit_code = int(exit_code)
    except (TypeError, ValueError):
        parsed_exit_code = -1
    prefixes = (
        "Release docs:",
        "Completion audit:",
        "Release slice manifest:",
        "Release scope:",
        "Public claim scope:",
        "Public release ready:",
        "Release state:",
    )
    lines = [
        line.strip()
        for line in str(stdout or "").splitlines()
        if line.strip().startswith(prefixes)
    ]
    manifest_gate_verified = any(
        line.startswith("Release slice manifest: reviewable") for line in lines
    )
    release_ready = (
        parsed_exit_code == 0
        and "Release docs: pass" in lines
        and "Release scope: llm_only" in lines
        and "Public release ready: yes" in lines
        and "Release state: ready_for_llm_only_release" in lines
    )
    fail_closed = (
        parsed_exit_code != 0
        and "Release scope: llm_only" in lines
        and "Public release ready: no" in lines
        and "Release state: blocked_release_evidence_pending" in lines
        and not any(
            line.startswith("Public release ready: yes")
            or line.startswith("Public release ready: limited")
            for line in lines
        )
    )
    return {
        "release_ready": release_ready,
        "manifest_gate_verified": manifest_gate_verified,
        "fail_closed": fail_closed,
        "exit_code": parsed_exit_code,
        "lines": lines,
    }


def _proposal_seed_script() -> str:
    return f"""
import json
from datetime import datetime, timezone
from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel
from agent.raphael.state import read_state, write_state

print('package_install_seed_action_proposals')
now = datetime.now(timezone.utc)
state = read_state()
kept = tuple(
    proposal
    for proposal in state.action_proposals
    if proposal.proposal_id not in {{{PROPOSAL_APPROVE_ID!r}, {PROPOSAL_REJECT_ID!r}}}
)
seeded = (
    ActionProposal(
        proposal_id={PROPOSAL_APPROVE_ID!r},
        action_type='skill_patch',
        risk=RiskLevel.R2,
        summary='Package smoke approve proposal.',
        evidence_refs=('package-install-smoke',),
        created_at=now,
        metadata={{'rollout_plan': {{
            'status': 'pending_approval',
            'verification_commands': [
                'pytest tests/agent/test_raphael_evolution.py -q',
                'hermes raphael readiness --readiness-profile llm --check',
            ],
            'promotion_gate': 'focused tests plus runtime, replay, or LLM smoke',
            'rollback_condition': 'next evidence or user feedback shows worse behavior',
        }}}},
    ),
    ActionProposal(
        proposal_id={PROPOSAL_REJECT_ID!r},
        action_type='skill_patch',
        risk=RiskLevel.R2,
        summary='Package smoke reject proposal.',
        evidence_refs=('package-install-smoke',),
        created_at=now,
        metadata={{'rollout_plan': {{'status': 'pending_approval'}}}},
    ),
)
write_state(
    RaphaelState(
        status_cards=state.status_cards,
        action_proposals=kept + seeded,
        updated_at=now,
    )
)
print(json.dumps({{'seeded': True, 'approve_ref': {PROPOSAL_APPROVE_REF!r}, 'reject_ref': {PROPOSAL_REJECT_REF!r}}}, sort_keys=True))
"""


def _proposal_render_script() -> str:
    return """
from agent.raphael.state import read_state
from agent.raphael.status import render_status

print('package_install_render_action_proposals')
print(render_status(read_state()))
"""


def _proposal_inspect_script() -> str:
    return f"""
import json
from agent.raphael.state import read_state

print('package_install_inspect_action_proposals')
state = read_state()
statuses = {{
    proposal.proposal_id: proposal.status
    for proposal in state.action_proposals
    if proposal.proposal_id in ({PROPOSAL_APPROVE_ID!r}, {PROPOSAL_REJECT_ID!r})
}}
print(json.dumps({{
    'statuses': statuses,
    'approve_status': statuses.get({PROPOSAL_APPROVE_ID!r}),
    'reject_status': statuses.get({PROPOSAL_REJECT_ID!r}),
}}, sort_keys=True))
"""


def _lifecycle_checks(
    exit_codes_by_label: dict[str, int],
    outputs: dict[str, str],
) -> dict[str, bool]:
    def exit_code(label: str) -> int | None:
        return exit_codes_by_label.get(label)

    status_after_install_enabled = (
        exit_code("status_after_install") == 0
        and _status_output_enabled(outputs.get("status_after_install", ""))
    )
    status_after_install_audit_only = (
        exit_code("status_after_install") == 0
        and _status_output_audit_only(outputs.get("status_after_install", ""))
    )
    status_after_enable_enabled = (
        exit_code("status_after_enable") == 0
        and _status_output_enabled(outputs.get("status_after_enable", ""))
    )
    status_after_enable_audit_only = (
        exit_code("status_after_enable") == 0
        and _status_output_audit_only(outputs.get("status_after_enable", ""))
    )
    return {
        "cli_status_after_install_enabled": status_after_install_enabled,
        "cli_status_after_install_audit_only": status_after_install_audit_only,
        "cli_install_enabled": (
            exit_code("install") == 0
            and "Raphael mode enabled" in outputs.get("install", "")
            and status_after_install_enabled
            and status_after_install_audit_only
        ),
        "cli_disable_keeps_plugin": (
            exit_code("disable") == 0
            and "Raphael mode disabled" in outputs.get("disable", "")
            and "plugin remains enabled" in outputs.get("disable", "")
        ),
        "cli_status_after_disable_guides_enable": (
            exit_code("status_after_disable") == 0
            and "Slash commands: available"
            in outputs.get("status_after_disable", "")
            and "Next action: hermes raphael enable"
            in outputs.get("status_after_disable", "")
        ),
        "cli_status_after_enable_enabled": status_after_enable_enabled,
        "cli_status_after_enable_audit_only": status_after_enable_audit_only,
        "cli_enable_restores_mode": (
            exit_code("enable") == 0
            and "Raphael mode enabled" in outputs.get("enable", "")
            and status_after_enable_enabled
            and status_after_enable_audit_only
        ),
        "cli_uninstall_disables_plugin": (
            exit_code("uninstall") == 0
            and "Raphael mode uninstalled/disabled"
            in outputs.get("uninstall", "")
        ),
        "cli_status_after_uninstall_guides_install": (
            exit_code("status_after_uninstall") == 0
            and "plugin disabled" in outputs.get("status_after_uninstall", "")
            and "Next action: hermes raphael install"
            in outputs.get("status_after_uninstall", "")
        ),
    }


def _proposal_lifecycle_checks(
    *,
    exit_codes_by_label: dict[str, int],
    outputs: dict[str, str],
) -> dict[str, bool]:
    rendered = outputs.get("render_action_proposals", "")
    approve_output = outputs.get("proposal_approve", "")
    reject_output = outputs.get("proposal_reject", "")
    inspect_output = outputs.get("inspect_action_proposals", "")
    inspect = _parse_last_json_object(inspect_output)
    safe_refs_present = (
        f"Approve: hermes raphael proposal approve {PROPOSAL_APPROVE_REF}" in rendered
        and f"Reject: hermes raphael proposal reject {PROPOSAL_REJECT_REF}" in rendered
    )
    raw_ids_hidden = (
        PROPOSAL_APPROVE_ID not in rendered
        and PROPOSAL_REJECT_ID not in rendered
        and PROPOSAL_APPROVE_ID not in approve_output
        and PROPOSAL_REJECT_ID not in reject_output
    )
    no_durable_warning = (
        "No durable change applied automatically" in approve_output
        and "No durable change applied automatically" in reject_output
    )
    approve_rollout_guidance = (
        "Next manual rollout:" in approve_output
        and "Rollout: approved" in approve_output
        and "Verify: pytest tests/agent/test_raphael_evolution.py -q; "
        "hermes raphael readiness --readiness-profile llm --check" in approve_output
        and "Promote: focused tests plus runtime, replay, or LLM smoke"
        in approve_output
        and "Rollback: next evidence or user feedback shows worse behavior"
        in approve_output
        and (
            "Apply: manual only after verification; approval did not mutate durable policy."
            in approve_output
        )
    )
    return {
        "cli_proposal_status_safe_refs": (
            exit_codes_by_label.get("seed_action_proposals") == 0
            and exit_codes_by_label.get("render_action_proposals") == 0
            and safe_refs_present
        ),
        "cli_proposal_approve_audited": (
            exit_codes_by_label.get("proposal_approve") == 0
            and f"Raphael action proposal approved: {PROPOSAL_APPROVE_REF}"
            in approve_output
            and no_durable_warning
        ),
        "cli_proposal_approve_rollout_guidance": approve_rollout_guidance,
        "cli_proposal_reject_audited": (
            exit_codes_by_label.get("proposal_reject") == 0
            and f"Raphael action proposal rejected: {PROPOSAL_REJECT_REF}"
            in reject_output
            and no_durable_warning
        ),
        "cli_proposal_resolutions_persisted": (
            exit_codes_by_label.get("inspect_action_proposals") == 0
            and inspect.get("approve_status") == "approved"
            and inspect.get("reject_status") == "rejected"
        ),
        "cli_proposal_raw_ids_hidden": raw_ids_hidden,
        "cli_proposal_no_durable_apply_warning": no_durable_warning,
    }


def _parse_last_json_object(text: str) -> dict[str, Any]:
    for line in reversed(str(text or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _status_output_enabled(output: str) -> bool:
    return (
        "Mode: enabled" in output
        and "Conversation injection: enabled" in output
        and "Slash commands: available" in output
    )


def _status_output_audit_only(output: str) -> bool:
    return "Evolution writes: audit-only" in output


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _command_records_digest(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _command_records_verified(
    records: list[dict[str, Any]],
    *,
    venv_fallback_used: bool,
) -> bool:
    labels = [str(record.get("label") or "") for record in records]
    expected = ["build_wheel"]
    if venv_fallback_used:
        expected.append("create_venv_uv_fallback")
    expected.extend(["install_wheel", "pythonpath_probe"])
    for label, _step_args in LIFECYCLE_STEPS:
        expected.append(label)
        if label == "status_after_install":
            expected.append("media_readiness_after_install")
            expected.append("llm_readiness_after_install")
        if label == "status_after_enable":
            expected.extend(
                [
                    "seed_action_proposals",
                    "render_action_proposals",
                    *(proposal_label for proposal_label, _ in PROPOSAL_CLI_STEPS),
                    "inspect_action_proposals",
                ]
            )
    if labels != expected:
        return False
    for record in records:
        command = record.get("command")
        cwd = str(record.get("cwd") or "").strip()
        if not isinstance(command, list) or not command or not cwd:
            return False
        try:
            int(record.get("exit_code"))
        except (TypeError, ValueError):
            return False
    return True


def _same_or_child(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _default_run_id(generated_at: str) -> str:
    suffix = generated_at.replace(":", "").replace("-", "").replace(".", "")
    return f"raphael-package-install-{suffix}"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

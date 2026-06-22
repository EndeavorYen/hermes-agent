from __future__ import annotations

import importlib


def _reload_cron_for_home(monkeypatch, home):
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_constants

    importlib.reload(hermes_constants)
    import cron.jobs as cron_jobs

    importlib.reload(cron_jobs)
    return cron_jobs


def test_visual_self_validation_cron_installs_live_no_agent_job(monkeypatch, tmp_path):
    cron_jobs = _reload_cron_for_home(monkeypatch, tmp_path)
    from scripts.visual_self_validation_cron import ensure_visual_self_validation_cron

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    report = ensure_visual_self_validation_cron(
        repo_root=repo_root,
        schedule="every 6h",
        live_mode="auto",
        enable_live_provider=True,
        case_timeout_seconds=240,
    )

    assert report["success"] is True
    assert report["action"] == "created"
    assert report["self_review"]["reduces_human_intervention"] is True
    assert report["self_review"]["cron_safe"] is True
    assert report["self_review"]["live_provider_enabled"] is True
    assert report["script"]["relative_path"] == "visual_self_validation_cron.sh"

    script_path = tmp_path / "scripts" / "visual_self_validation_cron.sh"
    assert script_path.exists()
    script = script_path.read_text(encoding="utf-8")
    assert "HERMES_VISUAL_LIVE_E2E=1" in script
    assert "--live-mode auto" in script
    assert "--case-timeout-seconds 240" in script
    assert "visual_scheduled_self_validation.py" in script

    jobs = cron_jobs.load_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["name"] == "Visual Agent Mode Self-Validation"
    assert job["schedule_display"] == "every 360m"
    assert job["script"] == "visual_self_validation_cron.sh"
    assert job["no_agent"] is True
    assert job["deliver"] == "local"
    assert job["workdir"] == str(repo_root)


def test_visual_self_validation_cron_is_idempotent_and_updates_existing_job(monkeypatch, tmp_path):
    cron_jobs = _reload_cron_for_home(monkeypatch, tmp_path)
    from scripts.visual_self_validation_cron import ensure_visual_self_validation_cron

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    first = ensure_visual_self_validation_cron(
        repo_root=repo_root,
        schedule="every 6h",
        live_mode="auto",
        enable_live_provider=True,
    )
    second = ensure_visual_self_validation_cron(
        repo_root=repo_root,
        schedule="every 12h",
        live_mode="auto",
        enable_live_provider=True,
    )
    third = ensure_visual_self_validation_cron(
        repo_root=repo_root,
        schedule="every 12h",
        live_mode="auto",
        enable_live_provider=True,
    )

    jobs = cron_jobs.load_jobs()
    assert len(jobs) == 1
    assert first["job_id"] == second["job_id"]
    assert second["job_id"] == third["job_id"]
    assert second["action"] == "updated"
    assert third["action"] == "unchanged"
    assert jobs[0]["schedule_display"] == "every 720m"

import json
from unittest.mock import MagicMock, patch

from cron.scheduler import run_job
from memory.layer2_store import Layer2Store


def _runtime():
    return {
        "api_key": "***",
        "base_url": "https://example.invalid/v1",
        "provider": "openrouter",
        "api_mode": "chat_completions",
    }


def test_run_job_applies_layer2_payload_for_opted_in_memory_pipeline():
    payload = {
        "observations": [
            {
                "observation_text": "The run checked a real artifact.",
                "source_event_id": "obs-1",
                "source_ref": "artifact://daily",
            }
        ],
        "candidate_events": [
            {
                "action": "create",
                "canonical_text": "Do not drop Layer-2 behavior during upstream upgrades",
                "kind": "heuristic",
                "proposed_target": "memory",
                "source_event_id": "cand-1",
                "evidence_source_event_id": "obs-1",
                "counts_for_recurrence": True,
            }
        ],
    }
    final = "Human report\n\n```hermes-layer2\n" + json.dumps(payload) + "\n```"
    job = {
        "id": "layer2-job",
        "name": "Layer-2 job",
        "prompt": "learn",
        "schedule_display": "manual",
        "memory_pipeline": {"enabled": True},
    }
    fake_db = MagicMock()

    with patch("dotenv.load_dotenv"), \
         patch("hermes_state.SessionDB", return_value=fake_db), \
         patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=_runtime()), \
         patch("run_agent.AIAgent") as agent_cls:
        agent = MagicMock()
        agent.run_conversation.return_value = {"final_response": final}
        agent_cls.return_value = agent

        success, output, final_response, error = run_job(job)

    assert success is True
    assert error is None
    assert final_response == "Human report"
    assert "```hermes-layer2" not in output
    assert "## Layer-2 Audit" in output
    assert "candidate_created" in output

    candidate = Layer2Store().get_candidate("Do not drop Layer-2 behavior during upstream upgrades")
    assert candidate["support_count"] == 1
    assert candidate["status"] == "active"


def test_run_job_ignores_layer2_payload_without_opt_in():
    payload = {
        "candidate_events": [
            {
                "action": "create",
                "canonical_text": "Non opted-in jobs must not mutate Layer-2",
                "source_event_id": "cand-1",
            }
        ]
    }
    final = "Human report\n\n```hermes-layer2\n" + json.dumps(payload) + "\n```"
    job = {
        "id": "plain-job",
        "name": "Plain job",
        "prompt": "learn",
        "schedule_display": "manual",
    }

    with patch("dotenv.load_dotenv"), \
         patch("hermes_state.SessionDB", return_value=MagicMock()), \
         patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=_runtime()), \
         patch("run_agent.AIAgent") as agent_cls:
        agent = MagicMock()
        agent.run_conversation.return_value = {"final_response": final}
        agent_cls.return_value = agent

        success, output, final_response, error = run_job(job)

    assert success is True
    assert error is None
    assert "```hermes-layer2" in final_response
    assert "## Layer-2 Audit" not in output
    assert Layer2Store().get_candidate("Non opted-in jobs must not mutate Layer-2") is None

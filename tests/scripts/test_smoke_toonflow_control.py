from __future__ import annotations

import json

import pytest

from plugins.toonflow_control.client import ToonflowControlError
from scripts import smoke_toonflow_control as smoke


def test_embedded_fake_smoke_is_no_spend_and_contract_only(capsys):
    exit_code = smoke.main(["--fake-server", "--no-spend"])
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["contract_version"] == "1.0"
    assert result["state"] == "succeeded"
    assert result["provider_requests"] == 0
    assert result["acceptance_proof"] == {
        "proof_id": "hermes_supervised",
        "passed": True,
        "evidence_class": "fixture",
        "billing_class": "not_applicable",
        "toonflow_contract_version": "1.0",
    }
    assert result["paths"] == [
        "/control/v1/capabilities",
        "/control/v1/projects",
        "/control/v1/runs",
        "/control/v1/runs/fake-run-1",
    ]
    assert "bridge_job_id" not in json.dumps(result)


def test_no_spend_rejects_server_without_fake_execution_evidence():
    class Client:
        def capabilities(self):
            return {
                "contract_version": "1.0",
                "operations": ["generate_shots"],
                "route_profiles": ["image.standard"],
            }

    with pytest.raises(ToonflowControlError) as caught:
        smoke.run_smoke(Client(), no_spend=True)
    assert caught.value.failure_class == "no_spend_not_proven"


def test_smoke_rejects_internal_or_billing_fields():
    with pytest.raises(ToonflowControlError) as caught:
        smoke.assert_public_response(
            {"run_id": "run-1", "billing_credentials": "secret"}
        )
    assert caught.value.failure_class == "boundary_violation"

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes
from agent.visual.learning.proposals import ALLOWED_PROPOSAL_TYPES
from agent.visual.learning.proposals import propose_visual_policy_updates


def build_visual_learning_replay(db_path: str | Path) -> dict[str, Any]:
    db_path = Path(db_path)
    _build_replay_fixture(db_path)
    outcomes = aggregate_visual_strategy_outcomes(db_path)
    proposals = propose_visual_policy_updates(outcomes)
    safety = _proposal_safety(proposals)
    failures: list[str] = []
    if not proposals:
        failures.append("no_learning_proposals")
    if safety["prompt_mutation_proposals"]:
        failures.append("prompt_mutation_proposal")
    if safety["unsafe_activation_proposals"]:
        failures.append("unsafe_activation_proposal")
    if not any(proposal.get("type") == "prefer_strategy" for proposal in proposals):
        failures.append("missing_prefer_strategy")
    return {
        "success": not failures,
        "failures": failures,
        "outcomes": {
            "bucket_count": outcomes["bucket_count"],
            "strategy_count": outcomes["strategy_count"],
        },
        "proposals": proposals,
        "safety": safety,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay visual learning against a privacy-safe fixture ledger.")
    parser.add_argument("--db-path", type=Path, default=Path("/tmp/hermes-visual-learning-replay.sqlite3"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_learning_replay(args.db_path)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual learning replay {status}")
    return 0 if payload["success"] else 1


def _build_replay_fixture(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    bucket = "visig_replay_glamour"
    strategy = "vstrat_replay_prefer"
    for index in range(24):
        request_id = ledger.record_request(
            user_prompt="[redacted replay prompt]",
            normalized_intent={"kind": "visual_package"},
            modality="package",
            operation="visual_package_generate",
            status="completed",
            metadata={"intent_signature": bucket},
        )
        attempt_id = ledger.record_attempt(
            request_id=request_id,
            candidate_index=index,
            provider="xai",
            model="grok-imagine",
            status="completed",
        )
        artifact_id = ledger.record_artifact(
            request_id=request_id,
            attempt_id=attempt_id,
            kind="image",
            local_path=f"/tmp/replay-{index}.png",
            content_hash=f"sha256:replay-{index}",
            mime_type="image/png",
            bytes=1024,
            width=1024,
            height=1024,
            freshness_status="fresh",
            is_stable=True,
        )
        ledger.record_delivery(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            platform="slack",
            destination_id="C_REPLAY",
            thread_id=f"T_REPLAY_{index}",
            delivery_status="sent",
        )
        ledger.record_judgment(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            judge_name="visual_quality_judge",
            score=0.86,
            verdict="pass",
            details={"scores": {"aesthetic_fit": 0.86, "composition": 0.84}},
            metadata={
                "intent_signature": bucket,
                "strategy_signature": strategy,
                "modality": "image",
            },
        )
        ledger.record_feedback(
            request_id=request_id,
            artifact_id=artifact_id,
            feedback_text="positive replay feedback",
            polarity=1.0,
            parsed={"signals": ["positive"]},
        )
        ledger.record_ranking(
            request_id=request_id,
            selected_artifact_id=artifact_id,
            decision="post",
            scores={"reward": {"final_score": 0.86, "confidence": 0.84}},
            metadata={
                "strategy_signature": strategy,
                "active_learning": {"action": "auto_post", "requires_user": False},
                "strategy_plan": {"strategy_signature": strategy},
            },
        )


def _proposal_safety(proposals: list[dict[str, Any]]) -> dict[str, int]:
    prompt_mutation = 0
    unsafe_activation = 0
    for proposal in proposals:
        if "prompt" in proposal or proposal.get("type") in {"rewrite_prompt", "policy_bypass"}:
            prompt_mutation += 1
        if proposal.get("activation_status") != "shadow" or proposal.get("type") not in ALLOWED_PROPOSAL_TYPES:
            unsafe_activation += 1
    return {
        "prompt_mutation_proposals": prompt_mutation,
        "unsafe_activation_proposals": unsafe_activation,
    }


if __name__ == "__main__":
    raise SystemExit(main())

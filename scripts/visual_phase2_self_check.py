from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.self_validation import run_visual_self_validation
from agent.visual.shadow_learning import record_shadow_update
from agent.visual.tracking import default_visual_ledger_path


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the visual Phase 2 self-validation gate.")
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    db_path = args.db_path
    request_id = args.request_id
    if args.fixture:
        db_path, request_id = _build_fixture()
    if db_path is None:
        db_path = default_visual_ledger_path()

    payload = run_visual_self_validation(db_path, request_id=request_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual phase2 self-check {status}")
    return 0 if payload["success"] else 1


def _build_fixture() -> tuple[Path, str]:
    hermes_home = Path(os.environ.get("HERMES_HOME") or "/tmp/hermes-visual-phase2-self-check")
    media_dir = hermes_home / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    image_path = media_dir / "phase2-fixture.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)

    db_path = hermes_home / "visual" / "phase2_self_check.sqlite3"
    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted phase2 self-check prompt",
        normalized_intent={"kind": "visual_phase2_self_check"},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="fixture",
        model="image",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path=str(image_path),
        uri=str(image_path),
        content_hash="sha256:phase2-fixture",
        mime_type="image/png",
        bytes=len(_ONE_PIXEL_PNG),
        width=1,
        height=1,
        is_stable=True,
        freshness_status="fresh",
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={"reward": {"final_score": 0.9, "confidence": 0.8}},
        metadata={"active_learning": {"action": "auto_post", "requires_user": False}},
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination="slack:C_PHASE2:T_PHASE2",
        destination_id="C_PHASE2",
        thread_id="T_PHASE2",
        delivery_status="sent",
    )
    record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature="visig_phase2_fixture",
        strategy_signature="composition.full_subject_visible@v1",
        proposed_change={"increase_weight": 0.01},
        evidence={"sample_count": 1, "expected_delta": 0.01},
        confidence=0.2,
    )
    return db_path, request_id


if __name__ == "__main__":
    raise SystemExit(main())

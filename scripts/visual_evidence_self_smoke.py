from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.media_probe import probe_media_reference
from scripts.visual_evidence_report import build_visual_evidence_report


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a privacy-safe visual evidence loop self-smoke.")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.work_dir is None:
        with tempfile.TemporaryDirectory(prefix="hermes-visual-smoke-") as tmp:
            return _run_and_emit(Path(tmp), emit_json=args.json)
    return _run_and_emit(args.work_dir, emit_json=args.json)


def _run_and_emit(work_dir: Path, *, emit_json: bool) -> int:
    payload = run_self_smoke(work_dir)
    if emit_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual evidence self-smoke {status}")
    return 0 if payload["success"] else 1


def run_self_smoke(work_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(work_dir)
    media_dir = work_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    image_path = media_dir / "synthetic.png"
    video_path = media_dir / "synthetic.mp4"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")

    ledger_path = work_dir / "visual" / "attempt_ledger.sqlite3"
    ledger = VisualAttemptLedger(ledger_path)
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted visual self-smoke prompt",
        normalized_intent={"kind": "visual_self_smoke"},
        modality="package",
        operation="visual_evidence_self_smoke",
        platform="slack",
        channel_id="C_SELF",
        thread_id="T_SELF",
        status="completed",
    )
    image_attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="fixture",
        model="fixture-image",
        status="completed",
    )
    video_attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=1,
        provider="fixture",
        model="fixture-video",
        status="completed",
    )
    image_artifact_id = _record_artifact(
        ledger,
        request_id=request_id,
        attempt_id=image_attempt_id,
        kind="image",
        path=image_path,
    )
    video_artifact_id = _record_artifact(
        ledger,
        request_id=request_id,
        attempt_id=video_attempt_id,
        kind="video",
        path=video_path,
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=image_attempt_id,
        artifact_id=image_artifact_id,
        judge_name="visual_quality_judge",
        score=0.86,
        verdict="pass",
        details={"scores": {"aesthetic_fit": 0.86, "composition": 0.82}},
        metadata={"intent_signature": "visig_self_smoke", "modality": "image"},
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=video_attempt_id,
        artifact_id=video_artifact_id,
        judge_name="visual_quality_judge",
        score=0.78,
        verdict="pass",
        details={"scores": {"motion_quality": 0.78, "composition": 0.80}},
        metadata={"intent_signature": "visig_self_smoke", "modality": "video"},
    )
    destination = "slack:C_SELF:T_SELF"
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=image_attempt_id,
        artifact_id=image_artifact_id,
        platform="slack",
        destination=destination,
        destination_id="C_SELF",
        thread_id="T_SELF",
        message_id="M_IMAGE",
        delivery_status="sent",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=video_attempt_id,
        artifact_id=video_artifact_id,
        platform="slack",
        destination=destination,
        destination_id="C_SELF",
        thread_id="T_SELF",
        message_id="M_VIDEO",
        delivery_status="sent",
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=image_artifact_id,
        feedback_text="image accepted",
        polarity=1.0,
        parsed={"label": "accept"},
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=video_artifact_id,
        feedback_text="video accepted",
        polarity=1.0,
        parsed={"label": "accept"},
    )

    report = build_visual_evidence_report(ledger_path)
    report["success"] = (
        report["success"]
        and report["feedback"]["count"] >= 2
        and report["requests"]["count"] >= 1
        and report["artifacts"]["count"] >= 2
    )
    return report


def _record_artifact(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    attempt_id: str,
    kind: str,
    path: Path,
) -> str:
    meta = probe_media_reference(path)
    return ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind=kind,
        local_path=meta.local_path,
        uri=str(path),
        content_hash=meta.sha256,
        mime_type=meta.mime_type,
        bytes=meta.bytes,
        width=meta.width,
        height=meta.height,
        is_stable=meta.is_stable,
        freshness_status=meta.freshness_status,
    )


if __name__ == "__main__":
    raise SystemExit(main())

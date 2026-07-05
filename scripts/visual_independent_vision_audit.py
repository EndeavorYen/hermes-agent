from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.independent_vision_audit import audit_independent_vision_judgments
from agent.visual.tracking import default_visual_ledger_path


VISION_JUDGE_PROMPT = """\
Evaluate this generated visual artifact for automated quality ranking.
Return only a JSON object with numeric values from 0.0 to 1.0:
{
  "reference_adherence": 0.5,
  "face_quality": 0.5,
  "visual_appeal": 0.5,
  "composition": 0.5,
  "pose_novelty": 0.5,
  "stocking_quality": 0.5
}
Do not include names, private prompt text, file paths, or prose.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run independent vision quality audit for visual artifacts.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    analyzer = None if args.dry_run else _analyze_with_vision_tool
    payload = audit_independent_vision_judgments(
        args.db_path,
        analyzer=analyzer,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    payload["dry_run"] = args.dry_run
    payload["limit"] = args.limit
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        action = "would audit" if args.dry_run else "audited"
        print(f"visual independent vision audit {action} {payload['candidate_count']} artifacts")
    return 0 if payload["success"] else 1


def _analyze_with_vision_tool(artifact: dict[str, Any]) -> Any:
    source = _artifact_source(artifact)
    if not source:
        raise ValueError("artifact has no analyzable source")
    from model_tools import _run_async
    from tools.vision_tools import vision_analyze_tool

    raw = _run_async(vision_analyze_tool(source, VISION_JUDGE_PROMPT))
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"analysis": raw}
    return raw


def _artifact_source(artifact: dict[str, Any]) -> str:
    for key in ("local_path", "source_url", "uri"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())

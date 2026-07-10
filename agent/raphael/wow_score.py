from __future__ import annotations

from collections.abc import Mapping


WOW_WEIGHTS = {
    "summon_appraisal": 1,
    "standby_summon": 1,
    "mission_followup": 2,
    "proof_gate": 2,
    "evolution_feedback": 1,
    "lifecycle_reversible": 1,
    "demo_under_one_minute": 1,
    "clean_output": 1,
}


def calculate_raphael_wow_score(signals: Mapping[str, bool]) -> tuple[int, tuple[str, ...]]:
    score = 0
    missing: list[str] = []
    for key, weight in WOW_WEIGHTS.items():
        if signals.get(key) is True:
            score += weight
        else:
            missing.append(key)
    return score, tuple(missing)


__all__ = ["WOW_WEIGHTS", "calculate_raphael_wow_score"]

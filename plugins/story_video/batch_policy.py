from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


class BatchBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BatchPolicy:
    initial_candidate_cap: int
    repair_candidate_cap: int
    max_candidates_per_shot: int = 2
    critical_max_candidates_per_shot: int = 4

    @classmethod
    def for_run(cls, shot_count: int) -> "BatchPolicy":
        initial = max(1, int(shot_count or 0))
        repairs = min(4, max(1, math.ceil(initial * 0.25)))
        return cls(initial_candidate_cap=initial, repair_candidate_cap=repairs)

    @property
    def max_total_candidates(self) -> int:
        return self.initial_candidate_cap + self.repair_candidate_cap


@dataclass
class BatchBudget:
    policy: BatchPolicy
    _generated_by_shot: dict[str, int] = field(default_factory=dict)
    _contract_hashes_by_shot: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total_generated(self) -> int:
        return sum(self._generated_by_shot.values())

    def generated_for(self, shot_id: str) -> int:
        return int(self._generated_by_shot.get(str(shot_id), 0))

    def contract_hashes_for(self, shot_id: str) -> tuple[str, ...]:
        return tuple(self._contract_hashes_by_shot.get(str(shot_id), ()))

    def can_generate(self, shot_id: str, critical: bool = False) -> bool:
        per_shot_cap = (
            self.policy.critical_max_candidates_per_shot
            if critical
            else self.policy.max_candidates_per_shot
        )
        return (
            self.total_generated < self.policy.max_total_candidates
            and self.generated_for(shot_id) < per_shot_cap
        )

    def record_generation(
        self,
        shot_id: str,
        contract_hash: str,
        *,
        critical: bool = False,
    ) -> None:
        normalized_shot_id = str(shot_id).strip()
        if not normalized_shot_id:
            raise ValueError("shot_id is required")
        if not self.can_generate(normalized_shot_id, critical=critical):
            raise BatchBudgetExceeded(
                f"Generation budget exhausted for {normalized_shot_id}"
            )
        self._generated_by_shot[normalized_shot_id] = (
            self.generated_for(normalized_shot_id) + 1
        )
        self._contract_hashes_by_shot.setdefault(normalized_shot_id, []).append(
            str(contract_hash or "")
        )

    def release_generation(self, shot_id: str, contract_hash: str) -> None:
        """Release one provider reservation that produced no candidate artifact."""
        normalized_shot_id = str(shot_id).strip()
        count = self.generated_for(normalized_shot_id)
        if not normalized_shot_id or count <= 0:
            return
        if count == 1:
            self._generated_by_shot.pop(normalized_shot_id, None)
        else:
            self._generated_by_shot[normalized_shot_id] = count - 1

        hashes = self._contract_hashes_by_shot.get(normalized_shot_id) or []
        expected = str(contract_hash or "")
        for index in range(len(hashes) - 1, -1, -1):
            if hashes[index] == expected:
                hashes.pop(index)
                break
        else:
            if hashes:
                hashes.pop()
        if not hashes:
            self._contract_hashes_by_shot.pop(normalized_shot_id, None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "story_video_batch_budget_v1",
            "policy": asdict(self.policy),
            "generated_by_shot": dict(self._generated_by_shot),
            "contract_hashes_by_shot": {
                shot_id: list(values)
                for shot_id, values in self._contract_hashes_by_shot.items()
            },
        }

    @classmethod
    def from_candidate_manifest(
        cls,
        policy: BatchPolicy,
        payload: dict[str, Any],
    ) -> "BatchBudget":
        candidate_keys: dict[str, set[str]] = {}
        max_rounds: dict[str, int] = {}
        contracts: dict[str, list[str]] = {}
        rows = [
            row
            for section in ("attempt_history", "outputs")
            for row in payload.get(section) or []
            if isinstance(row, dict)
        ]
        for row in rows:
            shot_id = str(row.get("shot_id") or "").strip()
            if not shot_id:
                continue
            candidate_key = str(
                row.get("candidate_id")
                or row.get("candidate_path")
                or row.get("local_path")
                or ""
            ).strip()
            if candidate_key:
                candidate_keys.setdefault(shot_id, set()).add(candidate_key)
            try:
                repair_round = max(0, int(row.get("repair_round") or 0))
            except (TypeError, ValueError):
                repair_round = 0
            max_rounds[shot_id] = max(max_rounds.get(shot_id, 0), repair_round)
            contract_hash = str(row.get("shot_contract_hash") or "").strip()
            if contract_hash:
                values = contracts.setdefault(shot_id, [])
                if contract_hash not in values:
                    values.append(contract_hash)

        shot_ids = set(candidate_keys) | set(max_rounds)
        generated = {
            shot_id: max(len(candidate_keys.get(shot_id, set())), max_rounds.get(shot_id, 0))
            for shot_id in shot_ids
        }
        return cls(
            policy=policy,
            _generated_by_shot=generated,
            _contract_hashes_by_shot=contracts,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BatchBudget":
        raw_policy = payload.get("policy") if isinstance(payload, dict) else None
        if not isinstance(raw_policy, dict):
            raise ValueError("batch budget policy is required")
        policy_values = dict(raw_policy)
        policy_values["critical_max_candidates_per_shot"] = max(
            4,
            int(policy_values.get("critical_max_candidates_per_shot") or 0),
        )
        policy = BatchPolicy(**policy_values)
        generated = {
            str(shot_id): int(count)
            for shot_id, count in (payload.get("generated_by_shot") or {}).items()
        }
        contracts = {
            str(shot_id): [str(value) for value in values]
            for shot_id, values in (payload.get("contract_hashes_by_shot") or {}).items()
            if isinstance(values, list)
        }
        return cls(
            policy=policy,
            _generated_by_shot=generated,
            _contract_hashes_by_shot=contracts,
        )


__all__ = [
    "BatchBudget",
    "BatchBudgetExceeded",
    "BatchPolicy",
]

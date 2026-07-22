from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ArtifactDeliveryDeduper:
    ttl_seconds: float = 300.0
    _seen: dict[tuple[str, str, str], float] = field(default_factory=dict)

    def mark_if_new(self, content_hash: str, destination: str, request_id: str) -> bool:
        if self.is_duplicate(content_hash, destination, request_id):
            return False
        self.mark(content_hash, destination, request_id)
        return True

    def is_duplicate(self, content_hash: str, destination: str, request_id: str) -> bool:
        now = time.time()
        self._prune(now)
        return (content_hash, destination, request_id) in self._seen

    def mark(self, content_hash: str, destination: str, request_id: str) -> None:
        now = time.time()
        self._prune(now)
        self._seen[(content_hash, destination, request_id)] = now

    def _prune(self, now: float) -> None:
        if self.ttl_seconds <= 0:
            self._seen.clear()
            return
        cutoff = now - self.ttl_seconds
        self._seen = {key: seen_at for key, seen_at in self._seen.items() if seen_at >= cutoff}


_GLOBAL_ARTIFACT_DELIVERY_DEDUPER = ArtifactDeliveryDeduper()


def get_artifact_delivery_deduper() -> ArtifactDeliveryDeduper:
    return _GLOBAL_ARTIFACT_DELIVERY_DEDUPER

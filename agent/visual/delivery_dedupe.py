"""TTL dedupe for visual artifact delivery."""

from __future__ import annotations

import time
from typing import Callable, Dict, Tuple


class ArtifactDeliveryDeduper:
    """Remember delivered artifact/request/destination triples for a short TTL."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 6 * 60 * 60,
        now: Callable[[], float] | None = None,
    ):
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._now = now or time.time
        self._seen: Dict[Tuple[str, str, str], float] = {}

    def mark_if_new(
        self,
        artifact_hash: str,
        destination: str,
        request_id: str,
    ) -> bool:
        artifact_hash = str(artifact_hash or "").strip()
        destination = str(destination or "").strip()
        request_id = str(request_id or "").strip()
        if not artifact_hash or not destination or not request_id:
            return False

        now = self._now()
        self._prune(now)
        key = (artifact_hash, destination, request_id)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True

    def _prune(self, now: float) -> None:
        if not self._seen:
            return
        cutoff = now - self.ttl_seconds
        stale = [key for key, timestamp in self._seen.items() if timestamp <= cutoff]
        for key in stale:
            self._seen.pop(key, None)

from __future__ import annotations

import pytest

from scripts.visual_agent_live_proof import _resolve_since


def test_resolve_since_converts_local_date_to_utc_midnight():
    assert (
        _resolve_since(
            since=None,
            since_local_date="2026-06-20",
            timezone_name="Asia/Taipei",
        )
        == "2026-06-19T16:00:00Z"
    )


def test_resolve_since_rejects_ambiguous_since_inputs():
    with pytest.raises(ValueError, match="Use either"):
        _resolve_since(
            since="2026-06-20T00:00:00Z",
            since_local_date="2026-06-20",
            timezone_name="Asia/Taipei",
        )

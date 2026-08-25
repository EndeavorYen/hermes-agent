"""Compact handoff must keep in-progress work live (Hermes-Bot P9 / rule 8)."""

from agent.context_compressor import SUMMARY_PREFIX


def test_summary_prefix_does_not_mark_work_already_addressed():
    lower = SUMMARY_PREFIX.lower()
    assert "already addressed" not in lower
    assert "do not wrap up" not in lower
    assert "unless the latest message explicitly asks" not in lower
    assert "live" in lower
    assert "continue that work" in lower
    assert "resume exactly" not in lower

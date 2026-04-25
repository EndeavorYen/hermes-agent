from memory.layer2_consolidate import consolidate_layer2
from memory.layer2_store import Layer2Store


def test_consolidate_merges_punctuation_variants_preserving_support(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Do not harden single-day evidence into durable rules",
        source_event_id="evt-1",
        event_ts="2026-04-01T00:00:00+00:00",
    )
    store.record_event(
        event_type="strengthen",
        canonical_text="Do not harden single-day evidence into durable rules.",
        source_event_id="evt-2",
        event_ts="2026-04-02T00:00:00+00:00",
    )

    candidates = store.list_candidates()
    assert len(candidates) == 1
    candidate = store.get_candidate("Do not harden single-day evidence into durable rules.")
    assert candidate["support_count"] == 2
    events = store.list_events("Do not harden single-day evidence into durable rules")
    assert len(events) == 2


def test_same_day_same_canonical_from_same_job_does_not_double_count(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    first = store.record_event(
        event_type="create",
        canonical_text="Use value-of-information before extra research",
        source_event_id="evt-1",
        job_id="daily-learning",
        event_ts="2026-04-25T20:00:00+00:00",
    )
    second = store.record_event(
        event_type="strengthen",
        canonical_text="Use value-of-information before extra research.",
        source_event_id="evt-2",
        job_id="daily-learning",
        event_ts="2026-04-25T21:00:00+00:00",
    )

    candidate = store.get_candidate("Use value-of-information before extra research")
    assert first["audit_label"] == "candidate_created"
    assert second["audit_label"] == "daily_replay_suppressed"
    assert candidate["support_count"] == 1
    events = store.list_events("Use value-of-information before extra research")
    assert events[-1]["counts_for_recurrence"] == 0
    assert events[-1]["support_delta"] == 0


def test_distinct_day_same_job_strengthens_existing_candidate(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Use value-of-information before extra research",
        source_event_id="evt-1",
        job_id="daily-learning",
        event_ts="2026-04-24T20:00:00+00:00",
    )
    strengthened = store.record_event(
        event_type="strengthen",
        canonical_text="Use value-of-information before extra research.",
        source_event_id="evt-2",
        job_id="daily-learning",
        event_ts="2026-04-25T21:01:00+00:00",
    )

    candidate = store.get_candidate("Use value-of-information before extra research")
    assert strengthened["audit_label"] == "candidate_strengthened"
    assert candidate["support_count"] == 2


def test_consolidate_marks_old_low_support_as_stale(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Weak old candidate",
        source_event_id="evt-old",
        event_ts="2026-04-01T00:00:00+00:00",
    )

    audits = consolidate_layer2(store=store, now="2026-04-20T00:00:00+00:00")

    candidate = store.get_candidate("Weak old candidate")
    assert candidate["status"] == "stale"
    assert any(item["audit_label"] == "candidate_marked_stale" for item in audits)


def test_consolidate_quarantines_when_contradictions_dominate(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Contested candidate",
        source_event_id="evt-1",
        event_ts="2026-04-01T00:00:00+00:00",
    )
    store.record_event(
        event_type="contradict",
        canonical_text="Contested candidate",
        source_event_id="evt-2",
        event_ts="2026-04-02T00:00:00+00:00",
    )

    audits = consolidate_layer2(store=store, now="2026-04-03T00:00:00+00:00")

    candidate = store.get_candidate("Contested candidate")
    assert candidate["status"] == "quarantine"
    assert any(item["audit_label"] == "candidate_quarantined" for item in audits)


def test_consolidate_prunes_old_stale_low_support_and_is_idempotent(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Old stale candidate",
        source_event_id="evt-1",
        event_ts="2026-03-01T00:00:00+00:00",
    )
    consolidate_layer2(store=store, now="2026-03-20T00:00:00+00:00")
    first = consolidate_layer2(store=store, now="2026-04-25T00:00:00+00:00")
    second = consolidate_layer2(store=store, now="2026-04-25T00:00:00+00:00")

    candidate = store.get_candidate("Old stale candidate")
    assert candidate["status"] == "pruned"
    assert any(item["audit_label"] == "candidate_pruned" for item in first)
    assert not any(item["audit_label"] == "candidate_pruned" for item in second)

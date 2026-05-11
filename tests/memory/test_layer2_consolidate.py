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


def test_consolidate_forced_exit_quarantines_old_high_support_questions(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    question = "What forced-exit rule should govern WATCH/PROMOTE_LATER candidates?"
    store.record_event(
        event_type="create",
        canonical_text=question,
        kind="question",
        source_event_id="evt-0",
        job_id="nightly-professor-question-distillation",
        event_ts="2026-04-01T00:00:00+00:00",
    )
    for idx in range(1, 8):
        store.record_event(
            event_type="strengthen",
            canonical_text=question,
            kind="question",
            source_event_id=f"evt-{idx}",
            job_id="nightly-professor-question-distillation",
            event_ts=f"2026-04-{(idx * 2) + 1:02d}T00:00:00+00:00",
        )

    audits = consolidate_layer2(store=store, now="2026-04-20T00:00:00+00:00")

    candidate = store.get_candidate(question)
    assert candidate["support_count"] == 8
    assert candidate["status"] == "quarantine"
    assert any(item["audit_label"] == "question_forced_exit_quarantined" for item in audits)
    assert store.query_candidates_for_pack(query_text="forced exit", min_support_count=2) == []


def test_consolidate_forced_exit_quarantine_is_idempotent(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    question = "What transition table prevents endless WATCH?"
    store.record_event(
        event_type="create",
        canonical_text=question,
        kind="question",
        source_event_id="evt-0",
        event_ts="2026-04-01T00:00:00+00:00",
    )
    for idx in range(1, 8):
        store.record_event(
            event_type="strengthen",
            canonical_text=question,
            kind="question",
            source_event_id=f"evt-{idx}",
            event_ts=f"2026-04-{idx + 1:02d}T00:00:00+00:00",
        )

    first = consolidate_layer2(store=store, now="2026-04-20T00:00:00+00:00")
    second = consolidate_layer2(store=store, now="2026-04-20T00:00:00+00:00")

    assert store.get_candidate(question)["status"] == "quarantine"
    assert any(item["audit_label"] == "question_forced_exit_quarantined" for item in first)
    assert not any(item["audit_label"] == "question_forced_exit_quarantined" for item in second)


def test_consolidate_forced_exit_only_applies_to_questions(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    observation = "Use value-of-information before additional research"
    store.record_event(
        event_type="create",
        canonical_text=observation,
        kind="observation",
        source_event_id="evt-0",
        event_ts="2026-04-01T00:00:00+00:00",
    )
    for idx in range(1, 8):
        store.record_event(
            event_type="strengthen",
            canonical_text=observation,
            kind="observation",
            source_event_id=f"evt-{idx}",
            event_ts=f"2026-04-{idx + 1:02d}T00:00:00+00:00",
        )

    audits = consolidate_layer2(store=store, now="2026-04-20T00:00:00+00:00")

    assert store.get_candidate(observation)["support_count"] == 8
    assert store.get_candidate(observation)["status"] == "active"
    assert not any(item["audit_label"] == "question_forced_exit_quarantined" for item in audits)


def test_consolidate_forced_exit_keeps_recent_high_support_questions_active(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    question = "What new evidence should trigger promotion?"
    store.record_event(
        event_type="create",
        canonical_text=question,
        kind="question",
        source_event_id="evt-0",
        event_ts="2026-04-10T00:00:00+00:00",
    )
    for idx in range(1, 8):
        store.record_event(
            event_type="strengthen",
            canonical_text=question,
            kind="question",
            source_event_id=f"evt-{idx}",
            event_ts=f"2026-04-{10 + idx:02d}T00:00:00+00:00",
        )

    audits = consolidate_layer2(store=store, now="2026-04-20T00:00:00+00:00")

    assert store.get_candidate(question)["support_count"] == 8
    assert store.get_candidate(question)["status"] == "active"
    assert not any(item["audit_label"] == "question_forced_exit_quarantined" for item in audits)


def test_consolidate_forced_exit_accepts_case_and_whitespace_kind_variants(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    question = "Which evidence exits sandbox validation?"
    store.record_event(
        event_type="create",
        canonical_text=question,
        kind=" Question ",
        source_event_id="evt-0",
        event_ts="2026-04-01T00:00:00+00:00",
    )
    for idx in range(1, 8):
        store.record_event(
            event_type="strengthen",
            canonical_text=question,
            kind="QUESTION",
            source_event_id=f"evt-{idx}",
            event_ts=f"2026-04-{idx + 1:02d}T00:00:00+00:00",
        )

    audits = consolidate_layer2(store=store, now="2026-04-20T00:00:00+00:00")

    assert store.get_candidate(question)["status"] == "quarantine"
    assert any(item["audit_label"] == "question_forced_exit_quarantined" for item in audits)


def test_consolidate_forced_exit_keeps_below_threshold_questions_active(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    question = "What evidence proves this candidate changed behavior?"
    store.record_event(
        event_type="create",
        canonical_text=question,
        kind="question",
        source_event_id="evt-0",
        event_ts="2026-04-01T00:00:00+00:00",
    )
    for idx in range(1, 7):
        store.record_event(
            event_type="strengthen",
            canonical_text=question,
            kind="question",
            source_event_id=f"evt-{idx}",
            event_ts=f"2026-04-{(idx * 2) + 1:02d}T00:00:00+00:00",
        )

    audits = consolidate_layer2(store=store, now="2026-04-30T00:00:00+00:00")

    candidate = store.get_candidate(question)
    assert candidate["support_count"] == 7
    assert candidate["status"] == "active"
    assert not any(item["audit_label"] == "question_forced_exit_quarantined" for item in audits)

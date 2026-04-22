"""Tests for cron Layer-2 sidecar memory MVP."""

import json
import sqlite3
from unittest.mock import MagicMock, patch

from cron.layer2_memory import Layer2Store, apply_layer2_payload, format_layer2_audit_section, parse_layer2_payload
from cron.scheduler import run_job


class TestLayer2Store:
    def test_normalizes_memory_target_to_prior_in_ledger(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        created = store.record_event(
            event_type="create",
            canonical_text="Repository uses uv",
            kind="env_fact",
            proposed_target="memory",
            routing_destination="memory",
            source_ref="artifact:1",
            source_event_id="evt-1",
        )

        candidate = store.get_candidate("Repository uses uv")
        assert created["candidate"]["proposed_target"] == "prior"
        assert created["candidate"]["routing_destination"] == "prior"
        assert candidate["proposed_target"] == "prior"
        assert candidate["routing_destination"] == "prior"

    def test_promotion_to_prior_reverse_maps_to_memory_store_target(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")
        job = {
            "id": "promotion-job",
            "memory_pipeline": {
                "enabled": True,
                "allow_durable_promotion_targets": ["memory"],
            },
        }
        payload = {
            "promotions": [
                {
                    "canonical_text": "Repository uses uv",
                    "target": "memory",
                    "content": "Repository uses uv",
                }
            ]
        }

        fake_memory_store = MagicMock()
        fake_memory_store.add.return_value = {"success": True}

        with patch("cron.layer2_memory.MemoryStore", return_value=fake_memory_store):
            audit = apply_layer2_payload(
                job,
                payload,
                source_ref="cron:promotion-job:run-1",
                store=store,
            )

        fake_memory_store.load_from_disk.assert_called_once()
        fake_memory_store.add.assert_called_once_with("memory", "Repository uses uv")
        candidate = store.get_candidate("Repository uses uv")
        events = store.list_events("Repository uses uv")
        assert candidate["proposed_target"] == "prior"
        assert candidate["routing_destination"] == "prior"
        assert events[-1]["durable_target"] == "memory"
        assert events[-1]["routing_destination"] == "prior"
        assert any(item["audit_label"] == "durable_write" for item in audit)

    def test_fresh_db_includes_generic_ledger_columns(self, tmp_path):
        db_path = tmp_path / "layer2.sqlite3"
        Layer2Store(db_path)

        with sqlite3.connect(db_path) as conn:
            candidate_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()
            }
            event_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(candidate_events)").fetchall()
            }

        observation_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(observations)").fetchall()
        }
        episode_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(episodes)").fetchall()
        }

        assert {"routing_destination", "subject_scope", "subject_id"} <= candidate_columns
        assert {
            "job_id",
            "job_run_id",
            "session_id",
            "prompt_snapshot_id",
            "routing_reason_codes",
            "routing_destination",
        } <= event_columns
        assert {
            "observation_text",
            "source_ref",
            "source_event_id",
            "subject_scope",
            "subject_id",
            "job_id",
            "job_run_id",
            "session_id",
            "prompt_snapshot_id",
            "tags_json",
            "metadata_json",
            "episode_id",
        } <= observation_columns
        assert {
            "summary_text",
            "source_ref",
            "subject_scope",
            "subject_id",
            "job_id",
            "job_run_id",
            "session_id",
            "prompt_snapshot_id",
            "tags_json",
            "metadata_json",
        } <= episode_columns
        with sqlite3.connect(db_path) as conn:
            context_pack_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(context_packs)").fetchall()
            }
        assert {
            "pack_name",
            "kind",
            "title",
            "content_text",
            "source_ref",
            "subject_scope",
            "subject_id",
            "job_id",
            "job_run_id",
            "session_id",
            "prompt_snapshot_id",
            "tags_json",
            "metadata_json",
            "refresh_policy_json",
        } <= context_pack_columns

    def test_schema_migration_is_idempotent_and_preserves_existing_rows(self, tmp_path):
        db_path = tmp_path / "layer2.sqlite3"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_text TEXT NOT NULL UNIQUE,
                    kind TEXT,
                    proposed_target TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    support_count INTEGER NOT NULL DEFAULT 0,
                    contradict_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    promoted_ref TEXT
                );

                CREATE TABLE candidate_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_ts TEXT NOT NULL,
                    source_ref TEXT,
                    source_event_id TEXT,
                    counts_for_recurrence INTEGER NOT NULL DEFAULT 1,
                    support_delta INTEGER NOT NULL DEFAULT 0,
                    contradict_delta INTEGER NOT NULL DEFAULT 0,
                    durable_target TEXT,
                    durable_content TEXT,
                    notes TEXT,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
                );

                INSERT INTO candidates (
                    canonical_text, kind, proposed_target, status,
                    support_count, contradict_count, created_at, updated_at, promoted_ref
                ) VALUES (
                    'Existing fact', 'fact', 'memory', 'active', 1, 0,
                    '2026-04-22T00:00:00+00:00', '2026-04-22T00:00:00+00:00', NULL
                );
                """
            )

        migrated = Layer2Store(db_path)
        migrated_again = Layer2Store(db_path)

        assert migrated.get_candidate("Existing fact")["canonical_text"] == "Existing fact"
        assert migrated_again.get_candidate("Existing fact")["canonical_text"] == "Existing fact"

        with sqlite3.connect(db_path) as conn:
            candidate_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()
            }
            event_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(candidate_events)").fetchall()
            }

        assert {"routing_destination", "subject_scope", "subject_id"} <= candidate_columns
        assert {"job_id", "session_id", "routing_reason_codes"} <= event_columns

    def test_query_candidates_for_pack_filters_active_destination_and_support(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        store.record_event(
            event_type="create",
            canonical_text="Weak prior fact",
            kind="env_fact",
            proposed_target="memory",
            routing_destination="memory",
            source_ref="artifact:1",
            source_event_id="evt-1",
            event_ts="2026-04-22T00:00:01+00:00",
        )
        store.record_event(
            event_type="create",
            canonical_text="Strong prior fact",
            kind="env_fact",
            proposed_target="memory",
            routing_destination="memory",
            source_ref="artifact:2",
            source_event_id="evt-2",
            event_ts="2026-04-22T00:00:02+00:00",
        )
        store.record_event(
            event_type="strengthen",
            canonical_text="Strong prior fact",
            source_ref="artifact:3",
            source_event_id="evt-3",
            event_ts="2026-04-22T00:00:03+00:00",
        )
        store.record_event(
            event_type="create",
            canonical_text="Strong user fact",
            kind="preference",
            proposed_target="user",
            routing_destination="user",
            source_ref="artifact:4",
            source_event_id="evt-4",
            event_ts="2026-04-22T00:00:04+00:00",
        )
        store.record_event(
            event_type="strengthen",
            canonical_text="Strong user fact",
            source_ref="artifact:5",
            source_event_id="evt-5",
            event_ts="2026-04-22T00:00:05+00:00",
        )
        store.record_event(
            event_type="create",
            canonical_text="Pruned prior fact",
            kind="env_fact",
            proposed_target="memory",
            routing_destination="memory",
            source_ref="artifact:6",
            source_event_id="evt-6",
            event_ts="2026-04-22T00:00:06+00:00",
        )
        store.record_event(
            event_type="prune",
            canonical_text="Pruned prior fact",
            source_ref="artifact:7",
            source_event_id="evt-7",
            counts_for_recurrence=False,
            event_ts="2026-04-22T00:00:07+00:00",
        )

        results = store.query_candidates_for_pack(
            destinations=["prior"],
            max_items=10,
            min_support_count=2,
        )

        assert [item["canonical_text"] for item in results] == ["Strong prior fact"]
        assert results[0]["routing_destination"] == "prior"
        assert results[0]["status"] == "active"
        assert results[0]["support_count"] == 2

    def test_query_candidates_for_pack_orders_by_support_then_updated_and_limits(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        store.record_event(
            event_type="create",
            canonical_text="Older high-support",
            kind="fact",
            proposed_target="user",
            source_ref="session:1",
            source_event_id="evt-1",
            event_ts="2026-04-22T00:00:01+00:00",
        )
        store.record_event(
            event_type="strengthen",
            canonical_text="Older high-support",
            source_ref="session:2",
            source_event_id="evt-2",
            event_ts="2026-04-22T00:00:02+00:00",
        )
        store.record_event(
            event_type="strengthen",
            canonical_text="Older high-support",
            source_ref="session:3",
            source_event_id="evt-3",
            event_ts="2026-04-22T00:00:03+00:00",
        )

        store.record_event(
            event_type="create",
            canonical_text="Newer high-support",
            kind="fact",
            proposed_target="user",
            source_ref="session:4",
            source_event_id="evt-4",
            event_ts="2026-04-22T00:00:04+00:00",
        )
        store.record_event(
            event_type="strengthen",
            canonical_text="Newer high-support",
            source_ref="session:5",
            source_event_id="evt-5",
            event_ts="2026-04-22T00:00:05+00:00",
        )
        store.record_event(
            event_type="strengthen",
            canonical_text="Newer high-support",
            source_ref="session:6",
            source_event_id="evt-6",
            event_ts="2026-04-22T00:00:06+00:00",
        )

        store.record_event(
            event_type="create",
            canonical_text="Medium-support",
            kind="fact",
            proposed_target="user",
            source_ref="session:7",
            source_event_id="evt-7",
            event_ts="2026-04-22T00:00:07+00:00",
        )
        store.record_event(
            event_type="strengthen",
            canonical_text="Medium-support",
            source_ref="session:8",
            source_event_id="evt-8",
            event_ts="2026-04-22T00:00:08+00:00",
        )

        results = store.query_candidates_for_pack(max_items=2, min_support_count=2)

        assert [item["canonical_text"] for item in results] == [
            "Newer high-support",
            "Older high-support",
        ]

    def test_create_strengthen_contradict_prune_and_promote(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        created = store.record_event(
            event_type="create",
            canonical_text="User prefers concise answers",
            kind="preference",
            proposed_target="user",
            source_ref="session:1",
            source_event_id="evt-1",
        )
        strengthened = store.record_event(
            event_type="strengthen",
            canonical_text="User prefers concise answers",
            kind="preference",
            proposed_target="user",
            source_ref="session:2",
            source_event_id="evt-2",
        )
        contradicted = store.record_event(
            event_type="contradict",
            canonical_text="User prefers concise answers",
            source_ref="session:3",
            source_event_id="evt-3",
        )
        pruned = store.record_event(
            event_type="prune",
            canonical_text="User prefers concise answers",
            source_ref="session:4",
            source_event_id="evt-4",
            counts_for_recurrence=False,
        )
        promoted = store.record_event(
            event_type="promote",
            canonical_text="User prefers concise answers",
            proposed_target="user",
            promoted_ref="user:User prefers concise answers",
            source_ref="session:5",
            source_event_id="evt-5",
            counts_for_recurrence=False,
            durable_target="user",
            durable_content="User prefers concise answers",
        )

        candidate = store.get_candidate("User prefers concise answers")
        assert created["audit_label"] == "candidate_created"
        assert strengthened["audit_label"] == "candidate_strengthened"
        assert contradicted["audit_label"] == "candidate_contradicted"
        assert pruned["audit_label"] == "candidate_pruned"
        assert promoted["audit_label"] == "candidate_promoted"
        assert candidate["support_count"] == 2
        assert candidate["contradict_count"] == 1
        assert candidate["status"] == "promoted"
        assert candidate["promoted_ref"] == "user:User prefers concise answers"
        assert [event["event_type"] for event in store.list_events("User prefers concise answers")] == [
            "create",
            "strengthen",
            "contradict",
            "prune",
            "promote",
        ]

    def test_counts_for_recurrence_false_does_not_increment(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        store.record_event(
            event_type="create",
            canonical_text="Build uses uv",
            kind="env_fact",
            proposed_target="memory",
            source_ref="artifact:1",
            source_event_id="evt-1",
            counts_for_recurrence=False,
        )

        candidate = store.get_candidate("Build uses uv")
        event = store.list_events("Build uses uv")[0]
        assert candidate["support_count"] == 0
        assert candidate["contradict_count"] == 0
        assert event["counts_for_recurrence"] == 0

    def test_duplicate_source_event_id_is_ignored_for_recurrence(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        first = store.record_event(
            event_type="create",
            canonical_text="User prefers concise answers",
            kind="preference",
            proposed_target="user",
            source_ref="session:1",
            source_event_id="evt-1",
        )
        duplicate = store.record_event(
            event_type="strengthen",
            canonical_text="User prefers concise answers",
            kind="preference",
            proposed_target="user",
            source_ref="session:1",
            source_event_id="evt-1",
        )

        candidate = store.get_candidate("User prefers concise answers")
        assert first["audit_label"] == "candidate_created"
        assert duplicate["audit_label"] == "duplicate_ignored"
        assert candidate["support_count"] == 1
        assert len(store.list_events("User prefers concise answers")) == 1

    def test_first_contradict_event_keeps_contradicted_audit_label(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        contradicted = store.record_event(
            event_type="contradict",
            canonical_text="Consensus implies correctness",
            kind="heuristic",
            proposed_target="memory",
            source_ref="cron:test",
            source_event_id="evt-contradict-first",
            counts_for_recurrence=False,
        )

        candidate = store.get_candidate("Consensus implies correctness")
        assert contradicted["audit_label"] == "candidate_contradicted"
        assert contradicted["event"]["event_type"] == "contradict"
        assert candidate["status"] == "active"
        assert candidate["support_count"] == 0
        assert candidate["contradict_count"] == 0

    def test_record_event_persists_generic_provenance_fields(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")

        recorded = store.record_event(
            event_type="create",
            canonical_text="User likes terse changelogs",
            kind="preference",
            proposed_target="user",
            routing_destination="user",
            subject_scope="session",
            subject_id="session-123",
            job_id="job-123",
            job_run_id="run-456",
            session_id="session-789",
            prompt_snapshot_id="prompt-001",
            routing_reason_codes=["cron_signal", "high_confidence"],
            source_ref="cron:job-123:session-789",
            source_event_id="evt-1",
        )

        candidate = store.get_candidate("User likes terse changelogs")
        event = store.list_events("User likes terse changelogs")[0]
        assert candidate["routing_destination"] == "user"
        assert candidate["subject_scope"] == "session"
        assert candidate["subject_id"] == "session-123"
        assert recorded["event"]["job_id"] == "job-123"
        assert event["job_run_id"] == "run-456"
        assert event["session_id"] == "session-789"
        assert event["prompt_snapshot_id"] == "prompt-001"
        assert json.loads(event["routing_reason_codes"]) == ["cron_signal", "high_confidence"]


class TestLayer2PayloadHelpers:
    def test_apply_layer2_payload_persists_normalized_routing_and_provenance(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")
        job = {
            "id": "job-123",
            "memory_pipeline": {"enabled": True},
        }
        payload = {
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Repository uses uv",
                    "kind": "env_fact",
                    "proposed_target": "memory",
                    "routing_destination": "memory",
                    "subject_scope": "repo",
                    "subject_id": "repo-1",
                    "routing_reason_codes": ["cron_summary", "explicit_candidate"],
                }
            ]
        }

        audit = apply_layer2_payload(
            job,
            payload,
            source_ref="cron:job-123:run-456",
            store=store,
        )

        candidate = store.get_candidate("Repository uses uv")
        event = store.list_events("Repository uses uv")[0]
        assert audit[0]["candidate"]["routing_destination"] == "prior"
        assert candidate["proposed_target"] == "prior"
        assert candidate["routing_destination"] == "prior"
        assert candidate["subject_scope"] == "repo"
        assert candidate["subject_id"] == "repo-1"
        assert event["routing_destination"] == "prior"
        assert event["job_id"] == "job-123"
        assert event["session_id"] == "run-456"
        assert json.loads(event["routing_reason_codes"]) == ["cron_summary", "explicit_candidate"]

    def test_apply_layer2_payload_persists_observations_and_episodes(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")
        job = {
            "id": "job-episodic",
            "memory_pipeline": {"enabled": True},
        }
        payload = {
            "episodes": [
                {
                    "summary_text": "Debugged flaky CI auth failure and documented workaround.",
                    "kind": "episode_summary",
                    "source_ref": "cron:job-episodic:run-1",
                    "subject_scope": "repo",
                    "subject_id": "repo-1",
                    "tags": ["ci", "auth"],
                    "metadata": {"branch": "main"},
                }
            ],
            "observations": [
                {
                    "observation_text": "gh auth status reported missing stored credentials.",
                    "kind": "tool_output",
                    "source_event_id": "obs-1",
                    "subject_scope": "repo",
                    "subject_id": "repo-1",
                    "tags": ["gh", "auth"],
                }
            ],
        }

        audit = apply_layer2_payload(
            job,
            payload,
            source_ref="cron:job-episodic:run-1",
            store=store,
        )

        episodes = store.list_episodes()
        observations = store.list_observations()
        assert len(episodes) == 1
        assert len(observations) == 1
        assert episodes[0]["summary_text"] == "Debugged flaky CI auth failure and documented workaround."
        assert json.loads(episodes[0]["tags_json"]) == ["auth", "ci"]
        assert json.loads(episodes[0]["metadata_json"]) == {"branch": "main"}
        assert observations[0]["observation_text"] == "gh auth status reported missing stored credentials."
        assert json.loads(observations[0]["tags_json"]) == ["auth", "gh"]
        assert any(item["audit_label"] == "episode_stored" for item in audit)
        assert any(item["audit_label"] == "observation_stored" for item in audit)

    def test_apply_layer2_payload_persists_context_packs_with_refresh_policy(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")
        job = {
            "id": "job-context-pack",
            "memory_pipeline": {"enabled": True},
        }
        payload = {
            "context_packs": [
                {
                    "pack_name": "repo-digest",
                    "kind": "repo_digest",
                    "title": "Repository digest",
                    "content": "Repository uses uv and pytest.",
                    "source_ref": "cron:job-context-pack:run-1",
                    "subject_scope": "repo",
                    "subject_id": "repo-1",
                    "tags": ["repo", "python"],
                    "metadata": {"branch": "main"},
                    "refresh_policy": {"strategy": "cron", "cadence": "daily"},
                }
            ]
        }

        audit = apply_layer2_payload(
            job,
            payload,
            source_ref="cron:job-context-pack:run-1",
            store=store,
        )

        context_pack = store.get_context_pack("repo-digest")
        assert context_pack is not None
        assert context_pack["kind"] == "repo_digest"
        assert context_pack["content_text"] == "Repository uses uv and pytest."
        assert context_pack["job_id"] == "job-context-pack"
        assert context_pack["session_id"] == "run-1"
        assert json.loads(context_pack["tags_json"]) == ["python", "repo"]
        assert json.loads(context_pack["metadata_json"]) == {"branch": "main"}
        assert json.loads(context_pack["refresh_policy_json"]) == {"cadence": "daily", "strategy": "cron"}
        assert any(item["audit_label"] == "context_pack_stored" for item in audit)

    def test_invalid_payload_is_left_in_response(self):
        payload_text = """Summary for humans.\n```hermes-layer2
{not valid json}
```"""
        clean, payload = parse_layer2_payload(payload_text)
        assert clean == payload_text
        assert payload is None

    def test_parse_and_apply_payload_non_opted_in_job_writes_nothing(self, tmp_path):
        payload_text = """Summary for humans.\n```hermes-layer2
{"candidate_events":[{"action":"create","canonical_text":"Prefers brief status notes","kind":"preference","proposed_target":"user"}]}
```"""
        clean, payload = parse_layer2_payload(payload_text)
        assert clean == "Summary for humans."
        audit = apply_layer2_payload(
            {"id": "job-1", "memory_pipeline": None},
            payload,
            source_ref="cron:job-1:run-1",
            store=Layer2Store(tmp_path / "layer2.sqlite3"),
        )
        assert audit == []

    def test_format_audit_section(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")
        audit = [
            store.record_event(
                event_type="create",
                canonical_text="User likes tables",
                kind="preference",
                proposed_target="user",
                source_ref="cron:test",
                source_event_id="evt-1",
            )
        ]
        section = format_layer2_audit_section(audit)
        assert "## Layer-2 Audit" in section
        assert "candidate_created" in section

    def test_skill_candidates_are_stored_and_rendered_with_skill_destination(self, tmp_path):
        store = Layer2Store(tmp_path / "layer2.sqlite3")
        audit = apply_layer2_payload(
            {"id": "job-skill", "memory_pipeline": {"enabled": True}},
            {
                "candidate_events": [
                    {
                        "action": "create",
                        "canonical_text": "When reviewing Hermes repo diffs, run targeted pytest after inspecting prompt-cache impacts.",
                        "kind": "procedure",
                        "proposed_target": "skill",
                        "routing_destination": "skill",
                        "routing_reason_codes": ["reusable_procedure", "manual_install_required"],
                    }
                ],
                "promotions": [
                    {
                        "canonical_text": "When reviewing Hermes repo diffs, run targeted pytest after inspecting prompt-cache impacts.",
                        "target": "skill",
                        "content": "Should not auto-install a skill.",
                    }
                ],
            },
            source_ref="cron:job-skill:run-1",
            store=store,
        )

        candidate = store.get_candidate(
            "When reviewing Hermes repo diffs, run targeted pytest after inspecting prompt-cache impacts."
        )
        event = store.list_events(candidate["canonical_text"])[0]
        section = format_layer2_audit_section(audit)

        assert candidate["proposed_target"] == "skill"
        assert candidate["routing_destination"] == "skill"
        assert event["routing_destination"] == "skill"
        assert json.loads(event["routing_reason_codes"]) == ["reusable_procedure", "manual_install_required"]
        assert "skill / procedure" in section
        assert "candidate_created" in section
        assert "durable_write" not in section


class TestRunJobLayer2Integration:
    def _run_job(self, tmp_path, monkeypatch, job, final_response):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        fake_db = MagicMock()

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            def run_conversation(self, prompt):
                return {"final_response": final_response}

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler._resolve_origin", return_value=None), \
             patch("dotenv.load_dotenv"), \
             patch("hermes_state.SessionDB", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "***",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent", FakeAgent):
            result = run_job(job)
        return result, fake_db

    def test_run_job_applies_valid_layer2_payload(self, tmp_path, monkeypatch):
        job = {
            "id": "memory-job",
            "name": "Memory Job",
            "prompt": "Summarize recurring facts.",
            "schedule_display": "every 1h",
            "memory_pipeline": {"enabled": True},
        }
        response = """Human summary.
```hermes-layer2
{"candidate_events":[{"action":"create","canonical_text":"User prefers concise answers","kind":"preference","proposed_target":"user","counts_for_recurrence":true}]}
```"""

        (success, output, final_response, error), fake_db = self._run_job(
            tmp_path, monkeypatch, job, response
        )

        assert success is True
        assert error is None
        assert final_response == "Human summary."
        assert "## Layer-2 Audit" in output
        store = Layer2Store(tmp_path / "cron" / "layer2_memory.sqlite3")
        candidate = store.get_candidate("User prefers concise answers")
        assert candidate["support_count"] == 1
        assert candidate["proposed_target"] == "user"
        fake_db.close.assert_called_once()

    def test_run_job_persists_layer2_provenance_metadata(self, tmp_path, monkeypatch):
        job = {
            "id": "memory-job",
            "name": "Memory Job",
            "prompt": "Summarize recurring facts.",
            "schedule_display": "every 1h",
            "memory_pipeline": {"enabled": True},
        }
        response = """Human summary.
```hermes-layer2
{"candidate_events":[{"action":"create","canonical_text":"Repository uses uv","kind":"env_fact","proposed_target":"memory","routing_destination":"memory","routing_reason_codes":["cron_summary"]}]}
```"""

        (success, _output, _final_response, error), _fake_db = self._run_job(
            tmp_path, monkeypatch, job, response
        )

        assert success is True
        assert error is None
        store = Layer2Store(tmp_path / "cron" / "layer2_memory.sqlite3")
        candidate = store.get_candidate("Repository uses uv")
        event = store.list_events("Repository uses uv")[0]
        assert candidate["routing_destination"] == "prior"
        assert event["job_id"] == "memory-job"
        assert event["session_id"].startswith("cron_memory-job_")
        assert json.loads(event["routing_reason_codes"]) == ["cron_summary"]

    def test_non_opted_in_job_does_not_write_layer2(self, tmp_path, monkeypatch):
        job = {
            "id": "regular-job",
            "name": "Regular Job",
            "prompt": "Summarize recurring facts.",
            "schedule_display": "every 1h",
        }
        response = """Human summary.
```hermes-layer2
{"candidate_events":[{"action":"create","canonical_text":"Do not store this","kind":"preference","proposed_target":"user"}]}
```"""

        (success, output, final_response, error), _fake_db = self._run_job(
            tmp_path, monkeypatch, job, response
        )

        assert success is True
        assert error is None
        assert final_response == response
        assert "## Layer-2 Audit" not in output
        store = Layer2Store(tmp_path / "cron" / "layer2_memory.sqlite3")
        assert store.list_candidates() == []

    def test_guarded_durable_promotion_only_writes_allowed_targets(self, tmp_path, monkeypatch):
        job = {
            "id": "promotion-job",
            "name": "Promotion Job",
            "prompt": "Promote approved facts.",
            "schedule_display": "every 1h",
            "memory_pipeline": {
                "enabled": True,
                "allow_durable_promotion_targets": ["user"],
            },
        }
        response = """Promoted summary.
```hermes-layer2
{"candidate_events":[{"action":"create","canonical_text":"User prefers concise answers","kind":"preference","proposed_target":"user"}],"promotions":[{"canonical_text":"User prefers concise answers","target":"user","content":"User prefers concise answers"},{"canonical_text":"Repository uses uv","target":"memory","content":"Repository uses uv"}]}
```"""

        (success, output, final_response, error), _fake_db = self._run_job(
            tmp_path, monkeypatch, job, response
        )

        assert success is True
        assert error is None
        assert final_response == "Promoted summary."
        assert "durable_write → user: User prefers concise answers" in output
        user_file = tmp_path / "memories" / "USER.md"
        memory_file = tmp_path / "memories" / "MEMORY.md"
        assert user_file.exists()
        assert "User prefers concise answers" in user_file.read_text(encoding="utf-8")
        assert not memory_file.exists() or "Repository uses uv" not in memory_file.read_text(encoding="utf-8")
        store = Layer2Store(tmp_path / "cron" / "layer2_memory.sqlite3")
        candidate = store.get_candidate("User prefers concise answers")
        assert candidate["status"] == "promoted"
        assert candidate["promoted_ref"] == "user:User prefers concise answers"

    def test_empty_visible_response_does_not_mutate_layer2(self, tmp_path, monkeypatch):
        job = {
            "id": "empty-visible-job",
            "name": "Empty Visible Job",
            "prompt": "Promote approved facts.",
            "schedule_display": "every 1h",
            "memory_pipeline": {"enabled": True},
        }
        response = """```hermes-layer2
{"candidate_events":[{"action":"create","canonical_text":"Invisible candidate","kind":"fact","proposed_target":"memory"}]}
```"""

        (success, output, final_response, error), _fake_db = self._run_job(
            tmp_path, monkeypatch, job, response
        )

        assert success is True
        assert final_response == ""
        assert "## Layer-2 Audit" not in output
        store = Layer2Store(tmp_path / "cron" / "layer2_memory.sqlite3")
        assert store.list_candidates() == []

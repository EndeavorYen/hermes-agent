from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.platforms.slack import SlackAdapter
from gateway.session import SessionSource


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    import gateway.platforms.slack as slack_mod

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
    monkeypatch.setattr(
        slack_mod,
        "public_export_media_path",
        lambda path: path,
        raising=False,
    )
    config = PlatformConfig(enabled=True, token="xoxb-fake")
    slack = SlackAdapter(config)
    slack._app = MagicMock()
    slack._resolve_thread_ts = MagicMock(return_value="171000.0001")
    slack._record_uploaded_file_thread = MagicMock()
    client = MagicMock()
    client.files_upload_v2 = AsyncMock(return_value={"ok": True, "file": {"id": "F1"}})
    slack._get_client = MagicMock(return_value=client)
    return slack


def test_slack_skips_artifact_not_selected_for_current_request(adapter, tmp_path):
    selected = _write_image(tmp_path / "selected.png")
    stale = _write_image(tmp_path / "stale.png")
    selected_uri = selected.as_uri()
    stale_uri = stale.as_uri()
    metadata = _visual_metadata(
        request_id="vrq_current",
        selected_artifact_ids=["var_selected"],
        artifacts={
            selected_uri: {
                "artifact_id": "var_selected",
                "attempt_id": "vat_selected",
                "content_hash": "sha256:selected",
            },
            stale_uri: {
                "artifact_id": "var_stale",
                "attempt_id": "vat_stale",
                "content_hash": "sha256:stale",
            },
        },
    )

    _run(
        adapter.send_multiple_images(
            "C12345",
            [(selected_uri, "selected"), (stale_uri, "stale")],
            metadata=metadata,
        )
    )

    client = adapter._get_client("C12345")
    client.files_upload_v2.assert_awaited_once()
    kwargs = client.files_upload_v2.await_args.kwargs
    assert [upload["filename"] for upload in kwargs["file_uploads"]] == [
        "selected.png"
    ]
    assert kwargs["initial_comment"] == "selected"

    rows = _delivery_rows(tmp_path)
    assert {(row["artifact_id"], row["delivery_status"]) for row in rows} == {
        ("var_stale", "skipped_stale"),
        ("var_selected", "sent"),
    }


def test_slack_records_delivery_result_for_uploaded_artifact(adapter, tmp_path):
    image = _write_image(tmp_path / "fresh.png")
    image_uri = image.as_uri()
    metadata = _visual_metadata(
        request_id="vrq_current",
        selected_artifact_ids=["var_fresh"],
        artifacts={
            image_uri: {
                "artifact_id": "var_fresh",
                "attempt_id": "vat_fresh",
                "content_hash": "sha256:fresh",
            }
        },
    )

    _run(
        adapter.send_multiple_images(
            "C12345",
            [(image_uri, "fresh")],
            metadata=metadata,
        )
    )

    rows = _delivery_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["request_id"] == "vrq_current"
    assert row["attempt_id"] == "vat_fresh"
    assert row["artifact_id"] == "var_fresh"
    assert row["platform"] == "slack"
    assert row["destination_id"] == "C12345"
    assert row["thread_id"] == "171000.0001"
    assert row["delivery_status"] == "sent"


def test_slack_skips_duplicate_visual_artifact_hash(adapter, tmp_path):
    first = _write_image(tmp_path / "first.png")
    second = _write_image(tmp_path / "second.png")
    first_uri = first.as_uri()
    second_uri = second.as_uri()
    metadata = _visual_metadata(
        request_id="vrq_current",
        selected_artifact_ids=["var_dup"],
        artifacts={
            first_uri: {
                "artifact_id": "var_dup",
                "attempt_id": "vat_dup",
                "content_hash": "sha256:dup",
            },
            second_uri: {
                "artifact_id": "var_dup",
                "attempt_id": "vat_dup",
                "content_hash": "sha256:dup",
            },
        },
    )

    _run(
        adapter.send_multiple_images(
            "C12345",
            [(first_uri, "first"), (second_uri, "second")],
            metadata=metadata,
        )
    )

    client = adapter._get_client("C12345")
    client.files_upload_v2.assert_awaited_once()
    kwargs = client.files_upload_v2.await_args.kwargs
    assert [upload["filename"] for upload in kwargs["file_uploads"]] == ["first.png"]

    rows = _delivery_rows(tmp_path)
    assert len(rows) == 2
    assert {row["delivery_status"] for row in rows} == {
        "skipped_duplicate",
        "sent",
    }


def test_slack_auto_builds_visual_metadata_for_all_batch_artifacts_when_missing(adapter, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path

    old = _write_image(tmp_path / "old.png")
    new = _write_image(tmp_path / "new.png")
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    _record_artifact_fixture(
        ledger,
        request_id="vrq_old",
        attempt_id="vat_old",
        artifact_id="var_old",
        local_path=str(old),
        content_hash="sha256:old",
        created_at="2026-06-19T01:00:00Z",
    )
    _record_artifact_fixture(
        ledger,
        request_id="vrq_new",
        attempt_id="vat_new",
        artifact_id="var_new",
        local_path=str(new),
        content_hash="sha256:new",
        created_at="2026-06-19T02:00:00Z",
    )

    _run(
        adapter.send_multiple_images(
            "C12345",
            [(old.as_uri(), "old"), (new.as_uri(), "new")],
            metadata={"thread_id": "171000.0001"},
        )
    )

    client = adapter._get_client("C12345")
    client.files_upload_v2.assert_awaited_once()
    kwargs = client.files_upload_v2.await_args.kwargs
    assert [upload["filename"] for upload in kwargs["file_uploads"]] == [
        "old.png",
        "new.png",
    ]

    rows = _delivery_rows(tmp_path)
    assert [(row["artifact_id"], row["delivery_status"]) for row in rows] == [
        ("var_old", "sent"),
        ("var_new", "sent"),
    ]


def test_slack_delivers_all_fresh_artifacts_in_same_response_batch(adapter, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    batch = []
    for idx in range(1, 5):
        image = _write_image(tmp_path / f"fresh_{idx}.png")
        artifact_id = f"var_fresh_{idx}"
        _record_artifact_fixture(
            ledger,
            request_id=f"vrq_fresh_{idx}",
            attempt_id=f"vat_fresh_{idx}",
            artifact_id=artifact_id,
            local_path=str(image),
            content_hash=f"sha256:fresh-{idx}",
            created_at=f"2026-06-19T02:00:0{idx}Z",
        )
        batch.append((image.as_uri(), f"fresh {idx}"))

    _run(
        adapter.send_multiple_images(
            "C12345",
            batch,
            metadata={"thread_id": "171000.0001"},
        )
    )

    client = adapter._get_client("C12345")
    client.files_upload_v2.assert_awaited_once()
    kwargs = client.files_upload_v2.await_args.kwargs
    assert [upload["filename"] for upload in kwargs["file_uploads"]] == [
        "fresh_1.png",
        "fresh_2.png",
        "fresh_3.png",
        "fresh_4.png",
    ]

    rows = _delivery_rows(tmp_path)
    assert [(row["artifact_id"], row["delivery_status"]) for row in rows] == [
        ("var_fresh_1", "sent"),
        ("var_fresh_2", "sent"),
        ("var_fresh_3", "sent"),
        ("var_fresh_4", "sent"),
    ]


def test_slack_records_delivery_when_local_image_is_public_exported(adapter, tmp_path, monkeypatch):
    import gateway.platforms.base as base_mod
    import gateway.platforms.slack as slack_mod

    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path

    source = _write_image(tmp_path / "source.png")
    exported = _write_image(tmp_path / "public.png")
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    _record_artifact_fixture(
        ledger,
        request_id="vrq_current",
        attempt_id="vat_current",
        artifact_id="var_current",
        local_path=str(source),
        content_hash="sha256:current",
        created_at="2026-06-19T02:00:00Z",
    )
    monkeypatch.setattr(
        base_mod,
        "public_export_media_path",
        lambda path: str(exported) if path == str(source) else path,
    )
    monkeypatch.setattr(
        slack_mod,
        "public_export_media_path",
        lambda path: str(exported) if path == str(source) else path,
    )

    async def handler(_event):
        return str(source)

    async def dispatch():
        adapter.set_message_handler(handler)
        event = MessageEvent(
            text="make image",
            source=SessionSource(platform=Platform.SLACK, chat_id="C12345"),
        )
        await adapter.handle_message(event)
        if adapter._background_tasks:
            await asyncio.gather(*adapter._background_tasks)

    _run(dispatch())

    client = adapter._get_client("C12345")
    client.files_upload_v2.assert_awaited_once()
    kwargs = client.files_upload_v2.await_args.kwargs
    assert [upload["file"] for upload in kwargs["file_uploads"]] == [str(exported)]

    rows = _delivery_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["request_id"] == "vrq_current"
    assert row["artifact_id"] == "var_current"
    assert row["delivery_status"] == "sent"


def _write_image(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return path


def _visual_metadata(
    *,
    request_id: str,
    selected_artifact_ids: list[str],
    artifacts: dict[str, dict[str, str]],
) -> dict:
    return {
        "visual_request_id": request_id,
        "selected_visual_artifact_ids": selected_artifact_ids,
        "visual_artifacts": artifacts,
    }


def _delivery_rows(tmp_path):
    db_path = tmp_path / "hermes_home" / "visual" / "attempt_ledger.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT request_id, attempt_id, artifact_id, platform,
                       destination_id, thread_id, delivery_status, error_type
                 FROM visual_deliveries
                 ORDER BY rowid
                """
            ).fetchall()
        ]


def _record_artifact_fixture(
    ledger,
    *,
    request_id: str,
    attempt_id: str,
    artifact_id: str,
    local_path: str,
    content_hash: str,
    created_at: str,
) -> None:
    ledger.record_request(
        request_id=request_id,
        user_prompt="fashion editorial portrait",
        normalized_intent={"modality": "image"},
        modality="image",
        operation="text_to_image",
        created_at=created_at,
    )
    ledger.record_attempt(
        request_id=request_id,
        attempt_id=attempt_id,
        candidate_index=0,
        provider="fake",
        model="fake-image",
        prompt_original="fashion editorial portrait",
        prompt_mediated="fashion editorial portrait",
        created_at=created_at,
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        kind="image",
        local_path=local_path,
        content_hash=content_hash,
        mime_type="image/png",
        bytes=10,
        is_stable=True,
        freshness_status="fresh",
        created_at=created_at,
    )

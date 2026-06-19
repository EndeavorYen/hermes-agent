from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.slack import SlackAdapter


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
                 ORDER BY delivered_at, delivery_id
                """
            ).fetchall()
        ]

"""Identifier helpers for visual generation records."""

from __future__ import annotations

import datetime as _dt
import uuid


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def new_request_id() -> str:
    return _new_id("vrq")


def new_attempt_id() -> str:
    return _new_id("vat")


def new_artifact_id() -> str:
    return _new_id("var")


def new_judgment_id() -> str:
    return _new_id("vjd")


def new_ranking_id() -> str:
    return _new_id("vrk")


def new_delivery_id() -> str:
    return _new_id("vdl")


def new_feedback_id() -> str:
    return _new_id("vfb")


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

from __future__ import annotations

from uuid import uuid4


def _new_visual_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def new_request_id() -> str:
    return _new_visual_id("vrq")


def new_attempt_id() -> str:
    return _new_visual_id("vat")


def new_artifact_id() -> str:
    return _new_visual_id("var")


def new_judgment_id() -> str:
    return _new_visual_id("vjg")


def new_ranking_id() -> str:
    return _new_visual_id("vrk")


def new_delivery_id() -> str:
    return _new_visual_id("vdl")


def new_feedback_id() -> str:
    return _new_visual_id("vfb")

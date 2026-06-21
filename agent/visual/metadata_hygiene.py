from __future__ import annotations

from typing import Any


PRIVATE_METADATA_KEYS = {
    "local_path",
    "absolute_path",
    "source_path",
    "cache_key",
    "cache_path",
    "filesystem",
    "gps",
    "gps_latitude",
    "gps_longitude",
    "camera_model",
    "camera_serial",
    "device_id",
    "user",
    "username",
}


def sanitize_deliverable_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key not in PRIVATE_METADATA_KEYS
    }

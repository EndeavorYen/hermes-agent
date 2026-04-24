"""Compatibility facade for the shared Layer-2 memory store.

Layer-2 is no longer owned by the cron package. Cron remains one producer of
Layer-2 payloads, while the shared implementation lives in memory.layer2_store.
"""

from memory.layer2_store import *  # noqa: F401,F403

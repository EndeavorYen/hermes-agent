"""Minimal runtime Layer-2 recall adapter."""

from __future__ import annotations

from typing import Any, Dict

from cron.layer2_memory import Layer2Store


def _format_candidate_line(candidate: Dict[str, Any]) -> str:
    destination = str(candidate.get("routing_destination") or candidate.get("proposed_target") or "prior").strip() or "prior"
    kind = str(candidate.get("kind") or "fact").strip() or "fact"
    canonical_text = str(candidate.get("canonical_text") or "").strip()
    support_count = int(candidate.get("support_count") or 0)
    return f"- [{destination}/{kind}] {canonical_text} (support={support_count})"


def _format_episode_line(episode: Dict[str, Any]) -> str:
    kind = str(episode.get("kind") or "episode_summary").strip() or "episode_summary"
    summary_text = str(episode.get("summary_text") or "").strip()
    source_ref = str(episode.get("source_ref") or "").strip()
    if not summary_text:
        return ""
    suffix = f" (source={source_ref})" if source_ref else ""
    return f"- [episodic/{kind}] {summary_text}{suffix}"


def _format_observation_line(observation: Dict[str, Any]) -> str:
    kind = str(observation.get("kind") or "observation").strip() or "observation"
    observation_text = str(observation.get("observation_text") or "").strip()
    source_ref = str(observation.get("source_ref") or "").strip()
    if not observation_text:
        return ""
    suffix = f" (source={source_ref})" if source_ref else ""
    return f"- [observation/{kind}] {observation_text}{suffix}"


def _format_context_pack_line(context_pack: Dict[str, Any]) -> str:
    pack_name = str(context_pack.get("pack_name") or "").strip()
    kind = str(context_pack.get("kind") or "context_pack").strip() or "context_pack"
    content_text = str(context_pack.get("content_text") or "").strip()
    source_ref = str(context_pack.get("source_ref") or "").strip()
    if not pack_name or not content_text:
        return ""
    suffix = f" (source={source_ref})" if source_ref else ""
    return f"- [context_pack/{kind}] {pack_name}: {content_text}{suffix}"


def _append_line(lines: list[str], total_chars: int, budget: int, line: str) -> int:
    if not line:
        return total_chars
    next_total = total_chars + len(line) + (1 if lines else 0)
    if next_total > budget:
        return total_chars
    lines.append(line)
    return next_total


def prefetch_layer2_context(
    *,
    max_items: int = 6,
    char_budget: int = 1500,
    min_support_count: int = 2,
    query_text: str | None = None,
    explicit_pack_names: list[str] | None = None,
    auto_select_context_packs: bool = False,
) -> str | None:
    store = Layer2Store()
    candidates = store.query_candidates_for_pack(
        destinations=["prior", "user"],
        max_items=max_items,
        min_support_count=min_support_count,
    )

    budget = max(1, int(char_budget))
    lines: list[str] = []
    total_chars = 0
    for candidate in candidates:
        total_chars = _append_line(lines, total_chars, budget, _format_candidate_line(candidate))

    requested_pack_names = [str(item).strip() for item in (explicit_pack_names or []) if str(item).strip()]
    should_include_context_packs = bool(requested_pack_names or auto_select_context_packs)
    remaining_slots = max(0, int(max_items) - len(lines))
    if should_include_context_packs and remaining_slots > 0:
        context_packs = store.query_context_packs_for_pack(
            explicit_pack_names=requested_pack_names or None,
            query_text=query_text,
            max_items=min(2, remaining_slots),
        )
        for context_pack in context_packs:
            total_chars = _append_line(lines, total_chars, budget, _format_context_pack_line(context_pack))
        remaining_slots = max(0, int(max_items) - len(lines))

    if remaining_slots > 0:
        for episode in store.query_episodes_for_pack(max_items=min(2, remaining_slots)):
            total_chars = _append_line(lines, total_chars, budget, _format_episode_line(episode))
        remaining_slots = max(0, int(max_items) - len(lines))
    if remaining_slots > 0:
        for observation in store.query_observations_for_pack(max_items=min(2, remaining_slots)):
            total_chars = _append_line(lines, total_chars, budget, _format_observation_line(observation))

    if not lines:
        return None
    return "\n".join(lines)

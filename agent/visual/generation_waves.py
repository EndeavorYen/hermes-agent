from __future__ import annotations

import concurrent.futures
import contextvars
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from agent.visual.provider_failures import classify_visual_provider_failure


_MAX_PARALLELISM = 3
_PROVIDER_PARALLELISM = {
    "openai": 3,
    "openai-codex": 3,
    "xai": 2,
    "grok": 2,
    "grok-build": 2,
}
_PRESSURE_FAILURES = {"provider_unavailable", "rate_limited", "timeout"}


@dataclass(frozen=True)
class GenerationWaveItem:
    key: str
    payload: Any
    group_key: str = ""
    requires_serial: bool = False


@dataclass(frozen=True)
class GenerationWaveTaskResult:
    key: str
    value: Any
    success: bool
    failure_class: str = ""
    error: str = ""
    skipped: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "success": self.success,
            "failure_class": self.failure_class or None,
            "error": self.error or None,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class GenerationWave:
    index: int
    parallelism: int
    item_keys: tuple[str, ...]
    succeeded: int
    failed: int
    pressure_detected: bool
    terminal_failure: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "parallelism": self.parallelism,
            "item_keys": list(self.item_keys),
            "succeeded": self.succeeded,
            "failed": self.failed,
            "pressure_detected": self.pressure_detected,
            "terminal_failure": self.terminal_failure or None,
        }


@dataclass(frozen=True)
class GenerationWaveRun:
    provider: str
    configured_parallelism: int
    final_parallelism: int
    max_parallelism_used: int
    results: tuple[GenerationWaveTaskResult, ...]
    waves: tuple[GenerationWave, ...]

    @property
    def total_dispatched(self) -> int:
        return sum(1 for result in self.results if not result.skipped)

    @property
    def total_succeeded(self) -> int:
        return sum(1 for result in self.results if result.success)

    @property
    def total_failed(self) -> int:
        return sum(
            1 for result in self.results if not result.success and not result.skipped
        )

    @property
    def total_skipped(self) -> int:
        return sum(1 for result in self.results if result.skipped)

    def to_record(self) -> dict[str, Any]:
        return {
            "mode": "provider_aware_generation_waves",
            "provider": self.provider,
            "configured_parallelism": self.configured_parallelism,
            "final_parallelism": self.final_parallelism,
            "max_parallelism_used": self.max_parallelism_used,
            "total_dispatched": self.total_dispatched,
            "total_succeeded": self.total_succeeded,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "waves": [wave.to_record() for wave in self.waves],
            "results": [result.to_record() for result in self.results],
        }


def resolve_generation_parallelism(
    provider: str | None,
    *,
    requested_limit: Any = None,
    config: dict[str, Any] | None = None,
) -> int:
    runtime_config = _runtime_config() if config is None else config
    image_gen = (
        runtime_config.get("image_gen")
        if isinstance(runtime_config, dict)
        and isinstance(runtime_config.get("image_gen"), dict)
        else {}
    )
    normalized_provider = _normalize_provider(
        provider or image_gen.get("provider") or ""
    )
    limits = [
        _PROVIDER_PARALLELISM.get(normalized_provider, _MAX_PARALLELISM),
        _positive_int(requested_limit),
        _positive_int(image_gen.get("max_parallel_requests")),
    ]
    provider_config = image_gen.get(normalized_provider)
    if isinstance(provider_config, dict):
        limits.append(_positive_int(provider_config.get("max_parallel_requests")))
    return max(1, min(limit for limit in limits if limit is not None))


class GenerationWaveScheduler:
    def __init__(
        self,
        *,
        provider: str | None,
        requested_parallelism: Any = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.provider = _normalize_provider(provider or "")
        self.configured_parallelism = resolve_generation_parallelism(
            provider,
            requested_limit=requested_parallelism,
            config=config,
        )

    def run(
        self,
        items: Sequence[GenerationWaveItem],
        worker: Callable[[Any], Any],
    ) -> GenerationWaveRun:
        pending = list(range(len(items)))
        results: list[GenerationWaveTaskResult | None] = [None] * len(items)
        waves: list[GenerationWave] = []
        current_parallelism = self.configured_parallelism
        max_parallelism_used = 0
        healthy_waves = 0
        terminal_failure = ""

        while pending:
            selected = _select_wave_indices(
                pending,
                items,
                limit=current_parallelism,
            )
            selected_set = set(selected)
            pending = [index for index in pending if index not in selected_set]
            wave_results = self._run_wave(selected, items, worker)
            for index, result in wave_results.items():
                results[index] = result

            failure_classes = {
                result.failure_class
                for result in wave_results.values()
                if result.failure_class
            }
            pressure_detected = bool(failure_classes & _PRESSURE_FAILURES)
            terminal_failure = next(
                (
                    failure
                    for failure in ("quota_exceeded", "authentication_required")
                    if failure in failure_classes
                ),
                "",
            )
            succeeded = sum(1 for result in wave_results.values() if result.success)
            waves.append(
                GenerationWave(
                    index=len(waves) + 1,
                    parallelism=len(selected),
                    item_keys=tuple(items[index].key for index in selected),
                    succeeded=succeeded,
                    failed=len(selected) - succeeded,
                    pressure_detected=pressure_detected,
                    terminal_failure=terminal_failure,
                )
            )
            max_parallelism_used = max(max_parallelism_used, len(selected))

            if terminal_failure:
                for index in pending:
                    results[index] = GenerationWaveTaskResult(
                        key=items[index].key,
                        value=None,
                        success=False,
                        failure_class=terminal_failure,
                        error="not dispatched after provider quota exhaustion",
                        skipped=True,
                    )
                pending.clear()
                break
            if pressure_detected:
                current_parallelism = max(1, current_parallelism - 1)
                healthy_waves = 0
            elif succeeded == len(selected):
                healthy_waves += 1
                if healthy_waves >= 2 and current_parallelism < self.configured_parallelism:
                    current_parallelism += 1
                    healthy_waves = 0
            else:
                healthy_waves = 0

        finalized = tuple(
            result
            if result is not None
            else GenerationWaveTaskResult(
                key=items[index].key,
                value=None,
                success=False,
                failure_class="unknown",
                error="generation result was not recorded",
                skipped=True,
            )
            for index, result in enumerate(results)
        )
        return GenerationWaveRun(
            provider=self.provider,
            configured_parallelism=self.configured_parallelism,
            final_parallelism=current_parallelism,
            max_parallelism_used=max_parallelism_used,
            results=finalized,
            waves=tuple(waves),
        )

    @staticmethod
    def _run_wave(
        selected: Sequence[int],
        items: Sequence[GenerationWaveItem],
        worker: Callable[[Any], Any],
    ) -> dict[int, GenerationWaveTaskResult]:
        wave_results: dict[int, GenerationWaveTaskResult] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(selected)),
            thread_name_prefix="visual-generation-wave",
        ) as executor:
            futures = {
                executor.submit(
                    contextvars.copy_context().run,
                    worker,
                    items[index].payload,
                ): index
                for index in selected
            }
            for future in concurrent.futures.as_completed(futures):
                index = futures[future]
                item = items[index]
                try:
                    value = future.result()
                except Exception as exc:
                    classification = classify_visual_provider_failure(exc)
                    wave_results[index] = GenerationWaveTaskResult(
                        key=item.key,
                        value=None,
                        success=False,
                        failure_class=str(classification.get("failure_class") or "unknown"),
                        error=str(exc),
                    )
                    continue
                success = not isinstance(value, dict) or value.get("success") is True
                classification = (
                    {}
                    if success
                    else classify_visual_provider_failure(
                        value if isinstance(value, dict) else RuntimeError(str(value))
                    )
                )
                wave_results[index] = GenerationWaveTaskResult(
                    key=item.key,
                    value=value,
                    success=success,
                    failure_class=str(classification.get("failure_class") or ""),
                    error=_payload_error(value) if not success else "",
                )
        return wave_results


def _select_wave_indices(
    pending: Sequence[int],
    items: Sequence[GenerationWaveItem],
    *,
    limit: int,
) -> list[int]:
    if not pending:
        return []
    serial_index = next(
        (index for index in pending if items[index].requires_serial),
        None,
    )
    if serial_index is not None:
        return [serial_index]
    selected: list[int] = []
    groups: set[str] = set()
    for index in pending:
        item = items[index]
        if item.requires_serial:
            continue
        group = item.group_key or item.key
        if group in groups:
            continue
        selected.append(index)
        groups.add(group)
        if len(selected) >= limit:
            break
    return selected or [pending[0]]


def _runtime_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        config = load_config() or {}
    except Exception:
        return {}
    return config if isinstance(config, dict) else {}


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, min(parsed, _MAX_PARALLELISM)) if parsed > 0 else None


def _normalize_provider(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "grok-build-image": "xai",
        "grok-imagine": "xai",
        "openai-codex-oauth": "openai-codex",
    }
    return aliases.get(normalized, normalized)


def _payload_error(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    for key in ("error", "message", "reason", "error_type"):
        if value.get(key):
            return str(value[key])
    return "provider generation failed"

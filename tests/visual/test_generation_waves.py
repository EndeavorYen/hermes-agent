import threading
import time


def test_generation_parallelism_is_provider_aware() -> None:
    from agent.visual.generation_waves import resolve_generation_parallelism

    assert resolve_generation_parallelism("openai-codex", config={}) == 3
    assert resolve_generation_parallelism("xai", config={}) == 2
    assert resolve_generation_parallelism(
        "openai-codex",
        config={"image_gen": {"max_parallel_requests": 2}},
    ) == 2
    assert resolve_generation_parallelism(
        "xai",
        config={"image_gen": {"xai": {"max_parallel_requests": 1}}},
    ) == 1


def test_generation_waves_overlap_work_and_preserve_input_order() -> None:
    from agent.visual.generation_waves import GenerationWaveItem
    from agent.visual.generation_waves import GenerationWaveScheduler

    active = 0
    max_active = 0
    lock = threading.Lock()

    def worker(value: int) -> dict[str, object]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.04 if value % 2 else 0.02)
        with lock:
            active -= 1
        return {"success": True, "value": value}

    run = GenerationWaveScheduler(provider="openai-codex", config={}).run(
        [GenerationWaveItem(key=f"shot-{value}", payload=value) for value in range(5)],
        worker,
    )

    assert max_active == 3
    assert [result.key for result in run.results] == [
        "shot-0",
        "shot-1",
        "shot-2",
        "shot-3",
        "shot-4",
    ]
    assert [result.value["value"] for result in run.results] == list(range(5))
    assert run.total_dispatched == 5
    assert run.max_parallelism_used == 3


def test_generation_waves_preserve_partial_success_and_isolate_exception() -> None:
    from agent.visual.generation_waves import GenerationWaveItem
    from agent.visual.generation_waves import GenerationWaveScheduler

    def worker(value: int) -> dict[str, object]:
        if value == 1:
            raise RuntimeError("provider transport failed")
        return {"success": True, "value": value}

    run = GenerationWaveScheduler(provider="openai-codex", config={}).run(
        [GenerationWaveItem(key=f"shot-{value}", payload=value) for value in range(3)],
        worker,
    )

    assert [result.success for result in run.results] == [True, False, True]
    assert run.results[1].failure_class == "unknown"
    assert run.total_succeeded == 2
    assert run.total_failed == 1


def test_generation_waves_do_not_parallelize_candidates_from_same_shot() -> None:
    from agent.visual.generation_waves import GenerationWaveItem
    from agent.visual.generation_waves import GenerationWaveScheduler

    run = GenerationWaveScheduler(provider="openai-codex", config={}).run(
        [
            GenerationWaveItem(key="shot-1-c1", group_key="shot-1", payload=1),
            GenerationWaveItem(key="shot-1-c2", group_key="shot-1", payload=2),
            GenerationWaveItem(key="shot-2-c1", group_key="shot-2", payload=3),
            GenerationWaveItem(key="shot-3-c1", group_key="shot-3", payload=4),
        ],
        lambda value: {"success": True, "value": value},
    )

    assert run.waves[0].item_keys == (
        "shot-1-c1",
        "shot-2-c1",
        "shot-3-c1",
    )
    assert run.waves[1].item_keys == ("shot-1-c2",)


def test_generation_waves_lock_serial_anchor_before_fresh_parallel_work() -> None:
    from agent.visual.generation_waves import GenerationWaveItem
    from agent.visual.generation_waves import GenerationWaveScheduler

    run = GenerationWaveScheduler(provider="openai-codex", config={}).run(
        [
            GenerationWaveItem(key="shot-1", payload=1),
            GenerationWaveItem(
                key="style-anchor",
                payload=2,
                requires_serial=True,
            ),
            GenerationWaveItem(key="shot-3", payload=3),
        ],
        lambda value: {"success": True, "value": value},
    )

    assert run.waves[0].item_keys == ("style-anchor",)
    assert run.waves[1].item_keys == ("shot-1", "shot-3")


def test_generation_waves_reduce_next_wave_after_rate_limit() -> None:
    from agent.visual.generation_waves import GenerationWaveItem
    from agent.visual.generation_waves import GenerationWaveScheduler

    def worker(value: int) -> dict[str, object]:
        if value == 1:
            return {
                "success": False,
                "status_code": 429,
                "error_type": "rate_limited",
                "error": "too many requests",
            }
        return {"success": True, "value": value}

    run = GenerationWaveScheduler(provider="openai-codex", config={}).run(
        [GenerationWaveItem(key=f"shot-{value}", payload=value) for value in range(5)],
        worker,
    )

    assert [wave.parallelism for wave in run.waves] == [3, 2]
    assert run.final_parallelism == 2
    assert run.total_dispatched == 5


def test_generation_waves_stop_undispatched_work_after_quota_exhaustion() -> None:
    from agent.visual.generation_waves import GenerationWaveItem
    from agent.visual.generation_waves import GenerationWaveScheduler

    dispatched: list[int] = []

    def worker(value: int) -> dict[str, object]:
        dispatched.append(value)
        if value == 0:
            return {
                "success": False,
                "error_type": "quota_exceeded",
                "error": "quota exceeded",
            }
        return {"success": True, "value": value}

    run = GenerationWaveScheduler(provider="xai", config={}).run(
        [GenerationWaveItem(key=f"shot-{value}", payload=value) for value in range(5)],
        worker,
    )

    assert sorted(dispatched) == [0, 1]
    assert run.total_dispatched == 2
    assert run.total_skipped == 3
    assert [result.failure_class for result in run.results[2:]] == [
        "quota_exceeded",
        "quota_exceeded",
        "quota_exceeded",
    ]


def test_generation_waves_stop_after_authentication_failure() -> None:
    from agent.visual.generation_waves import GenerationWaveItem
    from agent.visual.generation_waves import GenerationWaveScheduler

    def worker(value: int) -> dict[str, object]:
        if value == 0:
            return {
                "success": False,
                "status_code": 401,
                "error_type": "authentication_failed",
                "error": "access token expired",
            }
        return {"success": True, "value": value}

    run = GenerationWaveScheduler(provider="openai-codex", config={}).run(
        [GenerationWaveItem(key=f"shot-{value}", payload=value) for value in range(5)],
        worker,
    )

    assert run.total_dispatched == 3
    assert run.total_skipped == 2
    assert run.waves[0].terminal_failure == "authentication_required"

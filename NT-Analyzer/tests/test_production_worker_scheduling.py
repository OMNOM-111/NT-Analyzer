from __future__ import annotations

import threading
import time

from app import production_workers, runtime_env


class _FakeQueue:
    def __init__(self, *, sweep_error: Exception | None = None) -> None:
        self.sweep_calls = 0
        self.sweep_started = threading.Event()
        self.sweep_error = sweep_error

    def class_configs(self):
        return {
            name: {**config, "enabled": True}
            for name, config in production_workers.DEFAULT_WORKER_CLASSES.items()
        }

    def sweep_stale(self, *, limit: int = 1000) -> int:
        assert limit == 100
        self.sweep_calls += 1
        self.sweep_started.set()
        if self.sweep_error:
            raise self.sweep_error
        return 0


def test_run_once_claims_without_running_stale_maintenance(monkeypatch) -> None:
    class Queue:
        def claim(self, worker_class: str, *, worker_id: str):
            assert worker_class == "maintenance"
            assert worker_id == "schedule-test"
            return None

        def sweep_stale(self, *, limit: int = 100):
            raise AssertionError("run_once must not sweep stale leases")

    monkeypatch.setattr(production_workers, "get_queue", lambda: Queue())
    assert production_workers.run_once(
        "maintenance", worker_id="schedule-test",
    ) is None


def test_idle_backoff_sequence_is_bounded_and_resets_after_work(monkeypatch) -> None:
    monkeypatch.setattr(
        production_workers.random, "uniform", lambda low, high: (low + high) / 2,
    )
    service = production_workers.WorkerService(["maintenance"], poll_ms=250)
    assert service._next_poll_delay(0) == 0.25
    assert service._next_poll_delay(1) == 0.5
    assert service._next_poll_delay(2) == 1.0
    assert service._next_poll_delay(3) == 1.9

    monkeypatch.setattr(production_workers.random, "uniform", lambda low, high: low)
    assert service._next_poll_delay(3) == 1.8
    monkeypatch.setattr(production_workers.random, "uniform", lambda low, high: high)
    assert service._next_poll_delay(3) == 1.9
    assert service._next_poll_delay(0) == 0.275


def test_default_concurrency_is_preserved_and_only_one_sweeper_starts(monkeypatch) -> None:
    queue = _FakeQueue()
    monkeypatch.setattr(production_workers, "get_queue", lambda: queue)
    monkeypatch.setattr(production_workers, "run_once", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: False)
    service = production_workers.WorkerService(
        ["interactive_ai", "chart", "telemetry", "maintenance"], poll_ms=250,
    )

    assert service.start() == 11
    assert queue.sweep_started.wait(timeout=1.0)
    assert sum(t.name.startswith("sf-interactive_ai-") for t in service.threads) == 4
    assert sum(t.name.startswith("sf-chart-") for t in service.threads) == 4
    assert sum(t.name.startswith("sf-telemetry-") for t in service.threads) == 2
    assert sum(t.name.startswith("sf-maintenance-") for t in service.threads) == 1
    assert service.sweeper_thread is not None
    assert service.sweeper_thread.name == "sf-worker-sweeper"
    assert service.stop(grace_sec=2) is True
    assert queue.sweep_calls == 1


def test_all_default_worker_slots_can_execute_in_parallel(monkeypatch) -> None:
    queue = _FakeQueue()
    lock = threading.Lock()
    release = threading.Event()
    all_started = threading.Event()
    active = {
        "interactive_ai": 0,
        "chart": 0,
        "telemetry": 0,
        "maintenance": 0,
    }

    def blocking_run_once(worker_class: str, **_kwargs):
        with lock:
            active[worker_class] += 1
            if sum(active.values()) == 11:
                all_started.set()
        release.wait(timeout=2.0)
        with lock:
            active[worker_class] -= 1
        return {"status": "succeeded"}

    monkeypatch.setattr(production_workers, "get_queue", lambda: queue)
    monkeypatch.setattr(production_workers, "run_once", blocking_run_once)
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: False)
    service = production_workers.WorkerService(
        ["interactive_ai", "chart", "telemetry", "maintenance"], poll_ms=250,
    )

    service.start()
    try:
        assert all_started.wait(timeout=2.0)
        with lock:
            assert active == {
                "interactive_ai": 4,
                "chart": 4,
                "telemetry": 2,
                "maintenance": 1,
            }
    finally:
        release.set()
        assert service.stop(grace_sec=2) is True


def test_sweeper_storage_failure_waits_for_cadence_and_shutdown_is_graceful(
    monkeypatch,
) -> None:
    queue = _FakeQueue(
        sweep_error=production_workers.StorageUnavailableError("database unavailable"),
    )
    monkeypatch.setattr(production_workers, "get_queue", lambda: queue)
    monkeypatch.setattr(production_workers, "run_once", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)
    service = production_workers.WorkerService(["maintenance"], poll_ms=250)

    service.start()
    assert queue.sweep_started.wait(timeout=1.0)
    time.sleep(0.15)
    assert queue.sweep_calls == 1
    assert service.stop(grace_sec=2) is True


def test_storage_outage_does_not_create_a_tight_worker_retry(monkeypatch) -> None:
    calls = 0
    first = threading.Event()

    def unavailable(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        first.set()
        raise production_workers.StorageUnavailableError("database unavailable")

    monkeypatch.setattr(production_workers, "run_once", unavailable)
    monkeypatch.setattr(production_workers.random, "uniform", lambda low, high: low)
    service = production_workers.WorkerService(["maintenance"], poll_ms=250)
    thread = threading.Thread(target=service._loop, args=("maintenance", 0))
    thread.start()
    assert first.wait(timeout=1.0)
    time.sleep(0.25)
    assert calls == 1
    service.stop_event.set()
    thread.join(timeout=1.0)
    assert not thread.is_alive()


def test_job_arriving_during_sustained_idle_is_picked_up_within_two_seconds(
    monkeypatch,
) -> None:
    available = threading.Event()
    sustained_wait = threading.Event()
    picked = threading.Event()
    pickup_at = []
    service = production_workers.WorkerService(["maintenance"], poll_ms=250)
    original_wait = service.stop_event.wait

    def observed_wait(delay: float) -> bool:
        if delay >= 1.8:
            sustained_wait.set()
        return original_wait(delay)

    def run_once(*_args, **_kwargs):
        if not available.is_set():
            return None
        pickup_at.append(time.perf_counter())
        picked.set()
        service.stop_event.set()
        return {"status": "succeeded"}

    monkeypatch.setattr(service.stop_event, "wait", observed_wait)
    monkeypatch.setattr(production_workers, "run_once", run_once)
    monkeypatch.setattr(production_workers.random, "uniform", lambda low, high: high)
    thread = threading.Thread(target=service._loop, args=("maintenance", 0))
    thread.start()
    assert sustained_wait.wait(timeout=3.0)
    available_at = time.perf_counter()
    available.set()
    assert picked.wait(timeout=2.0)
    thread.join(timeout=1.0)

    assert pickup_at[0] - available_at <= 2.0
    assert not thread.is_alive()


def test_graceful_shutdown_waits_for_an_inflight_job(monkeypatch) -> None:
    queue = _FakeQueue()
    started = threading.Event()
    release = threading.Event()

    def blocking_run_once(*_args, **_kwargs):
        started.set()
        release.wait(timeout=2.0)
        return {"status": "succeeded"}

    monkeypatch.setattr(production_workers, "get_queue", lambda: queue)
    monkeypatch.setattr(production_workers, "run_once", blocking_run_once)
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)
    service = production_workers.WorkerService(["maintenance"], poll_ms=250)
    service.start()
    assert started.wait(timeout=1.0)
    timer = threading.Timer(0.15, release.set)
    timer.start()
    before = time.perf_counter()
    assert service.stop(grace_sec=2) is True
    elapsed = time.perf_counter() - before
    timer.join(timeout=1.0)

    assert elapsed >= 0.1
    assert all(not thread.is_alive() for thread in service.threads)
    assert not service.sweeper_thread.is_alive()

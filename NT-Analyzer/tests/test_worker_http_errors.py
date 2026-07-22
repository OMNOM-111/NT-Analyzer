from __future__ import annotations

from http import HTTPStatus

import pytest

from app import production_workers
from app import server as server_mod


@pytest.mark.parametrize(
    ("exc", "status", "code", "retry_after", "message"),
    [
        (
            production_workers.QueueQuotaExceeded("workspace queue is full"),
            HTTPStatus.TOO_MANY_REQUESTS,
            "queue_quota_exceeded",
            "1",
            "workspace queue is full",
        ),
        (
            production_workers.QueuePayloadTooLarge("payload exceeds class limit"),
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "queue_payload_too_large",
            None,
            "payload exceeds class limit",
        ),
        (
            production_workers.QueueIdempotencyConflict("key was reused"),
            HTTPStatus.CONFLICT,
            "queue_idempotency_conflict",
            None,
            "key was reused",
        ),
        (
            production_workers.ProductionQueueError("invalid queue request"),
            HTTPStatus.BAD_REQUEST,
            "production_queue_error",
            None,
            "invalid queue request",
        ),
        (
            production_workers.StorageUnavailableError("postgres password leaked here"),
            HTTPStatus.SERVICE_UNAVAILABLE,
            "storage_unavailable",
            "5",
            "worker queue is temporarily unavailable",
        ),
        (
            production_workers.StorageError("internal storage detail"),
            HTTPStatus.SERVICE_UNAVAILABLE,
            "storage_error",
            "5",
            "worker queue is temporarily unavailable",
        ),
    ],
)
def test_worker_queue_errors_have_safe_stable_http_mapping(
    exc, status, code, retry_after, message,
) -> None:
    handler = server_mod.Handler.__new__(server_mod.Handler)
    captured = {}

    def record(actual_status, actual_message, *, headers=None, code=""):
        captured.update(
            status=actual_status,
            message=actual_message,
            headers=headers or {},
            code=code,
        )

    handler._err = record
    handler._worker_queue_err(exc)

    assert captured == {
        "status": status,
        "message": message,
        "headers": ({"Retry-After": retry_after} if retry_after else {}),
        "code": code,
    }

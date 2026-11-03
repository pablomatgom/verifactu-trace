"""The Redis publisher, with a real Redis for the tests that need one.

The `redis_client` fixture (in conftest.py) skips the test locally when there is no Redis, and
fails it in CI, like the `engine` fixture does with PostgreSQL.
"""

import uuid

import pytest
from redis import Redis

from app.events import EventPublishError, RedisEventPublisher


def test_publish_adds_the_event_to_the_stream(redis_client: Redis):
    # A stream of its own, so the test does not mix with real events or other tests.
    stream = f"test.{uuid.uuid4()}"
    try:
        RedisEventPublisher(redis_client).publish(stream, {"invoice_id": "1", "total": "10.50"})
        RedisEventPublisher(redis_client).publish(stream, {"invoice_id": "2", "total": "20.00"})

        entries = redis_client.xrange(stream)
        # A stream keeps the events in the order they arrived: what traceability needs.
        assert [fields["invoice_id"] for _, fields in entries] == ["1", "2"]
        assert entries[0][1] == {"invoice_id": "1", "total": "10.50"}
    finally:
        redis_client.delete(stream)


def test_publish_wraps_the_redis_errors():
    # Nothing listens on port 1, so the connection fails without needing a Redis.
    unreachable = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)

    with pytest.raises(EventPublishError, match="invoice.issued"):
        RedisEventPublisher(unreachable).publish("invoice.issued", {"a": "b"})

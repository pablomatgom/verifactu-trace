import logging
from functools import lru_cache
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

from app.config import redis_url

logger = logging.getLogger(__name__)

# One Redis stream per kind of event. The services that react to it (traceability and
# submission) read the stream with their own consumer group, so each one gets every event.
INVOICE_ISSUED = "invoice.issued"

# How long to wait for Redis. An unreachable Redis must not keep a request waiting: the invoice
# is already saved when the event is published.
TIMEOUT_SECONDS = 2


class EventPublishError(Exception):
    """The event could not be published, for example because Redis is down."""


class EventPublisher(Protocol):
    """Something that can publish an event. The services depend on this, not on Redis."""

    def publish(self, stream: str, fields: dict[str, str]) -> None:
        """Add an event to a stream. Raises EventPublishError if it cannot be published."""
        ...


class RedisEventPublisher:
    """Publishes the events in Redis streams (XADD), which keep the order they arrive in."""

    def __init__(self, client: Redis):
        self._client = client

    def publish(self, stream: str, fields: dict[str, str]) -> None:
        try:
            self._client.xadd(stream, fields)  # type: ignore[arg-type]
        except RedisError as error:
            # Hide the Redis exception behind our own, so the services do not depend on it.
            raise EventPublishError(f"could not publish to the stream {stream}") from error


@lru_cache
def get_redis() -> Redis:
    """The Redis client, created on first use and shared by every request.

    Creating it does not connect: the connection is opened by the first command.
    """
    return Redis.from_url(
        redis_url(),
        decode_responses=True,
        socket_connect_timeout=TIMEOUT_SECONDS,
        socket_timeout=TIMEOUT_SECONDS,
    )


def get_publisher() -> EventPublisher:
    """Dependency of the endpoints that publish events, like get_session is for the database.

    The tests replace it with a publisher that does not need Redis.
    """
    return RedisEventPublisher(get_redis())

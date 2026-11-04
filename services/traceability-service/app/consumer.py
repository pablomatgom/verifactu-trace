"""Consumer of the `invoice.issued` stream: records each invoice issued as an event of its chain.

It reads the Redis stream with a *consumer group*. The group remembers which entries were
delivered and which were acknowledged (XACK), so:

- Every entry is processed once by the group, even with several replicas of this service.
- An entry that was delivered but not acknowledged (the service crashed, the database was down)
  stays pending and is delivered again, so no event is lost on this side.
- Another service (submission) reads the same stream with its own group and gets every entry too.
"""

import logging
import socket
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from redis import Redis
from redis.exceptions import RedisError, ResponseError
from sqlalchemy.orm import Session

from app.config import redis_url
from app.services import event_service
from app.services.event_service import EventData

logger = logging.getLogger(__name__)

# The stream published by document-service when an invoice is issued.
INVOICE_ISSUED_STREAM = "invoice.issued"
# Type of the event that is recorded in the chain of the invoice.
INVOICE_ISSUED_EVENT = "INVOICE_ISSUED"
# Name of the consumer group: all the replicas of this service share it.
GROUP = "traceability-service"

# How long to wait for new entries in each read. The Redis socket timeout must be longer.
BLOCK_MILLISECONDS = 1000
SOCKET_TIMEOUT_SECONDS = 5
# How many entries to take in each read.
BATCH_SIZE = 10
# An entry delivered to another consumer and not acknowledged for this long is taken over: that
# consumer is assumed dead (a container that was replaced keeps entries pending under its name).
CLAIM_AFTER_MILLISECONDS = 30_000
# Wait after a failure (Redis or the database are down) before trying again.
RETRY_SECONDS = 2

# The fields every entry of the stream must have (see the `invoice.issued` event in the README).
REQUIRED_FIELDS = ("invoice_id", "number", "delivery_note_id", "order_id", "total", "issued_at")


class InvalidEntry(Exception):
    """An entry of the stream that cannot be turned into an event, and never will."""


def create_redis() -> Redis:
    """The client the consumer reads with. Creating it does not connect."""
    return Redis.from_url(
        redis_url(),
        decode_responses=True,
        socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
    )


def to_event(message_id: str, fields: dict[str, str]) -> EventData:
    """Turn an `invoice.issued` entry into the event of the invoice's chain.

    Raises InvalidEntry if the entry lacks a field or has a value that cannot be read.
    """
    missing = [name for name in REQUIRED_FIELDS if not fields.get(name)]
    if missing:
        raise InvalidEntry(f"entry {message_id} lacks the fields {', '.join(missing)}")
    try:
        document_id = uuid.UUID(fields["invoice_id"])
        occurred_at = datetime.fromisoformat(fields["issued_at"])
    except ValueError as error:
        raise InvalidEntry(f"entry {message_id} has a field that cannot be read: {error}") from None
    if occurred_at.tzinfo is None:
        raise InvalidEntry(f"entry {message_id} has issued_at without a time zone")
    return EventData(
        document_id=document_id,
        event_type=INVOICE_ISSUED_EVENT,
        occurred_at=occurred_at,
        # The invoice id is the document the event belongs to, so it is not repeated here.
        payload={name: fields[name] for name in REQUIRED_FIELDS if name != "invoice_id"},
        source_message_id=message_id,
    )


class InvoiceIssuedConsumer:
    """Reads the stream in a background thread and records every entry."""

    def __init__(
        self,
        client: Redis,
        session_factory: Callable[[], Session],
        stream: str = INVOICE_ISSUED_STREAM,
        group: str = GROUP,
        name: str | None = None,
        block_milliseconds: int = BLOCK_MILLISECONDS,
        claim_after_milliseconds: int = CLAIM_AFTER_MILLISECONDS,
    ):
        self._client = client
        self._session_factory = session_factory
        self._stream = stream
        self._group = group
        # Each replica needs its own name inside the group. The container's hostname is unique.
        self._name = name or socket.gethostname()
        self._block_milliseconds = block_milliseconds
        self._claim_after_milliseconds = claim_after_milliseconds
        self._group_created = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def ensure_group(self) -> None:
        """Create the consumer group if it does not exist."""
        try:
            # id="0": the group starts at the beginning of the stream, so the invoices issued
            # before this service started for the first time are recorded too.
            self._client.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
            # The group already exists (another replica, or an earlier start): nothing to do.
        self._group_created = True

    def poll(self) -> int:
        """Read and record the entries that are waiting. Returns how many it handled."""
        if not self._group_created:
            self.ensure_group()
        # In this order: first what was delivered to this consumer and never acknowledged, then
        # what another consumer left pending for too long, and only then new entries.
        entries = self._read("0") or self._claim() or self._read(">", self._block_milliseconds)
        for message_id, fields in entries:
            self._handle(message_id, fields)
        return len(entries)

    def start(self) -> None:
        """Start reading in a background thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="invoice-issued-consumer")
        self._thread.daemon = True  # it must not keep the process alive when the app stops
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread and wait for it to finish what it is doing."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._block_milliseconds / 1000 + SOCKET_TIMEOUT_SECONDS)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception:
                # A worker must survive any failure (Redis or the database down, a bug in one
                # entry): the entries stay pending and are delivered again on the next try.
                logger.exception("Reading the stream %s failed, trying again", self._stream)
                self._stop.wait(RETRY_SECONDS)

    def _read(self, start: str, block: int | None = None) -> list[tuple[str, dict[str, str]]]:
        """XREADGROUP: `>` asks for new entries, `0` for the ones pending for this consumer."""
        response = self._client.xreadgroup(
            self._group,
            self._name,
            {self._stream: start},
            count=BATCH_SIZE,
            block=block,
        )
        # The reply is [[stream, [(id, fields), ...]]], or empty if there was nothing.
        return response[0][1] if response else []  # type: ignore[index,return-value]

    def _claim(self) -> list[tuple[str, dict[str, str]]]:
        """XAUTOCLAIM: take over the entries another consumer left pending for too long."""
        reply: Any = self._client.xautoclaim(
            self._stream,
            self._group,
            self._name,
            min_idle_time=self._claim_after_milliseconds,
            start_id="0-0",
            count=BATCH_SIZE,
        )
        # The reply is [next id to continue from, [(id, fields), ...], deleted ids].
        return reply[1]

    def _handle(self, message_id: str, fields: dict[str, str] | None) -> None:
        """Record one entry and acknowledge it."""
        try:
            if fields is None:
                raise InvalidEntry(f"entry {message_id} no longer exists in the stream")
            data = to_event(message_id, fields)
        except InvalidEntry:
            # Waiting would not fix it: acknowledge it so it does not block the ones after it.
            # The log carries the reason, which is the message of the exception.
            logger.exception("Discarded an invalid entry of %s", self._stream)
            self._client.xack(self._stream, self._group, message_id)
            return

        # If recording fails (database down) it raises and the entry is not acknowledged, so it
        # stays pending and is delivered again.
        with self._session_factory() as session:
            event_service.record_event(session, data)
        # Acknowledge only after the event is committed. If the service crashes right here, the
        # entry is delivered again and `source_message_id` makes recording it a no-op.
        try:
            self._client.xack(self._stream, self._group, message_id)
        except RedisError:
            logger.warning("Entry %s was recorded but not acknowledged", message_id, exc_info=True)

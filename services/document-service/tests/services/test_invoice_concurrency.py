"""Two requests to invoice the same delivery note at the same time: only one invoice is issued.

Like the delivery note concurrency test, it needs transactions that really commit, so it opens
its own sessions on the engine and cleans up afterwards.
"""

import threading
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.exceptions import DeliveryNoteAlreadyInvoiced
from app.models import Document
from app.repositories import counter_repository
from app.services import delivery_note_service, invoice_service, order_service
from app.services.delivery_note_service import DeliveredLineData, DeliveryNoteData
from app.services.invoice_service import InvoiceData
from app.services.order_service import OrderData
from app.services.pricing import LineData


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str]]] = []

    def publish(self, stream: str, fields: dict[str, str]) -> None:
        self.events.append((stream, fields))


def test_concurrent_requests_issue_only_one_invoice(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    with Session(engine) as session:
        order = order_service.create_order(
            session,
            OrderData(
                "Acme S.L.", "B12345678", [LineData("Widget", Decimal(10), Decimal(1), Decimal(21))]
            ),
        )
        delivery_note = delivery_note_service.create_delivery_note(
            session, DeliveryNoteData(order.id, [DeliveredLineData(1, Decimal(10))])
        )
        order_id, delivery_note_id = order.id, delivery_note.id

    # As in the delivery note test, each request waits just after checking until the other has
    # checked too, to force the overlap. With the lock on the delivery note the second request
    # cannot even check until the first one has finished, so the wait times out.
    both_checked = threading.Barrier(2)
    next_number = counter_repository.next_number

    def next_number_once_both_checked(*args, **kwargs):
        try:
            both_checked.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass  # the other request is waiting for the lock: it cannot arrive
        return next_number(*args, **kwargs)

    monkeypatch.setattr(counter_repository, "next_number", next_number_once_both_checked)

    publisher = RecordingPublisher()
    results: list[str] = []

    def issue() -> None:
        with Session(engine) as session:
            try:
                invoice_service.create_invoice(session, publisher, InvoiceData(delivery_note_id))
                results.append("created")
            except DeliveryNoteAlreadyInvoiced:
                results.append("rejected")

    threads = [threading.Thread(target=issue) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results) == ["created", "rejected"]
        # Only the invoice that was issued is announced.
        assert len(publisher.events) == 1
    finally:
        # The data was really committed, so remove it, starting from the end of the chain
        # because each document points to the previous one.
        with Session(engine) as session:
            session.execute(delete(Document).where(Document.parent_id == delivery_note_id))
            session.execute(delete(Document).where(Document.id == delivery_note_id))
            session.execute(delete(Document).where(Document.id == order_id))
            session.commit()

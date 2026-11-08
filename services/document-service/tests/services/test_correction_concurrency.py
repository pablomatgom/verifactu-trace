"""Two requests to rectify the same invoice at the same time: together they cannot take back more.

Like the invoice concurrency test, it needs transactions that really commit, so it opens its own
sessions on the engine and cleans up afterwards.
"""

import threading
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.exceptions import QuantityExceeded
from app.models import Document
from app.repositories import counter_repository
from app.services import (
    correction_service,
    delivery_note_service,
    invoice_service,
    order_service,
)
from app.services.correction_service import CorrectedLineData, CorrectionData
from app.services.delivery_note_service import DeliveredLineData, DeliveryNoteData
from app.services.invoice_service import InvoiceData
from app.services.order_service import OrderData
from app.services.pricing import LineData


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str]]] = []

    def publish(self, stream: str, fields: dict[str, str]) -> None:
        self.events.append((stream, fields))


def test_concurrent_corrections_cannot_take_back_more_than_the_invoice_billed(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    publisher = RecordingPublisher()
    with Session(engine) as session:
        order = order_service.create_order(
            session,
            OrderData(
                "Acme S.L.", "B12345678", [LineData("Widget", Decimal(4), Decimal(1), Decimal(21))]
            ),
        )
        delivery_note = delivery_note_service.create_delivery_note(
            session, DeliveryNoteData(order.id, [DeliveredLineData(1, Decimal(4))])
        )
        invoice = invoice_service.create_invoice(session, publisher, InvoiceData(delivery_note.id))
        order_id, delivery_note_id, invoice_id = order.id, delivery_note.id, invoice.id
    publisher.events.clear()

    # Each request waits just after checking until the other has checked too, to force the
    # overlap. With the lock on the invoice the second request cannot even check until the first
    # one has finished, so the wait times out.
    both_checked = threading.Barrier(2)
    next_number = counter_repository.next_number

    def next_number_once_both_checked(*args, **kwargs):
        try:
            both_checked.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass  # the other request is waiting for the lock: it cannot arrive
        return next_number(*args, **kwargs)

    monkeypatch.setattr(counter_repository, "next_number", next_number_once_both_checked)

    results: list[str] = []

    def rectify() -> None:
        with Session(engine) as session:
            try:
                # 3 of the 4 units each: any one of them is fine, both together are not.
                correction_service.create_correction(
                    session,
                    publisher,
                    CorrectionData(invoice_id, "Returned", [CorrectedLineData(1, Decimal(3))]),
                )
                results.append("created")
            except QuantityExceeded:
                results.append("rejected")

    threads = [threading.Thread(target=rectify) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results) == ["created", "rejected"]
        # Only the corrective invoice that was issued is announced.
        assert len(publisher.events) == 1
    finally:
        # The data was really committed, so remove it, starting from the end of the chain
        # because each document points to the previous one.
        with Session(engine) as session:
            session.execute(delete(Document).where(Document.parent_id == invoice_id))
            session.execute(delete(Document).where(Document.id == invoice_id))
            session.execute(delete(Document).where(Document.id == delivery_note_id))
            session.execute(delete(Document).where(Document.id == order_id))
            session.commit()

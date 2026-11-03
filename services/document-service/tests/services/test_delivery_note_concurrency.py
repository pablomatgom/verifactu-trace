"""Two delivery notes of the same order at the same time cannot deliver more than was ordered.

This test needs real transactions that really commit, so it does not use the `session` fixture
(which rolls everything back): it opens its own sessions on the engine and cleans up afterwards.
"""

import threading
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.exceptions import QuantityExceeded
from app.models import Document
from app.repositories import counter_repository
from app.services import delivery_note_service, order_service
from app.services.delivery_note_service import DeliveredLineData, DeliveryNoteData
from app.services.order_service import OrderData
from app.services.pricing import LineData


def test_concurrent_delivery_notes_cannot_exceed_the_order(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    with Session(engine) as session:
        order = order_service.create_order(
            session,
            OrderData(
                "Acme S.L.", "B12345678", [LineData("Widget", Decimal(10), Decimal(1), Decimal(21))]
            ),
        )
        order_id = order.id

    # Two threads running at once can happen to run one after the other, which would prove
    # nothing. To force the overlap, each request waits just after checking the quantities until
    # the other has checked too. With the lock on the order, the second request cannot even
    # check until the first has finished, so the wait times out and the first one carries on.
    # Without the lock both pass the check, meet at the barrier, and both would be created.
    both_checked = threading.Barrier(2)
    next_number = counter_repository.next_number

    def next_number_once_both_checked(*args, **kwargs):
        try:
            both_checked.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass  # the other request is waiting for the lock: it cannot arrive
        return next_number(*args, **kwargs)

    monkeypatch.setattr(counter_repository, "next_number", next_number_once_both_checked)

    # Both requests ask for 6 of the 10 ordered units: one of them has to be rejected.
    results: list[str] = []

    def deliver() -> None:
        data = DeliveryNoteData(order_id, [DeliveredLineData(order_line=1, quantity=Decimal(6))])
        with Session(engine) as session:
            try:
                delivery_note_service.create_delivery_note(session, data)
                results.append("created")
            except QuantityExceeded:
                results.append("rejected")

    threads = [threading.Thread(target=deliver) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results) == ["created", "rejected"]
    finally:
        # The data was really committed, so remove it. The delivery notes go first because
        # they point to the order; their lines go with them (ON DELETE CASCADE).
        with Session(engine) as session:
            session.execute(delete(Document).where(Document.parent_id == order_id))
            session.execute(delete(Document).where(Document.id == order_id))
            session.commit()

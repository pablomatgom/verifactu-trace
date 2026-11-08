"""A cancellation and a request that builds on the same document, at the same time.

Like the other concurrency tests, it needs transactions that really commit, so it opens its own
sessions on the engine and cleans up afterwards.
"""

import threading
import time
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.exceptions import ReferenceCancelled
from app.models import Document, DocumentStatus
from app.repositories import document_repository
from app.services import delivery_note_service, order_service
from app.services.delivery_note_service import DeliveredLineData, DeliveryNoteData
from app.services.order_service import OrderData
from app.services.pricing import LineData


@pytest.fixture
def order_id(engine: Engine):
    """An order that is really saved, removed with whatever hangs from it at the end."""
    with Session(engine) as session:
        order = order_service.create_order(
            session,
            OrderData(
                "Acme S.L.", "B12345678", [LineData("Widget", Decimal(10), Decimal(1), Decimal(21))]
            ),
        )
        saved_id = order.id
    yield saved_id
    with Session(engine) as session:
        session.execute(delete(Document).where(Document.parent_id == saved_id))
        session.execute(delete(Document).where(Document.id == saved_id))
        session.commit()


def test_a_document_being_cancelled_is_locked_for_the_other_request(engine: Engine, order_id):
    first = Session(engine)
    second = Session(engine)
    try:
        # The first request has read the order and not finished. The second must wait for it,
        # not read the old state: the timeout turns that wait into a quick failure of the test
        # instead of a test that hangs.
        assert document_repository.lock(first, order_id) is not None
        second.execute(text("SET LOCAL lock_timeout = '1s'"))

        with pytest.raises(OperationalError, match="lock"):
            document_repository.lock(second, order_id)
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_a_delivery_note_requested_while_the_order_is_being_cancelled_is_refused(
    engine: Engine, order_id
):
    outcome: dict[str, BaseException | None] = {}

    def deliver() -> None:
        try:
            with Session(engine) as session:
                delivery_note_service.create_delivery_note(
                    session, DeliveryNoteData(order_id, [DeliveredLineData(1, Decimal(5))])
                )
            outcome["error"] = None
        except BaseException as error:  # noqa: BLE001 - the test inspects whatever happened
            outcome["error"] = error

    with Session(engine) as canceller:
        # The cancellation has the order locked and has not committed yet.
        order = document_repository.lock(canceller, order_id)
        assert order is not None
        thread = threading.Thread(target=deliver)
        thread.start()
        # Give the delivery note request time to reach the lock and wait for it. Without the
        # lock it would not wait: it would see the order as ISSUED and create the delivery note.
        time.sleep(0.5)
        order.status = DocumentStatus.CANCELLED
        canceller.commit()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert isinstance(outcome["error"], ReferenceCancelled)

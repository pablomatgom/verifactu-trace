from decimal import Decimal

from redis import Redis
from sqlalchemy.orm import Session

from app.events import INVOICE_ISSUED, RedisEventPublisher
from app.services import delivery_note_service, invoice_service, order_service
from app.services.delivery_note_service import DeliveredLineData, DeliveryNoteData
from app.services.invoice_service import InvoiceData
from app.services.order_service import OrderData
from app.services.pricing import LineData


def test_issuing_an_invoice_publishes_the_event_in_the_redis_stream(
    session: Session, redis_client: Redis
):
    order = order_service.create_order(
        session,
        OrderData(
            "Acme S.L.", "B12345678", [LineData("Widget", Decimal(5), Decimal(2), Decimal(21))]
        ),
    )
    delivery_note = delivery_note_service.create_delivery_note(
        session, DeliveryNoteData(order.id, [DeliveredLineData(1, Decimal(5))])
    )

    invoice = invoice_service.create_invoice(
        session, RedisEventPublisher(redis_client), InvoiceData(delivery_note.id)
    )

    # The last entry of the stream is the one just published.
    [(entry_id, fields)] = redis_client.xrevrange(INVOICE_ISSUED, count=1)
    try:
        assert fields["invoice_id"] == str(invoice.id)
        assert fields["number"] == invoice.number
        assert fields["delivery_note_id"] == str(delivery_note.id)
        assert fields["order_id"] == str(order.id)
        assert fields["total"] == "12.10"
    finally:
        # The test rolls back the database, so it must not leave the event of a non-existing
        # invoice in the stream where the real services read.
        redis_client.xdel(INVOICE_ISSUED, entry_id)

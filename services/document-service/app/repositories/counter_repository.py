from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import DocumentCounter


def next_number(session: Session, series: str, year: int) -> int:
    """Return the next correlative number of a series and year.

    A single statement does both cases: the first number of a series inserts its counter row,
    and the following ones increment it. Updating the row locks it until the transaction ends,
    so two concurrent requests get different numbers, and a rollback gives the number back
    (no gaps). The caller must therefore keep this inside the transaction that saves the
    document.
    """
    statement = (
        insert(DocumentCounter)
        .values(series=series, year=year, last_number=1)
        .on_conflict_do_update(
            index_elements=[DocumentCounter.series, DocumentCounter.year],
            set_={"last_number": DocumentCounter.last_number + 1},
        )
        .returning(DocumentCounter.last_number)
    )
    return session.execute(statement).scalar_one()

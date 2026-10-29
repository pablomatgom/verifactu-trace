from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DocumentCounter(Base):
    """Last number issued for each series and year.

    The numbering is correlative: the counter is incremented inside the transaction that
    creates the document, so a rollback gives the number back and leaves no gap.
    """

    __tablename__ = "document_counters"

    series: Mapped[str] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(primary_key=True)
    last_number: Mapped[int]

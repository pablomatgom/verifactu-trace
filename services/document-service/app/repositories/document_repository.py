from sqlalchemy.orm import Session

from app.models import Document


def add(session: Session, document: Document) -> Document:
    """Stage a document (and its lines) and send it to the database without committing.

    flush() runs the INSERTs inside the current transaction, so constraint errors show up here
    and the generated values are available. Committing is up to the service.
    """
    session.add(document)
    session.flush()
    return document

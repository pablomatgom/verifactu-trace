import uuid

from sqlalchemy.orm import Session

from app.exceptions import DocumentNotFound
from app.models import Document
from app.repositories import document_repository


def get_document(session: Session, document_id: uuid.UUID) -> Document:
    """Return the order, delivery note or invoice with that id, or raise DocumentNotFound."""
    document = document_repository.get(session, document_id)
    if document is None:
        raise DocumentNotFound(f"document {document_id} does not exist")
    return document

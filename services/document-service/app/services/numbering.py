from app.models import DocumentType

# The series of each document type: a rule of the numbering, so it lives next to the format.
SERIES = {
    DocumentType.ORDER: "P",
}


def format_number(series: str, year: int, number: int) -> str:
    """Build the document number, such as P-2026-000001 (series, year, six-digit counter)."""
    return f"{series}-{year}-{number:06d}"

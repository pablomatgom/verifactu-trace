from app.models import DocumentType
from app.services.numbering import SERIES, format_number


def test_every_document_type_has_a_series():
    assert set(SERIES) == set(DocumentType)
    assert SERIES[DocumentType.ORDER] == "P"


def test_number_has_series_year_and_six_digits():
    assert format_number("P", 2026, 1) == "P-2026-000001"


def test_number_is_padded_but_never_truncated():
    assert format_number("P", 2026, 123456) == "P-2026-123456"
    assert format_number("P", 2026, 1234567) == "P-2026-1234567"

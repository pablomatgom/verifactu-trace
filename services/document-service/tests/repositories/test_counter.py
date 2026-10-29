from sqlalchemy.orm import Session

from app.repositories.counter_repository import next_number

# These tests use series "T" and "U", which the application never issues, so documents already
# saved in the database do not interfere.


def test_numbers_are_correlative(session: Session):
    assert [next_number(session, "T", 2026) for _ in range(3)] == [1, 2, 3]


def test_each_series_and_year_has_its_own_counter(session: Session):
    assert next_number(session, "T", 2026) == 1
    assert next_number(session, "T", 2026) == 2

    assert next_number(session, "U", 2026) == 1  # another series
    assert next_number(session, "T", 2027) == 1  # another year
    assert next_number(session, "T", 2026) == 3  # the first counter was not affected


def test_a_rollback_gives_the_number_back(session: Session):
    assert next_number(session, "T", 2026) == 1

    # A failed document is rolled back together with its number, so the next one reuses it.
    attempt = session.begin_nested()
    assert next_number(session, "T", 2026) == 2
    attempt.rollback()

    assert next_number(session, "T", 2026) == 2

import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

from app.services.hashing import GENESIS_HASH, canonical_content, compute_hash

DOCUMENT_ID = uuid.UUID("5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52")
OCCURRED_AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def content(**changes) -> str:
    values = {
        "document_id": DOCUMENT_ID,
        "sequence": 1,
        "event_type": "INVOICE_ISSUED",
        "occurred_at": OCCURRED_AT,
        "payload": {"number": "F-2026-000001", "total": "380.82"},
    }
    return canonical_content(**{**values, **changes})


def test_the_initial_hash_is_64_zeros():
    assert GENESIS_HASH == "0" * 64


def test_the_hash_is_sha256_in_hexadecimal():
    assert re.fullmatch(r"[0-9a-f]{64}", compute_hash(content(), GENESIS_HASH))


def test_the_hash_is_the_sha256_of_the_content_followed_by_the_previous_hash():
    # SHA-256 of "abc" is the reference value of the standard (FIPS 180-2).
    assert (
        compute_hash("abc", "")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert compute_hash("ab", "c") == compute_hash("abc", "")


def test_the_hash_of_an_event_does_not_change_between_versions():
    # Fixed on purpose: if the way the content is written ever changes, the hashes already
    # stored would no longer verify, and this test fails before that reaches anyone.
    assert (
        compute_hash(content(), GENESIS_HASH)
        == "0741fde33e4ee2990368a1ba86008a3ac66769e9e978b077905a9605369a4225"
    )


def test_the_same_event_always_gives_the_same_hash():
    first = compute_hash(content(), GENESIS_HASH)
    second = compute_hash(content(), GENESIS_HASH)

    assert first == second


def test_the_order_of_the_payload_keys_does_not_matter():
    first = content(payload={"a": 1, "b": 2})
    second = content(payload={"b": 2, "a": 1})

    assert first == second


def test_the_time_zone_does_not_matter_only_the_instant():
    madrid = timezone(timedelta(hours=2))

    assert content(occurred_at=OCCURRED_AT.astimezone(madrid)) == content()


def test_the_content_is_compact_json_with_sorted_keys():
    assert content(payload={}) == (
        '{"document_id":"5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52","event_type":"INVOICE_ISSUED",'
        '"occurred_at":"2026-10-14T09:30:00+00:00","payload":{},"sequence":1}'
    )


def test_changing_any_part_of_the_event_changes_the_hash():
    original = compute_hash(content(), GENESIS_HASH)

    changed = [
        content(sequence=2),
        content(event_type="INVOICE_CANCELLED"),
        content(occurred_at=OCCURRED_AT + timedelta(microseconds=1)),
        content(payload={"number": "F-2026-000001", "total": "380.83"}),
        content(document_id=uuid.uuid4()),
    ]

    assert all(compute_hash(other, GENESIS_HASH) != original for other in changed)


def test_the_previous_hash_is_part_of_the_hash():
    # This is what chains the events: with another previous hash the same event hashes differently.
    assert compute_hash(content(), GENESIS_HASH) != compute_hash(content(), "1" * 64)

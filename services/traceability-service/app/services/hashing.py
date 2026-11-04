"""The hash that chains the events of a document.

`hash = SHA-256(canonical content + previous hash)`. The canonical content is a JSON text that is
always written the same way for the same event, so recomputing it later (to verify the chain)
gives the same bytes.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

# `previous_hash` of the first event of a document, which has no previous event.
GENESIS_HASH = "0" * 64


def canonical_content(
    document_id: uuid.UUID,
    sequence: int,
    event_type: str,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> str:
    """The content of an event as a JSON text that does not depend on how it was written.

    Keys are sorted and there are no spaces, so the same event always gives the same text, and
    the date is always written in UTC, whatever time zone the database returns it in.
    """
    content = {
        "document_id": str(document_id),
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "payload": payload,
    }
    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(content: str, previous_hash: str) -> str:
    """SHA-256, as 64 hexadecimal characters, of the content followed by the previous hash."""
    return hashlib.sha256((content + previous_hash).encode("utf-8")).hexdigest()

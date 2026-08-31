"""PII masking, applied at silver — **before anything reaches the retrieval index**.

The support feed carries names, emails and phone numbers in four columns and inside
free text. Masking at silver rather than at query time is the difference between a
sensitive string never entering the vector of documents an LLM can see and a policy
that depends on every downstream caller remembering to redact.

The masks are deterministic per value, so a ticket that mentions the same customer
twice yields the same token twice and the corpus stays internally consistent — but
the token is a keyed digest, not a reversible encoding.
"""

from __future__ import annotations

import re
from hashlib import blake2b

import pandas as pd

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+91[- ]?)?[6-9]\d{9}\b|\b\d{3}-\d{4}-\d{4}\b")
ORDER_REF = re.compile(r"\bORD-\d{6,}\b")

TOKEN_CHARS = 8
"""Enough digest to keep two different customers distinct in a 36-month corpus, short
enough that a masked ticket body is still readable."""


def token(value: str, kind: str) -> str:
    """A stable, non-reversible surrogate for one sensitive value."""
    digest = blake2b(f"{kind}:{value}".encode(), digest_size=8).hexdigest()[:TOKEN_CHARS]
    return f"<{kind.upper()}:{digest}>"


def mask_value(value: object, kind: str) -> object:
    """Mask a whole field value — a name, an email address, a phone number."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    text = str(value)
    return token(text, kind) if text else text


def mask_text(value: object) -> object:
    """Mask identifiers *inside* free text, leaving the rest of the sentence intact.

    Order references are preserved: they are not personal data and the evidence layer
    needs them to link a ticket to an order.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    text = str(value)
    text = EMAIL.sub(lambda match: token(match.group(0), "email"), text)
    text = PHONE.sub(lambda match: token(match.group(0), "phone"), text)
    return text


def mask_column(values: pd.Series, column: str) -> pd.Series:
    """Mask one declared-PII column, choosing the rule from its name.

    Name-shaped and contact-shaped columns are replaced wholesale; anything else is
    treated as free text and scanned. Replacing a free-text body wholesale would
    destroy the evidence the retrieval layer exists to find.
    """
    lowered = column.lower()
    if lowered.endswith(("_name", "_email", "_phone")):
        kind = lowered.rsplit("_", 1)[-1]
        return values.map(lambda value: mask_value(value, kind))
    return values.map(mask_text)

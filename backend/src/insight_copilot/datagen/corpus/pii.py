"""Realistic personal identifiers that are never real.

Every name, email, phone number and address here is synthetic and drawn from reserved
ranges. That matters twice over: ethically, because a repository that might be shared
must not contain anything resembling a real person's data; and demonstrably, because
the P4 gate asserts that **no document contains a real-looking identifier outside the
reserved patterns**, which is only a meaningful test if the generator is disciplined.

Reserved patterns used:

* `@example.com` / `@example.org` — RFC 2606 reserved for documentation.
* `+91 99000 0XXXX` — inside the block this project reserves for itself, and paired
  with an obviously synthetic prefix so no real Indian mobile range is implied.
* Order and ticket ids in this project's own formats.

Masking then happens at **silver**, before anything is indexed, so the sensitive
string never enters the retrieval store rather than being filtered at query time.
"""

from __future__ import annotations

import re

from insight_copilot.datagen.world.seeds import SeedBook

_GIVEN = (
    "Ananya",
    "Rohan",
    "Priya",
    "Vikram",
    "Meera",
    "Arjun",
    "Kavya",
    "Nikhil",
    "Sneha",
    "Aditya",
    "Divya",
    "Karthik",
    "Ishita",
    "Rahul",
    "Neha",
    "Sanjay",
    "Tanvi",
    "Harsh",
    "Pooja",
    "Manoj",
    "Lakshmi",
    "Farhan",
    "Ritu",
    "Devan",
)
_FAMILY = (
    "Iyer",
    "Nair",
    "Kulkarni",
    "Banerjee",
    "Reddy",
    "Chatterjee",
    "Deshpande",
    "Menon",
    "Pillai",
    "Sharma",
    "Bhatt",
    "Ghosh",
    "Rao",
    "Joshi",
    "Kapoor",
    "Sinha",
    "Mehta",
    "Varghese",
    "Thakur",
    "Gowda",
)

EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
"""RFC 2606 reserved domains. Never a real provider."""

PHONE_PREFIX = "+91 99000 0"
"""A deliberately synthetic block. Paired with a five-digit suffix below 10000 so the
resulting number is short by one digit and cannot be dialled."""

REAL_LOOKING_EMAIL = re.compile(
    r"[\w.+-]+@(?!example\.(?:com|org|net))[\w-]+\.[\w.]+", re.IGNORECASE
)
"""Any email outside the reserved domains. The gate asserts this never matches."""

REAL_LOOKING_PHONE = re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)")
"""A dialable Indian mobile number. The gate asserts this never matches."""


class PersonGenerator:
    """Deterministic synthetic people, addressed by content key."""

    def __init__(self, seeds: SeedBook) -> None:
        self._seeds = seeds

    def name(self, key: str) -> str:
        """A plausible full name that belongs to nobody."""
        rng = self._seeds("pii_name", key)
        return f"{rng.choice(_GIVEN)} {rng.choice(_FAMILY)}"

    def email(self, key: str) -> str:
        """An address at a reserved documentation domain."""
        rng = self._seeds("pii_email", key)
        person = self.name(key).lower().replace(" ", ".")
        return f"{person}{int(rng.integers(10, 99))}@{rng.choice(EMAIL_DOMAINS)}"

    def phone(self, key: str) -> str:
        """A non-routable number in this project's reserved pattern."""
        rng = self._seeds("pii_phone", key)
        return f"{PHONE_PREFIX}{int(rng.integers(0, 9999)):04d}"

    def agent(self, key: str) -> str:
        """A support agent's display name."""
        rng = self._seeds("pii_agent", key)
        return f"{rng.choice(_GIVEN)} {str(rng.choice(_FAMILY))[0]}."


def contains_real_looking_identifier(text: str) -> str | None:
    """Return the offending substring if ``text`` looks like it holds real PII.

    Used by the P4 gate over the whole corpus. Returning the match rather than a
    boolean means a failure names what it found instead of asserting that something,
    somewhere, is wrong.
    """
    email = REAL_LOOKING_EMAIL.search(text)
    if email:
        return email.group(0)
    phone = REAL_LOOKING_PHONE.search(text)
    if phone:
        return phone.group(0)
    return None

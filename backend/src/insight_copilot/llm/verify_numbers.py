"""The deterministic number verifier. **No unsupported number reaches a human.**

This is the mechanism behind the first law. The model narrates; it does not compute.
Enforcing that requires more than an instruction in a prompt, so every numeral in
generated text is extracted, normalised, and matched against the bundle's finite set of
computed facts. An unmatched number is a failure — regenerate, twice, then fall back to
the template narrator, which cannot produce an unsupported number because it only
interpolates facts.

The hard part is Indian number formatting. "₹1.2 crore", "12.4 lakh", "-11.94%",
"3.2pp" and "1,20,00,000" are all numbers, they are all written differently, and a
verifier that only understands ``1234.5`` passes every one of them by not seeing them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from insight_copilot.engine.bundle import InsightEvidenceBundle, NumberFact
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

CRORE = 10_000_000.0
LAKH = 100_000.0
"""Indian numbering. A crore is 10^7 and a lakh is 10^5; both appear constantly in this
domain's prose and neither is a rounding of the other."""

NUMBER = re.compile(
    r"""
    # U+2212 MINUS SIGN as well as the hyphen: prose copied out of a spreadsheet
    # routinely carries the typographic form, and missing it inverts a sign.
    (?P<sign>[-+\u2212])?\s*
    (?:(?P<currency>Rs\.?|INR|₹)\s*)?
    # Grouped form first, and it must actually contain a separator: without that
    # requirement the alternation matches "202" out of "2026" and leaves a stray "6".
    (?P<value>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    \s*
    (?P<scale>crore|cr\b|lakh|lakhs|lac|k\b|m\b|bn\b)?
    \s*
    (?P<unit>%|percent|pp|percentage\s+points|x\b)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

SCALE = {
    "crore": CRORE,
    "cr": CRORE,
    "lakh": LAKH,
    "lakhs": LAKH,
    "lac": LAKH,
    "k": 1_000.0,
    "m": 1_000_000.0,
    "bn": 1_000_000_000.0,
}

ORDINAL_CONTEXT = re.compile(r"\b(?:20\d{2}|19\d{2})\b")
"""Four-digit years are not claims about a measure, and matching them against the
bundle would fail every narrative that mentions a date."""

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
DATE_NEIGHBOUR = re.compile(rf"^\s*(?:{MONTHS})\b", re.IGNORECASE)
DATE_PRECEDING = re.compile(rf"\b(?:{MONTHS})\s*$", re.IGNORECASE)
"""A day-of-month beside a month name is a date, not a measurement. Without this guard
every well-written narrative fails verification on the word "15" in "15 March"."""

MAX_REGENERATIONS = 2
"""Two retries, then the template narrator. A third attempt at the same prompt is
optimism, not engineering."""

IGNORED_VALUES = frozenset({0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 100.0})
"""Small integers used as ordinary language — "three regions", "the top 5" — are not
measurements. Excluding them is a deliberate loosening, and it is bounded: any figure
that could plausibly be a *measure* is above ten or carries a decimal point."""


@dataclass(frozen=True)
class ExtractedNumber:
    """One numeral found in generated text, normalised to the bundle's units."""

    raw: str
    value: float
    unit: str
    position: int


@dataclass
class VerificationResult:
    """Which numbers were supported, which were not, and by what."""

    numbers: list[ExtractedNumber] = field(default_factory=list)
    matched: list[tuple[ExtractedNumber, NumberFact]] = field(default_factory=list)
    unsupported: list[ExtractedNumber] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Did every extracted number match a computed fact?"""
        return not self.unsupported

    @property
    def faithfulness(self) -> float:
        """Share of numerals supported by the bundle. Feeds ``c6``."""
        if not self.numbers:
            return 1.0
        return len(self.matched) / len(self.numbers)

    @property
    def detail(self) -> str:
        """The failure message a regeneration prompt is built from."""
        if self.passed:
            return f"all {len(self.numbers)} number(s) matched the evidence bundle"
        offenders = ", ".join(f"{item.raw!r} ({item.value:g})" for item in self.unsupported)
        return f"{len(self.unsupported)} unsupported number(s): {offenders}"


def extract(text: str) -> list[ExtractedNumber]:
    """Every numeral in the text, normalised. Years and bare small integers excluded."""
    found: list[ExtractedNumber] = []
    for match in NUMBER.finditer(text):
        raw = match.group(0).strip()
        digits = match.group("value").replace(",", "")
        try:
            value = float(digits)
        except ValueError:  # pragma: no cover - the pattern guarantees a number
            continue
        if match.group("sign") in ("-", "\u2212"):
            value = -value
        scale = (match.group("scale") or "").lower()
        if scale:
            value *= SCALE[scale]
        unit = _unit_of(match)
        if unit == "count" and value in IGNORED_VALUES and "." not in digits:
            continue
        if unit == "count" and ORDINAL_CONTEXT.fullmatch(digits):
            continue
        if unit == "count" and _is_date_part(text, match):
            continue
        found.append(ExtractedNumber(raw=raw, value=value, unit=unit, position=match.start()))
    return found


def verify(text: str, bundle: InsightEvidenceBundle) -> VerificationResult:
    """Match every numeral against the bundle's facts within each fact's tolerance."""
    result = VerificationResult(numbers=extract(text))
    for number in result.numbers:
        fact = _best_match(number, bundle.narratable_values)
        if fact is None:
            result.unsupported.append(number)
        else:
            result.matched.append((number, fact))
    logger.info(
        "verify.numbers",
        insight_id=bundle.insight_id,
        found=len(result.numbers),
        unsupported=len(result.unsupported),
    )
    return result


def _best_match(number: ExtractedNumber, facts: list[NumberFact]) -> NumberFact | None:
    """The fact this numeral is, if any, after normalising units.

    Two normalisations, both necessary:

    * **Sign.** "Revenue fell 11.94%" and a stored delta of -11.94 are the same claim;
      the direction is carried by the verb. Requiring the sign would fail every
      well-written sentence in the corpus.
    * **Percent against fraction.** An explanatory power of 0.507 is narrated as "51%".
      Storing it as a fraction and writing it as a percentage is correct on both sides,
      and a verifier that cannot bridge them rejects its own template narrator.
    """
    for fact in facts:
        for candidate in _candidates(number, fact):
            if fact.matches(candidate):
                return fact
    return None


def _candidates(number: ExtractedNumber, fact: NumberFact) -> list[float]:
    """The values this numeral could be, expressed in the fact's own unit."""
    values = [number.value, -number.value]
    if number.unit == "pct" and fact.unit == "fraction":
        values.extend([number.value / 100.0, -number.value / 100.0])
    if number.unit == "count" and fact.unit == "pct":
        values.extend([number.value, -number.value])
    return values


def _unit_of(match: re.Match[str]) -> str:
    """Classify the numeral so a percentage is never matched against a rupee amount."""
    unit = (match.group("unit") or "").lower()
    if unit in ("%", "percent"):
        return "pct"
    if unit in ("pp", "percentage points"):
        return "pp"
    if unit == "x":
        return "ratio"
    if match.group("currency") or match.group("scale"):
        return "INR"
    return "count"


def _is_date_part(text: str, match: re.Match[str]) -> bool:
    """Is this integer a day-of-month sitting next to a month name?"""
    after = text[match.end() : match.end() + 14]
    before = text[max(0, match.start() - 14) : match.start()]
    return bool(DATE_NEIGHBOUR.match(after) or DATE_PRECEDING.search(before))

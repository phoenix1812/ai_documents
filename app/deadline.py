"""Deadlines read out of the document text.

Measured over the archive on 2026-11-03, 96 documents: the patterns find 14 date
wordings, and not one of them survives. Eleven are already expired, one is a
life insurance running to 2055, and the two on paperless 110 are different dates
in the same document. Those are exactly the three cases the gates and the refusal
rule below are built for, so the field stays empty instead of carrying a date he
cannot act on or one that was picked out of two.

The pattern classes are narrow on purpose. A date printed anywhere near the word
"bis" is often a period ("Lieferzeit bis zu 3 Wochen"), a reference or a second
deadline, so only wordings that name a due date are read. Where several dates
survive, the answer is refused: the same contract his archive shows carries both
"Vertragsablauf 01.12.2027" and "Aenderungsbeginn 01.12.2026", and picking one
would be a guess.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

DEADLINE_FIELD_NAME = "Frist"
DEADLINE_FIELD_TYPE = "date"

# A deadline further out than this is not something he has to act on, and the
# measured false positive sat 29 years ahead.
DEADLINE_MAX_YEARS_AHEAD = 2

# Longest alternative first: with \d{2} in front, "01.12.2027" would be read as
# day 1, month 12, year 20.
_DATE = (
    r"(?<![\d.])(?P<day>\d{1,2})\.\s*(?P<month>\d{1,2})\.\s*"
    r"(?P<year>\d{4}|\d{2})(?!\d)"
)

# A payment date is a real deadline: something has to happen by then. The
# umlauts carry their two letter spelling as an alternative because senders
# write "faellig" when their own tooling cannot produce an umlaut.
PAYMENT_DEADLINES: tuple[tuple[str, str], ...] = (
    ("zahlbar bis", rf"zahlbar\s+bis\s+(?:zum\s+|zur\s+)?{_DATE}"),
    ("fällig am", rf"f(?:ä|ae)llig\s+(?:am|zum|bis(?:\s+zum)?)\s+{_DATE}"),
    ("Zahlungsziel", rf"zahlungsziel\s*:?\s*{_DATE}"),
    ("Zahlung bis", rf"zahlung\s+bis\s+(?:zum\s+)?{_DATE}"),
    (
        "Rechtsmittelfrist",
        rf"(?:widerspruchs|einspruchs|rechtsmittel|k(?:ü|ue)ndigungs)frist"
        rf"(?:\s*(?:bis|zum|:))*\s*{_DATE}",
    ),
)

# A contract date only tells him when something changes. It is read when the
# document carries no payment deadline, never instead of one.
CONTRACT_DATES: tuple[tuple[str, str], ...] = (
    ("Vertragsablauf", rf"vertragsablauf\s*:?\s*{_DATE}"),
    ("Vertrag endet am", rf"vertrag\s+endet\s+am\s+{_DATE}"),
    ("läuft aus am", rf"l(?:ä|ae)uft\s+aus\s+am\s+{_DATE}"),
    ("gültig bis", rf"g(?:ü|ue)ltig\s+bis\s+(?:zum\s+)?{_DATE}"),
    ("Änderungsbeginn", rf"(?:ä|ae)nderungsbeginn\s*:?\s*{_DATE}"),
)

def _compile(classes: tuple[tuple[str, str], ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((label, re.compile(pattern, re.IGNORECASE)) for label, pattern in classes)


# Ordered: a payment deadline outranks a contract date.
_COMPILED_GROUPS = (_compile(PAYMENT_DEADLINES), _compile(CONTRACT_DATES))


@dataclass(frozen=True)
class Deadline:
    """One recognised deadline, with the wording it was read from."""

    date: str
    label: str
    evidence: str


def _parsed_date(match: re.Match[str]) -> date | None:
    year = int(match.group("year"))
    if year < 100:
        # A two digit year in a document he is filing now is never a past one.
        year += 2000 if year <= 50 else 1900

    try:
        return date(year, int(match.group("month")), int(match.group("day")))
    except ValueError:
        # 31.02. and friends are OCR damage, not metadata.
        return None


def _horizon(today: date) -> date:
    try:
        return today.replace(year=today.year + DEADLINE_MAX_YEARS_AHEAD)
    except ValueError:
        # 29 February has no counterpart two years later.
        return today.replace(year=today.year + DEADLINE_MAX_YEARS_AHEAD, day=28)


def extract_deadline(content: str | None, *, today: date | None = None) -> Deadline | None:
    """The single deadline the text states, or None.

    None covers three different answers and all three mean "do not write":
    the document names no deadline, the only date it names is outside the gates,
    or it names several and choosing one would be a guess.
    """

    text = " ".join(unicodedata.normalize("NFC", content or "").split())
    if not text:
        return None

    reference = today or date.today()
    latest = _horizon(reference)

    for classes in _COMPILED_GROUPS:
        kept: list[tuple[date, str, str]] = []
        for label, pattern in classes:
            for match in pattern.finditer(text):
                found = _parsed_date(match)
                if found is None or not reference <= found <= latest:
                    continue
                evidence = " ".join(text[match.start() : match.end()].split())
                kept.append((found, label, evidence))

        if not kept:
            continue

        if len({hit[0] for hit in kept}) != 1:
            return None

        found, label, evidence = kept[0]
        return Deadline(date=found.isoformat(), label=label, evidence=evidence)

    return None

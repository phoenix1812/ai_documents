"""Which amount in a document answers which question.

Measured over the archive on 2026-11-04, 99 documents: 1165 lines carry a
formatted number, and 734 of them carry no word at all. The number is a table
cell and its label sits on the line above it ("Neuer Jahresbeitrag" then
"1.088,99 EUR" on paperless 118). A role can therefore never be read from the
amount line alone, it is read from a two line window.

The catalog is closed on purpose. Its job is not to name every amount, it is to
keep an answer from taking the wrong amount out of the right document. Paperless
40 is the measured case: the AXA invoice states "Die Versicherungsteuer in Hoehe
von 19% wird auf den Nettobeitrag von 77,44 EUR erhoben, dies entspricht 14,71
EUR" and, two lines further down, "Beitrag Privathaftpflichtversicherung
jaehrlich 92,15 EUR". Whoever asks what the liability insurance costs and reads
the first number in that document gets 14,71 EUR. That is the failure the role
decides, and where the window does not decide, the amount stays unlabelled and
no answer is built from it.

The second axis is the modifier: netto or brutto. The same document proves the
role is not enough on its own, because "Beitrag" is stated for the net
contribution as well as for the total. Half of the modifiers come from the
document's own wording ("Entgelt fuer Einspeisung netto" against "... brutto" on
paperless 114), the other half from the only arithmetic that holds inside a
single row: paperless 40 writes "77,44 EUR 19,00 % 14,71 EUR 92,15 EUR" on one
line, and 77,44 plus 14,71 is 92,15. Nothing is ranked to pick a winner. A
number that neither wording nor row total decides stays without a modifier.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# A currency amount is written with exactly two decimals. Without that, "9,6000
# kW" (the installed capacity on paperless 114) reads as money. A percentage is
# written the same way and is not money either: "Umsatzsteuer 19,00 %" gave an
# amount of 19,00 EUR in the first measured pass.
AMOUNT_PATTERN = re.compile(
    r"(?<![\d.,])(?P<value>\d{1,3}(?:[.\s]\d{3})*,\d{2})(?!\d)(?!\s*%)"
)

# The OCR adds and drops umlauts depending on the sender's tooling, so every
# one of them carries its two letter spelling as an alternative. A character
# class would not do: "ae" is two characters, and a needle of six would then
# need seven.
_UMLAUT = {"ä": "(?:ae|ä)", "ö": "(?:oe|ö)", "ü": "(?:ue|ü)", "ß": "(?:ss|ß)"}

# Role label -> needles. Needles of four characters or fewer are matched as
# whole words, longer ones as a piece of a compound in either direction:
# "beitrag" has to reach "Nettobeitrag", "guthaben" has to reach
# "Guthabenbetrag" and "netto" has to reach "Nettobeitrag", while "rate" must
# not reach "Formate".
ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Beitrag", ("beitrag", "prämie", "versicherungsentgelt")),
    ("Gesamtbetrag", ("gesamtbetrag", "rechnungsbetrag", "zahlbetrag", "zu zahlen", "zahlbar")),
    ("Summe", ("summe", "zwischensumme", "endbetrag")),
    ("Forderung", ("forderung", "restbetrag", "offenes saldo", "schuld")),
    ("Guthaben", ("guthaben", "erstattung", "erstattet", "rückvergütung", "ausgezahlt")),
    ("Entgelt", ("entgelt", "vergütung", "einspeisung", "arbeitspreis", "grundpreis")),
    # "vst" is how the Domcura invoice abbreviates Versicherungsteuer (its
    # "VST Brutto" line sits three rows above the total it charges).
    ("Steuer", ("steuer", "mwst", "solzi", "estg", "vst")),
    ("Abschlag", ("abschlag", "rate", "vorauskasse", "vorausleistung")),
    ("Vorauszahlung", ("vorauszahlung", "jahresvorauszahlung")),
    ("Rente", ("rente", "anwartschaft", "altersversorgung")),
    ("Gebühr", ("gebühr", "umlage", "messstellenbetrieb", "entgeltgruppe")),
    ("Saldo", ("übertrag", "vortrag", "saldo", "neuer saldo")),
)

# The modifier words. Both spellings are read from the same window the role is
# read from, and a window holding both decides neither.
MODIFIER_NEEDLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("netto", ("netto",)),
    ("brutto", ("brutto",)),
)


def _build(needle: str) -> str:
    return "".join(_UMLAUT.get(ch, re.escape(ch)) for ch in needle.lower())


def _compile(needle: str) -> re.Pattern[str]:
    pattern = rf"\b{_build(needle)}\b" if len(needle) <= 4 else _build(needle)
    return re.compile(pattern, re.IGNORECASE)


_COMPILED: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (
        label,
        tuple(_compile(needle) for needle in needles),
    )
    for label, needles in ROLES
)

_COMPILED_MODIFIER: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (label, tuple(_compile(needle) for needle in needles))
    for label, needles in MODIFIER_NEEDLES
)


@dataclass
class Amount:
    """One number the text states, with the role and modifier its window gave
    it. Not frozen: a row total is only known once every number of the row has
    been read, and that is what sets ``modifier`` afterwards."""

    line: int
    value: str
    role: str | None
    needle: str | None
    origin: str
    modifier: str | None
    modifier_origin: str
    evidence: str


def _roles_in(segment: str) -> list[tuple[str, str]]:
    """Roles present in a text, with the needle that matched. A segment holding
    two different roles decides nothing, so the caller needs the count, not the
    first hit."""

    found: list[tuple[str, str]] = []
    for label, patterns in _COMPILED:
        for pattern in patterns:
            if pattern.search(segment):
                found.append((label, pattern.pattern))
                break
    return found


def _modifier_in(window: str) -> str | None:
    """netto, brutto, or nothing. Two different words in one window is nothing
    as well: the invoice that says "Netto 936,04 EUR" and "Brutto 1.088,99 EUR"
    in the same breath does not tell which one the window belongs to."""

    found = [
        label
        for label, patterns in _COMPILED_MODIFIER
        if any(pattern.search(window) for pattern in patterns)
    ]
    return found[0] if len(found) == 1 else None


def _tail(text: str) -> str:
    """The part of a line after its last amount: that is where a label like
    "Neuer Jahresbeitrag:" stands when the number itself is the next line."""

    last_end = 0
    for match in AMOUNT_PATTERN.finditer(text):
        last_end = match.end()
    return text[last_end:] if last_end else text


def _normalize(raw_value: str) -> str:
    """One spelling for the thousands separator. The senders write 1.088,99 and
    the OCR breaks the same number with a space; the archive should not end up
    carrying both as two different amounts."""

    return re.sub(r"\s+", ".", raw_value)


def as_cents(value: str) -> int:
    """A written figure in cents. Public because the question layer adds
    figures up and must read them exactly the way a role window does."""

    whole, fraction = value.replace(".", "").replace(" ", "").split(",")
    return int(whole) * 100 + int(fraction)


def format_cents(cents: int) -> str:
    """The archive's own spelling back: 1.088,99 with a dot thousands group."""

    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    grouped = f"{whole:,}".replace(",", ".")
    return f"{sign}{grouped},{fraction:02d}"


def _row_totals(rows: list["Amount"]) -> None:
    """The one arithmetic that needs no column knowledge: a row whose numbers
    add up to one of them. Measured on paperless 40, "77,44 EUR 19,00 % 14,71
    EUR 92,15 EUR" is one line, and 77,44 plus 14,71 is 92,15, so 92,15 is the
    gross of that row. Restricted to a single line on purpose: the same sum over
    a whole document would hit coincidences, because a document holds dozens of
    numbers."""

    if len(rows) < 3:
        return

    totals: list[tuple[Amount, str]] = []
    for candidate in rows:
        parts = [
            (a, b)
            for index, a in enumerate(rows)
            for b in rows[index + 1:]
            if a is not candidate and b is not candidate
            and as_cents(a.value) + as_cents(b.value) == as_cents(candidate.value)
        ]
        if parts:
            totals.append((candidate, f"{parts[0][0].value} + {parts[0][1].value}"))

    # Only a single number of the row adds up: two of them would mean the row
    # was read wrong rather than that it holds a total.
    if len(totals) == 1:
        candidate, note = totals[0]
        if candidate.modifier is None:
            candidate.modifier = "brutto"
            candidate.modifier_origin = f"Zeilensumme {note}"


def label_amounts(content: str | None) -> list[Amount]:
    """Every amount in the text, labelled with the role and the modifier its
    window states.

    ``role`` and ``modifier`` are None whenever the window does not decide, and
    that is the common case by measure: a bare number row whose previous line is
    prose with two roles in it stays unlabelled instead of being guessed.
    """

    text = unicodedata.normalize("NFC", content or "")
    if not text.strip():
        return []

    lines = [line.strip() for line in text.split("\n")]
    amounts: list[Amount] = []

    for index, line in enumerate(lines, 1):
        matches = list(AMOUNT_PATTERN.finditer(line))
        if not matches:
            continue

        previous = next(
            (candidate for candidate in reversed(lines[:index - 1]) if candidate),
            "",
        )

        rows: list[Amount] = []
        for position, match in enumerate(matches):
            start = matches[position - 1].end() if position else 0
            segment = line[start : match.start()]
            role = _roles_in(segment)
            origin = "eigene Zeile"

            # The line above is a label only when this line holds a single
            # number and that line holds none itself. Measured on paperless 37:
            # its installment rows read "10.Maerz wie bisher 525,00 7,00
            # 532,00", and the line above the first row is the table header,
            # where "zu zahlen" sits over the wrong column. Reading it as a
            # label turned the income tax figure into a total amount.
            above: list[tuple[str, str]] = []
            if len(matches) == 1 and not AMOUNT_PATTERN.search(previous):
                above = _roles_in(_tail(previous))

            window = segment
            if len(role) != 1:
                if len(above) == 1:
                    role, origin, window = above, "Zeile darueber", _tail(previous)
                elif (
                    not role
                    and not above
                    and len(matches) >= 2
                    and position == len(matches) - 1
                ):
                    # A row of a table with no label at all. Measured on the
                    # installment rows of paperless 37 and on the contribution
                    # rows of 40 and 114: the last number of such a row is the
                    # total of the row, never one of its parts. The label stays
                    # independent on purpose (his decision on 2026-11-04): it
                    # says "the row's total", not what kind of amount it is.
                    role, origin = [("Zeilenendwert", "")], "Zeilenendwert"
                else:
                    role, origin = [], ""
                    # The role is refused but the line still states its own
                    # wording, so the modifier is read from it.

            label, needle = role[0] if role else (None, None)
            modifier = _modifier_in(window)
            rows.append(
                Amount(
                    line=index,
                    value=_normalize(match.group("value")),
                    role=label,
                    needle=needle,
                    origin=origin,
                    modifier=modifier,
                    modifier_origin="Wort" if modifier else "",
                    evidence=line,
                )
            )

        _row_totals(rows)
        amounts.extend(rows)

    return amounts

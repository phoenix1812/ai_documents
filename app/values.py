"""Values a document states in words, besides the money figures.

The evidence layer showed only lines carrying a Geldbetrag, and that is a narrow
read of what a document says. Measured over the archive on 2026-11-04 (99
documents, fulltext over the API, 5235 lines with a digit): 1105 of those lines
carry a money figure - 21 %. The rest carry the other kind of answer he asks
for: an IdNr, an Aktenzeichen, a phone number, a validity date.

Shape alone cannot tell them apart, and the attempt is on record here: a
Kennzeichen read as a shape ("one to three letters, dash, digits") hit 1460
lines in 94 documents, while the same kind read from the word the document
itself prints hit 4 lines. So a value is read only where the document names it -
the label word and the value on the same line, or the label at the end of a
line and the value on the next one, possibly over a blank line the OCR leaves
between an announced number and itself. That is the same discipline
`app/roles.py` applies to a role and `app/deadline.py` to a date.

The distance between label and value is measured, not guessed. On the 118 lines
of this archive that print "Identifikationsnummer", "IdNr" or "Steuer-Id" the
number sits where the rule reaches it on 57 of them: in the label's own line on
56, and once below the blank line the OCR leaves after an announcement
(counted 2026-11-06, with this file's rules as they now stand). The other lines
held a 5-to-9-digit figure on 22 and nothing at all on 8, counted 2026-11-04
over a wider window than the rule uses - and that is the reason a kind without
a plausible value stays empty rather than showing the short number that happens
to be nearest.

`gueltigkeit` reads dates without the horizon gate `app/deadline.py` puts on its
write path. That is deliberate: this module answers on a page, where every
stated date is shown with its label, while a CustomField may only be written
when exactly one date can still be acted on.

A value is never picked out of several. Where a document states more than one
value of a kind, every one is returned with its line and the count rides along -
the same rule the layer already applies to competing amounts, where one document
holds a gross and a net figure of the same contribution side by side.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

# Label and value on one line: anything up to 60 characters may stand between
# them ("Identifikationsnummer (Steuer-IdNr):"), and the search is not greedy, so
# the nearest plausible value wins.
_SAME_LINE = r"[^\n]{0,60}?"
# Label at the end of its line, value on the next one - a short tail after the
# label word is allowed ("Geburtsdatum der versicherten Person"), and blank or
# whitespace-only lines between them too, up to two of them. Measured
# 2026-11-06 over the 99 documents with a fulltext, with every check this file
# now carries: the blank line brings 12 value lines in 10 documents - one
# 11-digit tax number, six IBAN, five phone numbers, all of them with digits and
# none a word. That tax number is the answer a question went without: its OCR
# prints a short tail after the label, then an empty line, then the number.
# Counted before the BIC case rule the same relaxation read 22 values in 15
# documents, and the difference is BIC word readings - which is why the two
# changes are shipped together. A line carrying text is never skipped: over the
# same run, a rule that skipped those too returned the very same values, so the
# strict form costs nothing.
_NEXT_LINE = r"[^\n]{0,40}?\r?\n(?:[^\S\n]*\r?\n){0,2}[^\S\n]{0,8}"
_DATE = r"\d{1,2}\.\s?\d{1,2}\.\s?(?:\d{4}|\d{2})"
# A number-ish answer: at least five characters of digits, letters, slash or dot.
_TOKEN = r"[A-Za-z0-9][A-Za-z0-9./\-]{4,24}"

_PAIRS = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))


def _fold(text: str | None) -> str:
    """Lowercase with one spelling per umlaut - the same measured rule
    `app.evidence.fold` applies to a question. Written here because this module
    must not import the layer that imports it."""

    lowered = unicodedata.normalize("NFC", text or "").lower()
    for letter, pair in _PAIRS:
        lowered = lowered.replace(letter, pair)
    return lowered


def _digits(text: str) -> int:
    return sum(character.isdigit() for character in text)


def _compact(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text)


def _digits_at_least(minimum: int) -> Callable[[str], bool]:
    def check(value: str) -> bool:
        return _digits(value) >= minimum

    return check


def _digits_between(low: int, high: int) -> Callable[[str], bool]:
    def check(value: str) -> bool:
        return low <= _digits(value) <= high

    return check


def _iban_ok(value: str) -> bool:
    """A German IBAN is 22 characters; anything else stays out.

    Measured 2026-11-04 over the archive: 222 values reached by the shape, 176
    of them exactly 22 characters beginning "DE". The other 46 were 17 to 35
    characters - truncated prints and a run that swallowed the following BIC -
    so the length is the rule here and a foreign IBAN is not shown at all rather
    than shown as a guess.
    """

    compact = _compact(value)
    return len(compact) == 22 and compact[:2].upper() == "DE"


def _bic_ok(value: str) -> bool:
    """Eight or eleven characters, and every letter in them uppercase.

    The shape rule compiles with IGNORECASE so that a lowercase "bic" needle is
    found too, and that lets the uppercase character run match ordinary words.
    Measured 2026-11-06 over the 99 documents with a fulltext: 18 of the
    readings the length alone accepted were plain words, 13 of them reachable
    before this change and 5 more once a blank line between label and value was
    allowed - the guard takes all 18 out and leaves the codes untouched, 119
    values down to 106 in the same 53 documents. A BIC is never printed in
    lowercase, so the case is checked here rather than in the pattern, which
    has to stay case-insensitive."""

    compact = _compact(value)
    return len(compact) in (8, 11) and compact == compact.upper()


def _has_at_sign(value: str) -> bool:
    return "@" in value and "." in value.split("@")[-1]


def _percent(value: str) -> bool:
    match = re.match(r"^(\d{1,3})(?:[.,](\d{1,3}))?", value)
    if not match:
        return False
    number = float(f"{match.group(1)}.{match.group(2) or 0}")
    return number <= 100


def _date_in(low: int, high: int) -> Callable[[str], bool]:
    """A date that parses and lies in the given year range.

    Without the range a page number written "12.05.2020" style or an OCR
    fragment would pass for a date.
    """

    def check(value: str) -> bool:
        # The four-digit year comes first in the alternation: read the other way
        # it would take "20" out of "2031" and pass a future date as 2020.
        match = re.match(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})", value)
        if not match:
            return False
        day, month, year = (int(part) for part in match.groups())
        if year < 100:
            year += 2000 if year < 30 else 1900
        return low <= year <= high and 1 <= month <= 12 and 1 <= day <= 31

    return check


@dataclass(frozen=True)
class Kind:
    """One answer type: what a question has to say to ask for it, what a
    document has to say to carry it, and what its value looks like."""

    key: str
    label: str
    ask: tuple[str, ...]
    needles: tuple[str, ...]
    value: str
    check: Callable[[str], bool] = _digits_at_least(3)
    shape_only: bool = False


@dataclass(frozen=True)
class Value:
    """One answer as printed, with the reason it was read at all."""

    kind: str
    label: str
    value: str
    line: int
    origin: str
    competing: int = 1


KINDS: tuple[Kind, ...] = (
    Kind(
        key="identifikationsnummer",
        label="Identifikationsnummer",
        ask=("identifikationsnummer", "idnr", "steuer-id", "steueridnr"),
        needles=(
            r"identifikationsnummer",
            r"identifikations[\s\-]*nr",
            r"id[\s\-]?nr",
            r"steuer[\s\-]?id",
        ),
        # The country key is printed by some senders and left out by others, so
        # both are read; 11 digits is the rule either way.
        value=r"((?:DE[ \t]?)?\d(?:[ \t]?\d){9,12})",
        check=_digits_between(11, 11),
    ),
    Kind(
        key="steuernummer",
        label="Steuernummer",
        ask=("steuernummer", "lbstnr"),
        needles=(r"steuernummer", r"steuer[\s\-]*nr", r"lbstnr"),
        value=r"(\d{1,4}(?:[ \t]?/[ \t]?\d{1,8}){1,3}|\d{9,11}(?:[ \t]?/[ \t]?\d{1,3})?)",
        check=_digits_between(9, 13),
    ),
    Kind(
        key="versicherungsnummer",
        label="Versicherungsnummer",
        ask=("versicherungsnummer", "versicherungsschein", "vmnummer"),
        needles=(
            r"versicherungsnummer",
            r"versicherungs[\s\-]*nr",
            r"vers[\.\-]*nr",
            r"versicherungsschein",
            r"vm[\s\-]*nr",
        ),
        value=r"([A-Za-z]?[ \t]?\d(?:[ \t]?\d){5,13})",
        check=_digits_between(6, 13),
    ),
    Kind(
        key="vertragsnummer",
        label="Vertragsnummer",
        ask=("vertragsnummer", "vertragnummer", "police", "scheinnummer"),
        needles=(r"vertragsnummer", r"vertrag[\s\-]*nr", r"police[\s\-]*nr", r"scheinnummer"),
        value=r"(" + _TOKEN + r")",
    ),
    Kind(
        key="mitgliedsnummer",
        label="Mitgliedsnummer",
        ask=("mitgliedsnummer", "kundennummer", "teilnehmernummer"),
        needles=(r"mitgliedsnummer", r"kundennummer", r"teilnehmernummer", r"mitglieder[\s\-]*nr"),
        value=r"(" + _TOKEN + r")",
    ),
    Kind(
        key="aktenzeichen",
        label="Aktenzeichen",
        ask=(
            "aktenzeichen",
            "buchungszeichen",
            "vorgangsnummer",
            "referenznummer",
            "belegnummer",
            "geschaeftsnummer",
            "bearbeitungsnummer",
        ),
        needles=(
            r"aktenzeichen",
            r"buchungszeichen",
            r"vorgangsnummer",
            r"referenznummer",
            r"belegnummer",
            r"gesch[aä]ftsnummer",
            r"bearbeitungsnummer",
        ),
        value=r"(" + _TOKEN + r")",
    ),
    Kind(
        key="kontonummer",
        label="Kontonummer",
        ask=("kontonummer", "bankverbindung", "girokonto"),
        needles=(r"kontonummer", r"konto[\s\-]*nr", r"girokonto"),
        value=r"(\d{8,14})",
        check=_digits_between(8, 14),
    ),
    Kind(
        key="iban",
        label="IBAN",
        ask=("iban",),
        needles=(r"iban",),
        value=r"([A-Z]{2}\d{2}(?:[ \t]?[A-Z0-9]{4}){1,5}[ \t]?[A-Z0-9]{1,4})",
        check=_iban_ok,
    ),
    Kind(
        key="bic",
        label="BIC",
        ask=("bic", "swift"),
        needles=(r"\bbic\b", r"swift[\s\-]*code"),
        # A BIC is eight or eleven characters and the run has to end there: a
        # nine-character print is OCR damage, and reading the first eight of it
        # would show a code the document never states. Both ends are bounded,
        # because an unbounded start lets the match slide one character into the
        # damaged run and come out as a different, valid-looking code.
        value=r"(\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b)",
        check=_bic_ok,
    ),
    Kind(
        key="telefon",
        label="Telefonnummer",
        ask=("telefon", "telefonnummer", "rufnummer", "handynummer", "mobilnummer"),
        needles=(
            r"telefonnummer",
            r"telefon",
            r"tel[\s\-]*nr",
            r"tel\.",
            r"rufnummer",
            r"handynummer",
            r"mobilnummer",
        ),
        # 7 to 14 digits: measured, 12 of the archive's 106 label-adjacent runs
        # carried 15 to 21 digits - those are two numbers written side by side,
        # not one phone number.
        value=r"((?:\+49|\(0\)|0)[\s/\-()0-9]{6,20}\d)",
        check=_digits_between(7, 14),
    ),
    Kind(
        key="email",
        label="E-Mail-Adresse",
        ask=("email", "e-mail", "mailadresse"),
        needles=(r"e-?mail",),
        value=r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
        check=_has_at_sign,
        shape_only=True,
    ),
    Kind(
        key="geburtsdatum",
        label="Geburtsdatum",
        ask=("geburtsdatum", "geboren", "geburtstag"),
        needles=(r"geburtstag", r"geburtsdatum", r"geb[\s\-]*am", r"geb\.", r"geboren"),
        value=r"(" + _DATE + r")",
        check=_date_in(1900, 2020),
    ),
    Kind(
        key="beitragssatz",
        label="Beitragssatz",
        ask=("beitragssatz", "prozentsatz", "hebesatz", "promille"),
        needles=(r"beitragssatz", r"prozent[\s\-]*satz", r"hebesatz"),
        value=r"(\d{1,3}(?:[.,]\d{1,3})?[ \t]?(?:%|Prozent|Promille))",
        check=_percent,
    ),
    Kind(
        key="gueltigkeit",
        label="Gültigkeit",
        ask=("gueltig", "befristet", "vertragsende", "vertragsablauf", "laufzeit", "frist"),
        needles=(
            r"g(?:ü|ue)ltig[\s\-]*bis",
            r"g(?:ü|ue)ltig[\s\-]*ab",
            r"befristet[\s\-]*bis",
            r"vertragsende",
            r"vertragsablauf",
            r"laufzeit[\s\-]*bis",
            r"zahlbar[\s\-]*bis",
            r"f(?:ä|ae)llig[\s\-]*(?:am|bis)",
        ),
        value=r"(" + _DATE + r")",
        check=_date_in(1990, 2100),
    ),
)

KIND_BY_KEY = {kind.key: kind for kind in KINDS}

# A question that only says "nummer" asks for a number of some kind without
# naming which; then every numbered kind is shown, none invented.
ANY_NUMBER_WORDS = ("nummer", "bezeichnung", "kennung")
ANY_DATE_WORDS = ("datum",)
# "wann" asks when, and in this archive a "wann" is a due or validity date, not
# the birthday of a person named in the question.
WHEN_WORDS = ("wann",)
DATE_KINDS = ("geburtsdatum", "gueltigkeit")
NUMBER_KINDS = (
    "identifikationsnummer",
    "steuernummer",
    "versicherungsnummer",
    "vertragsnummer",
    "mitgliedsnummer",
    "aktenzeichen",
    "kontonummer",
)


def kinds_from_question(text: str | None) -> tuple[str, ...]:
    """Which answer types this question asks for, read from its own words.

    Whole folded words only, so "nr" inside "nummer" is not its own ask word. A
    question naming no answer type asks for none, and the page then stays with
    the money figures it already showed.
    """

    lowered = _fold(text)
    tokens = set(re.findall(r"[a-z0-9][a-z0-9./\-]*", lowered))
    matched: list[str] = []
    for kind in KINDS:
        for word in kind.ask:
            folded = _fold(word)
            if folded in tokens or (" " in folded and folded in lowered):
                matched.append(kind.key)
                break
    if not matched and any(word in tokens for word in ANY_NUMBER_WORDS):
        matched.extend(NUMBER_KINDS)
    if not matched and any(word in tokens for word in ANY_DATE_WORDS):
        matched.extend(DATE_KINDS)
    if not matched and any(word in tokens for word in WHEN_WORDS):
        matched.append("gueltigkeit")
    return tuple(dict.fromkeys(matched))


def _rules(kind: Kind) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Label glued to value: same line and next line, compiled once."""

    if kind.shape_only:
        return (("Form", re.compile(kind.value)),)
    out: list[tuple[str, re.Pattern[str]]] = []
    for needle in kind.needles:
        out.append((needle, re.compile(rf"{needle}{_SAME_LINE}{kind.value}", re.IGNORECASE)))
        out.append((needle, re.compile(rf"{needle}{_NEXT_LINE}{kind.value}", re.IGNORECASE)))
    return tuple(out)


_COMPILED = {kind.key: _rules(kind) for kind in KINDS}


def extract_values(content: str | None, kinds: tuple[str, ...]) -> tuple[Value, ...]:
    """Every value of the asked kinds a document states next to its own label.

    Values come back as printed, line by line, each naming how label and value
    stood next to one another. `competing` carries how many distinct values of
    that kind the document holds, so the page can say "mehrere" instead of
    letting one look like the answer.
    """

    text = unicodedata.normalize("NFC", content or "")
    if not text.strip() or not kinds:
        return ()

    offsets = [0]
    for line in text.split("\n")[:-1]:
        offsets.append(offsets[-1] + len(line) + 1)

    by_kind: dict[str, list[Value]] = {}
    for key in kinds:
        kind = KIND_BY_KEY.get(key)
        if kind is None:
            continue
        found: list[Value] = []
        seen: set[tuple[int, str]] = set()
        for label, pattern in _COMPILED[key]:
            for match in pattern.finditer(text):
                raw = match.group(1).strip()
                if not kind.check(raw):
                    continue
                line_number = sum(offset <= match.start(1) for offset in offsets)
                label_line = sum(offset <= match.start() for offset in offsets)
                if kind.shape_only:
                    origin = "Form"
                elif label_line == line_number:
                    origin = "gleiche Zeile"
                elif line_number - label_line == 1:
                    origin = "Label eine Zeile hoeher"
                else:
                    origin = f"Label {line_number - label_line} Zeilen hoeher"
                handle = (line_number, _fold(raw))
                if handle in seen:
                    continue
                seen.add(handle)
                found.append(
                    Value(
                        kind=kind.key,
                        label=kind.label,
                        value=raw[:120],
                        line=line_number,
                        origin=origin,
                    )
                )
        if found:
            count = len({value.value for value in found})
            by_kind[key] = [
                Value(
                    kind=value.kind,
                    label=value.label,
                    value=value.value,
                    line=value.line,
                    origin=value.origin,
                    competing=count,
                )
                for value in found
            ]

    ordered = [value for key in kinds for value in by_kind.get(key, [])]
    return tuple(sorted(ordered, key=lambda item: (item.line, item.kind)))

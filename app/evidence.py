"""The question layer: which documents a question reaches, and which lines hold a number.

Built on these measurements against the live API (2026-11-04, 99 documents):

* the whole question as one ``query`` returns **0** hits, while a single content
  word returns its documents - Paperless' search is not a question answerer, so
  the question has to be taken apart here;
* ``Einspeisevergütung`` returns **0** while its stem ``Einspeis`` returns 3 -
  the index is word based and a compound is a blind spot, which is why every term
  is searched in variants and the page shows which variant hit;
* ``OR`` returns 0, so the union of the variant hits has to happen here;
* ``created__gte``/``created__lte`` filter the **intake** date, and ``after`` /
  ``before`` do nothing in 3.3.1 - a period is therefore shown as the
  approximation it is;
* the index does not fold umlauts: of 30 corpus words that carry one, 29 lost
  every hit when queried in the two-letter form ("abfallgebühren" 10 documents,
  "abfallgebuehren" 0). Since the corpus is split 503 umlaut words against 227
* it stems, and that decides what a variant may be. Measured: "vorauszahlung",
  "vorauszahlungen" and "vorauszahl" all reach the same 5 documents, while
  "beitra", "haftpflich" and "wohngebä" reach none - a cut only counts when the
  index can hold it, so cuts are taken from the archive's own vocabulary and the
  two fixed probes come last.

What this layer deliberately does not do is answer. It hands over candidate
documents and the lines inside them that carry a number, with the role and the
modifier `app.roles.py` read out of the document's own wording, and it names
every competing value instead of picking one. Measured reason: 818 of 2064
amounts in the archive carry a role, and of the questions he actually asks, one
(pid 114) has two right numbers, 429,27 netto and 510,83 brutto. Choosing one of
them is his call, not a guess by this code.

A line can also be kept for naming an answer type the question asked for - an
IdNr, an Aktenzeichen, a phone number, a validity date - through `app/values.py`,
which reads those values only where the document prints their own label. Measured
reason: 1105 of the archive's 5235 lines with a digit carry a Geldbetrag, and the
118 lines printing "Identifikationsnummer" carry none.

The one place a number is computed is the total (`TOTAL_WORDS`), and it is the
one place that needs an explicit rule: only amounts that already share both a
role and a modifier are added, because only then does the document itself say
these figures belong together. The addends stay on screen, so a total can always
be checked against them.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from app.roles import Amount
from app.roles import as_cents
from app.roles import format_cents
from app.roles import label_amounts
from app.values import KIND_BY_KEY
from app.values import Value
from app.values import extract_values
from app.values import kinds_from_question

# Hard caps. Every variant is one API call and every candidate is one fulltext
# call, so the budget bounds the page, not the archive.
MAX_VARIANTS_PER_TERM = 4
MAX_SEARCH_CALLS = 14
MAX_CANDIDATES = 12
MAX_ADDENDS = 6
LINE_CHARS = 200
VARIANT_BONUS = 0.05

# Question parts that carry no document value, in the folded spelling `fold`
# gives them. Deliberately missing: "offene", "beitrag", "rente", "steuer" -
# those do name things in his archive. "jahr" and "letztes" are here because a
# period is read off the question by `_period_of`, so the words that stated it
# have nothing left to search for. The three-letter group on the last line only
# matters since `_LETTERS` went down to three letters on 2026-11-06: "und",
# "wem" and the rest were too short to ever reach a search term before.
STOPWORDS = frozenset(
    """
    wie hoch ist sind bin war werden wird kann muss habe hatte hat gibt noch schon
    gerade bitte mal mir der die das dem den des ein eine einen zur zu aus von mit
    ueber fuer wer was welche welcher dieses diesem letztes letzte jahr jahre
    aktuell derzeit momentan circa ungefaehr mein meine meinen dein deine
    unser unsere uns ich du er sie es
    viel viele zahle zahlt zahlen zahlst bezahle bezahlt bezahlst bekomme bekommen
    bekommst kriegen schicken senden moechte waere haette koennte soll sollen
    und wem wen man nur aber denn als auf
    """.split()
)

# Words that ask for a total rather than for a figure stated in one place.
TOTAL_WORDS = (
    "insgesamt",
    "zusammen",
    "gesamt",
    "summe",
    "summier",
    "addier",
    "kumulier",
    "alle zahlungen",
    "jahresbetrag",
    "im jahr",
    "pro jahr",
)

# Only these two spellings of a period are read, because both were measured
# against his real questions. Anything vaguer ("neulich", "kuerzlich") stays a
# plain word search rather than silently cutting documents away.
_PERIOD_PATTERNS = (
    (re.compile(r"\b(?:19|20)\d{2}\b"), "Jahreszahl"),
    (re.compile(r"\b(?:letztes jahr|vorjahr)\b"), "Vorjahr"),
    (re.compile(r"\b(?:dieses jahr|diesem jahr|laufendes jahr)\b"), "laufendes Jahr"),
)

# A question word becomes a search term from three letters on. Measured
# 2026-11-06 over the 19 questions in the stored history: four letters dropped
# every word of a person's name, and three letters added back exactly two words
# - a first name and the short form of an inspection association, both content
# words. No three-letter filler came up in those 19; the ones German carries
# anyway ("und", "auf", "nur") sit in STOPWORDS now.
_LETTERS = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


@dataclass(frozen=True)
class Period:
    """A date range for the API, with the wording it was read from."""

    after: str | None
    before: str | None
    label: str = ""

    @property
    def stated(self) -> bool:
        return self.after is not None or self.before is not None


@dataclass(frozen=True)
class Question:
    raw: str
    terms: tuple[str, ...]
    variants: tuple[tuple[str, ...], ...]
    period: Period
    wants_total: bool
    kinds: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        return self.raw.strip()


@dataclass(frozen=True)
class Line:
    """One OCR line that carries a number, and why it was kept."""

    number: int
    text: str
    why: str
    amounts: tuple[Amount, ...]
    values: tuple[Value, ...] = ()


@dataclass(frozen=True)
class Candidate:
    document_id: int
    title: str
    correspondent: str | None
    created: str
    score: float
    matched: tuple[str, ...]
    lines: tuple[Line, ...]
    labelled: tuple[Amount, ...]

    @property
    def paperless_url_path(self) -> str:
        return f"/documents/{self.document_id}"


@dataclass(frozen=True)
class Attempt:
    """One API call, recorded so the page can say what was tried."""

    term: str
    variant: str
    sender: str | None
    period: str
    hits: int
    stage: str


@dataclass(frozen=True)
class Total:
    document_id: int
    role: str
    modifier: str | None
    addends: tuple[str, ...]
    value: str

    @property
    def statement(self) -> str:
        return " + ".join(self.addends) + " = " + self.value


@dataclass(frozen=True)
class Result:
    question: Question
    attempts: tuple[Attempt, ...]
    candidates: tuple[Candidate, ...]
    totals: tuple[Total, ...]
    notes: tuple[str, ...]
    sender: tuple[int, str] | None = None
    calls_used: int = 0
    closed_candidates: int = 0

    @property
    def question_key(self) -> str:
        """The one string a judgement about this answer is filed under.

        Not the question text: the same question comes back phrased
        differently, and a whole question is worth nothing to the index anyway
        (measured 2026-11-04: 0 hits). What decides which documents can answer
        is the content words, the sender the question names and the period it
        names, so those three are the key. Folded, because "Einspeiseverguetung"
        and "Einspeisevergütung" are the one question here, and sorted, because
        the word order carries nothing.

        The stated sender and period are used, not the stage that finally
        answered: a run that had to drop both filters still asked the same
        question, and its judgement must be findable again.
        """

        terms = ",".join(sorted({fold(term) for term in self.question.terms}))
        sender = str(self.sender[0]) if self.sender else "-"
        period = f"{self.question.period.after or ''}..{self.question.period.before or ''}"
        return f"{terms}|{sender}|{period}"


def normalize(text: str | None) -> str:
    """NFC, one space between words. macOS hands out NFD and the OCR does not
    care, so a compound typed by him and the same word in a document have to
    meet in one spelling before anything is compared."""

    return " ".join(unicodedata.normalize("NFC", text or "").split())


# The same two-letter spellings `app.roles.py` carries for its role needles, and
# for the same measured reason: one sender's OCR prints "Gebaeude", the next
# "Gebäude". Without the fold the eight-letter probe of "Gebäudeversicherung" is
# "gebäudever" and reaches neither spelling.
_UMLAUT_PAIRS = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))


def fold(text: str | None) -> str:
    """What the index is searched with: normalized, lowercase, one spelling per
    umlaut."""

    lowered = normalize(text).lower()
    for letter, pair in _UMLAUT_PAIRS:
        lowered = lowered.replace(letter, pair)
    return lowered


def content_terms(text: str) -> tuple[str, ...]:
    """The words a document could hold, in the spelling he typed them in.

    Kept unfolded on purpose: the index does not fold umlauts, so the surface
    form still has to reach the search."""

    words = [normalize(w).lower() for w in _LETTERS.findall(text)]
    kept: list[str] = []
    for word in words:
        if fold(word) in STOPWORDS or word in kept:
            continue
        kept.append(word)
    return tuple(kept)


def _period_of(text: str, today: date) -> Period:
    lowered = fold(text)
    for pattern, label in _PERIOD_PATTERNS:
        match = pattern.search(lowered)
        if not match:
            continue
        if label == "Jahreszahl":
            year = int(match.group())
        elif label == "Vorjahr":
            year = today.year - 1
        else:
            year = today.year
        return Period(f"{year}-01-01", f"{year}-12-31", label)
    return Period(None, None, "")


def parse_question(
    text: str,
    *,
    today: date | None = None,
    known_words: frozenset[str] | set[str] = frozenset(),
) -> Question:
    """Split a question into search terms, variants, a period and a total wish."""

    reference = today or date.today()
    terms = content_terms(text)
    lowered = fold(text)
    return Question(
        raw=normalize(text),
        terms=terms,
        variants=tuple(word_variants(word, known_words) for word in terms),
        period=_period_of(text, reference),
        wants_total=any(word in lowered for word in TOTAL_WORDS),
        kinds=kinds_from_question(text),
    )


def _vocabulary_cuts(surface: str, real: set[str] | frozenset[str]) -> list[str]:
    """Cuts of the asked word that begin a word the archive holds: first the tail
    (the compound's own last word), then the heads, longest first."""

    tails: list[str] = []
    for start in range(3, len(surface) - 5):
        tail = surface[start:]
        if len(tail) < 8:
            break
        if tail != surface and (tail in real or any(o.startswith(tail) for o in real)):
            tails.append(tail)
            if len(tails) >= 1:
                break

    heads: list[str] = []
    for end in range(len(surface) - 3, 5, -1):
        head = surface[:end]
        if head == surface:
            continue
        if head in real or any(o != surface and o.startswith(head) for o in real):
            heads.append(head)
            if len(heads) >= 2:
                break

    return [*tails, *heads]


def word_variants(word: str, known_words: set[str] | frozenset[str]) -> tuple[str, ...]:
    """How one term is looked up, and why it is looked up more than one way.

    The probes are the first reason. ``Einspeis`` is not reachable as a head of
    "Einspeisevergütung" from names alone - the archive spells the figure
    "Entgelt für Einspeisung" - but it is the first eight characters, and eight
    characters were measured to find the document. Cuts shorter than five
    characters would return half the archive.

    Both spellings are the second reason, and it is a measured one: searched over
    the live archive on 2026-11-04, 29 of 30 corpus words that carry an umlaut
    lose every hit when queried in the two-letter form ("abfallgebühren" gives
    10 documents, "abfallgebuehren" 0). The index does not fold. The corpus holds
    both spellings in bulk - 503 word types with an umlaut, 227 written out - so
    a question typed with umlauts has to probe both or it silently answers from
    half the archive.

    The third reason is the direction no rule of thumb can undo: a word typed as
    "Gebaeudeversicherung" cannot be unfolded safely, because "ss" is "ss" in
    "Schluss" and "ß" in "Straße". So the archive's own word list is asked which
    spelling it holds for the folded form, and that one is searched verbatim.
    Without the word list this direction stays a known gap.

    The order is the measured one too: a cut that begins an archive word hits, a
    blind cut often does not ("wohngebä" and "beitra" 0 documents, "vorauszahlung"
    5), so whole words come first, then the vocabulary's cuts, then the two fixed
    probes as the last rescue."""

    raw = normalize(word).lower()
    folded = fold(raw)
    real = {v for v in (fold(k) for k in known_words) if len(v) >= 4}
    cuts = _vocabulary_cuts(folded, real) if len(folded) >= 5 else []

    spellings = [raw] if folded == raw else [raw, folded]
    corpus_spelled = [
        spelling
        for spelling in sorted(normalize(k).lower() for k in known_words)
        if fold(spelling) == folded and spelling not in spellings
    ]
    probes = [p for p in (folded[:8], raw[:8], folded[:6], raw[:6]) if len(p) >= 5]

    seen: list[str] = []
    for variant in [*spellings, *corpus_spelled, *cuts, *probes]:
        if variant and variant not in seen:
            seen.append(variant)
    return tuple(seen[:MAX_VARIANTS_PER_TERM])


def sender_from_question(
    question: str,
    correspondents: list[tuple[int, str]],
) -> tuple[int, str, str] | None:
    """The correspondent a question names, if it names exactly one.

    A word from the question counts only when it belongs to one correspondent
    in the whole list. Measured reason: "Versicherung" stands in several names,
    and taking the first long word would have filtered the liability question
    onto the wrong sender.
    """

    lowered = fold(question)
    tokens: dict[str, list[int]] = {}
    for correspondent_id, name in correspondents:
        for token in {fold(t) for t in re.findall(r"[^\W\d_]{6,}", normalize(name))}:
            tokens.setdefault(token, []).append(correspondent_id)

    for correspondent_id, name in correspondents:
        for token in sorted(
            {fold(t) for t in re.findall(r"[^\W\d_]{6,}", normalize(name))},
            key=len,
            reverse=True,
        ):
            if len(tokens.get(token, [])) == 1 and token in lowered:
                return (correspondent_id, name, token)
    return None


def evidence_lines(
    content: str | None,
    variants: list[str],
    amounts: tuple[Amount, ...],
    kinds: tuple[str, ...] = (),
) -> tuple[Line, ...]:
    """The lines that hold a number, each carrying the role and modifier the
    document itself states for it.

    ``amounts`` comes from `app.roles.label_amounts` over the **whole** text, not
    line by line: half of the archive's labels sit on the line above the number
    ("Neuer Jahresbeitrag" and then "1.088,99 EUR" in pid 118), and a single line
    cannot see that.

    A line is kept when it carries a number and either a search variant or a role
    word. The role word matters because the answer to a cost question often sits
    on a line the question never names; the variant matters because the label
    above it may be OCR damage. A line with a number and neither is noise.

    ``kinds`` is the second reason a line can be kept at all: when the question
    asked for an answer type (`app.values.py` reads it from its own words), a line
    stating a value of that type is kept even without any money on it. Measured
    reason: the archive prints "Identifikationsnummer" on 118 lines, and on not
    one of them does a Geldbetrag stand next to it - without this the answer to
    that question could never be shown.
    """

    text = unicodedata.normalize("NFC", content or "")
    if not text.strip():
        return ()

    by_line: dict[int, list[Amount]] = {}
    for amount in amounts:
        by_line.setdefault(amount.line, []).append(amount)

    values_by_line: dict[int, list[Value]] = {}
    for value in extract_values(text, kinds):
        values_by_line.setdefault(value.line, []).append(value)

    needles = [v for v in variants if v]
    lines: list[Line] = []
    for number, raw in enumerate(text.split("\n"), 1):
        line = raw.strip()
        on_line = tuple(by_line.get(number, ()))
        on_kinds = tuple(values_by_line.get(number, ()))
        if not line or (not on_line and not on_kinds):
            continue

        hit_word = any(needle in fold(line) for needle in needles)
        roles_here = tuple(a for a in on_line if a.role)
        if not on_kinds and not hit_word and not roles_here:
            continue

        if on_line:
            why = (
                "Suchwort und Rollenwort"
                if hit_word and roles_here
                else ("Suchwort" if hit_word else "Rollenwort")
            )
        else:
            why = "gefragte Art"
        lines.append(
            Line(
                number=number,
                text=line[:LINE_CHARS],
                why=why,
                amounts=on_line,
                values=on_kinds,
            )
        )
    return tuple(lines)


def sum_values(values: list[str]) -> str | None:
    """Add German decimal figures. None when anything cannot be read."""

    try:
        total = sum(as_cents(value) for value in values)
    except (ValueError, AttributeError):
        return None
    return format_cents(total)


def totals_for(candidate: Candidate) -> tuple[Total, ...]:
    """Sums the document itself makes available: amounts that already share one
    role and one modifier, on different lines, excluding 0,00 rows.

    This is D1 and it is the only place this layer produces a figure that no
    sender printed. The grouping is what keeps it honest: adding 429,27 and
    510,83 would invent a third number out of netto and brutto, and they do not
    share a modifier, so they are never added.

    Measured live on 2026-11-04 with the word "Summe" as trigger: 15 totals came
    back, and the noisiest were groups of `Zeilenendwert` - the role a number
    gets when only its position at the end of a line spoke for it ("1.109,00 +
    1.109,00 = 2.218,00"). Two figures that merely sit at a line end do not
    belong together because the document says so, so that role is excluded.
    """

    groups: dict[tuple[str, str | None], dict[int, str]] = {}
    for amount in candidate.labelled:
        if amount.value == "0,00" or amount.role == "Zeilenendwert":
            continue
        groups.setdefault((amount.role, amount.modifier), {})[amount.line] = amount.value

    totals: list[Total] = []
    for (role, modifier), by_line in groups.items():
        values = [by_line[line] for line in sorted(by_line)]
        if len(values) < 2:
            continue
        if len(values) > MAX_ADDENDS:
            continue
        total = sum_values(values)
        if total is None:
            continue
        totals.append(
            Total(
                document_id=candidate.document_id,
                role=role,
                modifier=modifier,
                addends=tuple(values),
                value=total,
            )
        )
    return tuple(totals)


def _rank(hits: dict[int, dict[str, object]]) -> list[tuple[float, int]]:
    """Most different terms first, then the newest intake date, then the id."""

    return sorted(
        ((float(doc["score"]), document_id) for document_id, doc in hits.items()),
        key=lambda pair: (pair[0], str(hits[pair[1]]["created"]), pair[1]),
        reverse=True,
    )


def gather(
    question: str,
    *,
    search,
    fetch_document,
    correspondents: list[tuple[int, str]],
    known_words: set[str] | frozenset[str] = frozenset(),
    today: date | None = None,
    max_candidates: int = MAX_CANDIDATES,
    total_documents: int = 0,
) -> Result:
    """Run one question over the archive and collect its evidence.

    ``search(variant, sender_id, after, before)`` returns Paperless list items
    and ``fetch_document(document_id)`` returns one document with its fulltext.
    Both are injected: this module never imports a client, so the whole layer is
    testable against synthetic samples and cannot reach Paperless by itself.
    ``total_documents`` is the archive size the term weights are read against;
    without it every term counts the same.
    """

    parsed = parse_question(question, today=today, known_words=known_words)
    if not parsed.terms:
        return Result(
            question=parsed,
            attempts=(),
            candidates=(),
            totals=(),
            notes=("Die Frage hat kein Inhaltswort, das in einem Dokument stehen kann.",),
        )

    sender = sender_from_question(question, correspondents)
    notes: list[str] = []
    attempts: list[Attempt] = []
    calls = 0

    first_label = (
        "Absender und Zeitraum"
        if sender and parsed.period.stated
        else "Absender"
        if sender
        else "Zeitraum"
        if parsed.period.stated
        else "Suchbegriffe"
    )
    stages: list[tuple[str, int | None, Period]] = [
        (first_label, sender[0] if sender else None, parsed.period)
    ]
    if sender:
        stages.append(("ohne Absender", None, parsed.period))
    if parsed.period.stated:
        stages.append(
            ("ohne Zeitraum", sender[0] if sender else None, Period(None, None, ""))
        )
    if sender and parsed.period.stated:
        stages.append(("ohne Absender und ohne Zeitraum", None, Period(None, None, "")))

    hits: dict[int, dict[str, object]] = {}
    used_stage = ""
    for stage, sender_id, period in stages:
        hits, attempts, calls = _search_stage(
            parsed,
            stage=stage,
            sender_id=sender_id,
            period=period,
            search=search,
            calls=calls,
            attempts=attempts,
            total_documents=total_documents,
        )
        used_stage = stage
        if hits:
            if stage != first_label:
                notes.append(f"Erste Stufe traf nicht: gesucht über „{stage}“.")
            break
        notes.append(f"Stufe „{stage}“: 0 Treffer.")

    sender_dropped = used_stage in ("ohne Absender", "ohne Absender und ohne Zeitraum")
    period_dropped = used_stage in ("ohne Zeitraum", "ohne Absender und ohne Zeitraum")

    ranked = _rank(hits)
    opened: list[Candidate] = []
    variants_flat = [v for group in parsed.variants for v in group]
    for score, document_id in ranked[:max_candidates]:
        document = fetch_document(document_id) or {}
        content = document.get("content") or ""
        amounts = label_amounts(content)
        opened.append(
            Candidate(
                document_id=document_id,
                title=str(document.get("title") or f"Dokument {document_id}"),
                correspondent=document.get("correspondent_name")
                or document.get("correspondent"),
                created=str(document.get("created") or "")[:10],
                score=score,
                matched=tuple(
                    sorted(
                        {
                            variant
                            for variant in variants_flat
                            if variant in fold(content)
                        }
                    )
                ),
                lines=evidence_lines(content, variants_flat, amounts, parsed.kinds),
                labelled=tuple(a for a in amounts if a.role),
            )
        )

    totals: list[Total] = []
    if parsed.wants_total:
        for candidate in opened:
            totals.extend(totals_for(candidate))

    if parsed.kinds:
        labels = ", ".join(
            KIND_BY_KEY[key].label for key in parsed.kinds if key in KIND_BY_KEY
        )
        notes.append(
            f"Gefragte Art: {labels}. Zeilen, die so einen Wert nennen, stehen "
            "auch ohne Geldbetrag."
        )

    closed = max(0, len(ranked) - len(opened))
    if closed:
        notes.append(f"{closed} weitere Kandidaten wurden nicht geöffnet.")
    if calls >= MAX_SEARCH_CALLS and len(parsed.terms) > 1:
        notes.append("Suchbudget erschöpft, nicht alle Varianten wurden gesucht.")
    if sender and sender_dropped:
        notes.append(
            f"Absender „{sender[1]}“ erkannt, als Filter aber fallen gelassen, "
            "weil er nichts traf."
        )
    if parsed.period.stated and period_dropped:
        notes.append(
            f"Zeitraum {parsed.period.label} erkannt, als Filter aber fallen "
            "gelassen, weil er nichts traf."
        )

    return Result(
        question=parsed,
        attempts=tuple(attempts),
        candidates=tuple(opened),
        totals=tuple(totals),
        notes=tuple(notes),
        sender=(sender[0], sender[1]) if sender else None,
        calls_used=calls,
        closed_candidates=closed,
    )


def _weight(rarest: int, total_documents: int) -> float:
    """What one term is worth for the order of the candidates.

    Measured 2026-11-04: "zahle" stands in 30 of the 99 documents and "einspeis"
    in 3. Weights that ignore that let the 30-document word decide the order,
    which is what pushed the tax assessment out of the first three in the first
    live run of this layer."""

    if total_documents <= 0 or rarest <= 0:
        return 1.0
    return max(0.05, math.log(total_documents / rarest))


def _scored(hits: dict[int, dict[str, object]], rarest: dict[str, int], total: int) -> None:
    for entry in hits.values():
        weight = sum(
            _weight(rarest[term], total) for term in entry["terms"]  # type: ignore[union-attr]
        )
        extra = len(entry["variants"]) - 1  # type: ignore[arg-type]
        entry["score"] = round(weight + VARIANT_BONUS * max(0, extra), 2)


def _search_stage(
    parsed: Question,
    *,
    stage: str,
    sender_id: int | None,
    period: Period,
    search,
    calls: int,
    attempts: list[Attempt],
    total_documents: int,
) -> tuple[dict[int, dict[str, object]], list[Attempt], int]:
    hits: dict[int, dict[str, object]] = {}
    rarest: dict[str, int] = {}

    for term, variants in zip(parsed.terms, parsed.variants):
        for variant in variants:
            if calls >= MAX_SEARCH_CALLS:
                _scored(hits, rarest, total_documents)
                return hits, attempts, calls
            items = search(
                variant,
                sender_id=sender_id,
                after=period.after,
                before=period.before,
            )
            calls += 1
            attempts.append(
                Attempt(
                    term=term,
                    variant=variant,
                    sender=None if sender_id is None else str(sender_id),
                    period=period.label or period.after or "",
                    hits=len(items),
                    stage=stage,
                )
            )
            if items:
                rarest[term] = min(len(items), rarest.get(term, len(items)))
            for item in items:
                document_id = int(item["id"])
                entry = hits.setdefault(
                    document_id,
                    {
                        "created": item.get("created") or "",
                        "terms": set(),
                        "variants": set(),
                    },
                )
                entry["terms"].add(term)  # type: ignore[union-attr]
                entry["variants"].add(variant)  # type: ignore[union-attr]

    _scored(hits, rarest, total_documents)
    return hits, attempts, calls

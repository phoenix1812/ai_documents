"""The question layer: how a question reaches documents and which lines it shows.

Every sample here is synthetic. The search behaviours the module is built on were
measured against the live archive on 2026-11-04 and are encoded in the fake index
below: a whole question as one query returns nothing, a single content word
returns the documents carrying it, a compound misses when the sender wrote the
figure with a different word ("Einspeiseverguetung" asked, "Einspeisung" printed),
and the date filter works on the intake date. The point of the fake index is that
the layer is tested against the measured search behaviour rather than an ideal one.
"""

from __future__ import annotations

import inspect
import re
from datetime import date

import app.evidence as evidence
from app.evidence import Candidate
from app.evidence import MAX_ADDENDS
from app.evidence import MAX_SEARCH_CALLS
from app.evidence import MAX_VARIANTS_PER_TERM
from app.evidence import evidence_lines
from app.evidence import gather
from app.evidence import parse_question
from app.evidence import sender_from_question
from app.evidence import sum_values
from app.evidence import totals_for
from app.evidence import word_variants
from app.roles import label_amounts

TODAY = date(2026, 11, 4)

# Line 2 holds the printed word of a compound that was asked differently, line 3
# holds a role the question never names, line 4 is not money ("9,6" has one
# decimal), line 5 is a number that no label and no search word reaches.
FEED = {
    "id": 900,
    "title": "Abrechnung Beispielwerk Nord",
    "correspondent": 12,
    "correspondent_name": "Beispielwerk Versicherung",
    "created": "2026-03-04",
    "content": (
        "Abrechnung 4711\n"
        "Entgelt fuer Einspeisung 84,30 EUR\n"
        "Beitrag netto 120,45 EUR\n"
        "-Zaehlerstand 9,6\n"
        "Umlaufgrenze 12,00\n"
    ),
}

# Instalment rows the document labels the same way, gross beside net. This is the
# shape D1 is allowed to add within.
RATES = {
    "id": 901,
    "title": "Steuerbescheid Beispielamt",
    "correspondent": 7,
    "correspondent_name": "Beispielamt Mitte",
    "created": "2026-01-09",
    "content": (
        "Es werden festgesetzt\n"
        "1. Abschlag netto 100,00 EUR\n"
        "1. Abschlag brutto 119,00 EUR\n"
        "2. Abschlag netto 200,00 EUR\n"
        "2. Abschlag brutto 238,00 EUR\n"
        "3. Abschlag netto 0,00 EUR\n"
    ),
}

# The label sits on the line above the number, so a per-line read would lose it.
STAFFEL = {
    "id": 902,
    "title": "Vertragsmitteilung Ruhebank",
    "correspondent": 5,
    "correspondent_name": "Ruhebank Lebensversicherung",
    "created": "2025-11-30",
    "content": ("Neuer Jahresbeitrag\n" "1.234,56 EUR\n"),
}

# The OCR of this sender wrote the umlaut out, the next one printed it.
HOUSE = {
    "id": 903,
    "title": "Nachtrag Gebaeudeversicherung",
    "correspondent": 6,
    "correspondent_name": "Fiktivasse Versicherung",
    "created": "2026-06-01",
    "content": ("Gebaeudeversicherung Nr 12\n" "Beitrag brutto 1.200,00 EUR\n"),
}

HOUSE_UM = {
    "id": 904,
    "title": "Nachtrag Gebäudeversicherung",
    "correspondent": 6,
    "correspondent_name": "Fiktivasse Versicherung",
    "created": "2026-05-01",
    "content": ("Gebäudeversicherung Nr 13\n" "Beitrag brutto 1.400,00 EUR\n"),
}

DOCUMENTS = [FEED, RATES, STAFFEL, HOUSE, HOUSE_UM]

CORRESPONDENTS = [
    (12, "Beispielwerk Versicherung"),
    (7, "Beispielamt Mitte"),
    (5, "Ruhebank Lebensversicherung"),
    (6, "Fiktivasse Versicherung"),
]

ARCHIVE_WORDS = frozenset(
    {"einspeisung", "entgelt", "jahresbeitrag", "abschlag", "versicherung"}
)

# The two spellings the corpus holds for one and the same compound.
HOUSE_WORDS = frozenset({"gebäudeversicherung", "gebaeudeversicherung", "versicherung"})


class FakeIndex:
    """Paperless' search behaviour, as measured: word based matching, no union of
    terms, no question answering, intake dates in the range filter. The index is
    deliberately NOT umlaut-folding - it compares what the document spells, so a
    question typed with an umlaut only reaches an OCR that wrote "ae" when the
    layer folds its own variants."""

    def __init__(self, documents):
        self.documents = {doc["id"]: doc for doc in documents}
        self.calls: list[tuple] = []
        self.fetched: list[int] = []

    @staticmethod
    def _words(text: str) -> list[str]:
        return [w.lower() for w in re.findall(r"[^\W\d_]+", text)]

    def _matches(self, variant: str, doc: dict) -> bool:
        words = self._words(f"{doc.get('title', '')} {doc.get('content', '')}")
        return any(variant in word for word in words)

    def search(self, variant, *, sender_id=None, after=None, before=None):
        self.calls.append((variant, sender_id, after, before))
        items = []
        for doc in self.documents.values():
            if sender_id is not None and doc.get("correspondent") != sender_id:
                continue
            created = str(doc.get("created") or "")[:10]
            if after and created < after:
                continue
            if before and created > before:
                continue
            if self._matches(variant, doc):
                items.append(
                    {
                        "id": doc["id"],
                        "title": doc["title"],
                        "created": created,
                        "correspondent": doc.get("correspondent"),
                        "correspondent_name": doc.get("correspondent_name"),
                    }
                )
        return items

    def fetch_document(self, document_id):
        self.fetched.append(document_id)
        return self.documents.get(document_id)

    def run(self, question, **kwargs):
        return gather(
            question,
            search=self.search,
            fetch_document=self.fetch_document,
            correspondents=CORRESPONDENTS,
            today=TODAY,
            total_documents=len(self.documents),
            **kwargs,
        )


def sample(document_id, created, content, title=None, correspondent=None):
    return {
        "id": document_id,
        "title": title or f"Mapte {document_id}",
        "correspondent": correspondent,
        "created": created,
        "content": content,
    }


def test_the_whole_question_is_never_one_query():
    index = FakeIndex([FEED])
    index.run("Wie hoch ist der aktuelle Beitrag fuer die Einspeisung?")

    assert index.calls
    assert all(" " not in variant for variant, *_ in index.calls)
    assert not any(variant.startswith("wie") for variant, *_ in index.calls)


def test_a_question_is_split_into_its_content_words():
    parsed = parse_question("Wie hoch ist der Beitrag für die Rente?")

    assert parsed.terms == ("beitrag", "rente")


def test_a_three_letter_word_is_a_search_term_and_a_filler_is_not():
    """Measured 2026-11-06 over the 19 questions in the stored history: with a
    four-letter floor every word of a person's name was dropped, and the floor
    at three letters brought back exactly two words, both content words. The
    three-letter fillers German carries in a question are in STOPWORDS, so they
    still cost no search call."""

    parsed = parse_question("Welche Kontoauszuege hat Max?")
    assert parsed.terms == ("kontoauszuege", "max")

    filler = parse_question("Und was zahlt der Max?")
    assert filler.terms == ("max",)


def test_a_compound_is_reached_by_its_eight_letter_probe():
    # "Einspeis" is what the first eight letters of the asked word are, and it is
    # the piece the printed word shares. Measured on the live archive: the whole
    # compound returns 0, this probe returns its documents.
    variants = word_variants("Einspeiseverguetung", frozenset())

    assert variants[0] == "einspeiseverguetung"
    assert "einspeis" in variants
    assert len(variants) <= MAX_VARIANTS_PER_TERM

    index = FakeIndex([FEED])
    assert [c.document_id for c in index.run("Wie hoch war die Einspeiseverguetung?").candidates] == [900]


def test_both_spellings_of_an_umlaut_are_searched():
    # Measured on the live archive the day this layer was built: the index does
    # not fold, so "abfallgebuehren" returns 0 where "abfallgebühren" returns 10.
    # The corpus is split 503 umlaut word types against 227 written out, so a
    # question has to probe both or it answers from half the archive.
    index = FakeIndex([HOUSE, HOUSE_UM])
    result = index.run("Gebäudeversicherung")

    assert sorted(c.document_id for c in result.candidates) == [903, 904]

    # Typed as "ae" the word cannot be unfolded by a rule: "ss" is "ss" in
    # "Schluss" and "ß" in "Straße". The archive's own word list is what closes
    # this direction, and without it only one spelling is reached.
    index = FakeIndex([HOUSE, HOUSE_UM])
    assert [c.document_id for c in index.run("Gebaeudeversicherung").candidates] == [903]

    index = FakeIndex([HOUSE, HOUSE_UM])
    result = index.run("Gebaeudeversicherung", known_words=HOUSE_WORDS)
    assert sorted(c.document_id for c in result.candidates) == [903, 904]


def test_the_archive_vocabulary_adds_the_word_the_compound_ends_with():
    # The probes only ever cut the front of the asked word. The archive's own
    # word list adds the back: "versicherung" is what "Gebaeudeversicherung"
    # ends with, and it reaches documents that name the insurer but not the
    # building.
    with_vocabulary = word_variants("Gebaeudeversicherung", ARCHIVE_WORDS)
    without = word_variants("Gebaeudeversicherung", frozenset())

    assert "versicherung" in with_vocabulary
    assert "versicherung" not in without


def test_a_short_word_is_still_searched_verbatim():
    assert word_variants("Haus", frozenset()) == ("haus",)
    assert word_variants("Solar", frozenset())[0] == "solar"


def test_an_archive_word_outranks_a_blind_probe():
    # Measured: "wohngebä" reaches 0 documents and "versicherung" is a word the
    # archive holds. The probes are the last rescue, not the first attempt.
    variants = word_variants("Wohngebaeudeversicherung", frozenset({"versicherung"}))

    assert variants.index("versicherung") < variants.index("wohngeba")


def test_a_short_word_gets_no_variants():
    assert word_variants("Rente", frozenset()) == ("rente",)


def test_a_period_of_one_year_becomes_a_full_range():
    parsed = parse_question("Wie hoch war der Beitrag 2025?", today=TODAY)

    assert parsed.period.after == "2025-01-01"
    assert parsed.period.before == "2025-12-31"
    assert parsed.period.stated


def test_last_year_is_read_from_the_given_day():
    parsed = parse_question("Welche Zahlungen gab es letztes Jahr?", today=TODAY)

    assert parsed.period.label == "Vorjahr"
    assert parsed.period.after == "2025-01-01"


def test_a_question_without_a_period_sends_no_dates():
    parsed = parse_question("Wie hoch ist der Beitrag?", today=TODAY)

    assert not parsed.period.stated
    assert parsed.period.after is None


def test_a_total_word_switches_the_sum_step_on():
    assert parse_question("Wie hoch ist der Beitrag insgesamt?").wants_total
    assert not parse_question("Wie hoch ist der Beitrag?").wants_total


def test_the_word_summe_opens_the_total_stage() -> None:
    # Measured live on 2026-11-04: "Was summiert sich an Beitrag netto?" reached
    # twelve candidates and no total, because the trigger list had "zusammen" and
    # "addier" but not the word the stage is named after.
    assert parse_question("Wie hoch ist die Summe der Beitragsraten?").wants_total
    assert parse_question("Bitte die Zahlungen summieren.").wants_total
    assert not parse_question("Im Sommer war der Beitrag faellig.").wants_total


def test_only_a_sender_word_shared_by_one_name_filters():
    assert sender_from_question("Beitrag bei der Ruhebank", CORRESPONDENTS) == (
        5,
        "Ruhebank Lebensversicherung",
        "ruhebank",
    )
    # "Versicherung" stands in two names, so it may not cut the archive.
    assert sender_from_question("Wie hoch ist die Versicherung?", CORRESPONDENTS) is None


def test_a_sender_that_hits_nothing_is_dropped_and_said():
    index = FakeIndex([FEED, HOUSE])
    result = index.run("Ruhebank Einspeisung")

    assert result.sender == (5, "Ruhebank Lebensversicherung")
    assert any("fallen gelassen" in note for note in result.notes)
    assert any(attempt.stage == "ohne Absender" for attempt in result.attempts)
    assert [c.document_id for c in result.candidates] == [900]


def test_a_period_that_hits_nothing_is_dropped_and_said():
    index = FakeIndex([FEED, STAFFEL])
    result = index.run("Einspeisung 2019")

    assert result.question.period.after == "2019-01-01"
    assert any("Zeitraum" in note for note in result.notes)
    assert [c.document_id for c in result.candidates] == [900]


def test_every_search_stays_inside_the_call_budget():
    index = FakeIndex(DOCUMENTS)
    result = index.run(
        "Wie hoch ist der Jahresbeitrag fuer die Einspeisung und die Rente im Steuerbescheid?"
    )

    assert result.calls_used <= MAX_SEARCH_CALLS
    assert len(result.attempts) <= MAX_SEARCH_CALLS


def test_a_line_with_a_role_is_kept_even_though_the_question_never_names_it():
    amounts = label_amounts(FEED["content"])
    lines = evidence_lines(FEED["content"], ["einspeis"], amounts)

    assert [(line.number, line.why) for line in lines] == [
        (2, "Suchwort und Rollenwort"),
        (3, "Rollenwort"),
    ]


def test_a_number_line_without_a_label_and_without_a_search_word_is_noise():
    amounts = label_amounts(FEED["content"])
    lines = evidence_lines(FEED["content"], [], amounts)

    assert [line.number for line in lines] == [2, 3]
    assert 5 not in [line.number for line in lines]
    assert lines[0].amounts[0].role == "Entgelt"


def test_a_percentage_is_not_carried_onto_its_line():
    content = "Umsatzsteuer 19,00 %\n"

    assert evidence_lines(content, ["umsatzsteuer"], label_amounts(content)) == ()


def test_a_label_on_the_line_above_reaches_the_number():
    amounts = label_amounts(STAFFEL["content"])
    lines = evidence_lines(STAFFEL["content"], [], amounts)

    assert [line.number for line in lines] == [2]
    assert lines[0].amounts[0].role == "Beitrag"


def test_a_document_held_by_two_terms_ranks_first():
    index = FakeIndex(DOCUMENTS)
    result = index.run("Einspeisung Beitrag")

    assert result.candidates[0].document_id == 900
    assert result.candidates[0].score > result.candidates[1].score


def test_the_variant_that_hit_is_shown_on_the_candidate():
    index = FakeIndex([FEED])
    result = index.run("Wie hoch war die Einspeiseverguetung?")

    assert "einspeis" in result.candidates[0].matched


def test_only_amounts_that_share_role_and_modifier_are_added():
    index = FakeIndex([RATES])
    result = index.run("Wie hoch sind die Abschlaege insgesamt?")

    totals = {(t.role, t.modifier): t for t in result.totals}
    assert sorted(totals) == [("Abschlag", "brutto"), ("Abschlag", "netto")]
    assert totals[("Abschlag", "netto")].addends == ("100,00", "200,00")
    assert totals[("Abschlag", "netto")].value == "300,00"
    assert totals[("Abschlag", "brutto")].statement == "119,00 + 238,00 = 357,00"
    # net and gross of one row are never added into a third figure.
    assert "219,00" not in {t.value for t in result.totals}


def test_no_total_is_offered_when_the_question_does_not_ask_for_one():
    index = FakeIndex([RATES])

    assert index.run("Wie hoch sind die Abschlaege?").totals == ()


def test_a_lone_figure_is_not_a_total():
    assert totals_for(candidate_from("1. Abschlag netto 100,00 EUR\n")) == ()


def test_a_group_beyond_the_addend_cap_is_left_alone():
    content = "".join(
        f"{i}. Abschlag netto {10 * i},00 EUR\n" for i in range(1, MAX_ADDENDS + 2)
    )

    assert totals_for(candidate_from(content)) == ()


def test_figures_that_only_end_their_line_are_not_added():
    # Measured live on 2026-11-04: with "Summe" as trigger the archive produced
    # "1.109,00 + 1.109,00 = 2.218,00" out of two line-end figures. Nothing in the
    # document says those two belong together, so the role "Zeilenendwert" is not a
    # group to add.
    content = "1. Posten 10,00 110,00 EUR\n2. Posten 20,00 220,00 EUR\n"
    labelled = [a for a in label_amounts(content) if a.role]

    assert [a.value for a in labelled] == ["110,00", "220,00"]
    assert {a.role for a in labelled} == {"Zeilenendwert"}
    assert totals_for(candidate_from(content)) == ()


def test_a_sum_that_cannot_be_read_returns_nothing():
    assert sum_values(["100,00", "200,50"]) == "300,50"
    assert sum_values(["100,00", "keine Zahl"]) is None


def test_a_term_that_names_few_documents_decides_the_order():
    # Measured on the live archive: "zahle" stands in 30 of 99 documents and
    # "einspeis" in 3. Equal weights let the common word order the candidates,
    # and in the first live run that pushed the tax assessment past the third
    # place. Here the three common documents are also the newer ones, so only a
    # term weight can put the rare document first.
    documents = [
        sample(801, "2026-06-01", "Sammelmapte Tonnenweise 10,00 EUR\n"),
        sample(802, "2026-06-02", "Sammelmapte Tonnenweise 10,00 EUR\n"),
        sample(803, "2026-06-03", "Sammelmapte Tonnenweise 10,00 EUR\n"),
        sample(810, "2025-01-01", "Sammelmapte Querposten 20,00 EUR\n"),
    ]
    index = FakeIndex(documents)
    result = index.run("Sammelmapte Tonnenweise Querposten")

    assert result.candidates[0].document_id == 810
    assert result.candidates[0].score > result.candidates[1].score


def test_the_tail_of_a_compound_is_a_variant_when_the_archive_starts_with_it():
    # "Steuervorauszahlung" returns 0 documents, "vorauszahlung" returns the five
    # assessments - and the archive's own word is the plural, so the cut has to
    # be allowed to start a corpus word rather than be one verbatim.
    variants = word_variants("Steuervorauszahlung", frozenset({"vorauszahlungen"}))

    assert "vorauszahlung" in variants


def test_a_question_of_only_function_words_has_nothing_to_search():
    index = FakeIndex([FEED])
    result = index.run("Wie viel zahle ich 2026?")

    assert result.question.terms == ()
    assert result.candidates == ()
    assert result.notes == ("Die Frage hat kein Inhaltswort, das in einem Dokument stehen kann.",)


def test_the_layer_cannot_reach_paperless_by_itself():
    source = inspect.getsource(evidence)

    for forbidden in ("requests", "httpx", "paperless_client", "update_document"):
        assert forbidden not in source


def candidate_from(content: str) -> Candidate:
    amounts = label_amounts(content)
    return Candidate(
        document_id=999,
        title="Probe",
        correspondent=None,
        created="2026-01-01",
        score=1.0,
        matched=(),
        lines=evidence_lines(content, [], amounts),
        labelled=tuple(a for a in amounts if a.role),
    )

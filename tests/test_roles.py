"""The role vocabulary and the two line window that reads it.

The positive cases are copied from his own archive, because that is where the
wrong number sits: paperless 40 states the contribution tax of 14,71 EUR three
lines before the contribution of 92,15 EUR, and a search for the first number in
the document returns the tax. The negative cases are the measured ones too - 734
of the archive's 1165 amount lines carry no word at all, so most amounts have to
stay unlabelled rather than be guessed.
"""

from __future__ import annotations

from app.roles import AMOUNT_PATTERN
from app.roles import ROLES
from app.roles import as_cents
from app.roles import format_cents
from app.roles import label_amounts

# The AXA liability invoice, as its OCR text reads (paperless 40).
AXA = """Rechnungsdatum 16.06.2026
Die Versicherungsteuer in Höhe von 19% wird auf den Nettobeitrag von 77,44 EUR erhoben, dies ent
spricht 14,71 EUR.
Beitrag Privathaftpflichtversicherung jährlich 92,15 EUR
Gesamtbetrag 92,15 EUR
"""

# The Domcura residential invoice (paperless 118): label line, then bare number.
DOMCURA = """Neuer Jahresbeitrag
1.088,99 EUR
Netto
218,83 €
"""

# The tax assessment (paperless 37): installment rows whose header OCR mangled.
FINANZAMT = """Es werden festgesetzt Einkommensteuer Solidaritäts- Insgesamt
- found sind zu zahlen - . zuschlag__ . Bu
für 2026 zum
10.März wie bisher 525,00 7,00 532,00
10.Juni wie bisher 525,00 7,00 532,00
10.September 0,00 0,00 0,00
"""


def _one(text: str, value: str):
    found = [a for a in label_amounts(text) if a.value == value]
    assert len(found) == 1, f"{value} not found once in {[a.value for a in found]}"
    return found[0]


def _at(text: str, line: int, value: str):
    found = [a for a in label_amounts(text) if a.line == line and a.value == value]
    assert len(found) == 1, f"{value} on line {line} not found once"
    return found[0]


def test_the_contribution_wins_over_the_tax_in_the_same_document() -> None:
    # The invoice states 92,15 EUR twice, once as the contribution and once as
    # the total, and neither line is the tax line above it.
    assert _at(AXA, 4, "92,15").role == "Beitrag"
    assert _at(AXA, 4, "92,15").origin == "eigene Zeile"
    assert _at(AXA, 5, "92,15").role == "Gesamtbetrag"


def test_the_split_tax_sentence_labels_nothing() -> None:
    # "dies ent" / "spricht 14,71 EUR" is one sentence torn by a line break, and
    # the line above holds both the tax and the net contribution. Refusing is the
    # measured-correct answer: 14,71 EUR is not what a cost question wants.
    assert _one(AXA, "14,71").role is None
    assert _one(AXA, "77,44").role is None


def test_a_bare_number_reads_its_label_from_the_line_above() -> None:
    amount = _one(DOMCURA, "1.088,99")
    assert amount.role == "Beitrag"
    assert amount.origin == "Zeile darueber"


def test_a_table_row_does_not_read_its_neighbour_row_as_a_label() -> None:
    row = [a for a in label_amounts(FINANZAMT) if a.line == 4]
    assert [(a.value, a.role) for a in row] == [
        ("525,00", None),
        ("7,00", None),
        ("532,00", "Zeilenendwert"),
    ]


def test_thousands_and_signs_are_read_as_the_document_writes_them() -> None:
    assert _one("Neuer Beitrag: 1.088,99 EUR\n", "1.088,99").value == "1.088,99"
    assert _one("Beitrag 1 088,99 EUR\n", "1.088,99").value == "1.088,99"
    feed_in = _one("Entgelt für Einspeisung -429,27\n", "429,27")
    assert feed_in.role == "Entgelt"
    assert feed_in.evidence.startswith("Entgelt für Einspeisung -")


def test_capacity_is_not_money() -> None:
    # "9,6000 kW" is the installed output on paperless 114, not an amount.
    assert label_amounts("9,6000 kW Solarenergie an oder auf Gebäuden\n") == []
    assert AMOUNT_PATTERN.search("Betrag 34,50 EUR") is not None


def test_short_needles_do_not_match_inside_unrelated_words() -> None:
    assert _one("Anzahl der Formate 12,00 EUR\n", "12,00").role is None
    assert _one("monatliche Rate 84,99 EUR\n", "84,99").role == "Abschlag"


def test_a_two_letter_spelling_reaches_the_umlaut_needle() -> None:
    assert _one("Jahrespraemie 512,00 EUR\n", "512,00").role == "Beitrag"
    assert _one("Jahresprämie 512,00 EUR\n", "512,00").role == "Beitrag"


def test_the_row_end_does_not_inherit_its_line_role() -> None:
    # Paperless 114 Z323: "Umsatzsteuer 19 % auf -429,27 Euro -81,56". His
    # decision on 2026-11-04: Zeilenendwert stays what it is, the row total, and
    # does not take the role the line names for its other number.
    row = {a.value: a for a in label_amounts("Umsatzsteuer 19 % auf -429,27 Euro -81,56\n")}
    assert row["429,27"].role == "Steuer"
    assert row["81,56"].role == "Zeilenendwert"


def test_a_compound_that_carries_the_needle_as_its_head_still_counts() -> None:
    # Measured on paperless 114: the line reads "Guthabenbetrag -510,83". With a
    # word end after the needle this stayed a number without a role.
    assert _one("Guthabenbetrag -510,83\n", "510,83").role == "Guthaben"
    assert _one("Nettobeitrag von 77,44 EUR\n", "77,44").role == "Beitrag"


def test_an_unrelated_amount_stays_unlabelled() -> None:
    assert _one("Der Verbrauch betrug 340,00 EUR\n", "340,00").role is None


def test_two_roles_in_one_segment_decide_nothing() -> None:
    assert _one("Umsatzsteuer und Beitrag zusammen 59,99 EUR\n", "59,99").role is None


def test_the_catalog_is_closed_and_labels_are_distinct() -> None:
    labels = [label for label, _ in ROLES]
    assert len(labels) == len(set(labels))
    needles = [n for _, group in ROLES for n in group]
    assert len(needles) == len(set(needles)), f"duplicate needle in {needles}"


def test_empty_text_has_no_amounts() -> None:
    assert label_amounts(None) == []
    assert label_amounts("   \n\n") == []


# The modifier axis: netto or brutto, decided by the word or by the row.


def test_a_row_that_adds_up_marks_its_total_as_gross() -> None:
    # Paperless 40 line 37, the invoice's own arithmetic: 77,44 plus the 14,71
    # tax is 92,15. The row states no netto or brutto word, the sum does.
    row = label_amounts("Folgebeitrag 01.07.2026 - 77,44 EUR 19,00 % 14,71 EUR 92,15 EUR\n")
    by_value = {a.value: a for a in row}
    assert by_value["92,15"].modifier == "brutto"
    assert by_value["92,15"].modifier_origin == "Zeilensumme 77,44 + 14,71"
    assert by_value["77,44"].modifier is None
    assert by_value["14,71"].modifier is None


def test_a_word_in_the_window_sets_the_modifier() -> None:
    # Paperless 114 writes both spellings out on its own lines, 429,27 netto and
    # 510,83 brutto, three lines apart.
    assert _one("Entgelt für Einspeisung netto -429,27 EUR\n", "429,27").modifier == "netto"
    assert _one("Entgelt für Einspeisung brutto -510,83 EUR\n", "510,83").modifier == "brutto"


def test_a_window_holding_both_words_decides_neither() -> None:
    amount = _one("Netto wie brutto 500,00 EUR\n", "500,00")
    assert amount.modifier is None


def test_a_percentage_is_not_an_amount() -> None:
    # "Umsatzsteuer 19,00 %" handed 19,00 EUR to the first measured pass.
    row = label_amounts("Umsatzsteuer 19,00 % -81,56\n")
    assert [a.value for a in row] == ["81,56"]


def test_two_numbers_are_not_a_row_total() -> None:
    # Without a third number there is nothing to add up, and the last figure of
    # the row keeps no modifier.
    row = label_amounts("Posten 77,44 EUR 92,15 EUR\n")
    assert [a.modifier for a in row] == [None, None]


def test_a_row_with_two_possible_totals_is_not_read_as_a_table() -> None:
    # 1 plus 2 is 3 and 2 plus 3 is 5: that is a row read wrong, not a row
    # holding one gross figure, so no number gets a modifier.
    row = label_amounts("Betriebskosten 1,00 2,00 3,00 5,00 EUR\n")
    assert [a.modifier for a in row] == [None, None, None, None]


def test_a_figure_reads_to_cents_and_back_in_german_spelling() -> None:
    # The sum step hands its result back into the same spelling the document
    # uses, and a point for the thousands is not a comma before the decimals.
    assert as_cents("2.345,67") == 234567
    assert format_cents(234567) == "2.345,67"
    assert format_cents(30050) == "300,50"
    assert format_cents(0) == "0,00"

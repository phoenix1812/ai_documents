"""The answer types a document states in words, and how a question picks them.

Every sample is synthetic. The behaviours encoded here were measured against the
live archive on 2026-11-04 and are the reason the rules are drawn this way: shape
alone over-matches (a Kennzeichen read as a shape hit 1460 lines, read from its
own label 4), the Identifikationsnummer is eleven digits and no more, 12 of the
archive's 106 label-adjacent phone runs carried two numbers written side by side,
and 46 of the values a bare IBAN shape reached were 17 to 35 characters long.

The window between a label and its value is the other half of the rule: on 56 of
the 118 lines that print an IdNr label the number sits in the same line or the
next one, on 22 a short figure sits there instead, and on 8 nothing. Those 22 and
8 must stay empty rather than become an answer. A blank line is the one thing
that may be crossed, because the announcement letter that leaves one is the only
shape the measured archive holds where the number stood out of reach.
"""

from __future__ import annotations

from app.evidence import Amount
from app.evidence import evidence_lines
from app.evidence import parse_question
from app.values import KINDS
from app.values import extract_values
from app.values import kinds_from_question

SAMPLE = (
    "Belegnummer 7-0193/26\n"
    "Identifikationsnummer 23 456 789 012\n"
    "Versicherungsscheinnummer\n"
    "92 345 678\n"
    "IBAN DE12 5001 0517 0055 0310 70\n"
    "BIC GENODEM1ABC\n"
    "Telefon 030 1234567\n"
    "Geburtsdatum 12.05.1978\n"
    "Beitragssatz 14,6 Prozent\n"
    "gültig bis 31.12.2027\n"
)


def values_for(kind: str, text: str = SAMPLE):
    return [value for value in extract_values(text, (kind,)) if value.kind == kind]


def test_every_kind_is_askable_by_its_own_first_word():
    """The catalogue is closed: each entry answers to a word a question can use."""

    for kind in KINDS:
        assert kinds_from_question(kind.ask[0]) == (kind.key,), kind.key


def test_question_names_the_art_it_asks_for():
    assert kinds_from_question("Identifikationsnummer Max Mustermann") == (
        "identifikationsnummer",
    )
    assert kinds_from_question("Wann ist der Vertrag gültig bis?") == ("gueltigkeit",)
    assert kinds_from_question("Wie hoch ist der Beitragssatz in Prozent?") == (
        "beitragssatz",
    )


def test_umlaut_spellings_meet_on_the_folded_word():
    assert kinds_from_question("gültig") == kinds_from_question("gueltig")
    assert kinds_from_question("Geschäftsnummer") == ("aktenzeichen",)


def test_question_without_an_art_word_asks_for_none():
    assert kinds_from_question("Einspeisevergütung monatlich") == ()
    assert kinds_from_question("") == ()
    assert kinds_from_question(None) == ()


def test_a_bare_number_word_opens_the_numbered_kinds_and_nothing_else():
    """A plain "Nummer" asks which number without saying; a compound like
    "Telefonnummer" says, and then only that one is asked."""

    asked = kinds_from_question("Welche Nummer steht im Bescheid?")
    assert "identifikationsnummer" in asked
    assert "aktenzeichen" in asked
    assert "iban" not in asked
    assert "email" not in asked
    assert kinds_from_question("Telefonnummer") == ("telefon",)


def test_substring_of_a_longer_word_is_not_an_ask_word():
    assert kinds_from_question("Versicherungsnummer") == ("versicherungsnummer",)
    assert "bic" not in kinds_from_question("Fabrikat")


def test_label_and_value_in_one_line():
    idnr = values_for("identifikationsnummer")
    assert [value.value for value in idnr] == ["23 456 789 012"]
    assert idnr[0].line == 2
    assert idnr[0].origin == "gleiche Zeile"
    assert idnr[0].competing == 1


def test_label_at_the_line_end_reaches_down_one_line():
    versicherung = values_for("versicherungsnummer")
    assert [value.value for value in versicherung] == ["92 345 678"]
    assert versicherung[0].line == 4
    assert versicherung[0].origin == "Label eine Zeile hoeher"


def test_a_blank_line_between_label_and_value_is_crossed():
    """The OCR of a letter that announces a number prints the announcement, an
    empty line, then the number. Measured 2026-11-06 over the 99 documents with
    a fulltext: this shape is what held one archive value out of reach, and the
    whole relaxation across the archive is 22 values in 15 documents - 5 of them
    a word read as a BIC, which `test_a_bic_has_to_be_printed_in_uppercase`
    takes back out."""

    found = values_for(
        "identifikationsnummer",
        "Identifikationsnummer wird hiermit mitgeteilt:\n\n23 456 789 012\n",
    )
    assert [value.value for value in found] == ["23 456 789 012"]
    assert found[0].line == 3
    assert found[0].origin == "Label 2 Zeilen hoeher"


def test_a_line_with_text_on_it_is_never_skipped():
    """Only blank lines may stand between label and value: a line carrying text
    is a different statement, and measured over the same run the wider rule
    that skipped those too returned exactly the same 22 values."""

    assert values_for(
        "identifikationsnummer",
        "Identifikationsnummer:\nHier steht ein Satz\n23 456 789 012\n",
    ) == []


def test_each_kind_reads_only_its_own_label():
    assert values_for("kontonummer") == []
    assert values_for("email") == []
    assert [value.value for value in values_for("bic")] == ["GENODEM1ABC"]
    assert [value.value for value in values_for("iban")] == [
        "DE12 5001 0517 0055 0310 70"
    ]
    assert [value.value for value in values_for("telefon")] == ["030 1234567"]
    assert [value.value for value in values_for("geburtsdatum")] == ["12.05.1978"]
    assert [value.value for value in values_for("beitragssatz")] == ["14,6 Prozent"]
    assert [value.value for value in values_for("gueltigkeit")] == ["31.12.2027"]
    assert [value.value for value in values_for("aktenzeichen")] == ["7-0193/26"]


def test_two_competing_values_are_both_returned_with_their_count():
    text = "IBAN DE12 5001 0517 0055 0310 70\nIBAN DE99 1200 0000 1234 5678 90\n"
    found = values_for("iban", text)
    assert len(found) == 2
    assert {value.competing for value in found} == {2}
    assert [value.line for value in found] == [1, 2]


def test_an_eleven_digit_rule_is_a_rule_and_not_a_hint():
    """The IdNr is eleven digits; a ten-digit figure is a different number and
    must not be shown as its answer."""

    assert values_for("identifikationsnummer", "Identifikationsnummer 2345678901\n") == []
    assert values_for("identifikationsnummer", "Identifikationsnummer 45678\n") == []
    assert values_for("versicherungsnummer", "Versicherungsnummer 12345\n") == []


def test_a_run_of_two_phone_numbers_is_neither_one():
    assert values_for("telefon", "Telefon 0301234567890123\n") == []


def test_iban_shape_without_a_valid_length_stays_out():
    assert values_for("iban", "IBAN DE12 5001 0517\n") == []
    assert values_for("iban", "IBAN DE91 ABNA 0417 1643 00\n") == []
    # The printed IBAN running into the BIC after it: 27 characters, no space.
    assert values_for("iban", "IBAN DE12500105170055031070GENODEM1\n") == []


def test_bic_needs_eight_or_eleven_characters_and_the_run_has_to_end():
    assert [value.value for value in values_for("bic", "BIC DEUTDEFF\n")] == ["DEUTDEFF"]
    assert [value.value for value in values_for("bic", "BIC DEUTDEFF, Swift-Code\n")] == [
        "DEUTDEFF"
    ]
    assert values_for("bic", "BIC DEUTDEFFG\n") == []
    assert values_for("bic", "BIC DEUTDEFFGHIJKLM\n") == []


def test_a_bic_has_to_be_printed_in_uppercase():
    """The shape rules compile with IGNORECASE so that a label written in any
    case is found, and that lets the character run match an ordinary word:
    measured 2026-11-06, 18 of the archive's BIC readings were plain words, 13
    of them reachable before the case rule and 5 more once blank lines were
    allowed. A code is never printed in lowercase."""

    assert values_for("bic", "BIC Rechnung Nr. 12\n") == []
    assert [value.value for value in values_for("bic", "BIC: DEUTDEFF\n")] == ["DEUTDEFF"]
    assert values_for("bic", "Swift-Code GENODEd1ABC\n") == []
    # The word sitting below a blank line is the reading the relaxation added.
    assert values_for("bic", "BIC lautete:\n\nRechnung\n") == []


def test_dates_are_read_inside_their_own_horizon():
    assert values_for("geburtsdatum", "geboren 12.05.1978\n") != []
    assert values_for("geburtsdatum", "geb. 12.05.2031\n") == []
    assert values_for("gueltigkeit", "fällig am 05.11.2026\n") != []
    assert values_for("geburtsdatum", "Geburtsdatum 32.12.1978\n") == []


def test_a_rate_over_one_hundred_is_not_a_contribution_rate():
    assert values_for("beitragssatz", "Beitragssatz 150 Prozent\n") == []


def test_email_is_the_one_kind_read_from_its_shape():
    found = values_for("email", "Antwort an Beispiel.Abnehmer@example.org\n")
    assert [value.value for value in found] == ["Beispiel.Abnehmer@example.org"]
    assert found[0].origin == "Form"
    assert values_for("email", "Antwort an Beispiel.Abnehmer@example\n") == []


def test_asking_nothing_reads_nothing():
    assert extract_values(SAMPLE, ()) == ()
    assert extract_values("", ("bic",)) == ()
    assert extract_values(SAMPLE, ("unknown_kind",)) == ()


def test_values_come_back_in_line_order():
    found = extract_values(SAMPLE, ("geburtsdatum", "identifikationsnummer", "bic"))
    assert [value.line for value in found] == [2, 6, 8]
    assert found[1].kind == "bic"


def test_a_value_line_survives_without_any_money():
    """The measured reason: not one of the archive's 118 IdNr lines carries a
    Geldbetrag, so a money-only keep rule shows no answer at all."""

    lines = evidence_lines(SAMPLE, ["belegnummer"], (), ("aktenzeichen",))
    assert [line.number for line in lines] == [1]
    assert lines[0].why == "gefragte Art"
    assert lines[0].amounts == ()
    assert lines[0].values[0].value == "7-0193/26"


def test_without_an_asked_art_the_keep_rule_stays_money_only():
    assert evidence_lines(SAMPLE, ["belegnummer"], (), ()) == ()


def test_money_and_value_on_one_line_are_both_carried():
    amount = Amount(
        line=1,
        value="118,40",
        role="Beitrag",
        needle="beitrag",
        origin="gleiche Zeile",
        modifier=None,
        modifier_origin="",
        evidence="Beitrag 118,40 EUR",
    )
    text = "Identifikationsnummer 23 456 789 012 Beitrag 118,40 EUR\n"
    lines = evidence_lines(text, ["beitrag"], (amount,), ("identifikationsnummer",))
    assert lines[0].why == "Suchwort und Rollenwort"
    assert [item.value for item in lines[0].amounts] == ["118,40"]
    assert [value.value for value in lines[0].values] == ["23 456 789 012"]


def test_parse_question_carries_the_asked_art_into_the_layer():
    parsed = parse_question("Identifikationsnummer Max Mustermann")
    assert parsed.kinds == ("identifikationsnummer",)
    assert parse_question("Einspeisevergütung monatlich").kinds == ()

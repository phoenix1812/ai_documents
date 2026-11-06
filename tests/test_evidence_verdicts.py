"""Stufe (a): the reader says whether an answer was right, and it is remembered.

A judgement is stored under the question key the evidence page shows at the
bottom of its candidate list, so the same question phrased with the same words
finds it again - and a differently worded question visibly does not. Synthetic
samples only: no names, terms or figures from the archive.
"""

from __future__ import annotations

import pytest

from app.db import Database
from app.db import VERDICT_ANSWER
from app.db import VERDICT_HIT
from app.db import VERDICT_IRRELEVANT
from app.evidence import gather
from app.review_ui import evidence_verdict

KEY = "beitrag,versicherung|7|.."


@pytest.fixture()
def store(tmp_path):
    database = Database(str(tmp_path))
    try:
        yield database
    finally:
        database.close()


def fake_search(variant: str, *, sender_id, after, before):
    return [{"id": 900, "created": "2026-02-03", "title": "synthetisch"}]


def fake_fetch(document_id: int):
    return {"id": document_id, "content": "Zeile ohne Zahl\nBeitrag netto 40,00 EUR\n"}


def test_the_key_folds_spellings_and_word_order() -> None:
    """One question, two typings: the judgement has to be found again."""

    def ask(text: str):
        return gather(
            text,
            search=fake_search,
            fetch_document=fake_fetch,
            correspondents=[],
            known_words={"beitrag", "gebaeudeversicherung"},
            total_documents=99,
        ).question_key

    assert ask("Wie hoch ist der Beitrag zur Gebäudeversicherung?") == ask(
        "Gebaeudeversicherung, Beitrag?"
    )
    assert ask("Wie hoch ist der Beitrag zur Gebäudeversicherung?").startswith(
        "beitrag,gebaeudeversicherung|"
    )


def test_a_different_period_is_a_different_question() -> None:
    """Keying on the stated year, because 2025 and 2026 have different answers."""

    def ask(year: str):
        return gather(
            f"beitrag {year}",
            search=fake_search,
            fetch_document=fake_fetch,
            correspondents=[],
            known_words={"beitrag"},
            total_documents=99,
        ).question_key

    assert ask("2025") != ask("2026")
    assert "..2025-12-31" in ask("2025")


def test_a_document_judgement_is_overwritten_not_stacked(store: Database) -> None:
    store.record_verdict(KEY, 900, VERDICT_HIT)
    store.record_verdict(KEY, 900, VERDICT_IRRELEVANT)

    rows = store.verdicts_for_key(KEY)

    assert len(rows) == 1
    assert rows[0]["verdict"] == VERDICT_IRRELEVANT


def test_a_figure_judgement_sits_beside_the_document_judgement(store: Database) -> None:
    store.record_verdict(KEY, 900, VERDICT_HIT)
    store.record_verdict(KEY, 900, VERDICT_ANSWER, 2, "40,00", "Beitrag", "netto")

    rows = store.verdicts_for_key(KEY)

    assert [row["verdict"] for row in rows] == [VERDICT_HIT, VERDICT_ANSWER]
    assert rows[1]["line_number"] == 2
    assert rows[1]["amount_value"] == "40,00"
    assert rows[1]["amount_role"] == "Beitrag"
    assert rows[1]["amount_modifier"] == "netto"


def test_two_figures_in_one_line_are_two_decisions(store: Database) -> None:
    store.record_verdict(KEY, 900, VERDICT_ANSWER, 2, "40,00", "Beitrag", "netto")
    store.record_verdict(KEY, 900, VERDICT_ANSWER, 2, "48,00", "Beitrag", "brutto")

    assert len(store.verdicts_for_key(KEY)) == 2


def test_an_unknown_judgement_is_refused(store: Database) -> None:
    with pytest.raises(ValueError):
        store.record_verdict(KEY, 900, "vielleicht")
    with pytest.raises(ValueError):
        store.record_verdict("   ", 900, VERDICT_HIT)


def test_ruling_down_is_not_counted_as_an_answer(store: Database) -> None:
    store.record_verdict(KEY, 900, VERDICT_IRRELEVANT)
    store.record_verdict("andere|7|..", 901, VERDICT_HIT)

    assert store.confirming_verdict_counts([KEY, "andere|7|..", ""]) == {"andere|7|..": 1}
    assert store.confirming_verdict_counts([]) == {}


def test_a_history_row_carries_its_key(store: Database) -> None:
    store.record_search("beitrag versicherung", ["beitrag"], 1, 1, KEY)
    store.record_verdict(KEY, 900, VERDICT_ANSWER, 2, "40,00")

    entry = store.recent_searches(limit=3)[0]

    assert entry["question_key"] == KEY
    assert store.confirming_verdict_counts([entry["question_key"]])[KEY] == 1


def test_an_old_database_gains_the_judgements_table(store: Database) -> None:
    """An archive written before this change has no such table at all."""

    store.conn.execute("DROP TABLE evidence_verdicts")
    store.conn.commit()

    reopened = Database(str(store.db_file.parent))
    try:
        reopened.record_verdict(KEY, 900, VERDICT_HIT)
        assert len(reopened.verdicts_for_key(KEY)) == 1
    finally:
        reopened.close()


def test_the_judgement_writes_nothing_to_the_archive(monkeypatch, tmp_path) -> None:
    """A verdict is a row in this database, and the page has no client here.

    The guarantee this checks is the one the evidence page was built on: reading
    Paperless is a GET, and clicking an answer must not acquire the ability to
    write a document.
    """

    from app import review_ui
    from app.config import settings

    def forbidden(*args, **kwargs):
        raise AssertionError("the judgement path must not build a Paperless client")

    monkeypatch.setattr(review_ui, "PaperlessClient", forbidden)
    monkeypatch.setattr(settings, "db_path", str(tmp_path))

    response = evidence_verdict(
        q="beitrag versicherung",
        question_key=KEY,
        paperless_id=900,
        verdict=VERDICT_HIT,
        # Every remaining default is named: called outside a request, a FastAPI
        # Form default is the Form object rather than the value it stands for.
        line_number=0,
        amount_value="",
        amount_role=None,
        amount_modifier=None,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/evidence?q=beitrag%20versicherung"

    stored = Database(str(tmp_path))
    try:
        rows = stored.verdicts_for_key(KEY)
    finally:
        stored.close()

    assert [(row["paperless_id"], row["verdict"]) for row in rows] == [(900, VERDICT_HIT)]


def test_a_falsified_judgement_is_answered_with_400(monkeypatch, tmp_path) -> None:
    from app import review_ui
    from app.config import settings
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "db_path", str(tmp_path))

    with pytest.raises(HTTPException) as excinfo:
        review_ui.evidence_verdict(
            q="beitrag",
            question_key=KEY,
            paperless_id=900,
            verdict="egal",
            line_number=0,
            amount_value="",
            amount_role=None,
            amount_modifier=None,
        )

    assert excinfo.value.status_code == 400

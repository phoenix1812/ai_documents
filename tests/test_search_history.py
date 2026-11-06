"""D2: the question layer remembers what was asked.

Answering a question costs a budget of API calls, so the operator wants to see
which question he asked before and which term variants it was taken apart into.
Synthetic samples only - no names, terms or figures from the archive.
"""

from __future__ import annotations

import pytest

from app.db import SEARCH_HISTORY_LIMIT
from app.db import Database
from app.db import VERDICT_ANSWER
from app.db import VERDICT_HIT
from app.db import VERDICT_IRRELEVANT


@pytest.fixture()
def store(tmp_path):
    database = Database(str(tmp_path))
    try:
        yield database
    finally:
        database.close()


def test_a_question_is_read_back_newest_first(store: Database) -> None:
    store.record_search("erste frage", ["erste", "frage"], 2, 1, "erste|a|..")
    store.record_search("zweite frage", ["zweite", "zwei"], 5, 3, "zweite|b|..")

    history = store.recent_searches(limit=10)

    assert [entry["query"] for entry in history] == ["zweite frage", "erste frage"]
    assert history[0]["variants"] == ["zweite", "zwei"]
    assert (history[0]["hits"], history[0]["candidates"]) == (5, 3)
    assert history[1]["hits"] == 2


def test_variants_come_back_as_a_list_not_as_json_text(store: Database) -> None:
    store.record_search("frage mit anfang", ["a", "an"], 0, 0, "anfang|-|..")
    store.record_search("ohne varianten", None, 0, 0, "varianten|-|..")

    history = store.recent_searches()
    assert history[1]["variants"] == ["a", "an"]
    assert history[0]["variants"] == []


def test_a_blank_question_is_not_recorded(store: Database) -> None:
    store.record_search("   ", ["x"], 0, 0, "irgendein|schluessel|..")
    assert store.recent_searches() == []


def test_the_history_stays_bounded(store: Database) -> None:
    for number in range(SEARCH_HISTORY_LIMIT + 25):
        store.record_search(f"frage {number}", [], 0, 0, f"frage-{number}|-|..")

    history = store.recent_searches(limit=SEARCH_HISTORY_LIMIT)
    assert len(history) == SEARCH_HISTORY_LIMIT
    assert history[0]["query"] == f"frage {SEARCH_HISTORY_LIMIT + 24}"
    assert history[-1]["query"] == "frage 25"


def test_an_older_database_gains_the_table_without_losing_rows(store: Database) -> None:
    store.record_search("vor dem neustart", ["vor"], 1, 1, "vor|-|..")
    path = store.db_file.parent
    store.close()

    reopened = Database(str(path))
    try:
        assert [entry["query"] for entry in reopened.recent_searches()] == ["vor dem neustart"]
    finally:
        reopened.close()


def test_a_judgement_survives_the_history_being_capped(store: Database) -> None:
    """The verdicts table must not be swept by the ring buffer above it."""

    store.record_search("bleibende frage", [], 1, 1, "bleibend|-|..")
    store.record_verdict("bleibend|-|..", 900, VERDICT_HIT)

    for number in range(SEARCH_HISTORY_LIMIT + 25):
        store.record_search(f"andere frage {number}", [], 0, 0, f"andere-{number}|-|..")

    assert store.recent_searches(limit=400)[0]["query"] != "bleibende frage"
    assert [row["paperless_id"] for row in store.verdicts_for_key("bleibend|-|..")] == [900]

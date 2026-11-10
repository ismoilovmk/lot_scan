import logging
from datetime import datetime

import pytest
from fakes import FakeNotifier

import health
from storage import Storage

TITLES = {"a": "Площадка А", "b": "Площадка Б"}
NOON = datetime(2026, 11, 10, 12, 0, 0)


@pytest.fixture
def storage(tmp_path):
    store = Storage(str(tmp_path / "lots.db"))
    yield store
    store.close()


def runs(storage, outcomes, now=NOON, summary_hour=None, notifier=None):
    """Несколько проходов подряд. outcomes — по строке на проход: какие площадки упали."""
    notifier = notifier or FakeNotifier()
    for failed in outcomes:
        health.report(storage, notifier, now, TITLES, ["a", "b"], list(failed), summary_hour)
    return notifier.sent


# --- площадка перестала отвечать ---

def test_alert_comes_once_after_three_failures_in_a_row(storage):
    assert runs(storage, ["a", "a"]) == []
    assert runs(storage, ["a"]) == [
        "⚠️ Площадка А не отвечает уже 3 проверки подряд. Лоты с неё пока не приходят."]
    assert runs(storage, ["a", "a", "a"]) == []


def test_recovery_is_reported_only_after_an_alert(storage):
    assert runs(storage, ["a", "a", "a", "a"]) != []
    assert runs(storage, [""]) == ["✅ Площадка А снова отвечает."]
    assert len(runs(storage, ["a", "a", "a"])) == 1         # ровно три сбоя — уже писали, значит и отбой нужен
    assert runs(storage, [""]) == ["✅ Площадка А снова отвечает."]
    assert runs(storage, ["", "a", "a", ""]) == []          # два сбоя подряд — ещё не повод писать


def test_success_resets_the_count(storage):
    assert runs(storage, ["a", "a", "", "a", "a"]) == []
    assert len(runs(storage, ["a"])) == 1


def test_sources_are_counted_separately(storage):
    sent = runs(storage, ["a", "ab", "ab", "ab"])
    assert sent == ["⚠️ Площадка А не отвечает уже 3 проверки подряд. Лоты с неё пока не приходят.",
                    "⚠️ Площадка Б не отвечает уже 3 проверки подряд. Лоты с неё пока не приходят."]


def test_source_that_was_not_checked_keeps_its_count(storage):
    runs(storage, ["a", "a"])
    notifier = FakeNotifier()
    health.report(storage, notifier, NOON, TITLES, ["b"], [], None)      # проход только по площадке Б
    assert runs(storage, ["a"], notifier=notifier) == [
        "⚠️ Площадка А не отвечает уже 3 проверки подряд. Лоты с неё пока не приходят."]


def test_alert_is_repeated_next_time_when_telegram_failed(storage, caplog):
    runs(storage, ["a", "a"])
    with caplog.at_level(logging.WARNING):
        runs(storage, ["a"], notifier=FakeNotifier(fail=True))
    assert "Служебное сообщение не отправлено" in caplog.text
    assert len(runs(storage, ["a"])) == 1


# --- итог дня ---

def evening(hour=20, minute=0, day=10):
    return datetime(2026, 11, day, hour, minute, 0)


def test_summary_comes_once_a_day_after_the_set_hour(storage):
    assert runs(storage, [""], evening(19, 59), 20) == []
    assert runs(storage, [""], evening(20, 0), 20) == [
        "📊 Итог дня 10.11: новых лотов просмотрено — 0, отправлено — 0. Все площадки отвечают."]
    assert runs(storage, ["", ""], evening(20, 40), 20) == []
    assert len(runs(storage, [""], evening(23, 0, day=11), 20)) == 1


def test_summary_counts_lots_of_that_day(tmp_path):
    clock = [evening(9, 0, day=9)]
    store = Storage(str(tmp_path / "lots.db"), lambda: clock[0])
    store.mark("a", "вчера", True)
    clock[0] = evening(9, 0)
    store.mark("a", "1", True)
    store.mark("a", "2", False)
    store.mark("a", "3", False)
    assert runs(store, [""], evening(), 20) == [
        "📊 Итог дня 10.11: новых лотов просмотрено — 3, отправлено — 1. Все площадки отвечают."]
    store.close()


def test_summary_names_sources_that_keep_failing(storage):
    sent = runs(storage, ["ab", "b", "b"], evening(), 20)
    assert sent[0] == "📊 Итог дня 10.11: новых лотов просмотрено — 0, отправлено — 0. Сбой при последней проверке: Площадка А, Площадка Б."
    assert sent[1].startswith("⚠️ Площадка Б")
    assert len(sent) == 2


def test_summary_is_off_without_the_setting(storage):
    assert runs(storage, [""], evening(23, 59), None) == []


def test_summary_is_repeated_when_telegram_failed(storage):
    runs(storage, [""], evening(), 20, FakeNotifier(fail=True))
    assert len(runs(storage, [""], evening(20, 20), 20)) == 1

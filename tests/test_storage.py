import sqlite3

from storage import Storage


def test_storage_remembers_lots_between_runs(tmp_path):
    path = str(tmp_path / "t.db")
    first = Storage(path)
    assert not first.is_seen("uzex_etender", "1")
    first.mark("uzex_etender", "1", True, "Баннер")
    first.mark("uzex_etender", "1", False, "повторная отметка ничего не меняет")
    assert first.is_seen("uzex_etender", "1")
    assert not first.is_seen("uzex_auction", "1")   # тот же номер на другой площадке — другой лот
    assert not first.is_seen("uzex_etender", "2")
    first.close()

    second = Storage(path)                           # бот перезапустили
    assert second.is_seen("uzex_etender", "1")
    second.close()


def test_storage_keeps_what_was_decided_about_the_lot(tmp_path):
    path = str(tmp_path / "t.db")
    store = Storage(path)
    store.mark("a", "1", True, "Б" * 500)
    store.mark("a", "2", False)
    store.close()

    rows = sqlite3.connect(path).execute("SELECT lot_id, matched, title, first_seen FROM lots ORDER BY lot_id").fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("1", 1, "Б" * 300), ("2", 0, "")]
    assert len(rows[0][3]) == len("2026-11-09T13:00:00")   # время первого просмотра, до секунд

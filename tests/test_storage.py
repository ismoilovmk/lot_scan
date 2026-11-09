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


def test_duplicate_means_same_fingerprint_already_sent_and_still_open(tmp_path):
    store = Storage(str(tmp_path / "t.db"))
    store.mark("a", "1", True, "Баннер", "отпечаток", "2026-11-16T09:00:00")
    assert store.is_duplicate("отпечаток", "2026-11-10T00:00:00")
    assert store.is_duplicate("отпечаток", "2026-11-16T09:00:00")      # срок ещё не вышел
    assert not store.is_duplicate("отпечаток", "2026-11-16T09:00:01")  # объявлен заново после срока — новый шанс
    assert not store.is_duplicate("другой", "2026-11-10T00:00:00")
    store.close()


def test_lot_that_was_not_sent_does_not_block_a_copy(tmp_path):
    store = Storage(str(tmp_path / "t.db"))
    store.mark("a", "1", False, "Крахмал", "отпечаток", "2026-11-16T09:00:00")
    assert not store.is_duplicate("отпечаток", "2026-11-10T00:00:00")
    store.close()


def test_sent_lot_without_deadline_stays_a_duplicate(tmp_path):
    store = Storage(str(tmp_path / "t.db"))
    store.mark("a", "1", True, "Баннер", "отпечаток", "")
    assert store.is_duplicate("отпечаток", "2999-01-01T00:00:00")
    store.close()


def test_empty_fingerprint_is_never_a_duplicate(tmp_path):
    store = Storage(str(tmp_path / "t.db"))
    store.mark("a", "1", True, "", "", "")
    assert not store.is_duplicate("", "2026-11-10T00:00:00")
    store.close()


def test_database_from_previous_version_keeps_working(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE lots (source TEXT NOT NULL, lot_id TEXT NOT NULL, first_seen TEXT NOT NULL,
                   matched INTEGER NOT NULL, title TEXT, PRIMARY KEY (source, lot_id))""")
    old.execute("INSERT INTO lots VALUES ('a', '1', '2026-11-09T13:00:00', 1, 'Баннер')")
    old.commit()
    old.close()

    for _ in range(2):            # повторное открытие не падает
        store = Storage(path)
        assert store.is_seen("a", "1")
        store.mark("a", "2", True, "Вывеска", "отпечаток", "2026-11-16T09:00:00")
        assert store.is_duplicate("отпечаток", "2026-11-10T00:00:00")
        store.close()

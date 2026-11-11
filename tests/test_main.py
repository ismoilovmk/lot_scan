import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fakes import FakeNotifier, FakeSource, make_lot

import main as bot
import notifier as notifier_module
from filters import LotFilter, fingerprint
from notifier import ConsoleNotifier, TelegramNotifier
from storage import Storage

CFG = {"services": {"Реклама": ["баннер"]}, "regions": {"Свои": ["ферган"]}, "allow_unknown_region": True}
NOW = datetime(2026, 11, 9, 12, 0, 0)


@pytest.fixture
def storage(tmp_path):
    store = Storage(str(tmp_path / "lots.db"))
    yield store
    store.close()


def forget_env(monkeypatch, *names):
    """Убирает переменные окружения на время теста; после теста всё возвращается как было,
    даже если код под тестом успел их задать."""
    for name in names:
        monkeypatch.setenv(name, "временно")
        monkeypatch.delenv(name)


def remembered(storage):
    """Что бот записал в базу о каждом лоте: {id лота: подошёл ли он}."""
    return {lot_id: bool(matched) for lot_id, matched in storage.conn.execute("SELECT lot_id, matched FROM lots")}


def scan(source, storage, notifier=None, dry_run=False, cfg=CFG):
    notifier = notifier or FakeNotifier()
    stats = bot.scan_source(source, None, cfg, LotFilter(cfg), storage, notifier, dry_run)
    return stats, notifier


# --- один проход по площадке ---

def test_matching_lot_is_sent_once(storage):
    source = FakeSource([make_lot("1", number="2611", customer="Хокимият")])
    stats, notifier = scan(source, storage)
    assert stats == {"listed": 1, "new": 1, "in_region": 1, "sent": 1}
    assert len(notifier.sent) == 1
    assert "<b>Изготовление баннера</b>" in notifier.sent[0]
    assert "Услуга: Реклама" in notifier.sent[0]
    assert "Совпало: баннер" in notifier.sent[0]
    assert "https://example.test/lot/1" in notifier.sent[0]

    stats, notifier = scan(source, storage)
    assert stats == {"listed": 1, "new": 0, "in_region": 0, "sent": 0}
    assert notifier.sent == []


def test_keyword_found_only_in_lot_details_still_matches(storage):
    source = FakeSource([make_lot("1", title="Услуги печатные")], details={"1": "баннер 3х6"})
    stats, notifier = scan(source, storage)
    assert stats["sent"] == 1
    assert "<b>Услуги печатные</b>" in notifier.sent[0]


def test_lot_from_priority_region_is_marked(storage):
    cfg = {**CFG, "regions": {"Фергана": ["ферган"], "Ташкент": ["ташкент"]}, "priority_region": "Фергана"}
    lots = [make_lot("1", customer="А"), make_lot("2", region="город Ташкент", customer="Б")]
    _, notifier = scan(FakeSource(lots), storage, cfg=cfg)
    assert [text.splitlines()[0] for text in notifier.sent] == ["🟢 Фергана", "<b>Изготовление баннера</b>"]


TWO_CHATS = {**CFG, "services": {"Реклама": ["баннер"], "Перевозка": ["юк ташиш"]}, "service_chats": {"Перевозка": "-200"}}


def test_lot_goes_to_the_chat_of_its_service(storage):
    lots = [make_lot("1", customer="А"), make_lot("2", title="Юк ташиш хизмати", customer="Б")]
    stats, notifier = scan(FakeSource(lots), storage, cfg=TWO_CHATS)
    assert stats["sent"] == 2
    assert notifier.chats == ["", "-200"]
    assert "Услуга: Перевозка" in notifier.sent[1] and "Реклама" not in notifier.sent[1]


def test_lot_about_services_of_two_chats_goes_to_both(storage):
    lot = make_lot("1", title="Баннер ва юк ташиш хизмати")
    stats, notifier = scan(FakeSource([lot]), storage, cfg=TWO_CHATS)
    assert stats["sent"] == 1                                   # лот один, сообщений два
    assert notifier.chats == ["", "-200"]
    assert "Услуга: Реклама" in notifier.sent[0] and "Перевозка" not in notifier.sent[0]
    assert "Услуга: Перевозка" in notifier.sent[1]
    assert scan(FakeSource([lot]), storage, cfg=TWO_CHATS)[1].sent == []


def test_same_lot_under_another_number_is_sent_once(storage):
    copy = {"customer": "Хокимият", "price": 500.0}
    source = FakeSource([make_lot("1", **copy), make_lot("2", title=" изготовление БАННЕРА ", **copy)])
    stats, notifier = scan(source, storage)
    assert stats == {"listed": 2, "new": 2, "in_region": 2, "sent": 1}
    assert len(notifier.sent) == 1
    assert "https://example.test/lot/1" in notifier.sent[0]
    assert scan(source, storage)[0]["new"] == 0   # копию запомнили, больше не рассматриваем


def test_same_lot_on_another_platform_is_sent_once(storage):
    copy = {"customer": "Хокимият", "price": 500.0}
    scan(FakeSource([make_lot("1", source="a", **copy)], key="a"), storage)
    stats, notifier = scan(FakeSource([make_lot("77", source="b", **copy)], key="b"), storage)
    assert (stats["sent"], notifier.sent) == (0, [])


def test_copy_of_a_lot_is_recorded_as_not_sent(storage):
    copy = {"customer": "Хокимият", "price": 500.0}
    scan(FakeSource([make_lot("1", **copy), make_lot("2", **copy)]), storage)
    assert remembered(storage) == {"1": True, "2": False}


def test_lots_that_differ_are_both_sent(storage):
    source = FakeSource([make_lot("1", customer="Хокимият", price=500.0), make_lot("2", customer="Банк", price=500.0),
                         make_lot("3", customer="Хокимият", price=900.0)])
    assert scan(source, storage)[0]["sent"] == 3


def test_expired_copy_does_not_block_a_new_announcement(storage):
    copy = {"customer": "Хокимият", "price": 500.0}
    storage.mark("fake", "old", True, "Изготовление баннера", fingerprint(make_lot("x", **copy)), "2000-01-01T00:00:00")
    assert scan(FakeSource([make_lot("1", **copy)]), storage)[0]["sent"] == 1


def test_copy_found_only_after_details_are_loaded_is_not_sent(storage):
    # у некоторых площадок настоящее название появляется только в подробностях
    class Enriching(FakeSource):
        def enrich(self, client, lot):
            lot.title = "Баннер для школы"
            return lot

    source = Enriching([make_lot("1", title="Услуги рекламные"), make_lot("2", title="Услуги прочие рекламные")])
    assert scan(source, storage)[0]["sent"] == 1


def test_lot_from_other_region_is_skipped_without_loading_details(storage):
    source = FakeSource([make_lot("1", region="Сурхандарьинская область")])
    stats, notifier = scan(source, storage)
    assert stats == {"listed": 1, "new": 1, "in_region": 0, "sent": 0}
    assert (notifier.sent, source.enriched) == ([], [])
    assert scan(source, storage)[0]["new"] == 0  # запомнили, второй раз не смотрим


def test_lot_without_keywords_is_remembered_but_not_sent(storage):
    source = FakeSource([make_lot("1", title="Картофельный крахмал")])
    stats, notifier = scan(source, storage)
    assert stats == {"listed": 1, "new": 1, "in_region": 1, "sent": 0}
    assert (notifier.sent, source.enriched) == ([], ["1"])
    assert scan(source, storage)[0]["new"] == 0


def test_lot_with_unknown_region_is_sent(storage):
    stats, _ = scan(FakeSource([make_lot("1", region="")]), storage)
    assert stats["sent"] == 1


def test_expired_lot_is_ignored_and_not_remembered(storage):
    source = FakeSource([make_lot("1", deadline="2000-01-01T00:00:00")])
    stats, notifier = scan(source, storage)
    assert stats == {"listed": 1, "new": 0, "in_region": 0, "sent": 0}
    assert notifier.sent == []
    assert not storage.is_seen("fake", "1")


def test_lot_without_deadline_is_not_treated_as_expired(storage):
    stats, _ = scan(FakeSource([make_lot("1", deadline="")]), storage)
    assert stats["sent"] == 1


def test_database_records_which_lots_matched(storage):
    source = FakeSource([make_lot("1"), make_lot("2", region="Сурхандарьинская область"),
                         make_lot("3", title="Крахмал")])
    scan(source, storage)
    assert remembered(storage) == {"1": True, "2": False, "3": False}


def test_dry_run_shows_lots_but_remembers_nothing(storage):
    source = FakeSource([make_lot("1"), make_lot("2", region="Сурхандарьинская область"),
                         make_lot("3", title="Крахмал")])
    for _ in range(2):  # второй пробный проход показывает то же самое
        stats, notifier = scan(source, storage, dry_run=True)
        assert stats == {"listed": 3, "new": 3, "in_region": 2, "sent": 1}
        assert len(notifier.sent) == 1
    assert not any(storage.is_seen("fake", lot_id) for lot_id in "123")


def test_lot_whose_details_failed_is_retried_next_time_and_others_go_on(storage, caplog):
    source = FakeSource([make_lot("1", customer="Хокимият"), make_lot("2", customer="Банк")], broken_ids={"1"})
    with caplog.at_level(logging.WARNING):
        stats, notifier = scan(source, storage)
    assert stats == {"listed": 2, "new": 2, "in_region": 2, "sent": 1}
    assert "https://example.test/lot/2" in notifier.sent[0]
    assert "Лот fake 1: подробности не получены (HTTP 500)" in caplog.text

    source.broken_ids.clear()  # сайт починился
    stats, notifier = scan(source, storage)
    assert stats == {"listed": 2, "new": 1, "in_region": 1, "sent": 1}
    assert "https://example.test/lot/1" in notifier.sent[0]


def test_lot_is_not_remembered_when_telegram_fails(storage):
    source = FakeSource([make_lot("1")])
    with pytest.raises(RuntimeError, match="Telegram недоступен"):
        scan(source, storage, FakeNotifier(fail=True))
    assert not storage.is_seen("fake", "1")
    assert scan(source, storage)[0]["sent"] == 1  # Telegram ожил — лот ушёл


# --- срок подачи ---

def test_lot_expires_only_after_its_deadline():
    assert bot.is_expired("2026-11-09T11:59:59", NOW)
    assert not bot.is_expired("2026-11-09T12:00:00", NOW)
    assert not bot.is_expired("2026-11-09T12:00:01", NOW)


@pytest.mark.parametrize("value", ["", None, "скоро"])
def test_unreadable_deadline_is_not_expired(value):
    assert not bot.is_expired(value, NOW)


def test_now_is_tashkent_time_without_timezone():
    now = bot.tashkent_now()
    assert now.tzinfo is None
    assert abs(now - (datetime.utcnow() + timedelta(hours=5))) < timedelta(seconds=5)


# --- проход по всем площадкам ---

@pytest.fixture
def project(tmp_path, monkeypatch):
    """Пустая папка проекта вместо настоящей: своя база, свой config.yaml и .env."""
    monkeypatch.setattr(bot, "ROOT", tmp_path)
    forget_env(monkeypatch, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    return tmp_path


def use_sources(monkeypatch, *sources):
    monkeypatch.setattr(bot, "ALL_SOURCES", list(sources))


def test_run_checks_only_enabled_sources(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("1", source="a")], key="a"),
                FakeSource([make_lot("2", source="b")], key="b"),
                FakeSource([make_lot("3", source="c")], key="c"))
    notifier = FakeNotifier()
    bot.run_once({**CFG, "sources": {"a": True, "b": False}}, notifier, dry_run=False)
    assert len(notifier.sent) == 1
    assert "https://example.test/lot/1" in notifier.sent[0]


def test_run_without_sources_section_checks_nothing(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("1")], key="a"))
    notifier = FakeNotifier()
    bot.run_once(CFG, notifier, dry_run=False)
    assert notifier.sent == []


def test_single_source_can_be_run_even_if_disabled(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("1", source="a")], key="a"),
                FakeSource([make_lot("2", source="b")], key="b"))
    notifier = FakeNotifier()
    bot.run_once({**CFG, "sources": {"a": True, "b": False}}, notifier, dry_run=False, only="b")
    assert len(notifier.sent) == 1
    assert "https://example.test/lot/2" in notifier.sent[0]


def test_broken_source_does_not_stop_the_others(project, monkeypatch, caplog):
    use_sources(monkeypatch, FakeSource([], key="a", fail_listing=True),
                FakeSource([make_lot("2", source="b")], key="b"))
    notifier = FakeNotifier()
    with caplog.at_level(logging.INFO):
        failed = bot.run_once({**CFG, "sources": {"a": True, "b": True}}, notifier, dry_run=False)
    assert failed == ["a"]
    assert len(notifier.sent) == 1
    assert "a: проход прерван из-за ошибки" in caplog.text
    assert "сайт недоступен" in caplog.text
    assert "b: в списке 1, новых 1, в нужном регионе 1, отправлено 1" in caplog.text


def test_run_reports_no_failures_when_all_sources_work(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("1", source="a")], key="a"))
    assert bot.run_once({**CFG, "sources": {"a": True}}, FakeNotifier(), dry_run=False) == []


def test_telegram_failure_counts_as_failed_source(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("1", source="a")], key="a"),
                FakeSource([], key="b"))
    cfg = {**CFG, "sources": {"a": True, "b": True}}
    assert bot.run_once(cfg, FakeNotifier(fail=True), dry_run=False) == ["a"]


def test_run_remembers_sent_lots_in_project_database(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("1", source="a")], key="a"))
    cfg = {**CFG, "sources": {"a": True}}
    first, second = FakeNotifier(), FakeNotifier()
    bot.run_once(cfg, first, dry_run=False)
    bot.run_once(cfg, second, dry_run=False)
    assert (len(first.sent), len(second.sent)) == (1, 0)
    assert (project / "lots.db").exists()


def test_new_word_in_vocabulary_brings_back_open_lots_rejected_before(project, monkeypatch, caplog):
    lots = [make_lot("1", source="a"), make_lot("2", source="a", title="Флаер тайёрлаш")]
    use_sources(monkeypatch, FakeSource(lots, key="a"))
    cfg = {**CFG, "sources": {"a": True}}
    wider = {**cfg, "services": {"Реклама": ["баннер"], "Полиграфия": ["флаер"]}}
    first, second, third, fourth = FakeNotifier(), FakeNotifier(), FakeNotifier(), FakeNotifier()
    bot.run_once(cfg, first, dry_run=False)
    bot.run_once(cfg, second, dry_run=False)
    with caplog.at_level(logging.INFO):
        bot.run_once(wider, third, dry_run=False)
    bot.run_once(wider, fourth, dry_run=False)
    assert [len(n.sent) for n in (first, second, third, fourth)] == [1, 0, 1, 0]
    assert "<b>Флаер тайёрлаш</b>" in third.sent[0]
    assert caplog.text.count("Слова или регионы изменились") == 1


def test_dry_run_with_new_vocabulary_forgets_nothing(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("2", source="a", title="Флаер тайёрлаш")], key="a"))
    cfg = {**CFG, "sources": {"a": True}}
    wider = {**cfg, "services": {"Полиграфия": ["флаер"]}}
    bot.run_once(cfg, FakeNotifier(), dry_run=False)
    bot.run_once(wider, FakeNotifier(), dry_run=True)
    after = FakeNotifier()
    bot.run_once(cfg, after, dry_run=False)        # прежний словарь: пробный проход ничего не сбросил
    assert after.sent == []


def test_run_tells_when_a_source_keeps_failing(project, monkeypatch):
    broken = FakeSource([], key="a", fail_listing=True)
    broken.title = "Площадка А"
    use_sources(monkeypatch, broken, FakeSource([], key="b"))
    cfg = {**CFG, "sources": {"a": True, "b": True}}
    notifier = FakeNotifier()
    for _ in range(2):
        bot.run_once(cfg, notifier, dry_run=False)
    assert notifier.sent == []
    assert bot.run_once(cfg, notifier, dry_run=False) == ["a"]
    assert notifier.sent == ["⚠️ Площадка А не отвечает уже 3 проверки подряд. Лоты с неё пока не приходят."]


def test_dry_run_sends_no_service_messages(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([], key="a", fail_listing=True))
    monkeypatch.setattr(bot, "tashkent_now", lambda: datetime(2026, 11, 10, 21, 0, 0))
    notifier = FakeNotifier()
    for _ in range(4):
        bot.run_once({**CFG, "sources": {"a": True}, "daily_summary_hour": 20}, notifier, dry_run=True)
    assert notifier.sent == []


def test_run_sends_summary_of_the_day_in_tashkent_time(project, monkeypatch):
    lots = [make_lot("1", source="a"), make_lot("2", source="a", title="Крахмал")]
    use_sources(monkeypatch, FakeSource(lots, key="a"), FakeSource([], key="off"))
    cfg = {**CFG, "sources": {"a": True}, "daily_summary_hour": 20}
    notifier = FakeNotifier()
    monkeypatch.setattr(bot, "tashkent_now", lambda: datetime(2026, 11, 10, 19, 40, 0))
    bot.run_once(cfg, notifier, dry_run=False)
    assert len(notifier.sent) == 1                       # только сам лот
    monkeypatch.setattr(bot, "tashkent_now", lambda: datetime(2026, 11, 10, 20, 0, 0))
    bot.run_once(cfg, notifier, dry_run=False)
    assert notifier.sent[1:] == [
        "📊 Итог дня 10.11: новых лотов просмотрено — 2, отправлено — 1. Все площадки отвечают."]


def test_run_without_summary_setting_sends_no_summary(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([], key="a"))
    monkeypatch.setattr(bot, "tashkent_now", lambda: datetime(2026, 11, 10, 23, 0, 0))
    notifier = FakeNotifier()
    bot.run_once({**CFG, "sources": {"a": True}}, notifier, dry_run=False)
    assert notifier.sent == []


TRANSPORT = {**CFG, "sources": {"a": True}, "services": {"Реклама": ["баннер"], "Перевозка": ["юк ташиш"]},
             "service_chats": {"Перевозка": "TELEGRAM_CHAT_ID_TRANSPORT"}}


def transport_lots(monkeypatch):
    forget_env(monkeypatch, "TELEGRAM_CHAT_ID_TRANSPORT")
    lots = [make_lot("1", source="a", customer="А"), make_lot("2", source="a", title="Юк ташиш хизмати", customer="Б")]
    use_sources(monkeypatch, FakeSource(lots, key="a"))


def test_service_chat_is_taken_from_environment(project, monkeypatch):
    transport_lots(monkeypatch)
    monkeypatch.setenv("TELEGRAM_CHAT_ID_TRANSPORT", "-200")
    notifier = FakeNotifier()
    bot.run_once(TRANSPORT, notifier, dry_run=False)
    assert notifier.chats == ["", "-200"]


def test_service_without_its_chat_waits_until_the_chat_is_set(project, monkeypatch, caplog):
    transport_lots(monkeypatch)
    first, second, third = FakeNotifier(), FakeNotifier(), FakeNotifier()
    with caplog.at_level(logging.WARNING):
        bot.run_once(TRANSPORT, first, dry_run=False)
    assert first.chats == [""]                                  # реклама ушла, перевозка — нет
    assert "Перевозка: не задан TELEGRAM_CHAT_ID_TRANSPORT, лоты по этой услуге пока не ищу" in caplog.text
    monkeypatch.setenv("TELEGRAM_CHAT_ID_TRANSPORT", "-200")
    bot.run_once(TRANSPORT, second, dry_run=False)
    bot.run_once(TRANSPORT, third, dry_run=False)
    assert second.chats == ["-200"] and "<b>Юк ташиш хизмати</b>" in second.sent[0]   # лот не потерян
    assert third.sent == []


def test_dry_run_shows_lots_of_every_chat_even_without_settings(project, monkeypatch):
    transport_lots(monkeypatch)
    notifier = FakeNotifier()
    bot.run_once(TRANSPORT, notifier, dry_run=True)
    assert notifier.chats == ["", "TELEGRAM_CHAT_ID_TRANSPORT"]


def test_run_passes_dry_run_through(project, monkeypatch):
    use_sources(monkeypatch, FakeSource([make_lot("1", source="a")], key="a"))
    cfg = {**CFG, "sources": {"a": True}}
    for _ in range(2):
        notifier = FakeNotifier()
        bot.run_once(cfg, notifier, dry_run=True)
        assert len(notifier.sent) == 1


class ClientSpy(FakeSource):
    def list_lots(self, client, cfg):
        self.pause = client.pause
        self.host_pauses = client.host_pauses
        return iter([])


@pytest.mark.parametrize("cfg_extra, pause", [({}, 0.5), ({"request_pause_seconds": 1.5}, 1.5)])
def test_run_uses_request_pause_from_config(project, monkeypatch, cfg_extra, pause):
    spy = ClientSpy([], key="a")
    use_sources(monkeypatch, spy)
    bot.run_once({**CFG, "sources": {"a": True}, **cfg_extra}, FakeNotifier(), dry_run=False)
    assert spy.pause == pause


@pytest.mark.parametrize("cfg_extra, expected", [({}, {}), ({"host_pauses": {"api.xt-xarid.uz": 65}}, {"api.xt-xarid.uz": 65})])
def test_run_uses_per_site_pauses_from_config(project, monkeypatch, cfg_extra, expected):
    spy = ClientSpy([], key="a")
    use_sources(monkeypatch, spy)
    bot.run_once({**CFG, "sources": {"a": True}, **cfg_extra}, FakeNotifier(), dry_run=False)
    assert spy.host_pauses == expected


def test_real_config_enables_xt_xarid_with_a_minute_between_requests():
    cfg = yaml.safe_load((Path(bot.__file__).parent / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["sources"]["xt_xarid"] is True
    assert cfg["host_pauses"]["api.xt-xarid.uz"] >= 61     # из-за рубежа сайт даёт 1 запрос в 60 секунд
    assert "33.2466" in cfg["xt_xarid_regions"]            # Ферганская область
    for key in ("xt_xarid", "uzex_civil", "tendergpt"):
        assert cfg["sources"][key] is True
        assert key in [source.key for source in bot.ALL_SOURCES]


# --- .env ---

def test_env_file_is_loaded_without_overriding_existing_values(tmp_path, monkeypatch):
    forget_env(monkeypatch, "RM_TOKEN", "RM_CHAT", "RM_QUOTED", "RM_SINGLE", "RM_URL", "RM_COMMENTED")
    monkeypatch.setenv("RM_CHAT", "уже задан")
    env = tmp_path / ".env"
    env.write_text(
        "# комментарий\n"
        "\n"
        " RM_TOKEN = 123:ABC \n"
        "RM_CHAT=-100500\n"
        'RM_QUOTED="в кавычках"\n'
        "RM_SINGLE='одинарные'\n"
        "RM_URL=https://x.test/?a=b\n"
        "# RM_COMMENTED=1\n"
        "строка без знака равно\n",
        encoding="utf-8",
    )
    bot.load_env(env)
    assert os.environ["RM_TOKEN"] == "123:ABC"
    assert os.environ["RM_CHAT"] == "уже задан"
    assert os.environ["RM_QUOTED"] == "в кавычках"
    assert os.environ["RM_SINGLE"] == "одинарные"
    assert os.environ["RM_URL"] == "https://x.test/?a=b"
    assert "RM_COMMENTED" not in os.environ


def test_missing_env_file_is_fine(tmp_path):
    bot.load_env(tmp_path / "нет такого файла")


# --- выбор способа отправки ---

def test_dry_run_prints_instead_of_sending(project):
    assert isinstance(bot.make_notifier(dry_run=True), ConsoleNotifier)


def test_real_run_sends_to_chat_from_env(project, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100500")
    notifier = bot.make_notifier(dry_run=False)
    assert isinstance(notifier, TelegramNotifier)
    assert notifier.url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert notifier.chat_id == "-100500"


@pytest.mark.parametrize("present", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", None])
def test_real_run_without_full_telegram_settings_stops_with_hint(project, monkeypatch, present):
    if present:
        monkeypatch.setenv(present, "x")
    with pytest.raises(SystemExit, match="Не заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID"):
        bot.make_notifier(dry_run=False)


# --- команда chatid ---

def test_chatid_needs_token(project):
    with pytest.raises(SystemExit, match="Сначала впишите TELEGRAM_BOT_TOKEN"):
        bot.show_chats()


def test_chatid_lists_chats_for_token(project, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    asked = []
    monkeypatch.setattr(bot, "find_chats", lambda token: asked.append(token) or [("111", "Bilol (личный чат)"), ("-5", "Лоты (группа)")])
    bot.show_chats()
    out = capsys.readouterr().out
    assert asked == ["123:ABC"]
    assert "впишите в .env как TELEGRAM_CHAT_ID" in out
    assert "  111   Bilol (личный чат)\n  -5   Лоты (группа)\n" in out


def test_chatid_explains_when_nobody_wrote_to_bot(project, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(bot, "find_chats", lambda token: [])
    with pytest.raises(SystemExit, match="Боту пока никто не писал"):
        bot.show_chats()


def test_chatid_shows_telegram_error_as_plain_message(project, monkeypatch):
    def refuse(token):
        raise RuntimeError("Telegram не принял токен.")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "плохой")
    monkeypatch.setattr(bot, "find_chats", refuse)
    with pytest.raises(SystemExit, match="Telegram не принял токен."):
        bot.show_chats()


# --- журнал работы ---

def test_log_goes_to_file_in_utf8(tmp_path):
    root = logging.getLogger()
    saved, saved_level = root.handlers[:], root.level
    try:
        bot.setup_logging(tmp_path / "bot.log")
        logging.getLogger("bot").info("проверка журнала")
        logging.getLogger("bot").debug("отладка не пишется")
        for handler in root.handlers:
            handler.flush()
        text = (tmp_path / "bot.log").read_text(encoding="utf-8")
        assert "INFO проверка журнала" in text
        assert "отладка" not in text
        assert any(type(h) is logging.StreamHandler for h in root.handlers)
    finally:
        for handler in root.handlers:
            if handler not in saved:
                handler.close()
        root.handlers[:] = saved
        root.setLevel(saved_level)


# --- командная строка ---

@pytest.fixture
def cli(project, monkeypatch):
    """cli(*аргументы) запускает бота как из терминала, в пустой папке проекта."""
    cfg = {**CFG, "interval_minutes": 7, "sources": {"a": True, "b": False}, "shop_keywords": ["баннер", "оракал"]}
    (project / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (project / ".env").write_text("TELEGRAM_BOT_TOKEN=123:ABC\nTELEGRAM_CHAT_ID=-100500\n", encoding="utf-8")
    use_sources(monkeypatch, FakeSource([make_lot("1", source="a")], key="a"),
                FakeSource([make_lot("2", source="b")], key="b"))
    logged = []
    monkeypatch.setattr(bot, "setup_logging", logged.append)

    posts = []

    class Ok:
        status_code, ok = 200, True

    monkeypatch.setattr(notifier_module.requests, "post", lambda url, json, timeout: posts.append((url, json)) or Ok())
    monkeypatch.setattr(notifier_module.time, "sleep", lambda seconds: None)

    def run(*argv):
        bot.main(list(argv))

    run.posts, run.logged, run.project = posts, logged, project
    return run


def test_cli_dry_run_prints_lot_and_sends_nothing(cli, capsys):
    cli("run", "--dry-run")
    out = capsys.readouterr().out
    assert "<b>Изготовление баннера</b>" in out
    assert "https://example.test/lot/1" in out and "lot/2" not in out
    assert cli.posts == []
    assert cli.logged == [cli.project / "bot.log"]


def test_cli_run_sends_lot_to_chat_from_env_file(cli):
    cli("run")
    assert len(cli.posts) == 1
    url, payload = cli.posts[0]
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert payload["chat_id"] == "-100500"
    assert "https://example.test/lot/1" in payload["text"]


def test_cli_source_option_runs_one_source(cli, capsys):
    cli("run", "--dry-run", "--source", "b")
    out = capsys.readouterr().out
    assert "lot/2" in out and "lot/1" not in out


def test_cli_test_command_sends_hello(cli, capsys):
    cli("test")
    assert [p[1]["text"] for p in cli.posts] == ["Проверка связи: бот Reklama Master подключён и может присылать лоты."]
    assert "Сообщение отправлено" in capsys.readouterr().out


def test_cli_test_command_explains_wrong_chat_instead_of_traceback(cli, monkeypatch, capsys):
    class Refused:
        status_code, ok = 400, False
        text = '{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}'

    monkeypatch.setattr(notifier_module.requests, "post", lambda url, json, timeout: Refused())
    with pytest.raises(SystemExit) as stop:
        cli("test")
    message = str(stop.value)
    assert "Telegram ответил 400" in message and "chat not found" in message
    assert "Проверьте TELEGRAM_CHAT_ID" in message and "python main.py chatid" in message
    assert "Сообщение отправлено" not in capsys.readouterr().out


def test_cli_chatid_works_with_token_only(cli, monkeypatch, capsys):
    (cli.project / ".env").write_text("TELEGRAM_BOT_TOKEN=123:ABC\n", encoding="utf-8")
    monkeypatch.setattr(bot, "find_chats", lambda token: [("111", "Bilol (личный чат)")])
    cli("chatid")
    assert "111   Bilol (личный чат)" in capsys.readouterr().out
    assert cli.posts == []


def test_cli_prices_prints_report_for_configured_words(cli, monkeypatch, capsys):
    seen = {}

    def fake_report(client, keywords):
        seen["pause"] = client.pause
        return f"отчёт по словам {keywords}"

    monkeypatch.setattr(bot, "price_report", fake_report)
    cli("prices", "--dry-run")
    assert "отчёт по словам ['баннер', 'оракал']" in capsys.readouterr().out
    assert seen["pause"] == 0.5


class StopLoop(Exception):
    pass


def test_cli_loop_repeats_after_configured_interval(cli, monkeypatch, capsys):
    naps = []

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 2:
            raise StopLoop

    monkeypatch.setattr(bot.time, "sleep", nap)
    with pytest.raises(StopLoop):
        cli("loop", "--dry-run")
    assert naps == [7 * 60, 7 * 60]
    assert capsys.readouterr().out.count("<b>Изготовление баннера</b>") == 2


def test_cli_run_ends_with_error_when_a_source_failed_but_still_sends_the_rest(cli, monkeypatch, capsys):
    # на сервере по коду выхода видно, что проход был неполным (GitHub пришлёт письмо)
    use_sources(monkeypatch, FakeSource([], key="a", fail_listing=True),
                FakeSource([make_lot("2", source="b")], key="b"),
                FakeSource([], key="c", fail_listing=True))
    (cli.project / "config.yaml").write_text(
        yaml.safe_dump({**CFG, "sources": {"a": True, "b": True, "c": True}}, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SystemExit) as stop:
        cli("run", "--dry-run")
    assert str(stop.value) == "Не удалось проверить площадки: a, c"
    assert "https://example.test/lot/2" in capsys.readouterr().out


def test_cli_run_ends_quietly_when_everything_worked(cli):
    cli("run", "--dry-run")   # SystemExit не возникает


def test_cli_loop_keeps_going_after_a_failed_source(cli, monkeypatch):
    use_sources(monkeypatch, FakeSource([], key="a", fail_listing=True))
    naps = []

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 2:
            raise StopLoop

    monkeypatch.setattr(bot.time, "sleep", nap)
    with pytest.raises(StopLoop):
        cli("loop", "--dry-run")
    assert len(naps) == 2


def test_cli_rejects_unknown_command(cli):
    with pytest.raises(SystemExit):
        cli("взлететь")


# --- цепочка запусков на GitHub: каждая проверка назначает следующую ---

HOURS = {"interval_minutes": 20, "work_hours": [7, 20]}


def at(hour, minute, day=10):
    return datetime(2026, 11, day, hour, minute, 0)


@pytest.mark.parametrize("previous, now, expected", [
    (at(12, 0), at(12, 6), at(12, 20)),            # через 20 минут после начала прошлой проверки
    (at(12, 0), at(12, 25), at(12, 25)),           # прошлая проверка затянулась — сразу
    (at(6, 50), at(6, 55), at(7, 10)),
    (at(20, 39), at(20, 45), at(20, 59)),          # последний рабочий час — до его конца
    (at(20, 45), at(20, 50), at(7, 0, day=11)),    # вечером — на утро следующего дня
    (at(23, 50), at(23, 55), at(7, 0, day=11)),
    (at(21, 0), at(2, 0, day=11), at(7, 0, day=11)),   # ночью — на утро этого же дня
    (at(6, 30), at(6, 35), at(7, 0)),
])
def test_next_check_is_due_after_interval_but_only_in_work_hours(previous, now, expected):
    assert bot.next_check(previous, now, HOURS) == expected


def test_without_work_hours_bot_checks_around_the_clock():
    assert bot.next_check(at(23, 50), at(23, 55), {"interval_minutes": 30}) == at(0, 20, day=11)
    assert bot.next_check(at(3, 0), at(3, 1), {}) == at(3, 20)          # интервал по умолчанию — 20 минут


def waiting(cli, monkeypatch, now, *argv):
    """Запускает команду wait в заданный момент; возвращает, на сколько секунд бот уснул."""
    slept = []
    monkeypatch.setattr(bot, "tashkent_now", lambda: now)
    monkeypatch.setattr(bot.time, "sleep", slept.append)
    cli("wait", *argv)
    return slept


def epoch(moment):
    return str(int(moment.replace(tzinfo=bot.TASHKENT).timestamp()))


def test_cli_wait_sleeps_until_interval_after_previous_check(cli, monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        assert waiting(cli, monkeypatch, at(12, 3), "--since", epoch(at(12, 0))) == [4 * 60]   # интервал в тесте — 7 минут
    assert "Следующая проверка в 10.11 12:07, жду 4 мин" in caplog.text


def test_cli_wait_does_not_sleep_when_check_is_overdue(cli, monkeypatch):
    assert waiting(cli, monkeypatch, at(12, 30), "--since", epoch(at(12, 0))) == [0]


@pytest.mark.parametrize("argv", [(), ("--since", "")])
def test_cli_wait_without_previous_check_sleeps_whole_interval(cli, monkeypatch, argv):
    assert waiting(cli, monkeypatch, at(12, 0), *argv) == [7 * 60]


def test_cli_wait_at_night_sleeps_at_most_five_hours(cli, monkeypatch):
    cfg = {**CFG, **HOURS}
    (cli.project / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert waiting(cli, monkeypatch, at(21, 0)) == [5 * 3600]                       # до утра 10 часов
    assert waiting(cli, monkeypatch, at(2, 0, day=11)) == [5 * 3600]                # ровно пять часов до 07:00
    assert waiting(cli, monkeypatch, at(6, 0, day=11)) == [3600]


def test_cli_wait_needs_no_telegram_settings(cli, monkeypatch):
    (cli.project / ".env").unlink()
    assert waiting(cli, monkeypatch, at(12, 0)) == [7 * 60]
    assert cli.posts == []


def night_config(cli):
    cfg = {**CFG, **HOURS, "sources": {"a": True}}
    (cli.project / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")


@pytest.mark.parametrize("now, sent", [(at(6, 59), 0), (at(7, 0), 1), (at(20, 59), 1), (at(21, 0), 0)])
def test_cli_chain_run_skips_the_check_outside_work_hours(cli, monkeypatch, caplog, now, sent):
    night_config(cli)
    monkeypatch.setattr(bot, "tashkent_now", lambda: now)
    with caplog.at_level(logging.INFO):
        cli("run", "--work-hours-only")
    assert len(cli.posts) == sent
    assert ("Нерабочие часы: проверку пропускаю" in caplog.text) == (sent == 0)


def test_cli_manual_run_works_at_night_too(cli, monkeypatch):
    night_config(cli)
    monkeypatch.setattr(bot, "tashkent_now", lambda: at(3, 0))
    cli("run")
    assert len(cli.posts) == 1


def test_real_config_work_hours_match_the_backup_schedule():
    cfg = yaml.safe_load((Path(bot.__file__).parent / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["work_hours"] == [7, 20]          # запасное расписание в scan.yml: с 07:00 до 20:59
    assert cfg["work_hours"][0] <= cfg["daily_summary_hour"] <= cfg["work_hours"][1]

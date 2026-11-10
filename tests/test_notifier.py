import pytest

import notifier
from notifier import (ConsoleNotifier, TelegramNotifier, chats_from_updates, find_chats,
                      format_deadline, format_lot, format_price)
from sources.base import Lot


# --- оформление сообщения ---

def test_price_is_shown_with_spaces_and_currency():
    assert format_price(79800000.0) == "79 800 000 сум"
    assert format_price(5980000.4, "Сом") == "5 980 000 сум"
    assert format_price(1000, "Сум") == "1 000 сум"
    assert format_price(1000, "") == "1 000 сум"
    assert format_price(1500, "USD") == "1 500 USD"
    assert format_price(0) == "0 сум"
    assert format_price(None) == "не указана"


def test_deadline_is_shown_as_local_date():
    assert format_deadline("2026-11-13T09:00:00") == "13.11.2026 09:00"
    assert format_deadline("завтра") == "завтра"
    assert format_deadline("") == "не указан"
    assert format_deadline(None) == "не указан"


def test_full_message_text():
    lot = Lot(
        source="uzex_etender", source_title="UzEX etender (отбор)", lot_id="5", number="2611",
        title="Баннер <3x6> & монтаж", customer='ООО "Хоким"', region="Ферганская область, Коканд",
        price=79800000.0, deadline="2026-11-13T09:00:00", url="https://etender.uzex.uz/lot/5?a=1&b=2",
    )
    assert format_lot(lot, {"Баннеры": ["баннер"], "Реклама": ["реклам", "reklama"]}) == "\n".join([
        "<b>Баннер &lt;3x6&gt; &amp; монтаж</b>",
        "",
        "Площадка: UzEX etender (отбор)",
        "Лот №: 2611",
        "Заказчик: ООО &quot;Хоким&quot;",
        "Регион: Ферганская область, Коканд",
        "Стартовая цена: 79 800 000 сум",
        "Срок подачи: 13.11.2026 09:00",
        "Услуга: Баннеры; Реклама",
        "Совпало: баннер, реклам, reklama",
        "",
        "https://etender.uzex.uz/lot/5?a=1&amp;b=2",
    ])


def test_message_for_lot_with_missing_fields():
    lot = Lot(source="s", source_title="Площадка", lot_id="77", title="Вывеска", currency="USD", price=10.0)
    lines = format_lot(lot, {"Вывески": ["вывеск"]}).split("\n")
    assert lines[3] == "Лот №: 77"            # нет номера — показываем id
    assert lines[4] == "Заказчик: не указан"
    assert lines[5] == "Регион: не указан"
    assert lines[6] == "Стартовая цена: 10 USD"
    assert lines[7] == "Срок подачи: не указан"


def test_long_title_is_cut_to_400_chars():
    def lot(title):
        return Lot(source="s", source_title="S", lot_id="1", title=title)

    assert format_lot(lot("я" * 400), {"x": ["x"]}).split("\n")[0] == "<b>" + "я" * 400 + "</b>"
    assert format_lot(lot("я" * 401), {"x": ["x"]}).split("\n")[0] == "<b>" + "я" * 400 + "…</b>"


def test_console_notifier_prints_message(capsys):
    ConsoleNotifier().send("привет")
    assert capsys.readouterr().out == "-" * 60 + "\nпривет\n"


# --- отправка в Telegram ---

class Reply:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self.ok = status < 400
        self.data = data or {}
        self.text = text

    def json(self):
        return self.data


@pytest.fixture
def telegram(monkeypatch):
    """telegram(*ответы) подменяет сеть: .posts — что отправили, .naps — сколько ждали."""

    class Net:
        posts, gets, naps, replies = [], [], [], []

        def __call__(self, *replies):
            self.posts, self.gets, self.naps, self.replies = [], [], [], list(replies)
            return self

    net = Net()

    def post(url, json, timeout):
        net.posts.append({"url": url, "json": json, "timeout": timeout})
        return net.replies.pop(0)

    def get(url, timeout):
        net.gets.append({"url": url, "timeout": timeout})
        return net.replies.pop(0)

    monkeypatch.setattr(notifier.requests, "post", post)
    monkeypatch.setattr(notifier.requests, "get", get)
    monkeypatch.setattr(notifier.time, "sleep", lambda seconds: net.naps.append(seconds))
    return net


def test_message_is_sent_to_chat_as_html(telegram):
    net = telegram(Reply())
    TelegramNotifier("123:ABC", "-100500").send("<b>Лот</b>")
    assert net.posts == [{
        "url": "https://api.telegram.org/bot123:ABC/sendMessage",
        "json": {"chat_id": "-100500", "text": "<b>Лот</b>", "parse_mode": "HTML",
                 "disable_web_page_preview": True},
        "timeout": 30,
    }]
    assert net.naps == [1.1]  # пауза после сообщения, чтобы не превысить лимит Telegram


def test_too_long_message_is_cut_to_telegram_limit(telegram):
    net = telegram(Reply(), Reply())
    bot = TelegramNotifier("t", "c", pause=0)
    bot.send("я" * 4000)
    bot.send("я" * 4001)
    assert [len(p["json"]["text"]) for p in net.posts] == [4000, 4000]
    assert net.naps == [0, 0]


def test_waits_as_long_as_telegram_asks_then_sends(telegram):
    net = telegram(Reply(429, {"parameters": {"retry_after": 7}}), Reply())
    TelegramNotifier("t", "c").send("x")
    assert len(net.posts) == 2
    assert net.naps == [8, 1.1]


def test_waits_six_seconds_when_telegram_gives_no_hint(telegram):
    net = telegram(Reply(429), Reply(429, {"parameters": {}}), Reply())
    TelegramNotifier("t", "c").send("x")
    assert net.naps == [6, 6, 1.1]


def test_gives_up_after_three_refusals(telegram):
    net = telegram(Reply(429), Reply(429), Reply(429), Reply())
    with pytest.raises(RuntimeError, match="Telegram не принял сообщение после трёх попыток"):
        TelegramNotifier("t", "c").send("x")
    assert len(net.posts) == 3


def test_telegram_error_is_reported_with_status_and_reason(telegram):
    net = telegram(Reply(400, text="Bad Request: chat not found" + "!" * 400), Reply())
    with pytest.raises(RuntimeError) as error:
        TelegramNotifier("t", "c").send("x")
    assert str(error.value) == "Telegram ответил 400: " + ("Bad Request: chat not found" + "!" * 400)[:300]
    assert len(net.posts) == 1
    assert net.naps == []


# --- поиск ID чата ---

def test_chats_from_updates():
    updates = [
        {"message": {"chat": {"id": 111, "type": "private", "first_name": "Bilol", "last_name": "I."}}},
        {"message": {"chat": {"id": 111, "type": "private", "first_name": "Bilol", "last_name": "I."}}},
        {"my_chat_member": {"chat": {"id": -1005, "type": "supergroup", "title": "Лоты"}}},
        {"channel_post": {"chat": {"id": -7, "type": "channel", "title": "Канал"}}},
        {"message": {"chat": {"id": 222, "type": "private", "last_name": "Только фамилия"}}},
        {"message": {"chat": {"id": 333, "type": "private", "username": "nick"}}},
        {"message": {"chat": {"id": 444, "type": "group"}}},
        {"edited_message": {"text": "без чата"}},
        {"message": None},
    ]
    assert chats_from_updates(updates) == [
        ("111", "Bilol I. (личный чат)"),
        ("-1005", "Лоты (группа)"),
        ("-7", "Канал (канал)"),
        ("222", "Только фамилия (личный чат)"),
        ("333", "nick (личный чат)"),
        ("444", "без названия (группа)"),
    ]
    assert chats_from_updates([]) == []


def test_find_chats_asks_telegram_who_wrote_to_bot(telegram):
    net = telegram(Reply(data={"result": [{"message": {"chat": {"id": 5, "type": "private", "first_name": "A"}}}]}))
    assert find_chats("123:ABC") == [("5", "A (личный чат)")]
    assert net.gets == [{"url": "https://api.telegram.org/bot123:ABC/getUpdates", "timeout": 30}]


def test_find_chats_with_no_updates(telegram):
    telegram(Reply(data={"ok": True}))
    assert find_chats("t") == []


@pytest.mark.parametrize("status", [401, 404])
def test_wrong_token_is_explained(telegram, status):
    telegram(Reply(status))
    with pytest.raises(RuntimeError, match="Telegram не принял токен. Проверьте TELEGRAM_BOT_TOKEN"):
        find_chats("плохой")


def test_other_telegram_failure_is_reported(telegram):
    telegram(Reply(500, text="oops" * 100))
    with pytest.raises(RuntimeError) as error:
        find_chats("t")
    assert str(error.value) == "Telegram ответил 500: " + ("oops" * 100)[:300]


def test_priority_region_is_marked_above_the_title():
    lot = Lot(source="s", source_title="S", lot_id="1", title="Баннер")
    lines = format_lot(lot, {"Баннеры <1>": ["баннер"]}, "Фергана & область").splitlines()
    assert lines[:2] == ["🟢 Фергана &amp; область", "<b>Баннер</b>"]
    assert "Услуга: Баннеры &lt;1&gt;" in lines
    assert format_lot(lot, {"Баннеры": ["баннер"]}, "").splitlines()[0] == "<b>Баннер</b>"

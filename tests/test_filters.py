import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filters import LotFilter, normalize
from notifier import chats_from_updates, format_deadline, format_lot, format_price
from sources.base import Lot
from storage import Storage

CFG = {
    "keywords": ["реклам", "баннер", "banner", "hajmli harf", "пешлавха"],
    "exclude_keywords": ["рекламац"],
    "regions": ["ферган", "фаргона", "fargona", "ташкент", "тошкент", "чилонзор"],
    "allow_unknown_region": True,
}


def test_normalize_uzbek_letters_and_apostrophes():
    assert normalize("Фарғона  ВИЛОЯТИ") == "фаргона вилояти"
    assert normalize("Farg‘ona") == normalize("Farg'ona") == "fargona"
    assert normalize("Ўзбекистон ҳудуди қ") == "узбекистон худуди к"
    assert normalize(None) == ""


def test_keywords_match_russian_uzbek_any_case():
    f = LotFilter(CFG)
    assert f.match_keywords("Изготовление БАННЕРОВ и вывесок") == ["баннер"]
    assert f.match_keywords("Tashqi banner tayyorlash") == ["banner"]
    assert f.match_keywords("Hajmli harflar o‘rnatish") == ["hajmli harf"]
    assert f.match_keywords("Пешлавҳа тайёрлаш") == ["пешлавха"]
    assert f.match_keywords("Услуги рекламные") == ["реклам"]
    assert f.match_keywords("Картофельный крахмал") == []


def test_exclude_phrase_removes_false_positive():
    f = LotFilter(CFG)
    assert f.match_keywords("Рассмотрение рекламаций по качеству") == []
    assert f.match_keywords("Рекламация и наружная реклама") == ["реклам"]


def test_region_filter():
    f = LotFilter(CFG)
    assert f.region_ok("Ферганская область, Коканд")
    assert f.region_ok("Фарғона вилояти")
    assert f.region_ok("город Ташкент, Мирабадский район")
    assert f.region_ok("Чилонзор тумани")
    assert not f.region_ok("Сурхандарьинская область, Термез")
    assert f.region_ok("")  # регион не указан — пропускаем
    assert not LotFilter({**CFG, "allow_unknown_region": False}).region_ok("")


def test_storage_remembers_lots(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    assert not s.is_seen("uzex_etender", "1")
    s.mark("uzex_etender", "1", True, "Баннер")
    s.mark("uzex_etender", "1", True, "Баннер")  # повтор не падает
    assert s.is_seen("uzex_etender", "1")
    assert not s.is_seen("uzex_auction", "1")
    s.close()


def test_chats_from_updates():
    updates = [
        {"message": {"chat": {"id": 111, "type": "private", "first_name": "Bilol"}}},
        {"message": {"chat": {"id": 111, "type": "private", "first_name": "Bilol"}}},
        {"my_chat_member": {"chat": {"id": -1005, "type": "supergroup", "title": "Лоты"}}},
        {"edited_message": {"text": "без чата"}},
    ]
    assert chats_from_updates(updates) == [("111", "Bilol (личный чат)"), ("-1005", "Лоты (группа)")]
    assert chats_from_updates([]) == []


def test_message_format():
    lot = Lot(
        source="uzex_etender", source_title="UzEX etender (отбор)", lot_id="5", number="2611",
        title="Баннер <3x6>", customer="Хокимият", region="Ферганская область",
        price=79800000.0, deadline="2026-11-13T09:00:00", url="https://etender.uzex.uz/lot/5",
    )
    text = format_lot(lot, ["баннер"])
    assert "<b>Баннер &lt;3x6&gt;</b>" in text
    assert "79 800 000 сум" in text
    assert "13.11.2026 09:00" in text
    assert "https://etender.uzex.uz/lot/5" in text
    assert format_price(None) == "не указана"
    assert format_deadline("") == "не указан"

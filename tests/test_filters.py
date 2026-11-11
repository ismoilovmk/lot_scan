import pytest

from filters import LotFilter, by_chat, fingerprint, normalize, vocabulary_signature
from sources.base import Lot

CFG = {
    "services": {"Реклама": ["реклам", "баннер", "banner", "hajmli harf", "пешлавха"]},
    "exclude_keywords": ["рекламац"],
    "regions": {"Свои": ["ферган", "фаргона", "fargona", "ташкент", "тошкент", "чилонзор"]},
    "allow_unknown_region": True,
}


def words(lot_filter, text):
    """Найденные слова подряд, без разбивки по услугам."""
    return [word for found in lot_filter.match(text).values() for word in found]


def same(*spellings):
    return len({normalize(s) for s in spellings}) == 1


def test_case_spaces_and_uzbek_letters_do_not_matter():
    assert same("Фарғона  ВИЛОЯТИ", "фаргона вилояти", " Фаргона\nвилояти ")
    assert same("Ўзбекистон ҳудуди Қ, ёлка", "узбекистон худуди к, елка")
    assert not same("фергана", "фаргона")
    assert normalize(None) == normalize("") == ""


def test_all_apostrophe_kinds_are_ignored():
    for apostrophe in "'’‘`ʻʼ´":
        assert same(f"Farg{apostrophe}ona", "fargona")


@pytest.mark.parametrize("mixed, plain", [
    ("бaннер", "баннер"),      # латинская a
    ("баннeр", "баннер"),      # латинская e
    ("pеклaмa", "реклама"),    # латинские p и a
    ("bаnnеr", "banner"),      # кириллические а и е в латинском слове
    ("oракал", "оракал"),      # латинская o
    ("cтeнд", "стенд"),        # латинские c и e
    ("xoкимият", "хокимият"),  # латинские x и o
    ("yлица", "улица"),        # латинская y
])
def test_latin_lookalikes_inside_cyrillic_words_do_not_matter(mixed, plain):
    assert mixed != plain and same(mixed, plain)


def test_keywords_match_russian_uzbek_any_case():
    f = LotFilter(CFG)
    assert words(f, "Изготовление БАННЕРОВ и вывесок") == ["баннер"]
    assert words(f, "Tashqi banner tayyorlash") == ["banner"]
    assert words(f, "Hajmli harflar o‘rnatish") == ["hajmli harf"]
    assert words(f, "Пешлавҳа тайёрлаш") == ["пешлавха"]
    assert words(f, "Услуги рекламные") == ["реклам"]
    assert words(f, "Реклама: banner и баннер") == ["реклам", "баннер", "banner"]
    assert words(f, "Картофельный крахмал") == []
    assert words(f, "") == []


def test_lot_typed_with_mixed_alphabets_is_still_found():
    f = LotFilter(CFG)
    assert words(f, "Изготовление бaннeров") == ["баннер"]   # латинские a и e
    assert words(f, "Tashqi bаnner") == ["banner"]            # кириллическая а
    assert words(f, "Pеклaмныe услуги") == ["реклам"]


def test_matched_keywords_are_reported_as_written_in_config():
    f = LotFilter({"services": {"Реклама": ["  ПЕШЛАВҲА ", "Hajmli  Harf", "", None, "   "]}})
    assert words(f, "пешлавха ва hajmli harflar") == ["ПЕШЛАВҲА", "Hajmli  Harf"]
    assert words(f, "none") == []      # пустые строки и пропуски в списке не считаются словами


def test_exclude_phrase_removes_false_positive():
    f = LotFilter(CFG)
    assert words(f, "Рассмотрение рекламаций по качеству") == []
    assert words(f, "Рекламация и наружная реклама") == ["реклам"]
    assert words(f, "Pекламaция") == []   # исключение тоже не зависит от алфавита
    # вырезанная фраза не склеивает соседние слова в новое ключевое
    assert words(LotFilter({"services": {"Реклама": ["zb"]}, "exclude_keywords": ["qq"]}), "zqqb") == []


def test_region_filter():
    f = LotFilter(CFG)
    assert f.region_ok("Ферганская область, Коканд")
    assert f.region_ok("Фарғона вилояти")
    assert f.region_ok("Farg‘ona viloyati")
    assert f.region_ok("Фepгaнcкaя область")     # латинские e, p, a, c
    assert f.region_ok("город Ташкент, Мирабадский район")
    assert f.region_ok("Чилонзор тумани")
    assert not f.region_ok("Сурхандарьинская область, Термез")


def test_lot_without_region_follows_the_setting():
    assert LotFilter(CFG).region_ok("")
    assert LotFilter(CFG).region_ok("   ")
    assert LotFilter({"regions": {"Свои": ["ферган"]}}).region_ok("")   # по умолчанию пропускаем
    assert not LotFilter({**CFG, "allow_unknown_region": False}).region_ok("")
    assert not LotFilter({**CFG, "allow_unknown_region": False}).region_ok(None)


def test_no_regions_configured_means_whole_country():
    f = LotFilter({"services": {"Реклама": ["баннер"]}, "allow_unknown_region": False})
    assert f.region_ok("Сурхандарьинская область")
    assert not f.region_ok("")


def test_empty_config_matches_nothing_by_keyword():
    assert words(LotFilter({}), "баннер") == []


def lot(title="Баннер 3х6", customer="Хокимият", price=1000.0):
    return Lot(source="a", source_title="A", lot_id="1", title=title, customer=customer, price=price)


def test_same_lot_written_differently_has_same_fingerprint():
    assert fingerprint(lot()) == fingerprint(lot(title=" БАННЕР  3х6 ", customer="хокимият"))
    assert fingerprint(lot()) == fingerprint(Lot(source="b", source_title="B", lot_id="99", title="Баннер 3х6",
                                                 customer="Хокимият", price=1000.0, url="другая ссылка"))


def test_different_lots_have_different_fingerprints():
    assert fingerprint(lot()) != fingerprint(lot(title="Вывеска"))
    assert fingerprint(lot()) != fingerprint(lot(customer="Банк"))
    assert fingerprint(lot()) != fingerprint(lot(price=2000.0))
    assert fingerprint(lot(price=None)) == fingerprint(lot(price=0))
    assert fingerprint(lot(price=None)) != fingerprint(lot(price=1))


def test_lot_without_title_has_no_fingerprint():
    assert fingerprint(lot(title="  ")) == ""


# --- услуги и приоритетный регион ---

SERVICES = {
    "services": {
        "Баннеры": ["баннер", "banner"],
        "Печать на одежде": ["dtf", "Футболка + чоп"],
        "Пустая": [],
    },
    "regions": {"Фергана": ["ферган", "коканд"], "Ташкент": ["ташкент"]},
    "priority_region": "Фергана",
}


def test_match_tells_which_services_the_lot_is_about():
    f = LotFilter(SERVICES)
    assert f.match("Tashqi banner va баннер") == {"Баннеры": ["баннер", "banner"]}
    assert f.match("DTF усулда баннер чоп этиш") == {"Баннеры": ["баннер"], "Печать на одежде": ["dtf"]}
    assert list(f.match("dtf и баннер")) == ["Баннеры", "Печать на одежде"]   # в порядке config.yaml
    assert f.match("Картофельный крахмал") == {}


def test_rule_with_plus_needs_every_part_in_any_order():
    f = LotFilter(SERVICES)
    assert f.match("Футболкаларга логотип чоп этиш") == {"Печать на одежде": ["Футболка + чоп"]}
    assert f.match("Чоп этиш: футболка") == {"Печать на одежде": ["Футболка + чоп"]}
    assert f.match("Футболка трикотажная") == {}
    assert f.match("Китоб чоп этиш") == {}


def test_rule_made_only_of_pluses_and_spaces_is_ignored():
    f = LotFilter({"services": {"А": [" + ", "+", "баннер +"]}})
    assert f.match("что угодно") == {}
    assert f.match("баннер") == {"А": ["баннер +"]}


def test_region_name_and_priority():
    f = LotFilter(SERVICES)
    assert f.region_name("Ферганская область, Коканд") == "Фергана"
    assert f.region_name("город Ташкент") == "Ташкент"
    assert f.region_name("Самарканд") == f.region_name("") == f.region_name(None) == ""
    assert f.region_name("Ташкент, склад в Фергане") == "Фергана"     # первый регион списка важнее
    assert f.priority("Қўқон, Ферганская обл.") == "Фергана"
    assert f.priority("город Ташкент") == f.priority("") == f.priority("Самарканд") == ""
    assert LotFilter({**SERVICES, "priority_region": None}).priority("Фергана") == ""
    assert LotFilter({"regions": {"Ташкент": ["ташкент"]}, "priority_region": "Фергана"}).priority("Бухара") == ""


def test_vocabulary_signature_changes_only_with_search_settings():
    base = vocabulary_signature(SERVICES)
    assert base == vocabulary_signature({**SERVICES, "interval_minutes": 5, "sources": {"a": True}})
    changed = [
        {**SERVICES, "services": {**SERVICES["services"], "Баннеры": ["баннер"]}},
        {**SERVICES, "exclude_keywords": ["рекламац"]},
        {**SERVICES, "regions": {"Фергана": ["ферган"]}},
        {**SERVICES, "allow_unknown_region": False},
        {**SERVICES, "xt_xarid_regions": ["33.2466"]},
    ]
    signatures = [vocabulary_signature(cfg) for cfg in changed]
    assert base not in signatures and len(set(signatures)) == len(signatures)
    assert vocabulary_signature({}) == vocabulary_signature({"sources": {}})
    reordered = {**SERVICES, "services": dict(reversed(SERVICES["services"].items()))}
    assert vocabulary_signature(reordered) == base      # услуги переставили местами — искать то же самое


def test_found_services_are_split_by_their_chats():
    found = {"Баннеры": ["баннер"], "Перевозка": ["юк ташиш"], "Вывески": ["вывеск"], "Экспедирование": ["экспедир"]}
    chats = {"Перевозка": "-200", "Экспедирование": "-200", "Нет такой услуги": "-300"}
    assert by_chat(found, chats) == {
        "": {"Баннеры": ["баннер"], "Вывески": ["вывеск"]},
        "-200": {"Перевозка": ["юк ташиш"], "Экспедирование": ["экспедир"]},
    }
    assert by_chat(found, {}) == {"": found}
    assert by_chat({}, chats) == {}

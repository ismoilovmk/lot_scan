from filters import LotFilter, normalize

CFG = {
    "keywords": ["реклам", "баннер", "banner", "hajmli harf", "пешлавха"],
    "exclude_keywords": ["рекламац"],
    "regions": ["ферган", "фаргона", "fargona", "ташкент", "тошкент", "чилонзор"],
    "allow_unknown_region": True,
}


def test_normalize_uzbek_letters_and_apostrophes():
    assert normalize("Фарғона  ВИЛОЯТИ") == "фаргона вилояти"
    assert normalize("Ўзбекистон ҳудуди Қ, ёлка") == "узбекистон худуди к, елка"
    assert normalize(" много   пробелов\nи\tстрок ") == "много пробелов и строк"
    assert normalize(None) == ""


def test_all_apostrophe_kinds_are_ignored():
    for apostrophe in "'’‘`ʻʼ´":
        assert normalize(f"Farg{apostrophe}ona") == "fargona"


def test_keywords_match_russian_uzbek_any_case():
    f = LotFilter(CFG)
    assert f.match_keywords("Изготовление БАННЕРОВ и вывесок") == ["баннер"]
    assert f.match_keywords("Tashqi banner tayyorlash") == ["banner"]
    assert f.match_keywords("Hajmli harflar o‘rnatish") == ["hajmli harf"]
    assert f.match_keywords("Пешлавҳа тайёрлаш") == ["пешлавха"]
    assert f.match_keywords("Услуги рекламные") == ["реклам"]
    assert f.match_keywords("Реклама: banner и баннер") == ["реклам", "баннер", "banner"]
    assert f.match_keywords("Картофельный крахмал") == []
    assert f.match_keywords("") == []


def test_keywords_from_config_are_normalized_too():
    f = LotFilter({"keywords": ["  ПЕШЛАВҲА ", "Hajmli  Harf", "", None, 2026]})
    assert f.keywords == ["пешлавха", "hajmli harf", "none", "2026"]
    assert f.match_keywords("пешлавха") == ["пешлавха"]


def test_exclude_phrase_removes_false_positive():
    f = LotFilter(CFG)
    assert f.match_keywords("Рассмотрение рекламаций по качеству") == []
    assert f.match_keywords("Рекламация и наружная реклама") == ["реклам"]
    # вырезанная фраза не склеивает соседние слова в новое ключевое
    assert LotFilter({"keywords": ["аб"], "exclude_keywords": ["xx"]}).match_keywords("аxxб") == []


def test_region_filter():
    f = LotFilter(CFG)
    assert f.region_ok("Ферганская область, Коканд")
    assert f.region_ok("Фарғона вилояти")
    assert f.region_ok("Farg‘ona viloyati")
    assert f.region_ok("город Ташкент, Мирабадский район")
    assert f.region_ok("Чилонзор тумани")
    assert not f.region_ok("Сурхандарьинская область, Термез")


def test_lot_without_region_follows_the_setting():
    assert LotFilter(CFG).region_ok("")
    assert LotFilter(CFG).region_ok("   ")
    assert LotFilter({"regions": ["ферган"]}).region_ok("")   # по умолчанию пропускаем
    assert not LotFilter({**CFG, "allow_unknown_region": False}).region_ok("")
    assert not LotFilter({**CFG, "allow_unknown_region": False}).region_ok(None)


def test_no_regions_configured_means_whole_country():
    f = LotFilter({"keywords": ["баннер"], "allow_unknown_region": False})
    assert f.region_ok("Сурхандарьинская область")
    assert not f.region_ok("")


def test_empty_config_matches_nothing_by_keyword():
    assert LotFilter({}).match_keywords("баннер") == []

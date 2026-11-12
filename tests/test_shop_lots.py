import pytest
from fakes import FakeClient

from sources import uzex_shop
from sources.uzex_shop import EShopLots, ShopLots

SHOP = "https://xarid-api-shop.uzex.uz/Common"
CFG = {"shop_keywords": ["баннер"], "interval_minutes": 20, "shop_offers_per_pass": 300}
OPEN = {"id": 5878738, "display_no": "261111145878738", "start_date": "2026-11-11T15:06:31",
        "end_date": "2026-11-13T15:06:31", "amount": 60.0, "price": 50000.0, "status_id": 1, "status_name": "Новый"}
REFUSED = {**OPEN, "id": 5878091, "end_date": "0001-01-01T00:00:00", "status_id": 15, "status_name": "Отказано казначейством"}
FERGANA = [{"id": 30, "name": "Ферганская область", "children": [
    {"id": 300, "name": "город Коканд", "children": []}, {"id": 301, "name": "Кувинский район", "children": []}]}]


def offer(offer_id, name="Услуга по установке баннера"):
    return {"id": offer_id, "product_name": f" {name} ", "display_no": f"SO{offer_id}"}


LOCAL = {"is_local_manufacturer": 1, "producer_country_id": 244}   # так сайт отбирает Milliy do'kon


def shop(offers, lots=None, regions=None, details=None, scope=LOCAL):
    """Ведёт себя как магазин: предложения по слову, торги по предложению, районы и карточка торга.

    scope — чем запрос списка должен отличать один магазин от другого (у Elektron do'kon отбора нет).
    """
    lots, regions, details = lots or {}, regions or {}, details or {}

    def handler(method, url, body):
        name, _, key = url[len(SHOP) + 1:].partition("/")
        if name == "GetOffersList":
            assert method == "POST"
            assert {key: body[key] for key in body if key not in ("keyword", "from", "to")} == scope
            rows = offers.get(body["keyword"], [])
            return [{**row, "total_count": len(rows)} for row in rows[body["from"] - 1:body["to"]]]
        assert method == "GET"
        return {"GetOfferLots": lots, "GetLotRegionsDistricts": regions, "GetLot": details}[name].get(int(key), [])

    return handler


def scan(client, cfg=CFG, minute=0, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(uzex_shop.time, "time", lambda: minute * 60)
    return list(ShopLots().list_lots(client, cfg))


def test_open_trade_on_an_offer_becomes_lot(monkeypatch):
    client = FakeClient(shop({"баннер": [offer(7)]}, {7: [REFUSED, OPEN]}, {5878738: FERGANA}))
    (lot,) = scan(client, monkeypatch=monkeypatch)
    assert (lot.source, lot.source_title) == ("uzex_shop", "Milliy do'kon (торг по предложению)")
    assert (lot.lot_id, lot.number) == ("5878738", "261111145878738")
    assert lot.title == "Услуга по установке баннера"
    assert lot.region == "Ферганская область, город Коканд, Кувинский район"
    assert lot.price == 3000000.0                       # цена за единицу на количество
    assert lot.deadline == "2026-11-13T15:06:31"
    assert lot.url == "https://xarid.uzex.uz/shop/lot-details/5878738"
    assert lot.customer == ""                           # заказчика площадка не показывает


def test_only_new_trades_are_taken(monkeypatch):
    client = FakeClient(shop({"баннер": [offer(7)]}, {7: [REFUSED, {**OPEN, "status_id": 2}]}))
    assert scan(client, monkeypatch=monkeypatch) == []


def polled(client):
    return [int(call[1].rsplit("/", 1)[1]) for call in client.calls if "GetOfferLots" in call[1]]


def test_shop_is_asked_for_twelve_offers_at_a_time(monkeypatch):
    client = FakeClient(shop({"баннер": [offer(i) for i in range(1, 31)]}))
    scan(client, monkeypatch=monkeypatch)
    asked = [(call[2]["from"], call[2]["to"]) for call in client.calls if "GetOffersList" in call[1]]
    assert set(asked) == {(1, 12), (13, 24), (25, 36)}       # больше двенадцати строк магазин не отдаёт
    assert polled(client) == list(range(1, 31))


def test_offer_found_by_two_words_is_checked_once(monkeypatch):
    cfg = {**CFG, "shop_keywords": ["баннер", "установк"]}
    client = FakeClient(shop({"баннер": [offer(7)], "установк": [offer(7), offer(8)]}, {7: [OPEN]}))
    assert [lot.lot_id for lot in scan(client, cfg, monkeypatch=monkeypatch)] == ["5878738"]
    assert polled(client) == [7, 8]


def test_offers_are_checked_in_parts_one_part_per_pass(monkeypatch):
    cfg = {**CFG, "shop_keywords": ["баннер", "вывеск"], "shop_offers_per_pass": 24}
    offers = {"баннер": [offer(i) for i in range(1, 31)], "вывеск": [offer(i) for i in range(101, 114)]}
    seen = []
    for minute in (0, 20, 40, 60):
        client = FakeClient(shop(offers))
        scan(client, cfg, minute, monkeypatch)
        seen.append(polled(client))
    assert seen == [list(range(1, 25)),                              # две страницы по двенадцать
                    list(range(25, 31)) + list(range(101, 113)),     # хвост первого слова и начало второго
                    [113],
                    list(range(1, 25))]                              # и снова по кругу


def test_part_is_chosen_by_the_clock_not_by_previous_runs(monkeypatch):
    cfg = {**CFG, "shop_offers_per_pass": 12, "interval_minutes": 10}
    client = FakeClient(shop({"баннер": [offer(i) for i in range(1, 37)]}))
    scan(client, cfg, 25, monkeypatch)                   # третий десятиминутный отрезок
    assert polled(client) == list(range(25, 37))


def test_defaults_when_settings_are_missing(monkeypatch):
    client = FakeClient(shop({"баннер": [offer(i) for i in range(1, 402)]}))
    scan(client, {"shop_keywords": ["баннер"]}, 20, monkeypatch)
    assert polled(client) == list(range(301, 402))       # по 300 за проход, отрезок — 20 минут


def test_tiny_part_size_still_reads_a_page(monkeypatch):
    client = FakeClient(shop({"баннер": [offer(i) for i in range(1, 14)]}))
    scan(client, {**CFG, "shop_offers_per_pass": 5}, 0, monkeypatch)
    assert polled(client) == list(range(1, 13))


def test_no_keywords_or_no_offers_means_no_requests_for_trades(monkeypatch):
    client = FakeClient(shop({}))
    assert scan(client, {}, monkeypatch=monkeypatch) == []
    assert client.calls == []
    assert scan(client, CFG, monkeypatch=monkeypatch) == []
    assert polled(client) == []
    assert len(client.calls) == 1                        # один запрос на слово, чтобы узнать, что предложений нет


@pytest.mark.parametrize("trade", [{**OPEN, "price": None}, {**OPEN, "amount": None}, {**OPEN, "price": 0}])
def test_trade_without_price_or_amount_has_no_price(monkeypatch, trade):
    client = FakeClient(shop({"баннер": [offer(7)]}, {7: [trade]}))
    assert scan(client, monkeypatch=monkeypatch)[0].price is None


def test_trade_without_delivery_region_has_empty_region(monkeypatch):
    client = FakeClient(shop({"баннер": [offer(7)]}, {7: [OPEN]}))
    assert scan(client, monkeypatch=monkeypatch)[0].region == ""


def test_details_add_what_the_supplier_wrote_about_the_offer(monkeypatch):
    client = FakeClient(shop({"баннер": [offer(7)]}, {7: [OPEN]}, details={
        5878738: {"condition": "уф баннер чоп этиш", "product_name": "Услуга по установке баннера"}}))
    (lot,) = scan(client, monkeypatch=monkeypatch)
    lot = ShopLots().enrich(client, lot)
    assert lot.details == "уф баннер чоп этиш"
    assert ShopLots().enrich(FakeClient(shop({}, details={5878738: {"condition": None}})), lot).details == ""


def test_elektron_dokon_is_the_same_shop_without_the_local_manufacturer_filter(monkeypatch):
    monkeypatch.setattr(uzex_shop.time, "time", lambda: 0)
    client = FakeClient(shop({"баннер": [offer(7)]}, {7: [REFUSED, OPEN]}, {5878738: FERGANA}, scope={}))
    (lot,) = EShopLots().list_lots(client, CFG)
    assert (lot.source, lot.source_title) == ("uzex_eshop", "Elektron do'kon (торг по предложению)")
    assert (lot.lot_id, lot.title, lot.price) == ("5878738", "Услуга по установке баннера", 3000000.0)
    assert lot.url == "https://xarid.uzex.uz/shop/lot-details/5878738"


def test_both_shops_are_scanned():
    from sources import ALL_SOURCES
    assert {"uzex_shop", "uzex_eshop"} <= {source.key for source in ALL_SOURCES}

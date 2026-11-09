from fakes import FakeClient, uzex_list

from sources.base import Lot, Source, join_region, paged
from sources.uzex_etender import UzexEtender
from sources.uzex_shop import price_report
from sources.uzex_xarid import UzexAuction, UzexCompetition

import pytest


def numbered(count):
    return [{"id": i} for i in range(1, count + 1)]


# --- постраничное чтение ---

def test_paged_reads_everything_when_server_silently_returns_fewer_rows():
    client = FakeClient(uzex_list(numbered(30), silent_cap=12))
    got = list(paged(client, "url", "origin", {}, page_size=100))
    assert [row["id"] for row in got] == list(range(1, 31))


def test_paged_reads_everything_in_full_pages():
    client = FakeClient(uzex_list(numbered(45)))
    got = list(paged(client, "url", "origin", {}, page_size=20))
    assert [row["id"] for row in got] == list(range(1, 46))
    assert [(c[2]["from"], c[2]["to"]) for c in client.calls] == [(1, 20), (21, 40), (41, 60)]


def test_paged_stops_exactly_at_max_rows():
    client = FakeClient(uzex_list(numbered(100), silent_cap=12))
    got = list(paged(client, "url", "origin", {}, page_size=20, max_rows=25))
    assert [row["id"] for row in got] == list(range(1, 26))


def test_paged_does_not_ask_beyond_last_row():
    client = FakeClient(uzex_list(numbered(20)))
    assert len(list(paged(client, "url", "origin", {}, page_size=20))) == 20
    assert len(client.calls) == 1


def test_paged_empty_list_gives_nothing():
    client = FakeClient(uzex_list([]))
    assert list(paged(client, "url", "origin", {})) == []


def test_paged_keeps_filter_fields_in_every_request():
    client = FakeClient(uzex_list(numbered(3)))
    list(paged(client, "the-url", "origin", {"keyword": "баннер"}, page_size=2))
    assert [c[1] for c in client.calls] == ["the-url", "the-url"]
    assert client.calls[0][2] == {"keyword": "баннер", "from": 1, "to": 2}
    assert client.calls[1][2] == {"keyword": "баннер", "from": 3, "to": 4}


def test_paged_fails_loudly_when_site_stops_reporting_total():
    # без общего числа строк нельзя понять, всё ли прочитано; молча отдать одну страницу — потерять лоты
    client = FakeClient(lambda method, url, body: [{"id": 1}])
    with pytest.raises(KeyError, match="total_count"):
        list(paged(client, "url", "origin", {}))


def test_join_region_skips_empty_parts():
    assert join_region("город Ташкент", " Юнусабадский район ") == "город Ташкент, Юнусабадский район"
    assert join_region(None, "Чилонзор тумани") == "Чилонзор тумани"
    assert join_region(None, "  ") == ""


def test_base_source_requires_list_and_leaves_lot_unchanged():
    lot = Lot(source="s", source_title="S", lot_id="1", title="Баннер", details="оракал")
    assert Source().enrich(None, lot) is lot
    assert lot.search_text() == "Баннер\nоракал"
    with pytest.raises(NotImplementedError):
        Source().list_lots(None, {})


# --- etender ---

ETENDER_ROW = {
    "id": 523550, "display_no": "26120012523550", "name": "  Tashqi reklama xizmatlari ",
    "end_date": "2026-11-16T09:31:00", "cost": 9155024480.0, "seller_name": " XALQ BANK ",
    "region_name": None, "district_name": "Чилонзор тумани", "currency_codeabc": "UZS",
    "category_name": "Услуги рекламные",
}


def etender_site(method, url, body):
    assert url == "https://apietender.uzex.uz/api/common/TradeList"
    rows = {1: [ETENDER_ROW], 2: [{**ETENDER_ROW, "id": 7, "name": None, "currency_codeabc": None}]}
    return uzex_list(rows[body["typeid"]])(method, url, body)


def test_etender_turns_site_rows_into_lots():
    client = FakeClient(etender_site)
    lots = list(UzexEtender().list_lots(client, {}))
    assert len(lots) == 2
    # тело запроса снято с сайта: другие значения дают другой список
    assert [call[2] for call in client.calls] == [
        {"is_agent": None, "Is_Scientific": None, "System_Id": 0, "typeid": 1, "from": 1, "to": 100},
        {"is_agent": None, "Is_Scientific": None, "System_Id": 0, "typeid": 2, "from": 1, "to": 100},
    ]
    lot = lots[0]
    assert (lot.source, lot.lot_id, lot.number) == ("uzex_etender", "523550", "26120012523550")
    assert lot.title == "Tashqi reklama xizmatlari"
    assert lot.customer == "XALQ BANK"
    assert lot.region == "Чилонзор тумани"
    assert (lot.price, lot.currency) == (9155024480.0, "UZS")
    assert lot.deadline == "2026-11-16T09:31:00"
    assert lot.url == "https://etender.uzex.uz/lot/523550"
    assert lot.source_title == "UzEX etender (отбор)"
    assert lots[1].source_title == "UzEX etender (тендер)"


def test_etender_category_is_not_searched_and_blanks_are_safe():
    lots = list(UzexEtender().list_lots(FakeClient(etender_site), {}))
    assert "рекламные" not in lots[0].search_text()
    assert (lots[1].title, lots[1].currency) == ("", "UZS")


# --- аукцион ---

AUCTION_ROW = {
    "id": 422433, "display_no": "26121007422433", "category_name": " Услуги рекламные ",
    "start_cost": 5980000.0, "end_date": "2026-11-13T10:12:00",
    "region_name": "город Ташкент", "district_name": "Юнусабадский район",
}
AUCTION_DETAIL = {
    "customer_name": " АО O`ZBEKISTON POCHTASI ", "description": "срочно",
    "js_details": [
        {"product_name": "Табличка информационная", "description": "оракал, УФ-печать"},
        {"product_name": " Печатная продукция ", "description": None},
        {"product_name": "Табличка информационная", "description": "наклейка"},
        {"product_name": None, "description": "без названия"},
    ],
}


def test_auction_reads_all_lots_from_server_that_rejects_big_pages():
    rows = [{**AUCTION_ROW, "id": i} for i in range(1, 46)]
    client = FakeClient(uzex_list(rows, reject_above=20))
    lots = list(UzexAuction().list_lots(client, {}))
    assert [lot.lot_id for lot in lots] == [str(i) for i in range(1, 46)]
    assert client.calls[0][1] == "https://xarid-api-auction.uzex.uz/Common/GetMinimizedLotsList"
    assert client.calls[0][2]["region_ids"] == []


def test_auction_turns_site_row_into_lot():
    lot = next(UzexAuction().list_lots(FakeClient(uzex_list([AUCTION_ROW])), {}))
    assert (lot.source, lot.source_title) == ("uzex_auction", "UzEX аукцион")
    assert (lot.lot_id, lot.number) == ("422433", "26121007422433")
    assert lot.title == "Услуги рекламные"
    assert lot.region == "город Ташкент, Юнусабадский район"
    assert (lot.price, lot.deadline) == (5980000.0, "2026-11-13T10:12:00")
    assert lot.url == "https://xarid.uzex.uz/auction/detail/422433"


def test_auction_details_give_position_names_customer_and_search_text():
    source = UzexAuction()
    lot = next(source.list_lots(FakeClient(uzex_list([AUCTION_ROW])), {}))
    client = FakeClient(lambda method, url, body: AUCTION_DETAIL)
    lot = source.enrich(client, lot)
    assert client.calls == [("GET", "https://xarid-api-auction.uzex.uz/Common/GetLot/422433", None)]
    assert lot.title == "Табличка информационная; Печатная продукция"
    assert lot.customer == "АО O`ZBEKISTON POCHTASI"
    assert lot.details.split("\n") == ["оракал, УФ-печать", "наклейка", "без названия", "срочно"]
    assert "рекламные" not in lot.search_text()  # категория в поиск не попадает


def test_auction_lot_without_positions_keeps_category_as_title():
    source = UzexAuction()
    lot = next(source.list_lots(FakeClient(uzex_list([AUCTION_ROW])), {}))
    lot = source.enrich(FakeClient(lambda *a: {"customer_name": None, "js_details": None}), lot)
    assert (lot.title, lot.customer, lot.details) == ("Услуги рекламные", "", "")


def test_very_long_position_list_is_cut_to_300_chars():
    source = UzexAuction()
    lot = next(source.list_lots(FakeClient(uzex_list([AUCTION_ROW])), {}))
    detail = {"js_details": [{"product_name": f"Позиция номер {i}"} for i in range(60)]}
    assert len(source.enrich(FakeClient(lambda *a: detail), lot).title) == 300


# --- отбор (69-ПКМ) ---

COMPETITION_ROW = {
    "id": 25303, "end_date_submitting_offers": "2026-11-13T10:00:00",
    "customer_region_name": "город Ташкент", "customer_district_name": "Юнусабадский район",
    "category_name": "Услуги рекламные", "cost": 12000000.0,
}


def test_competition_turns_site_row_into_lot():
    client = FakeClient(uzex_list([COMPETITION_ROW]))
    lot = next(UzexCompetition().list_lots(client, {}))
    assert client.calls[0][1] == "https://xarid-api-purchase.uzex.uz/Common/GetCompetitions"
    assert (lot.source, lot.source_title) == ("uzex_competition", "UzEX отбор (69-ПКМ)")
    assert (lot.lot_id, lot.number, lot.title) == ("25303", "25303", "Услуги рекламные")
    assert lot.region == "город Ташкент, Юнусабадский район"
    assert (lot.price, lot.deadline) == (12000000.0, "2026-11-13T10:00:00")
    assert lot.url == "https://xarid.uzex.uz/purchase/competition/detail/25303"


def test_competition_looks_only_at_latest_lots():
    rows = [{**COMPETITION_ROW, "id": i} for i in range(1, 31)]
    lots = list(UzexCompetition().list_lots(FakeClient(uzex_list(rows)), {"competition_max_lots": 5}))
    assert [lot.lot_id for lot in lots] == ["1", "2", "3", "4", "5"]


def test_competition_default_limit_is_300_lots():
    rows = [{**COMPETITION_ROW, "id": i} for i in range(1, 321)]
    assert len(list(UzexCompetition().list_lots(FakeClient(uzex_list(rows)), {}))) == 300


def test_competition_details_include_requirements_text():
    source = UzexCompetition()
    lot = next(source.list_lots(FakeClient(uzex_list([COMPETITION_ROW])), {}))
    detail = {
        "customer_name": "AGROSTAR", "description": "D", "note": "N", "competition_description": "banner kerak",
        "js_details": [{"product_name": "Услуга по размещению", "description": "щит 3х6"}],
    }
    client = FakeClient(lambda method, url, body: detail)
    lot = source.enrich(client, lot)
    assert client.calls[0][1] == "https://xarid-api-purchase.uzex.uz/Common/GetCompetition/25303"
    assert (lot.title, lot.customer) == ("Услуга по размещению", "AGROSTAR")
    assert lot.details.split("\n") == ["щит 3х6", "D", "N", "banner kerak"]


# --- отчёт по ценам Milliy do'kon ---

def offer(name, unit, price):
    return {"product_name": name, "unit_name": unit, "price": price}


def test_price_report_groups_offers_and_shows_min_median_max():
    rows = [
        offer(" Печать баннера ", "кв. метр", 40000.0),
        offer("Печать баннера", "кв. метр", 100000.0),
        offer("Печать баннера", "кв. метр", 60000.0),
        offer("Печать баннера", "кв. метр", 0),          # без цены — не считаем
        offer("Монтаж баннера", None, 1500000.0),
    ]
    client = FakeClient(uzex_list(rows, silent_cap=2))
    report = price_report(client, ["баннер"]).split("\n")
    assert report[0] == "Цены в Milliy do'kon (предложения поставщиков)"
    assert report[1:3] == ["", "«баннер»: всего предложений 5, просмотрено 5"]
    assert report[3] == "  • Печать баннера — 3 предл., за кв. метр: мин 40 000, медиана 60 000, макс 100 000 сум"
    assert report[4] == "  • Монтаж баннера — 1 предл., за ед.: мин 1 500 000, медиана 1 500 000, макс 1 500 000 сум"
    assert client.calls[0][1] == "https://xarid-api-shop.uzex.uz/Common/GetOffersList"
    assert client.calls[0][2]["keyword"] == "баннер"
    assert client.calls[0][2]["is_local_manufacturer"] == 1


def test_price_report_shows_only_eight_most_common_positions():
    rows = [offer(f"Позиция {i}", "шт", 1000.0) for i in range(12)] + [offer("Частая", "шт", 5.0)] * 2
    report = price_report(FakeClient(uzex_list(rows)), ["x"]).split("\n")
    assert len(report) == 3 + 8
    assert report[3].startswith("  • Частая — 2 предл.")


def test_price_report_looks_at_300_offers_at_most():
    rows = [offer("Баннер", "шт", 1000.0)] * 350
    report = price_report(FakeClient(uzex_list(rows)), ["x"])
    assert "всего предложений 350, просмотрено 300" in report


def test_price_report_with_single_offer():
    report = price_report(FakeClient(uzex_list([offer("Баннер", "шт", 1000.0)])), ["баннер"])
    assert "«баннер»: всего предложений 1, просмотрено 1" in report
    assert "  • Баннер — 1 предл., за шт: мин 1 000, медиана 1 000, макс 1 000 сум" in report


def test_price_report_for_several_words_and_no_offers():
    report = price_report(FakeClient(uzex_list([])), ["оракал", "вывеск"])
    assert "«оракал»: всего предложений 0, просмотрено 0" in report
    assert "«вывеск»: всего предложений 0, просмотрено 0" in report

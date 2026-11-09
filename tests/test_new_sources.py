import json

import pytest
from fakes import FakeClient

from sources.tendergpt import TenderGpt
from sources.uzex_civil import UzexCivil

# --- etender: отбор по 69-ПКМ ---

CIVIL_ROW = {
    "id": 18959, "display_id": "26120500018959", "name": " Баннеры для школы ", "customer_name": " Хокимият ",
    "cost": 158000000.0, "currency_name": "Сум", "end_date": "2026-11-16T15:24:27",
    "delivery_address": "Farg'ona sh.", "provision_address": "Farg'ona viloyati, Quva tumani",
    "description": "длинное описание",
}


def civil_list(rows):
    """Список этого раздела принимает From/To с большой буквы, на маленькие отвечает пустым списком."""

    def handler(method, url, body):
        assert (method, url) == ("POST", "https://apietender.uzex.uz/api/CivilContracts/GetList")
        assert body["status_Id"] == 3
        page = rows[body["From"] - 1:body["To"]]
        return [{**row, "total_count": len(rows)} for row in page]

    return handler


def test_civil_row_becomes_lot():
    lot = next(UzexCivil().list_lots(FakeClient(civil_list([CIVIL_ROW])), {}))
    assert (lot.source, lot.source_title) == ("uzex_civil", "UzEX etender (отбор 69-ПКМ)")
    assert (lot.lot_id, lot.number) == ("18959", "26120500018959")
    assert (lot.title, lot.customer) == ("Баннеры для школы", "Хокимият")
    assert lot.region == "Farg'ona sh., Farg'ona viloyati, Quva tumani"
    assert (lot.price, lot.currency) == (158000000.0, "UZS")
    assert lot.deadline == "2026-11-16T15:24:27"
    assert lot.url == "https://etender.uzex.uz/civil-detail/18959"


def test_civil_reads_all_pages():
    rows = [{**CIVIL_ROW, "id": i} for i in range(1, 231)]
    lots = list(UzexCivil().list_lots(FakeClient(civil_list(rows)), {}))
    assert [lot.lot_id for lot in lots] == [str(i) for i in range(1, 231)]


def test_civil_details_add_positions_and_description():
    source = UzexCivil()
    lot = next(source.list_lots(FakeClient(civil_list([CIVIL_ROW])), {}))
    detail = {"description": "ТЗ: вывеска", "js_products": json.dumps([
        {"Product_Name": "Баннер", "Description": "3х6", "Category_Name": "не ищем",
         "Js_Properties": [{"User_Value": "винил"}]}], ensure_ascii=False)}
    client = FakeClient(lambda method, url, body: detail)
    lot = source.enrich(client, lot)
    assert client.calls == [("GET", "https://apietender.uzex.uz/api/CivilContracts/Get/18959", None)]
    assert lot.details.split("\n") == ["Баннер", "3х6", "винил", "ТЗ: вывеска"]
    assert lot.title == "Баннеры для школы"


# --- tendergpt.uz ---

TG_ROW = {
    "id_number": 253, "id": "uuid-253", "status": "Идёт прием заявок", "title": "Баннер\n",
    "original_price": "UZS 1500000", "currency": "UZS", "full_title_organization": "ACG",
    "customer_info_full_title_organization": " ASIAN CHEMICAL ",
    "customer_info_address": "Узбекистан, ФЕРГАНА", "closing_date_of_applications": "2026-11-13 14:32:00",
}


def tg_site(rows):
    def handler(method, url, body):
        assert (method, url.split("?")[0]) == ("POST", "https://tendergpt.uz/lk/api/v3/procedures/search")
        assert body["statuses"] == [] and "CONTEST" in body["purchaseTypes"]
        page = int(url.split("page=")[1].split("&")[0])
        limit = int(url.split("limit=")[1])
        return {"status": "success", "total": len(rows), "data": rows[(page - 1) * limit:page * limit]}

    return handler


def first_lot(row=TG_ROW):
    return next(TenderGpt().list_lots(FakeClient(tg_site([row])), {}))


def test_tendergpt_row_becomes_lot():
    lot = first_lot()
    assert (lot.source, lot.source_title) == ("tendergpt", "TenderGPT")
    assert (lot.lot_id, lot.number) == ("253", "253")
    assert (lot.title, lot.customer) == ("Баннер", "ASIAN CHEMICAL")
    assert lot.region == "Узбекистан, ФЕРГАНА"
    assert (lot.price, lot.currency) == (1500000.0, "UZS")
    assert lot.deadline == "2026-11-13T14:32:00"
    assert lot.url == "https://tendergpt.uz/tender/253"


def test_tendergpt_uses_organizer_when_customer_is_missing():
    assert first_lot({**TG_ROW, "customer_info_full_title_organization": None}).customer == "ACG"


def test_tendergpt_currency():
    assert first_lot({**TG_ROW, "currency": "USD"}).currency == "USD"
    assert first_lot({**TG_ROW, "currency": None}).currency == "UZS"


def test_tendergpt_skips_lots_not_accepting_bids():
    rows = [TG_ROW, {**TG_ROW, "id_number": 9, "status": "Завершена"}]
    assert [lot.lot_id for lot in TenderGpt().list_lots(FakeClient(tg_site(rows)), {})] == ["253"]


def test_tendergpt_reads_all_pages_and_stops():
    client = FakeClient(tg_site([{**TG_ROW, "id_number": i} for i in range(1, 121)]))
    assert len(list(TenderGpt().list_lots(client, {}))) == 120
    assert [c[1].split("?")[1] for c in client.calls] == ["page=1&limit=50", "page=2&limit=50", "page=3&limit=50"]


def test_tendergpt_exact_last_page_needs_no_extra_request():
    client = FakeClient(tg_site([{**TG_ROW, "id_number": i} for i in range(1, 51)]))
    assert len(list(TenderGpt().list_lots(client, {}))) == 50
    assert len(client.calls) == 1


def test_tendergpt_empty_site():
    assert list(TenderGpt().list_lots(FakeClient(tg_site([])), {})) == []


@pytest.mark.parametrize("value, price", [
    ("UZS 1500000", 1500000.0), ("1500000,50 UZS", 1500000.5), ("UZS 1 500 000", 1500000.0),
    ("UZS 0", None), ("0,00 UZS", None), ("без цены", None), ("1,000,000.00", None), (None, None),
])
def test_tendergpt_price_formats(value, price):
    assert first_lot({**TG_ROW, "original_price": value}).price == price


def test_tendergpt_lot_without_deadline():
    assert first_lot({**TG_ROW, "closing_date_of_applications": None}).deadline == ""


def test_tendergpt_details_add_position_names():
    answers = {
        "https://tendergpt.uz/lk/api/v1/procedures/253": {"lots": [{"id": "L1"}, {"id": "L2"}]},
        "https://tendergpt.uz/lk/api/v1/lots/L1/positions?limit=50&page=1":
            {"data": [{"name": "Вывеска\n", "info": "световая", "ikpu_name": "Реклама"}]},
        "https://tendergpt.uz/lk/api/v1/lots/L2/positions?limit=50&page=1":
            {"data": [{"name": "Монтаж", "info": None, "ikpu_name": None}]},
    }
    client = FakeClient(lambda method, url, body: answers[url])
    lot = TenderGpt().enrich(client, first_lot())
    assert lot.details.split("\n") == ["Вывеска", "световая", "Реклама", "Монтаж"]
    assert all(call[0] == "GET" for call in client.calls)


def test_tendergpt_lot_without_positions():
    assert TenderGpt().enrich(FakeClient(lambda *a: {"lots": None}), first_lot()).details == ""

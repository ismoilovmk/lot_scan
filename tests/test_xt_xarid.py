import pytest
from fakes import FakeClient

from sources.xt_xarid import XtXarid

REGIONS = ["33.2466", "33.2137"]
CFG = {"xt_xarid_regions": REGIONS}

AREA_PATH = [
    {"path": "area.33.2466", "name": "Ферганская область"},
    {"path": "area.33.2466.2467", "name": "Районы Ферганской области"},
    {"path": "area.33.2466.2467.2470", "name": "Кувинский район"},
    {"path": "area.33", "name": "Республика Узбекистан"},
]
SELECTION = {
    "id": 9584982, "name": " Отбор ", "status": "open", "close_at": "2026-11-16", "totalcost": 5.0e8,
    "currency": "UZS", "area": "33.2466.2467.2470",
    "meta": {
        "company_name": ' "QUVA TUMAN" hokimligi ', "area_path": AREA_PATH,
        "good_maps": [
            {"name": "Баннер", "desc": "3х6 м, люверсы",
             "translate_name": {"uz-UZ@latin": "Banner", "uz-UZ@cyrillic": "Баннер уз", "ru-RU": "Баннер"}},
            {"name": " Монтаж вывески ", "desc": None, "translate_name": None},
            {"name": "Баннер"},
            {"name": None},
        ],
    },
}
AUCTION = {
    "id": 9409891, "name": None, "status": "publicated", "close_at": "2026-11-09T07:56:23.600000Z",
    "start_price": 26792000.0, "currency": "UZS", "area": "33.2137.2138.2146",
    "meta": {"company_name": "Toshkent MCHJ", "good_maps": [{"name": "Реле"}],
             "area_path": [{"name": "город Ташкент"}, {"name": "Республика Узбекистан"}]},
}


def site(rows_by_ref):
    """Отвечает как api.xt-xarid.uz: список по имени справочника, с limit и offset."""

    def handler(method, url, body):
        assert (method, url) == ("POST", "https://api.xt-xarid.uz/rpc")
        assert (body["jsonrpc"], body["method"], body["params"]["op"]) == ("2.0", "ref", "read")
        params = body["params"]
        rows = rows_by_ref.get(params["ref"], [])
        return {"jsonrpc": "2.0", "id": body["id"],
                "result": rows[params["offset"]:params["offset"] + params["limit"]]}

    return handler


def lots_from(rows_by_ref, cfg=CFG):
    client = FakeClient(site(rows_by_ref))
    return list(XtXarid().list_lots(client, cfg)), client


def test_asks_each_procedure_once_for_open_lots_in_configured_regions():
    lots, client = lots_from({})
    assert lots == []
    asked = [(c[2]["params"]["ref"], c[2]["params"]["filters"], c[2]["params"]["limit"], c[2]["params"]["offset"])
             for c in client.calls]
    assert asked == [
        ("ref_reduction_object_public", {"status": ["publicated"], "delivery_regions": REGIONS}, 100, 0),
        ("ref_selection_public", {"status": ["open"], "delivery_regions": REGIONS}, 100, 0),
        ("ref_request_proposals_public", {"status": ["open"], "delivery_regions": REGIONS}, 100, 0),
        ("ref_tender_public", {"status": ["open"], "delivery_regions": REGIONS}, 100, 0),
    ]
    fields = [c[2]["params"]["fields"] for c in client.calls]
    assert fields[0] == ["id", "name", "status", "close_at", "currency", "area", "meta", "start_price"]
    assert fields[1] == ["id", "name", "status", "close_at", "currency", "area", "meta", "totalcost"]
    # весь запрос целиком — в том виде, в каком его шлёт сам сайт
    assert client.calls[0][2] == {
        "id": 1, "jsonrpc": "2.0", "method": "ref",
        "params": {"ref": "ref_reduction_object_public", "op": "read", "limit": 100, "offset": 0,
                   "filters": {"status": ["publicated"], "delivery_regions": REGIONS}, "fields": fields[0]},
    }


def test_without_configured_regions_asks_for_whole_country():
    _, client = lots_from({}, cfg={})
    assert client.calls[0][2]["params"]["filters"] == {"status": ["publicated"]}


def test_selection_row_becomes_lot():
    lots, _ = lots_from({"ref_selection_public": [SELECTION]})
    assert len(lots) == 1
    lot = lots[0]
    assert (lot.source, lot.source_title) == ("xt_xarid", "XT-Xarid (отбор)")
    assert (lot.lot_id, lot.number) == ("9584982", "9584982")
    assert lot.title == "Отбор — Баннер; Монтаж вывески"
    assert lot.customer == '"QUVA TUMAN" hokimligi'
    assert lot.region == "Ферганская область, Районы Ферганской области, Кувинский район"
    assert (lot.price, lot.currency) == (5.0e8, "UZS")
    assert lot.deadline == "2026-11-16T23:59:59"   # указан только день — лот открыт до его конца
    assert lot.url == "https://xt-xarid.uz/procedure/9584982/core"
    assert lot.details.split("\n") == ["3х6 м, люверсы", "Banner", "Баннер уз", "Баннер"]


def test_auction_row_becomes_lot_with_tashkent_time_and_goods_as_title():
    lots, _ = lots_from({"ref_reduction_object_public": [AUCTION]})
    lot = lots[0]
    assert lot.source_title == "XT-Xarid (аукцион)"
    assert lot.title == "Реле"
    assert lot.customer == "Toshkent MCHJ"
    assert lot.region == "город Ташкент"
    assert lot.price == 26792000.0
    assert lot.deadline == "2026-11-09T12:56:23"    # 07:56 UTC = 12:56 в Ташкенте
    assert lot.details == ""


def test_other_procedures_are_labelled():
    lots, _ = lots_from({"ref_request_proposals_public": [SELECTION], "ref_tender_public": [SELECTION]})
    assert [lot.source_title for lot in lots] == ["XT-Xarid (запрос предложений)", "XT-Xarid (тендер)"]


def test_row_with_almost_nothing_is_still_a_lot():
    lots, _ = lots_from({"ref_tender_public": [{"id": 5, "name": "Вывеска", "meta": None, "close_at": None}]})
    lot = lots[0]
    assert (lot.title, lot.customer, lot.region, lot.price, lot.deadline, lot.currency) == \
        ("Вывеска", "", "", None, "", "UZS")


@pytest.mark.parametrize("close_at, deadline", [
    ("2026-11-02T07:56:23.600Z", "2026-11-02T12:56:23"),
    ("2026-12-31T20:00:00Z", "2027-01-01T01:00:00"),
    ("2026-11-11", "2026-11-11T23:59:59"),
    ("2026-11-11T10:00:00", "2026-11-11T10:00:00"),
    ("", ""),
    ("скоро", "скоро"),
])
def test_deadline_formats(close_at, deadline):
    lots, _ = lots_from({"ref_tender_public": [{"id": 1, "close_at": close_at}]})
    assert lots[0].deadline == deadline


def test_title_is_not_doubled_when_lot_name_equals_its_only_position():
    row = {"id": 1, "name": "Услуга по размещению рекламы",
           "meta": {"good_maps": [{"name": "Услуга по размещению рекламы"}]}}
    lots, _ = lots_from({"ref_tender_public": [row]})
    assert lots[0].title == "Услуга по размещению рекламы"


def test_long_title_is_cut_to_300_chars():
    row = {"id": 1, "name": "Н", "meta": {"good_maps": [{"name": f"Позиция номер {i}"} for i in range(60)]}}
    lots, _ = lots_from({"ref_tender_public": [row]})
    assert len(lots[0].title) == 300 and lots[0].title.startswith("Н — Позиция номер 0; ")


def test_reads_further_pages_until_a_short_one():
    rows = [{"id": i} for i in range(1, 251)]
    lots, client = lots_from({"ref_selection_public": rows})
    assert [lot.lot_id for lot in lots] == [str(i) for i in range(1, 251)]
    offsets = [c[2]["params"]["offset"] for c in client.calls if c[2]["params"]["ref"] == "ref_selection_public"]
    assert offsets == [0, 100, 200]


def test_full_last_page_needs_one_more_request_to_see_the_end():
    rows = [{"id": i} for i in range(1, 101)]
    lots, client = lots_from({"ref_selection_public": rows})
    assert len(lots) == 100
    offsets = [c[2]["params"]["offset"] for c in client.calls if c[2]["params"]["ref"] == "ref_selection_public"]
    assert offsets == [0, 100]


def test_site_error_in_reply_stops_the_pass_with_its_message():
    client = FakeClient(lambda method, url, body: {"error": {"message": "Превышено количество запросов"}})
    with pytest.raises(RuntimeError, match="xt-xarid.uz: Превышено количество запросов"):
        list(XtXarid().list_lots(client, CFG))
    assert len(client.calls) == 1

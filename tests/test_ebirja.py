from urllib.parse import parse_qs, urlsplit

import pytest
from fakes import FakeClient

from sources.ebirja import Ebirja

API = "https://xarid-api.ebirja.uz"
FERGANA = {"title_ru": "Ферганская область", "title_uz": "Farg'ona viloyati"}
KOKAND = {"title_ru": "город Коканд"}
TASHKENT = {"title_ru": "город Ташкент"}

AUCTION = {"id": 1326, "lot": "26521007050541", "title": " № 1001 Ta'mirlash ", "total_sum": 28316797.43,
           "company": {"title": " Қўқон локомотив депоси филиали ", "region": TASHKENT, "district": None},
           "region": FERGANA, "district": KOKAND, "auction_end": "2026-11-16 08:55:10"}
TENDER = {"id": 1962, "lot": "26521012051679", "type": 2, "title": "Kontakt-markaz xizmatlari", "total_price": 812422152,
          "company": {"title": "Texnopark", "region": TASHKENT, "district": {"title_ru": "Мирзо-Улугбекский район"}},
          "end_date": "2026-11-18 10:50:09"}
OFFER = {"id": 346, "lot": "26521138011299", "title": "Burg'ilash ishlari", "total_price": 1492218000,
         "company": {"title": "Binokor", "region": TASHKENT, "district": None},
         "region": {"title_ru": "Самаркандская область"}, "district": None, "end_date": "2027-09-24 11:17:41"}


def site(lists=None, views=None, per_page=100):
    """Ведёт себя как xarid-api.ebirja.uz: страницы с нуля, в ответе result и errors."""
    lists = lists or {}
    views = views or {}

    def handler(method, url, body):
        assert method == "GET"
        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}" == API
        query = parse_qs(parts.query)
        path = parts.path.strip("/")
        if path in views:
            assert query["expand"] == ["e_references"]
            return {"result": views[path][query["id"][0]], "errors": []}
        if path.startswith("auction/"):
            path += "?auction_type=" + query["auction_type"][0]
        if path.startswith("tender-v2/"):
            assert query["state[]"] == ["50"]                       # только открытые для заявок
            assert query["type[]"] == ["1", "2", "3", "4", "5", "6", "8"]
        rows = lists.get(path, [])
        assert query["perPage"] == query["size"] == [str(per_page)]
        page = int(query["currentPage"][0])
        pages = -(-len(rows) // per_page)
        return {"result": {"data": rows[page * per_page:(page + 1) * per_page],
                           "meta": {"totalCount": len(rows), "pageCount": pages, "currentPage": page}}, "errors": []}

    return handler


def lots(**lists):
    names = {"auction": "auction/auction/active?auction_type=1", "local": "auction/auction/active?auction_type=2",
             "tender": "tender-v2/producer/landing-lots", "offer": "offer-request/offer-request/announce-list"}
    client = FakeClient(site({names[key]: rows for key, rows in lists.items()}))
    return list(Ebirja().list_lots(client, {})), client


def test_auction_row_becomes_lot():
    (lot,), _ = lots(auction=[AUCTION])
    assert (lot.source, lot.source_title) == ("ebirja", "Ebirja (аукцион)")
    assert (lot.lot_id, lot.number) == ("auction-1326", "26521007050541")
    assert (lot.title, lot.customer) == ("№ 1001 Ta'mirlash", "Қўқон локомотив депоси филиали")
    assert lot.region == "Ферганская область, город Коканд"          # место поставки, а не адрес заказчика
    assert (lot.price, lot.currency) == (28316797.43, "UZS")
    assert lot.deadline == "2026-11-16T08:55:10"
    assert lot.url == "https://ebirja.uz/ru/auction/1326"


def test_local_auction_has_its_own_name_and_link():
    (lot,), _ = lots(local=[AUCTION])
    assert (lot.source_title, lot.lot_id) == ("Ebirja (местный аукцион)", "local-1326")
    assert lot.url == "https://ebirja.uz/ru/local-auction/1326"


@pytest.mark.parametrize("kind, title", [(1, "тендер"), (3, "тендер"), (5, "тендер"), (2, "отбор"), (4, "отбор"), (8, "отбор")])
def test_tender_and_selection_come_from_one_list(kind, title):
    (lot,), _ = lots(tender=[{**TENDER, "type": kind}])
    assert lot.source_title == f"Ebirja ({title})"
    assert (lot.lot_id, lot.number) == ("tender-1962", "26521012051679")
    assert lot.region == "город Ташкент, Мирзо-Улугбекский район"     # своего региона у лота нет — берём заказчика
    assert (lot.price, lot.deadline) == (812422152, "2026-11-18T10:50:09")
    assert lot.url == "https://ebirja.uz/ru/tender/1962"


def test_request_for_proposals_row_becomes_lot():
    (lot,), _ = lots(offer=[OFFER])
    assert (lot.source_title, lot.lot_id) == ("Ebirja (запрос предложений)", "offer-346")
    assert lot.region == "Самаркандская область"
    assert lot.url == "https://ebirja.uz/ru/offer-request/346"


def test_all_sections_are_read_in_order():
    found, client = lots(auction=[AUCTION], local=[{**AUCTION, "id": 2}], tender=[TENDER], offer=[OFFER])
    assert [lot.lot_id for lot in found] == ["auction-1326", "local-2", "tender-1962", "offer-346"]
    assert len(client.calls) == 4


def test_all_pages_of_a_section_are_read():
    rows = [{**AUCTION, "id": i} for i in range(1, 231)]
    found, client = lots(auction=rows)
    assert [lot.lot_id for lot in found] == [f"auction-{i}" for i in range(1, 231)]
    pages = [parse_qs(urlsplit(call[1]).query)["currentPage"][0] for call in client.calls if "auction_type=1" in call[1]]
    assert pages == ["0", "1", "2"]


def test_lot_with_missing_fields():
    (lot,), _ = lots(offer=[{"id": 7, "company": None}])
    assert (lot.title, lot.number, lot.customer, lot.region, lot.price, lot.deadline) == ("", "", "", "", None, "")


def test_site_error_stops_the_pass():
    client = FakeClient(lambda method, url, body: {"result": None, "errors": {"type": ["Type мажбурий майдон"]}})
    with pytest.raises(RuntimeError, match="ebirja.uz: .*Type мажбурий майдон"):
        list(Ebirja().list_lots(client, {}))


POSITION = {"description": "ТЗ: баннер 3х6",
            "classifier": {"title_ru": "Услуга по установке баннера", "title_uz": "Banner o'rnatish xizmati",
                           "title_uzk": "Баннер ўрнатиш хизмати", "title_en": "не ищем"}}


@pytest.mark.parametrize("row, section, path, field", [
    (AUCTION, "auction", "auction/auction/auction-view", "auction_classifiers"),
    (AUCTION, "local", "auction/auction/auction-view", "auction_classifiers"),
    (TENDER, "tender", "tender-v2/producer/landing-lots-view", "products"),
    (OFFER, "offer", "offer-request/offer-request/announce-view", "classifiers"),
])
def test_details_add_position_names_and_descriptions(row, section, path, field):
    (lot,), _ = lots(**{section: [row]})
    detail = {field: [POSITION, {"description": None, "classifier": None}], "description": "Общее описание"}
    client = FakeClient(site(views={path: {str(row["id"]): detail}}))
    title = lot.title
    lot = Ebirja().enrich(client, lot)
    assert lot.details.split("\n") == ["Услуга по установке баннера", "Banner o'rnatish xizmati",
                                       "Баннер ўрнатиш хизмати", "ТЗ: баннер 3х6", "Общее описание"]
    assert lot.title == title
    assert len(client.calls) == 1


def test_lot_without_positions_has_empty_details():
    (lot,), _ = lots(offer=[OFFER])
    client = FakeClient(site(views={"offer-request/offer-request/announce-view": {"346": {"classifiers": None}}}))
    assert Ebirja().enrich(client, lot).details == ""

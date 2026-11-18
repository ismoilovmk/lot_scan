"""Разделы xarid.uzex.uz, которые открываются только из Узбекистана: Taklif so'rovi и Mahalliy auksion."""
from fakes import FakeClient

from sources.uzex_local import UzexLocalAuction, UzexRequest

PREQUEST = "https://xarid-api-prequest.uzex.uz/api/Public"
AUCTIONX = "https://xarid-api-auctionx.uzex.uz/api/Lot"

REQUEST_ROW = {"id": 140025, "displayId": "261291380140025", "endDate": "2026-11-18T09:17:34", "startCost": 20500000.0,
               "customerName": "FARG'ONA VILOYATI BOJXONA BOSHQARMASI", "address": "Фарғона шаҳри Тошкент кўчаси 5 уй ",
               "categoryName": "Услуги печатные", "statusName": "Опубликован"}
REQUEST_CARD = {**REQUEST_ROW, "deliveryAddress": "Қува тумани", "details": [
    {"productName": "Баннер", "description": "Баннер 3х6 м с люверсами"},
    {"productName": "Баннер", "description": None},
    {"productName": " Визитная карточка ", "description": "4+4"}]}

AUCTION_ROW = {"id": 1668, "displayNo": "26111131001668", "startCost": 422120560.0, "customerName": None,
               "endDate": "2026-11-18T10:00:00", "regionName": "Ферганская область", "districtName": "Кувинский район",
               "categoryName": "Продукты минеральные неметаллические прочие"}
AUCTION_CARD = {**AUCTION_ROW, "customerName": " Қува туман йўллардан фойдаланиш ДМ ", "details": [
    {"productName": "Асфальт", "description": "Смесь плотная мелкозернистая"}]}


def site(rows, cards=None):
    """Ведёт себя как новые разделы UzEX: ответ {Status, Data}, строки from..to, totalCount в каждой строке."""
    cards = cards or {}

    def handler(method, url, body):
        if method == "POST":
            page = rows[body["from"] - 1:body["to"]]
            return {"Status": 200, "Data": [{**row, "totalCount": len(rows)} for row in page], "message": "Success"}
        return {"Status": 200, "Data": cards[int(url.rsplit("=", 1)[1])], "message": "Success"}

    return handler


def test_request_for_proposals_row_becomes_lot():
    client = FakeClient(site([REQUEST_ROW]))
    (lot,) = UzexRequest().list_lots(client, {})
    assert client.calls[0][:2] == ("POST", f"{PREQUEST}/GetLots")
    assert (lot.source, lot.source_title) == ("uzex_request", "UzEX запрос предложений (Taklif so'rovi)")
    assert (lot.lot_id, lot.number) == ("140025", "261291380140025")
    assert lot.title == "Услуги печатные"                       # до карточки известна только категория
    assert lot.customer == "FARG'ONA VILOYATI BOJXONA BOSHQARMASI"
    assert lot.region == "Фарғона шаҳри 5 уй"                   # региона в списке нет, только адрес заказчика
    assert (lot.price, lot.deadline) == (20500000.0, "2026-11-18T09:17:34")
    assert lot.url == "https://xarid.uzex.uz/request-proposal/3/detail/140025"


def test_request_card_gives_positions_and_delivery_address():
    client = FakeClient(site([REQUEST_ROW], {140025: REQUEST_CARD}))
    source = UzexRequest()
    (lot,) = source.list_lots(client, {})
    lot = source.enrich(client, lot)
    assert client.calls[-1][:2] == ("GET", f"{PREQUEST}/GetLot?id=140025")
    assert lot.title == "Баннер; Визитная карточка"              # одинаковые позиции не повторяются
    assert lot.details == "Баннер 3х6 м с люверсами\n4+4\nҚува тумани"


def test_local_auction_row_becomes_lot():
    client = FakeClient(site([AUCTION_ROW]))
    (lot,) = UzexLocalAuction().list_lots(client, {})
    assert client.calls[0][:2] == ("POST", f"{AUCTIONX}/GetList")
    assert (lot.source, lot.source_title) == ("uzex_local_auction", "UzEX местный аукцион (Mahalliy auksion)")
    assert (lot.lot_id, lot.number) == ("1668", "26111131001668")
    assert lot.title == "Продукты минеральные неметаллические прочие"
    assert lot.region == "Ферганская область, Кувинский район"
    assert (lot.price, lot.deadline, lot.customer) == (422120560.0, "2026-11-18T10:00:00", "")
    assert lot.url == "https://xarid.uzex.uz/new-auction/detail/1668"


def test_local_auction_card_gives_positions_and_customer():
    client = FakeClient(site([AUCTION_ROW], {1668: AUCTION_CARD}))
    source = UzexLocalAuction()
    (lot,) = source.list_lots(client, {})
    lot = source.enrich(client, lot)
    assert client.calls[-1][:2] == ("GET", f"{AUCTIONX}/Get?id=1668")
    assert lot.title == "Асфальт"
    assert lot.customer == "Қува туман йўллардан фойдаланиш ДМ"
    assert lot.details == "Смесь плотная мелкозернистая"


def test_card_without_positions_keeps_the_category_and_customer():
    client = FakeClient(site([REQUEST_ROW], {140025: {"details": None, "customerName": None}}))
    source = UzexRequest()
    (lot,) = source.list_lots(client, {})
    lot = source.enrich(client, lot)
    assert (lot.title, lot.details) == ("Услуги печатные", "")
    assert lot.customer == "FARG'ONA VILOYATI BOJXONA BOSHQARMASI"


def test_list_is_read_page_by_page_until_the_total():
    rows = [{**REQUEST_ROW, "id": i} for i in range(1, 251)]
    client = FakeClient(site(rows))
    assert [lot.lot_id for lot in UzexRequest().list_lots(client, {})] == [str(i) for i in range(1, 251)]
    assert [(call[2]["from"], call[2]["to"]) for call in client.calls] == [(1, 100), (101, 200), (201, 300)]


def test_short_page_does_not_lose_the_rest():
    rows = [{**AUCTION_ROW, "id": i} for i in range(1, 8)]
    handler = site(rows)
    client = FakeClient(lambda method, url, body: handler(method, url, {**body, "to": min(body["to"], body["from"] + 2)}))
    assert len(list(UzexLocalAuction().list_lots(client, {}))) == 7     # сервер отдаёт по три строки


def test_empty_section_gives_no_lots():
    for answer in ({"Status": 200, "Data": [], "message": "Success"}, {"Status": 200, "Data": None}):
        client = FakeClient(lambda method, url, body, answer=answer: answer)
        assert list(UzexLocalAuction().list_lots(client, {})) == []
        assert len(client.calls) == 1


def test_both_sections_are_scanned():
    from sources import ALL_SOURCES
    assert {"uzex_request", "uzex_local_auction"} <= {source.key for source in ALL_SOURCES}


import pytest


@pytest.mark.parametrize("address, region", [
    ("Жиззах вилояти Жиззах шахри Тошкент кўчаси 5 уй", "Жиззах вилояти Жиззах шахри 5 уй"),
    ("Navoiy sh., Farg'ona ko'chasi 12", "Navoiy sh., 12"),
    ("Buxoro, Toshkent ko‘chasi, 3", "Buxoro, 3"),
    ("г. Самарканд, улица Ташкентская, 7", "г. Самарканд, 7"),
    ("Нукус, ул. Ферганская 1", "Нукус, 1"),
    ("Тошкент шаҳри, Амир Темур кучаси 4", "Тошкент шаҳри, Амир 4"),
    (None, ""),
])
def test_street_named_after_a_city_is_not_taken_for_the_region(address, region):
    client = FakeClient(site([{**REQUEST_ROW, "address": address}]))
    (lot,) = UzexRequest().list_lots(client, {})
    assert lot.region == region

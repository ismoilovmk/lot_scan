import pytest
from fakes import FakeClient

from filters import fingerprint
from sources.cooperation import CooperationCatalog

LIST = "https://new.cooperation.uz/ocelot/api-shop/LotRequest/GetLotsInTrade"

ROW = {
    "statusId": 6, "beginDate": "2026-11-09T13:02:31.762405", "endDate": "2026-11-11T14:12:31.762405",
    "lotTnved": "4911109000", "lotEnkt": None, "measureName": "кв. метр", "productName": " Реклама банери ",
    "lotNumber": "SL1621455", "offerNumber": "O1573111", "quantity": 107, "isCertificate": True,
    "minPart": 5, "maxPart": 100,
}


def catalog(rows, page_cap=None):
    """Ведёт себя как список сайта: skip/take в адресе, общее число в result.count.

    page_cap — сервер молча отдаёт не больше стольких строк, сколько бы ни просили."""

    def handler(method, url, body):
        assert method == "GET" and url.startswith(LIST + "?")
        params = dict(part.split("=") for part in url.split("?", 1)[1].split("&"))
        skip, take = int(params["skip"]), int(params["take"])
        if page_cap is not None:
            take = min(take, page_cap)
        return {"statusCode": 200, "result": {"result": rows[skip:skip + take], "count": len(rows)}, "error": None}

    return handler


def lots(rows, **kwargs):
    return list(CooperationCatalog().list_lots(FakeClient(catalog(rows, **kwargs)), {}))


def test_catalog_request_becomes_lot():
    lot = lots([ROW])[0]
    assert (lot.source, lot.source_title) == ("cooperation_catalog", "Cooperation (электронный каталог)")
    assert (lot.lot_id, lot.number) == ("SL1621455", "SL1621455")
    assert lot.title == "Реклама банери — 107 кв. метр"
    assert lot.deadline == "2026-11-11T14:12:31"          # сайт отдаёт ташкентское время, доли секунды не нужны
    # страница оферты, по которой запрошена цена; раздел в адресе сайт не проверяет, поэтому 0
    assert lot.url == "https://new.cooperation.uz/e-catalog/0/O1573111"
    # заказчика, региона и цены сайт в открытом списке не показывает
    assert (lot.customer, lot.region, lot.price) == ("", "", None)


def test_two_requests_for_same_product_are_not_duplicates_when_amounts_differ():
    first, second = lots([ROW, {**ROW, "lotNumber": "SL1621456", "quantity": 88}])
    assert fingerprint(first) != fingerprint(second)


@pytest.mark.parametrize("quantity, measure, title", [
    (34.5, "кв. метр", "Реклама банери — 34.5 кв. метр"),
    (10.0, "штук", "Реклама банери — 10 штук"),
    (None, "штук", "Реклама банери"),
    (3, None, "Реклама банери — 3"),
])
def test_amount_in_title(quantity, measure, title):
    assert lots([{**ROW, "quantity": quantity, "measureName": measure}])[0].title == title


def test_reads_all_pages_even_when_site_gives_less_than_asked():
    rows = [{**ROW, "lotNumber": f"SL{i}"} for i in range(1, 1121)]
    assert [lot.lot_id for lot in lots(rows, page_cap=300)] == [f"SL{i}" for i in range(1, 1121)]


def test_empty_catalog_makes_one_request():
    client = FakeClient(catalog([]))
    assert list(CooperationCatalog().list_lots(client, {})) == []
    assert len(client.calls) == 1


def test_exact_last_page_needs_no_extra_request():
    client = FakeClient(catalog([{**ROW, "lotNumber": f"SL{i}"} for i in range(1, 1001)]))
    assert len(list(CooperationCatalog().list_lots(client, {}))) == 1000
    assert len(client.calls) == 2


def test_site_that_promises_more_rows_than_it_gives_does_not_hang_the_pass():
    reply = {"statusCode": 200, "result": {"result": [], "count": 5}, "error": None}
    client = FakeClient(lambda method, url, body: reply)
    assert list(CooperationCatalog().list_lots(client, {})) == []
    assert len(client.calls) == 1


@pytest.mark.parametrize("reply, shown", [
    ({"statusCode": 500, "result": None, "error": "сбой"}, "сбой"),
    ({"statusCode": 500, "result": {"result": [ROW], "count": 1}, "error": "сбой"}, "сбой"),   # код ошибки важнее данных
    ({"statusCode": 200, "result": None, "error": None}, "200"),                               # данных нет вовсе
    ({"statusCode": 503, "result": None, "error": None}, "503"),
    ({"result": None}, "None"),
])
def test_site_error_stops_the_pass_instead_of_hiding_lots(reply, shown):
    with pytest.raises(RuntimeError) as failure:
        list(CooperationCatalog().list_lots(FakeClient(lambda method, url, body: reply), {}))
    assert str(failure.value) == f"cooperation.uz: {shown}"


@pytest.mark.parametrize("offer", [None, "", " "])
def test_lot_without_offer_links_to_the_list_of_requests(offer):
    assert lots([{**ROW, "offerNumber": offer}])[0].url == "https://new.cooperation.uz/active-trades?tab=eCatalog"


def test_lot_without_deadline():
    assert lots([{**ROW, "endDate": None}])[0].deadline == ""

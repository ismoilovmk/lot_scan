"""tendergpt.uz — коммерческие закупки частных компаний."""
from __future__ import annotations

import re

from .base import Lot, Source

ORIGIN = "https://tendergpt.uz"
API = f"{ORIGIN}/lk/api"
PAGE = 50
ACCEPTING_BIDS = "Идёт прием заявок"
# тело запроса снято с сайта: без полного списка способов закупки часть лотов не приходит
SEARCH = {
    "title": "", "region": None, "statuses": [], "inn": "", "publicationDateFrom": "", "publicationDateTo": "",
    "priceFrom": None, "priceBefore": None, "prepaymentFrom": "", "deliveryTime": "", "currencies": None,
    "purchaseTypes": ["REQUEST_OFFERS", "REQUEST_PRICE", "CONTEST", "MAKE_OFFERS", "REQUEST_QUOTATION",
                      "QUOTATION_MAKE_OFFERS", "COMPETITIVE_SELECTION", "PREQUALIFICATION", "MINI_PURCHASE",
                      "STOCK_MARKET", "AUCTION", "AUCTION_DOWN"],
    "ikpuPrefixs": None,
}


def _price(value: str | None) -> float | None:
    """'UZS 1500000' -> 1500000.0. Ноль на этой площадке значит «цена не указана»."""
    digits = re.sub(r"[^\d.,]", "", value or "").replace(",", ".")
    try:
        return float(digits) or None
    except ValueError:
        return None


class TenderGpt(Source):
    key = "tendergpt"
    title = "TenderGPT"

    def list_lots(self, client, cfg):
        page = 1
        while True:
            reply = client.post_json(f"{API}/v3/procedures/search?page={page}&limit={PAGE}", ORIGIN, SEARCH)
            for row in reply["data"]:
                if row.get("status") == ACCEPTING_BIDS:
                    yield self._lot(row)
            if page * PAGE >= reply["total"]:
                return
            page += 1

    def _lot(self, row: dict) -> Lot:
        customer = row.get("customer_info_full_title_organization") or row.get("full_title_organization") or ""
        return Lot(
            source=self.key,
            source_title=self.title,
            lot_id=str(row["id_number"]),
            number=str(row["id_number"]),
            title=(row.get("title") or "").strip(),
            customer=customer.strip(),
            region=row.get("customer_info_address") or "",
            price=_price(row.get("original_price")),
            currency=row.get("currency") or "UZS",
            deadline=(row.get("closing_date_of_applications") or "").replace(" ", "T"),
            url=f"{ORIGIN}/tender/{row['id_number']}",
        )

    def enrich(self, client, lot):
        procedure = client.get_json(f"{API}/v1/procedures/{lot.lot_id}", ORIGIN)
        texts = []
        for part in procedure.get("lots") or []:
            positions = client.get_json(f"{API}/v1/lots/{part['id']}/positions?limit=50&page=1", ORIGIN)
            for item in positions["data"]:
                texts += [item.get("name"), item.get("info"), item.get("ikpu_name")]
        lot.details = "\n".join(text.strip() for text in texts if text)
        return lot

"""xarid.uzex.uz — аукцион на понижение и отбор наилучших предложений (69-ПКМ).

В списках этих разделов нет названия лота, только категория, поэтому
названия позиций подтягиваются отдельным запросом по каждому лоту.
"""
from __future__ import annotations

from .base import Lot, Source, join_region, paged

ORIGIN = "https://xarid.uzex.uz"
AUCTION_API = "https://xarid-api-auction.uzex.uz/Common"
PURCHASE_API = "https://xarid-api-purchase.uzex.uz/Common"


def _positions(data: dict) -> tuple[str, str]:
    """Возвращает (названия позиций через '; ', все описания одним текстом)."""
    names, texts = [], []
    for item in data.get("js_details") or []:
        name = (item.get("product_name") or "").strip()
        if name and name not in names:
            names.append(name)
        texts.append(item.get("description") or "")
    return "; ".join(names), "\n".join(t for t in texts if t)


def _apply_details(lot: Lot, data: dict, extra_fields: tuple[str, ...]) -> Lot:
    names, texts = _positions(data)
    if names:
        lot.title = names[:300]
    lot.customer = (data.get("customer_name") or "").strip()
    extra = "\n".join(str(data.get(f) or "") for f in extra_fields)
    # Категорию в поиск не берём: «Услуги рекламные и исследование рынка» ловит опросы и т.п.
    lot.details = "\n".join(p for p in (texts, extra) if p)
    return lot


class UzexAuction(Source):
    key = "uzex_auction"
    title = "UzEX аукцион"

    def list_lots(self, client, cfg):
        url = f"{AUCTION_API}/GetMinimizedLotsList"
        # больше 20 строк за запрос этот раздел не отдаёт (HTTP 500)
        for row in paged(client, url, ORIGIN, {"region_ids": []}, page_size=20):
            yield Lot(
                source=self.key,
                source_title=self.title,
                lot_id=str(row["id"]),
                number=str(row.get("display_no") or ""),
                title=(row.get("category_name") or "").strip(),
                region=join_region(row.get("region_name"), row.get("district_name")),
                price=row.get("start_cost"),
                deadline=row.get("end_date") or "",
                url=f"{ORIGIN}/auction/detail/{row['id']}",
            )

    def enrich(self, client, lot):
        data = client.get_json(f"{AUCTION_API}/GetLot/{lot.lot_id}", ORIGIN)
        return _apply_details(lot, data, ("description",))


class UzexCompetition(Source):
    key = "uzex_competition"
    title = "UzEX отбор (69-ПКМ)"

    def list_lots(self, client, cfg):
        url = f"{PURCHASE_API}/GetCompetitions"
        max_rows = int(cfg.get("competition_max_lots", 300))
        for row in paged(client, url, ORIGIN, {"region_ids": []}, max_rows=max_rows):
            yield Lot(
                source=self.key,
                source_title=self.title,
                lot_id=str(row["id"]),
                number=str(row["id"]),
                title=(row.get("category_name") or "").strip(),
                region=join_region(row.get("customer_region_name"), row.get("customer_district_name")),
                price=row.get("cost"),
                deadline=row.get("end_date_submitting_offers") or "",
                url=f"{ORIGIN}/purchase/competition/detail/{row['id']}",
            )

    def enrich(self, client, lot):
        data = client.get_json(f"{PURCHASE_API}/GetCompetition/{lot.lot_id}", ORIGIN)
        return _apply_details(lot, data, ("description", "note", "competition_description"))

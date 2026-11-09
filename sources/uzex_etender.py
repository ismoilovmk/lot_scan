"""etender.uzex.uz — тендеры и отбор наилучших предложений."""
from __future__ import annotations

from .base import Lot, Source, join_region, paged

ORIGIN = "https://etender.uzex.uz"
API = "https://apietender.uzex.uz/api/common/TradeList"

# typeid в запросе -> как называется раздел
TYPES = {1: "отбор", 2: "тендер"}


class UzexEtender(Source):
    key = "uzex_etender"
    title = "UzEX etender"

    def list_lots(self, client, cfg):
        for type_id, type_name in TYPES.items():
            body = {"is_agent": None, "Is_Scientific": None, "System_Id": 0, "typeid": type_id}
            for row in paged(client, API, ORIGIN, body):
                yield Lot(
                    source=self.key,
                    source_title=f"{self.title} ({type_name})",
                    lot_id=str(row["id"]),
                    number=str(row.get("display_no") or ""),
                    title=(row.get("name") or "").strip(),
                    customer=(row.get("seller_name") or "").strip(),
                    region=join_region(row.get("region_name"), row.get("district_name")),
                    price=row.get("cost"),
                    currency=row.get("currency_codeabc") or "UZS",
                    deadline=row.get("end_date") or "",
                    url=f"{ORIGIN}/lot/{row['id']}",
                )

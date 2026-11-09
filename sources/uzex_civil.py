"""etender.uzex.uz — раздел «Eng yaxshi takliflarni tanlash (69-son VMQ)»."""
from __future__ import annotations

from .base import Lot, Source, join_region, paged
from .uzex_etender import ORIGIN, position_texts

API = "https://apietender.uzex.uz/api/CivilContracts"
PUBLISHED = 3  # статус «опубликован»


class UzexCivil(Source):
    key = "uzex_civil"
    title = "UzEX etender (отбор 69-ПКМ)"

    def list_lots(self, client, cfg):
        # этот раздел понимает только From/To с большой буквы
        for row in paged(client, f"{API}/GetList", ORIGIN, {"status_Id": PUBLISHED}, keys=("From", "To")):
            yield Lot(
                source=self.key,
                source_title=self.title,
                lot_id=str(row["id"]),
                number=str(row.get("display_id") or ""),
                title=(row.get("name") or "").strip(),
                customer=(row.get("customer_name") or "").strip(),
                region=join_region(row.get("delivery_address"), row.get("provision_address")),
                price=row.get("cost"),
                deadline=row.get("end_date") or "",
                url=f"{ORIGIN}/civil-detail/{row['id']}",
            )

    def enrich(self, client, lot):
        data = client.get_json(f"{API}/Get/{lot.lot_id}", ORIGIN)
        texts = position_texts(data.get("js_products")) + [data.get("description")]
        lot.details = "\n".join(str(text) for text in texts if text)
        return lot

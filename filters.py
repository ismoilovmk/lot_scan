"""Фильтр лотов по ключевым словам и региону."""
from __future__ import annotations

# Узбекская кириллица -> ближайшие русские буквы, чтобы "Фарғона" и "Фаргона" совпадали
_LETTERS = str.maketrans({"ё": "е", "ў": "у", "қ": "к", "ғ": "г", "ҳ": "х"})
_APOSTROPHES = "'’‘`ʻʼ´"


def normalize(text: str) -> str:
    text = (text or "").lower().translate(_LETTERS)
    for ch in _APOSTROPHES:
        text = text.replace(ch, "")
    return " ".join(text.split())


def _norm_list(values) -> list[str]:
    return [n for n in (normalize(str(v)) for v in values or []) if n]


class LotFilter:
    def __init__(self, cfg: dict):
        self.keywords = _norm_list(cfg.get("keywords"))
        self.excludes = _norm_list(cfg.get("exclude_keywords"))
        self.regions = _norm_list(cfg.get("regions"))
        self.allow_unknown_region = bool(cfg.get("allow_unknown_region", True))

    def match_keywords(self, text: str) -> list[str]:
        """Какие ключевые слова нашлись в тексте (пустой список — лот не подходит)."""
        text = normalize(text)
        for phrase in self.excludes:
            text = text.replace(phrase, " ")
        return [k for k in self.keywords if k in text]

    def region_ok(self, region: str) -> bool:
        region = normalize(region)
        if not region:
            return self.allow_unknown_region
        if not self.regions:
            return True
        return any(r in region for r in self.regions)

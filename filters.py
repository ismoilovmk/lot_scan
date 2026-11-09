"""Фильтр лотов по ключевым словам и региону."""
from __future__ import annotations

# Узбекская кириллица -> ближайшие русские буквы, чтобы "Фарғона" и "Фаргона" совпадали
_LETTERS = str.maketrans({"ё": "е", "ў": "у", "қ": "к", "ғ": "г", "ҳ": "х"})
# Кириллические буквы, на вид неотличимые от латинских. В документах их постоянно путают
# ("бaннер" с латинской a), поэтому перед сравнением приводим их к одному виду.
_LOOKALIKES = str.maketrans("аеорсху", "aeopcxy")
_APOSTROPHES = "'’‘`ʻʼ´"


def normalize(text: str) -> str:
    """Вид текста для сравнения: без регистра, лишних пробелов, апострофов и путаницы алфавитов."""
    text = (text or "").lower().translate(_LETTERS).translate(_LOOKALIKES)
    for ch in _APOSTROPHES:
        text = text.replace(ch, "")
    return " ".join(text.split())


def _words(values) -> list[tuple[str, str]]:
    """Слова из config.yaml: [(как написано, вид для сравнения)]. Пустые значения пропускаются."""
    written = [str(value).strip() for value in values or [] if value is not None]
    return [(word, normalize(word)) for word in written if word]


class LotFilter:
    def __init__(self, cfg: dict):
        self.keywords = _words(cfg.get("keywords"))
        self.excludes = [form for _, form in _words(cfg.get("exclude_keywords"))]
        self.regions = [form for _, form in _words(cfg.get("regions"))]
        self.allow_unknown_region = bool(cfg.get("allow_unknown_region", True))

    def match_keywords(self, text: str) -> list[str]:
        """Какие ключевые слова нашлись в тексте (пустой список — лот не подходит)."""
        text = normalize(text)
        for phrase in self.excludes:
            text = text.replace(phrase, " ")
        return [word for word, form in self.keywords if form in text]

    def region_ok(self, region: str) -> bool:
        region = normalize(region)
        if not region:
            return self.allow_unknown_region
        if not self.regions:
            return True
        return any(r in region for r in self.regions)

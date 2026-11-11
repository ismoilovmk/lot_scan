"""Фильтр лотов по ключевым словам и региону."""
from __future__ import annotations

import hashlib
import json

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


def _written(values) -> list[str]:
    """Слова из config.yaml как написаны. Пустые значения пропускаются."""
    return [word for word in (str(value).strip() for value in values or [] if value is not None) if word]


def _forms(values) -> list[str]:
    return [normalize(word) for word in _written(values)]


def _rules(values) -> list[tuple[str, list[str]]]:
    """Правила услуги: [(как написано, части)]. «чоп + футболка» — в тексте должны быть обе части."""
    rules = [(rule, [part for part in map(normalize, rule.split("+")) if part]) for rule in _written(values)]
    return [(rule, parts) for rule, parts in rules if parts]


def _groups(section, parse) -> list[tuple[str, list]]:
    """Раздел config.yaml вида «название: [слова]» -> [(название, разобранные слова)]."""
    return [(str(name), parse(words)) for name, words in (section or {}).items()]


# Настройки, от которых зависит, какие лоты подходят. Изменились — старые отказы пересматриваются.
_VOCABULARY = ("services", "exclude_keywords", "regions", "allow_unknown_region", "xt_xarid_regions")


def vocabulary_signature(cfg: dict) -> str:
    """Отпечаток настроек поиска: одинаковый, пока слова и регионы не менялись."""
    text = json.dumps([cfg.get(key) for key in _VOCABULARY], sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def fingerprint(lot) -> str:
    """Признак «это тот же самый лот»: одно название, заказчик и цена, под каким бы номером он ни шёл."""
    title = normalize(lot.title)
    if not title:
        return ""
    price = lot.price or 0
    return f"{title}|{normalize(lot.customer)}|{price:.0f}"


def by_chat(found: dict[str, list[str]], service_chats: dict[str, str]) -> dict[str, dict[str, list[str]]]:
    """Делит найденные услуги по чатам: {чат: {услуга: слова}}. Чат «» — основной."""
    groups: dict[str, dict[str, list[str]]] = {}
    for service, words in found.items():
        groups.setdefault(service_chats.get(service, ""), {})[service] = words
    return groups


class LotFilter:
    def __init__(self, cfg: dict):
        self.services = _groups(cfg.get("services"), _rules)
        self.excludes = _forms(cfg.get("exclude_keywords"))
        self.regions = _groups(cfg.get("regions"), _forms)
        self.priority_region = str(cfg.get("priority_region") or "")
        self.allow_unknown_region = bool(cfg.get("allow_unknown_region", True))

    def match(self, text: str) -> dict[str, list[str]]:
        """Услуги, о которых лот: {услуга: найденные слова}. Пусто — лот не подходит."""
        text = normalize(text)
        for phrase in self.excludes:
            text = text.replace(phrase, " ")
        found = {}
        for name, rules in self.services:
            words = [rule for rule, parts in rules if all(part in text for part in parts)]
            if words:
                found[name] = words
        return found

    def region_name(self, region: str) -> str:
        """Название региона из config.yaml, к которому относится адрес. Пусто — ни к одному."""
        region = normalize(region)
        return next((name for name, forms in self.regions if any(form in region for form in forms)), "")

    def priority(self, region: str) -> str:
        """Название приоритетного региона, если лот из него, иначе пусто."""
        name = self.region_name(region)
        return name if name and name == self.priority_region else ""

    def region_ok(self, region: str) -> bool:
        if not normalize(region):
            return self.allow_unknown_region
        return not self.regions or bool(self.region_name(region))

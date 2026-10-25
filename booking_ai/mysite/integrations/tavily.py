"""Поиск объявлений в интернете через Tavily (https://tavily.com).

Клиент синхронный: граф LangGraph работает в рабочем потоке и вызывает `deps.search_web(filters)` как обычную функцию.
Страницы сайтов мы сами не скачиваем, берём только заголовок, ссылку и фрагмент текста из ответа Tavily,
поэтому robots.txt здесь не затрагивается. Цену и прочие поля из фрагментов не вытаскиваем: угаданная цена
хуже, чем её отсутствие. Пользователь получает ссылку на первоисточник и проверяет объявление на сайте."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

log = logging.getLogger("booking_ai.tavily")

TAVILY_URL = "https://api.tavily.com/search"

CATEGORY_WORDS = {
    "real_estate": "недвижимость", "real_estate_rent": "аренда недвижимости", "apartment_rent": "аренда квартиры",
    "room_rent": "аренда комнаты", "house_rent": "аренда дома", "real_estate_sale": "продажа недвижимости",
    "apartment_sale": "купить квартиру", "house_sale": "купить дом", "hotel": "отель",
    "tourist_services": "туристические услуги",
}


class WebSearchLimitError(Exception):
    """Исчерпан суточный лимит поиска в интернете."""


def _num(value) -> str:
    text = str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def build_query(filters: dict) -> str:
    """Текст запроса из фильтров. Пустая строка, если искать по сути нечего: зря платить за запрос не нужно."""
    category = CATEGORY_WORDS.get(filters.get("category") or "")
    place = filters.get("city") or filters.get("country")
    extra = [str(x) for x in (filters.get("extra") or [])][:3]
    if not (category or place or filters.get("property_type") or extra):
        return ""
    parts = [category or filters.get("property_type") or "объявления", place]
    if filters.get("rooms") is not None:
        parts.append(f"{filters['rooms']} комн.")
    currency = filters.get("currency") or ""
    if filters.get("price_min") is not None:
        parts.append(f"от {_num(filters['price_min'])} {currency}".strip())
    if filters.get("price_max") is not None:
        parts.append(f"до {_num(filters['price_max'])} {currency}".strip())
    parts += extra
    return " ".join(" ".join(str(p) for p in parts if p).split())[:300]


def parse_results(data: dict, limit: int) -> list[dict]:
    """Ответ Tavily → результаты в формате, который понимает граф. Всё, что не похоже на http(s)-ссылку, отбрасываем."""
    found = []
    items = data.get("results") if isinstance(data, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        url = item["url"].strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        host = parsed.netloc.lower().removeprefix("www.")
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        snippet = item.get("content") if isinstance(item.get("content"), str) else ""
        found.append({"id": None, "title": (title.strip() or host)[:255], "description": snippet.strip()[:300],
                      "source_url": url[:2048], "source_name": host[:128], "status": "external",
                      "price": None, "currency": None})
        if len(found) >= limit:
            break
    return found


class TavilySearch:
    def __init__(self, api_key: str, *, max_results: int = 5, timeout: float = 15.0,
                 transport: httpx.BaseTransport | None = None):
        self._key = api_key
        self.max_results = max_results
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __call__(self, filters: dict) -> list[dict]:
        query = build_query(filters)
        if not query:
            return []
        # ключ только в заголовке: в тексте ошибок httpx он не появляется
        response = self._http.post(
            TAVILY_URL, headers={"Authorization": f"Bearer {self._key}"},
            json={"query": query, "max_results": self.max_results, "search_depth": "basic", "include_answer": False})
        response.raise_for_status()
        return parse_results(response.json(), self.max_results)

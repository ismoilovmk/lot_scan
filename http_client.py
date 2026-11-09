"""HTTP-клиент: паузы между запросами и повтор при временных ошибках."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

# API UzEX отвечает 403/500 на запросы без обычных браузерных заголовков
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
}
RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, pause: float = 0.5, timeout: float = 40, retries: int = 3):
        self.pause = pause
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last = 0.0

    def post_json(self, url: str, origin: str, body: dict):
        return self._request("POST", url, origin, body)

    def get_json(self, url: str, origin: str):
        return self._request("GET", url, origin, None)

    def _request(self, method: str, url: str, origin: str, body):
        headers = {"Origin": origin, "Referer": origin + "/"}
        error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            wait = self._last + self.pause - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.request(method, url, json=body, headers=headers, timeout=self.timeout)
                self._last = time.monotonic()
                if resp.status_code in RETRY_STATUSES:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                self._last = time.monotonic()
                error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and status not in RETRY_STATUSES:
                    break  # 403/404 повтором не лечатся
                if attempt < self.retries:
                    delay = 5 * attempt
                    log.warning("%s %s: %s — повтор через %s с", method, url, exc, delay)
                    time.sleep(delay)
        raise RuntimeError(f"{method} {url} не удался: {error}") from error

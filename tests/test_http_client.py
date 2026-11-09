import pytest
import requests

import http_client
from http_client import HttpClient


class FakeClock:
    """Время идёт только когда кто-то «спит», поэтому тесты мгновенные и точные."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.now += seconds


class FakeResponse:
    def __init__(self, status=200, data=None, bad_json=False):
        self.status_code = status
        self.data = data
        self.bad_json = bad_json

    def json(self):
        if self.bad_json:
            raise ValueError("не JSON")
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, answers, clock):
        self.answers = list(answers)
        self.clock = clock
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers,
                           "timeout": timeout, "at": self.clock.now})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def site(monkeypatch):
    """site(answers) -> (client, session): клиент, который вместо сети получает answers по очереди."""
    clock = FakeClock()
    monkeypatch.setattr(http_client.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(http_client.time, "sleep", clock.sleep)

    def make(answers, **kwargs):
        client = HttpClient(**kwargs)
        client.session = FakeSession(answers, clock)
        return client, client.session

    return make


def test_post_sends_body_and_site_headers_and_returns_json(site):
    client, session = site([FakeResponse(data=[{"id": 1}])])
    assert client.post_json("https://api.test/list", "https://site.test", {"from": 1}) == [{"id": 1}]
    call = session.calls[0]
    assert (call["method"], call["url"], call["json"]) == ("POST", "https://api.test/list", {"from": 1})
    assert call["headers"] == {"Origin": "https://site.test", "Referer": "https://site.test/"}
    assert call["timeout"] == 40


def test_get_sends_no_body(site):
    client, session = site([FakeResponse(data={"id": 5})])
    assert client.get_json("https://api.test/lot/5", "https://site.test") == {"id": 5}
    assert (session.calls[0]["method"], session.calls[0]["json"]) == ("GET", None)


def test_real_session_looks_like_a_browser():
    headers = HttpClient().session.headers
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    assert headers["Accept"] == "application/json, text/plain, */*"
    assert headers["Accept-Language"] == "ru"


@pytest.mark.parametrize("failure", [
    FakeResponse(status=429), FakeResponse(status=500), FakeResponse(status=502),
    FakeResponse(status=503), FakeResponse(status=504),
    requests.ConnectionError("нет связи"), requests.Timeout("таймаут"), FakeResponse(bad_json=True),
])
def test_temporary_failure_is_retried(site, failure):
    client, session = site([failure, FakeResponse(data="ok")])
    assert client.get_json("u", "o") == "ok"
    assert len(session.calls) == 2


@pytest.mark.parametrize("status", [400, 403, 404])
def test_permanent_failure_is_not_retried(site, status):
    client, session = site([FakeResponse(status=status), FakeResponse(data="ok")])
    with pytest.raises(RuntimeError, match=f"GET u не удался: HTTP {status}"):
        client.get_json("u", "o")
    assert len(session.calls) == 1


def test_gives_up_after_three_attempts(site):
    client, session = site([FakeResponse(status=500)] * 5)
    with pytest.raises(RuntimeError, match="POST u не удался: HTTP 500"):
        client.post_json("u", "o", {})
    assert len(session.calls) == 3


def test_number_of_attempts_is_configurable(site):
    client, session = site([FakeResponse(status=500)] * 5, retries=2)
    with pytest.raises(RuntimeError):
        client.get_json("u", "o")
    assert len(session.calls) == 2


def test_waits_longer_before_each_retry_and_not_after_the_last(site):
    client, session = site([FakeResponse(status=500)] * 3)
    start = session.clock.now
    with pytest.raises(RuntimeError):
        client.get_json("u", "o")
    times = [call["at"] - start for call in session.calls]
    assert times == [0, 5.0, 15.0]            # ждём 5 с, затем 10 с
    assert session.clock.now - start == 15.0  # после последней попытки не ждём


def test_requests_are_spaced_by_pause(site):
    client, session = site([FakeResponse(data=1), FakeResponse(data=2), FakeResponse(data=3)], pause=0.5)
    client.get_json("u", "o")
    client.get_json("u", "o")
    session.clock.now += 0.2   # часть паузы уже прошла сама
    client.get_json("u", "o")
    times = [call["at"] - 1000.0 for call in session.calls]
    assert times == [0, 0.5, 1.0]


def test_no_extra_wait_when_pause_already_passed(site):
    client, session = site([FakeResponse(data=1), FakeResponse(data=2)], pause=0.5)
    client.get_json("u", "o")
    session.clock.now += 0.5
    client.get_json("u", "o")   # FakeClock.sleep упадёт, если попросят спать 0 секунд
    assert session.calls[1]["at"] == 1000.5


# --- сайты со своим лимитом запросов ---

SLOW = "https://api.slow.test/rpc"
FAST = "https://api.fast.test/list"


def test_slow_host_gets_its_own_longer_pause(site):
    client, session = site([FakeResponse(data=i) for i in range(4)], pause=0.5,
                           host_pauses={"api.slow.test": 65})
    client.get_json(SLOW, "o")
    client.get_json(FAST, "o")     # другой сайт не ждёт паузу медленного
    client.get_json(FAST, "o")
    client.get_json(SLOW, "o")
    times = [(call["url"], call["at"] - 1000.0) for call in session.calls]
    assert times == [(SLOW, 0), (FAST, 0), (FAST, 0.5), (SLOW, 65)]


def test_retry_on_slow_host_waits_at_least_its_pause(site):
    client, session = site([FakeResponse(status=429), FakeResponse(status=429), FakeResponse(data="ok")],
                           host_pauses={"api.slow.test": 65})
    assert client.post_json(SLOW, "o", {}) == "ok"
    assert [call["at"] - 1000.0 for call in session.calls] == [0, 65, 130]


def test_long_retry_delay_is_kept_when_longer_than_host_pause(site):
    client, session = site([FakeResponse(status=500), FakeResponse(status=500), FakeResponse(data="ok")],
                           host_pauses={"api.slow.test": 7})
    client.get_json(SLOW, "o")
    assert [call["at"] - 1000.0 for call in session.calls] == [0, 7, 17]   # 7 (пауза сайта), затем 10

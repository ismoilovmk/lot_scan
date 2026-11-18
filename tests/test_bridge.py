"""Мост: компьютер в Узбекистане, через интернет которого сервер ходит на сайты, закрытые для дата-центров."""
import socket
import threading

import pytest

import bridge


@pytest.fixture
def listener():
    """listener(reply) -> (порт, что прислали): местный «мост», который на приветствие отвечает reply.

    reply=None — соединение принимает, но молчит: так выглядит мост после обрыва связи.
    """
    servers = []

    def make(reply):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        servers.append(server)
        heard = []

        def serve():
            try:
                link, _ = server.accept()
            except OSError:
                return
            with link:
                link.settimeout(2)
                try:
                    heard.append(link.recv(16))
                    if reply is not None:
                        link.sendall(reply)
                    link.recv(1)  # держим соединение, пока его не закроет проверяющий
                except OSError:
                    pass

        threading.Thread(target=serve, daemon=True).start()
        return server.getsockname()[1], heard

    yield make
    for server in servers:
        server.close()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_living_bridge_answers_the_socks_greeting(listener):
    port, heard = listener(b"\x05\x00")
    assert bridge.answers(port, timeout=1) is True
    assert heard == [b"\x05\x01\x00"]          # «SOCKS5, один способ входа, без пароля»


def test_port_that_listens_but_keeps_silent_is_not_a_bridge(listener):
    port, _ = listener(None)
    assert bridge.answers(port, timeout=0.3) is False


@pytest.mark.parametrize("reply", [b"\x05\xff", b"\x04\x00", b"HT", b""])
def test_wrong_answer_is_not_a_bridge(listener, reply):
    port, _ = listener(reply)
    assert bridge.answers(port, timeout=1) is False


def test_closed_port_is_not_a_bridge():
    assert bridge.answers(free_port(), timeout=1) is False


def test_proxy_is_the_first_port_where_the_bridge_answers():
    asked = []

    def answers(port):
        asked.append(port)
        return port in (1081, 1082)

    cfg = {"bridge": {"ports": [1080, "1081", 1082]}}
    assert bridge.proxy(cfg, answers) == "socks5h://127.0.0.1:1081"
    assert asked == [1080, 1081]               # дальше первого живого порта не ищем


def test_no_proxy_when_no_port_answers_or_no_bridge_is_configured():
    assert bridge.proxy({"bridge": {"ports": [1080, 1081]}}, lambda port: False) == ""
    assert bridge.proxy({"bridge": {"ports": []}}, lambda port: True) == ""
    assert bridge.proxy({"bridge": None}, lambda port: True) == ""
    assert bridge.proxy({}, lambda port: True) == ""


def test_proxy_asks_the_real_port_by_default(listener):
    port, _ = listener(b"\x05\x00")
    assert bridge.proxy({"bridge": {"ports": [free_port(), port]}}) == f"socks5h://127.0.0.1:{port}"

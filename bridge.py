"""Мост: обычный компьютер в Узбекистане, через интернет которого сервер ходит на закрытые для него сайты.

new.cooperation.uz не отвечает адресам дата-центров, а с домашнего или офисного интернета открывается.
Компьютер-мост подключается к серверу командой «ssh -R порт» (файл tools/most.bat), и на сервере
появляется местный порт: всё, что бот отправит в него, выйдет в интернет с того компьютера (SOCKS5).
"""
from __future__ import annotations

import socket

GREETING = b"\x05\x01\x00"  # «SOCKS5, один способ входа, без пароля»
ACCEPTED = b"\x05\x00"      # мост согласен


def answers(port: int, timeout: float = 3.0) -> bool:
    """Жив ли мост на этом порту сервера.

    После обрыва связи порт ещё долго числится открытым, поэтому мало к нему подключиться:
    мост надо спросить и дождаться ответа.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as link:
            link.sendall(GREETING)
            return link.recv(2) == ACCEPTED
    except OSError:
        return False


def proxy(cfg: dict, answers=answers) -> str:
    """Адрес живого моста для запросов или пустая строка, если моста сейчас нет."""
    ports = (cfg.get("bridge") or {}).get("ports") or []
    port = next((int(port) for port in ports if answers(int(port))), None)
    return f"socks5h://127.0.0.1:{port}" if port else ""

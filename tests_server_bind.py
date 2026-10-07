"""app.server 监听地址回归测试：HOST / PORT 可配置，默认 127.0.0.1:8000。

运行：python tests_server_bind.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

from app.server import listen_address

ROOT = Path(__file__).resolve().parent


@contextmanager
def env(**values):
    old = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def check_listen_address():
    with env(HOST=None, PORT=None):
        assert listen_address() == ("127.0.0.1", 8000)
    with env(HOST="", PORT=""):
        assert listen_address() == ("127.0.0.1", 8000)
    with env(HOST="0.0.0.0", PORT="9001"):
        assert listen_address() == ("0.0.0.0", 9001)
    with env(HOST=" 0.0.0.0 ", PORT=" 8080 "):
        assert listen_address() == ("0.0.0.0", 8080)
    for bad in ["abc", "0", "70000"]:
        with env(PORT=bad):
            try:
                listen_address()
            except SystemExit:
                pass
            else:
                raise AssertionError(f"PORT={bad!r} 应该报错")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def lan_ip() -> str | None:
    """本机的非回环地址（UDP connect 不会真的发包）；拿不到就返回 None。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def wait_health(port: int, proc: subprocess.Popen, host: str = "127.0.0.1") -> None:
    deadline = time.time() + 15
    while True:
        try:
            with urlopen(f"http://{host}:{port}/health", timeout=2) as response:
                assert json.load(response)["ok"] is True
            return
        except OSError:
            if proc.poll() is not None or time.time() > deadline:
                raise AssertionError(f"server 没有启动: {proc.stdout.read() if proc.stdout else ''}")
            time.sleep(0.2)


@contextmanager
def running_server(host: str):
    port = free_port()
    child_env = {**os.environ, "HOST": host, "PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=ROOT, env=child_env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_health(port, proc)
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def check_server_honours_host():
    ip = lan_ip()
    with running_server("0.0.0.0") as port:
        # HOST=0.0.0.0：回环和本机网卡地址都能访问（Docker 端口映射走的就是网卡地址）
        if ip:
            assert reachable(ip, port), f"HOST=0.0.0.0 时 {ip}:{port} 应可访问"
    with running_server("127.0.0.1") as port:
        # 默认 127.0.0.1：只允许本机回环访问
        if ip:
            assert not reachable(ip, port), f"HOST=127.0.0.1 时 {ip}:{port} 不应可访问"
    return ip


if __name__ == "__main__":
    check_listen_address()
    ip = check_server_honours_host()
    print(f"ok (LAN IP check: {ip or 'skipped, no non-loopback address'})")

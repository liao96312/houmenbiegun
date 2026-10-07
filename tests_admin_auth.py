"""后台鉴权回归测试：所有 /api/admin/* 接口在 FastAPI(app.main) 和标准库(app.server)两套实现里都必须校验 ADMIN_TOKEN。

运行：python tests_admin_auth.py（FastAPI 部分需要 httpx，CI 会额外安装）
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import core

TOKEN = "test-admin-token-123"

READ_ROUTES = [
    "/api/admin/scenes",
    "/api/admin/prompts",
    "/api/admin/safety-events",
    "/api/admin/feedback",
    "/api/admin/conversations",
]
EXPORT_ROUTES = [
    "/api/admin/export/safety-events.csv",
    "/api/admin/export/feedback.csv",
    "/api/admin/export/conversations.csv",
]
WRITE_ROUTES = {
    "/api/admin/scenes": lambda: list(core.SCENES),
    "/api/admin/prompts": lambda: dict(core.PROMPTS),
}


@contextmanager
def admin_token(value: str | None):
    old = os.environ.get("ADMIN_TOKEN")
    if value is None:
        os.environ.pop("ADMIN_TOKEN", None)
    else:
        os.environ["ADMIN_TOKEN"] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("ADMIN_TOKEN", None)
        else:
            os.environ["ADMIN_TOKEN"] = old


@contextmanager
def no_disk_writes(*modules):
    """写接口测试时不真正改 data/*.json。"""
    saved = []
    for module in modules:
        saved.append((module, module.save_scenes, module.save_prompts))
        module.save_scenes = lambda body: None
        module.save_prompts = lambda body: None
    try:
        yield
    finally:
        for module, scenes, prompts in saved:
            module.save_scenes = scenes
            module.save_prompts = prompts


def check_core():
    with admin_token(None):
        assert core.admin_auth_error(TOKEN)[0] == 503
        assert not core.admin_token_ok(None)
        assert not core.admin_token_configured()
        assert core.warn_if_admin_token_missing() is False
    with admin_token("   "):
        assert core.admin_auth_error(TOKEN)[0] == 503
    with admin_token(TOKEN):
        assert core.admin_auth_error(None) == (401, "admin token required")
        assert core.admin_auth_error("")[0] == 401
        assert core.admin_auth_error("wrong")[0] == 401
        assert core.admin_auth_error(TOKEN + "x")[0] == 401
        assert core.admin_auth_error(TOKEN) is None
        assert core.admin_token_ok(TOKEN)
        assert core.warn_if_admin_token_missing() is True
    assert core.extract_admin_token(TOKEN, None) == TOKEN
    assert core.extract_admin_token(None, f"Bearer {TOKEN}") == TOKEN
    assert core.extract_admin_token(None, f"bearer {TOKEN}") == TOKEN
    assert core.extract_admin_token(None, f"Basic {TOKEN}") is None
    assert core.extract_admin_token(None, "Bearer ") is None
    assert core.extract_admin_token(None, None) is None


def run_matrix(request):
    """request(method, path, headers, body) -> status。对读/导出/写接口跑完整矩阵。"""
    cases = [("GET", path, None) for path in READ_ROUTES + EXPORT_ROUTES]
    cases += [("POST", path, make()) for path, make in WRITE_ROUTES.items()]
    checked = 0
    for method, path, body in cases:
        with admin_token(None):
            # ADMIN_TOKEN 未设置：即使带了口令也必须拒绝（fail closed）
            assert request(method, path, {}, body) == 503, (method, path, "unset/no token")
            assert request(method, path, {"X-Admin-Token": TOKEN}, body) == 503, (method, path, "unset/with token")
        with admin_token(TOKEN):
            assert request(method, path, {}, body) == 401, (method, path, "no token")
            assert request(method, path, {"X-Admin-Token": "wrong"}, body) == 401, (method, path, "wrong token")
            assert request(method, path, {"Authorization": "Bearer wrong"}, body) == 401, (method, path, "wrong bearer")
            assert request(method, path, {"X-Admin-Token": TOKEN}, body) == 200, (method, path, "correct token")
            assert request(method, path, {"Authorization": f"Bearer {TOKEN}"}, body) == 200, (method, path, "correct bearer")
        checked += 1
    return checked


def check_fastapi():
    from fastapi.testclient import TestClient

    from app import main

    # 防止以后新增的 /api/admin/* 路由漏掉鉴权：所有这类路由都必须挂 require_admin
    admin_paths = [route.path for route in main.app.routes if getattr(route, "path", "").startswith("/api/admin/")]
    assert set(READ_ROUTES + EXPORT_ROUTES) <= set(admin_paths), admin_paths
    for route in main.app.routes:
        if getattr(route, "path", "").startswith("/api/admin/"):
            calls = [dep.call for dep in route.dependant.dependencies]
            assert main.require_admin in calls, f"{route.path} 缺少 require_admin"

    client = TestClient(main.app)

    def request(method, path, headers, body):
        if method == "GET":
            return client.get(path, headers=headers).status_code
        return client.post(path, headers=headers, json=body).status_code

    with no_disk_writes(main):
        checked = run_matrix(request)
    with admin_token(TOKEN):
        # 公开接口不受影响
        assert client.get("/health").status_code == 200
        assert client.get("/api/scenes").status_code == 200
        assert client.get("/admin").status_code == 200
        response = client.get("/api/admin/export/feedback.csv", headers={"X-Admin-Token": TOKEN})
        assert response.headers["content-type"].startswith("text/csv")
    return checked


def check_stdlib_server():
    from app import server

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.RequestHandlerClass.log_message = lambda *args: None
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def request(method, path, headers, body):
        data = None
        headers = dict(headers)
        if method == "POST":
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10) as response:
                response.read()
                return response.status
        except HTTPError as exc:
            return exc.code

    try:
        with no_disk_writes(server):
            checked = run_matrix(request)
        with admin_token(TOKEN):
            assert request("GET", "/health", {}, None) == 200
            assert request("GET", "/api/scenes", {}, None) == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
    return checked


if __name__ == "__main__":
    check_core()
    fastapi_checked = check_fastapi()
    stdlib_checked = check_stdlib_server()
    print(f"ok: core + FastAPI {fastapi_checked} routes + stdlib {stdlib_checked} routes")

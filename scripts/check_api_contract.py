from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.server import Handler


def http_json(base: str, method: str, path: str, payload: dict | None = None) -> int:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(base + path, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status
    except HTTPError as error:
        return error.code


def check_client(client, base: str | None = None) -> list[str]:
    errors: list[str] = []
    get = (lambda path: client.get(path).status_code) if base is None else (lambda path: http_json(base, "GET", path))
    post = (lambda path, data: client.post(path, json=data).status_code) if base is None else (lambda path, data: http_json(base, "POST", path, data))
    if get("/health") != 200 or get("/api/scenes") != 200:
        errors.append("health/scenes contract")
    if get("/api/admin/scenes") != 401:
        errors.append("admin auth contract")
    conversation = post("/api/conversations", {"scene_id": "supermarket_backdoor", "user_id": f"contract-{uuid.uuid4()}"})
    if conversation != 200:
        errors.append("conversation create contract")
    if base is None:
        conversation_id = client.post("/api/conversations", json={"scene_id": "supermarket_backdoor"}).json()["conversation_id"]
    else:
        import urllib.parse
        request = Request(base + "/api/auth/login")
        with urlopen(request, timeout=5) as response:
            _ = json.loads(response.read())
        request = Request(base + "/api/conversations", data=json.dumps({"scene_id": "supermarket_backdoor"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            conversation_id = json.loads(response.read())["conversation_id"]
    long_status = post("/api/chat/message", {"conversation_id": conversation_id, "content": "x" * 1201})
    if long_status != 413:
        errors.append("input limit contract")
    return errors


def main() -> int:
    os.environ.pop("ADMIN_TOKEN", None)
    errors = check_client(TestClient(app))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        errors.extend(check_client(None, f"http://127.0.0.1:{server.server_port}"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    if errors:
        print("api contract failed")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("api contract ok: FastAPI and zero-dependency server share health, scenes, auth, create and input-limit behavior")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

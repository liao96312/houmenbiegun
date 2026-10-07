from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app


def main() -> int:
    client = TestClient(app)
    user_id = f"limit-test-{uuid.uuid4()}"
    conversation = client.post("/api/conversations", json={"scene_id": "supermarket_backdoor", "user_id": user_id})
    if conversation.status_code != 200:
        print(f"limits check failed: conversation status {conversation.status_code}")
        return 1
    conversation_id = conversation.json()["conversation_id"]
    too_long = client.post("/api/chat/message", json={"conversation_id": conversation_id, "content": "x" * 1201})
    if too_long.status_code != 413:
        print(f"limits check failed: long input status {too_long.status_code}")
        return 1
    statuses = [
        client.post("/api/chat/message", json={"conversation_id": conversation_id, "content": f"今天有点累 {i}"}).status_code
        for i in range(21)
    ]
    if statuses[-1] != 429 or any(status not in {200, 429} for status in statuses):
        print(f"limits check failed: model statuses {statuses}")
        return 1
    tts = client.post("/api/tts", json={"text": "hello"})
    if tts.status_code != 404:
        print(f"limits check failed: tts status {tts.status_code}")
        return 1
    print("limits check ok: 413 input, 429 model rate limit, 404 disabled TTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

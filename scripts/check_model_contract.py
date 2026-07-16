from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import MODEL_EVENTS, SCENES, ask_model, fallback_reply


class FakeResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def main() -> int:
    scene = SCENES[0]
    history = [{"role": "user", "content": "今天被工作烦到了"}]
    old_key = os.environ.get("AI_API_KEY")
    os.environ["AI_API_KEY"] = "contract-test-only"
    responses = {
        "success": FakeResponse({"choices": [{"message": {"content": "先坐会儿，今天先别急着想完。"}}]}),
        "empty": FakeResponse({"choices": [{"message": {"content": ""}}]}),
        "malformed": FakeResponse({"choices": []}),
    }
    failures: list[str] = []
    events_before = len(MODEL_EVENTS)
    try:
        with patch("app.core.urlopen", return_value=responses["success"]):
            if ask_model(scene, history, "今天被工作烦到了") == fallback_reply(scene, "今天被工作烦到了"):
                failures.append("success response unexpectedly used fallback")
        for name, error in {
            "401": HTTPError("https://api.deepseek.com/v1/chat/completions", 401, "unauthorized", {}, None),
            "429": HTTPError("https://api.deepseek.com/v1/chat/completions", 429, "rate limited", {}, None),
            "5xx": HTTPError("https://api.deepseek.com/v1/chat/completions", 503, "unavailable", {}, None),
            "timeout": TimeoutError("timed out"),
            "network": URLError("offline"),
        }.items():
            with patch("app.core.urlopen", side_effect=error):
                reply = ask_model(scene, history, "今天被工作烦到了")
                if not reply or len(reply) > 120:
                    failures.append(f"{name} did not return bounded fallback")
        for name in ("empty", "malformed"):
            with patch("app.core.urlopen", return_value=responses[name]):
                reply = ask_model(scene, history, "今天被工作烦到了")
                if not reply:
                    failures.append(f"{name} returned empty fallback")
    finally:
        if old_key is None:
            os.environ.pop("AI_API_KEY", None)
        else:
            os.environ["AI_API_KEY"] = old_key
    if len(MODEL_EVENTS) <= events_before:
        failures.append("model events were not recorded")
    if failures:
        print("model contract failed")
        print("\n".join(f"- {item}" for item in failures))
        return 1
    print("model contract ok: success, 401, 429, 5xx, timeout, network, empty and malformed response")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import mimetypes
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core import ANALYTICS, CONVERSATION_SUMMARIES, FEEDBACK, PROMPTS, ROOT, SAFETY_EVENTS, SCENES, MAX_INPUT_CHARS, RATE_LIMIT_MAX_MESSAGES, RATE_LIMIT_MAX_MODEL_CALLS, admin_token_ok, ask_model, branch_node, branch_start, branches_for_scene, config_status, csv_text, rate_limit_allowed, record_conversation_summary, record_feedback, record_safety_event, risk_level_for, safety_reply, safety_resources, save_prompts, save_scenes, scene_by_id, summarize, track, validate_input_text


CONVERSATIONS: dict[str, dict] = {}
MAX_BODY_BYTES = 1_000_000


class PayloadTooLarge(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self.json({"ok": True, "service": "houmenwufenzhong"})
        if path == "/":
            return self.file("static/index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            return self.file(
                path.lstrip("/"),
                mimetypes.guess_type(path)[0] or "application/octet-stream",
                allowed_root=ROOT / "static",
            )
        if path == "/admin":
            return self.file("static/admin.html", "text/html; charset=utf-8")
        if path == "/api/scenes":
            return self.json([
                {
                    "scene_id": s["scene_id"],
                    "display_name": s["display_name"],
                    "description": s["description"],
                    "poster_url": s["poster_url"],
                    "character": s.get("character", {}),
                }
                for s in SCENES
            ])
        if path == "/api/analytics":
            return self.json(ANALYTICS)
        if path == "/api/config":
            return self.json(config_status())
        if path == "/api/auth/login":
            return self.json({"user_id": str(uuid.uuid4()), "provider": "anonymous"})
        if path.startswith("/api/admin/") and not admin_token_ok(self.headers.get("X-Admin-Token")):
            return self.error(401, "admin token required")
        if path == "/api/admin/scenes":
            return self.json(SCENES)
        if path == "/api/admin/prompts":
            return self.json(PROMPTS)
        if path == "/api/admin/safety-events":
            return self.json(SAFETY_EVENTS)
        if path == "/api/admin/feedback":
            return self.json(FEEDBACK)
        if path == "/api/admin/conversations":
            return self.json(CONVERSATION_SUMMARIES)
        if path == "/api/admin/export/safety-events.csv":
            return self.text(csv_text(SAFETY_EVENTS), "text/csv; charset=utf-8")
        if path == "/api/admin/export/feedback.csv":
            return self.text(csv_text(FEEDBACK), "text/csv; charset=utf-8")
        if path == "/api/admin/export/conversations.csv":
            return self.text(csv_text(CONVERSATION_SUMMARIES), "text/csv; charset=utf-8")
        if path.startswith("/api/scenes/"):
            scene = scene_by_id(unquote(path.rsplit("/", 1)[-1]))
            return self.json(scene) if scene else self.error(404, "scene not found")
        if path.startswith("/api/branches/"):
            scene_id = unquote(path.rsplit("/", 1)[-1])
            tree = branches_for_scene(scene_id)
            return self.json(tree) if tree else self.error(404, "branches not found")
        return self.error(404, "not found")

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self.body()
        except PayloadTooLarge:
            return self.error(413, "request too large")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return self.error(400, "invalid json")
        if path == "/api/conversations":
            scene = scene_by_id(body.get("scene_id", ""))
            if not scene:
                return self.error(404, "scene not found")
            conversation_id = str(uuid.uuid4())
            CONVERSATIONS[conversation_id] = {
                "scene": scene,
                "messages": [],
                "risk_level": 0,
                "entry_mode": body.get("entry_mode", "talk"),
                "user_id": body.get("user_id"),
                "started_at": time.time(),
            }
            track("conversations")
            track("scene_enter", scene["scene_id"])
            return self.json({"conversation_id": conversation_id, "opening_message": scene["opening_line"]})

        if path == "/api/chat/message":
            conversation = CONVERSATIONS.get(body.get("conversation_id", ""))
            if not conversation:
                return self.error(404, "conversation not found")
            try:
                content = validate_input_text(body.get("content", ""), MAX_INPUT_CHARS)
            except ValueError as exc:
                return self.error(413, str(exc))
            subject = conversation.get("user_id") or body.get("conversation_id", "")
            if not rate_limit_allowed(subject, "messages", RATE_LIMIT_MAX_MESSAGES):
                return self.error(429, "too many messages")
            risk_level = risk_level_for(content)
            conversation["risk_level"] = max(conversation["risk_level"], risk_level)
            track("messages")
            if risk_level:
                track("safety_hits")
                record_safety_event({
                    "conversation_id": body.get("conversation_id", ""),
                    "scene_id": conversation["scene"]["scene_id"],
                    "risk_level": risk_level,
                    "trigger_text": content,
                    "action_taken": "safety_reply" if risk_level >= 2 else "normal_reply",
                })
            if risk_level < 2 and not rate_limit_allowed(subject, "model", RATE_LIMIT_MAX_MODEL_CALLS):
                return self.error(429, "model rate limit reached")
            reply = safety_reply() if risk_level >= 2 else ask_model(conversation["scene"], conversation["messages"], content)
            conversation["messages"].extend([
                {"role": "user", "content": content},
                {"role": "assistant", "content": reply},
            ])
            return self.json({
                "reply": reply,
                "risk_level": risk_level,
                "should_end": risk_level >= 2,
                "safety_resources": safety_resources() if risk_level >= 2 else None,
            })

        if path == "/api/chat/branch":
            conversation = CONVERSATIONS.get(body.get("conversation_id", ""))
            if not conversation:
                return self.error(404, "conversation not found")
            user_label = body.get("user_label")
            if user_label:
                try:
                    user_label = validate_input_text(user_label, MAX_INPUT_CHARS)
                except ValueError as exc:
                    return self.error(413, str(exc))
            subject = conversation.get("user_id") or body.get("conversation_id", "")
            if not rate_limit_allowed(subject, "messages", RATE_LIMIT_MAX_MESSAGES):
                return self.error(429, "too many messages")
            scene_id = conversation["scene"]["scene_id"]
            node_id = body.get("node_id")
            if node_id:
                node = branch_node(scene_id, node_id)
            else:
                node = branch_start(scene_id)
            if not node:
                return self.error(404, "branch node not found")
            track("branch_turns")
            if node["is_ending"]:
                track("branch_endings", node.get("ending_type") or "unknown")
            if node.get("ending_type") == "safety":
                track("safety_hits")
                record_safety_event({
                    "conversation_id": body.get("conversation_id", ""),
                    "scene_id": scene_id,
                    "risk_level": 3,
                    "trigger_text": f"branch:{node['node_id']}",
                    "action_taken": "safety_reply",
                })
                reply = node["companion_line"]
            else:
                reply = node["companion_line"]
            # 把分支回复也记进会话历史，方便后续自由聊天接续
            if user_label:
                conversation["messages"].append({"role": "user", "content": user_label})
            conversation["messages"].append({"role": "assistant", "content": reply})
            return self.json({
                "node_id": node["node_id"],
                "companion_line": node["companion_line"],
                "analysis": node["analysis"],
                "options": node["options"],
                "is_ending": node["is_ending"],
                "ending_type": node["ending_type"],
                "should_end": node.get("ending_type") == "safety",
                "safety_resources": safety_resources() if node.get("ending_type") == "safety" else None,
            })

        if path.startswith("/api/conversations/") and path.endswith("/end"):
            conversation_id = path.split("/")[-2]
            conversation = CONVERSATIONS.get(conversation_id)
            if not conversation:
                return self.error(404, "conversation not found")
            track("ended")
            duration = max(0, int(time.time() - conversation["started_at"]))
            summary = summarize(conversation["messages"], conversation["risk_level"])
            track("duration_seconds", amount=duration)
            record_conversation_summary({
                "conversation_id": conversation_id,
                "scene_id": conversation["scene"]["scene_id"],
                "risk_level": conversation["risk_level"],
                "summary": summary,
                "duration_seconds": duration,
            })
            return self.json({
                "ending_line": conversation["scene"]["closing_line"],
                "summary": summary,
            })

        if path == "/api/admin/scenes":
            if not admin_token_ok(self.headers.get("X-Admin-Token")):
                return self.error(401, "admin token required")
            try:
                save_scenes(body)
            except (TypeError, ValueError):
                return self.error(400, "bad scenes")
            return self.json({"ok": True})

        if path == "/api/admin/prompts":
            if not admin_token_ok(self.headers.get("X-Admin-Token")):
                return self.error(401, "admin token required")
            try:
                save_prompts(body)
            except (TypeError, ValueError):
                return self.error(400, "bad prompts")
            return self.json({"ok": True})

        if path == "/api/tts":
            if os.getenv("TTS_ENABLED", "").lower() != "true":
                return self.error(404, "tts disabled")
            try:
                text = validate_input_text(body.get("text", ""), MAX_INPUT_CHARS)
            except ValueError as exc:
                return self.error(413, str(exc))
            return self.json({"audio_url": None, "text": text})

        if path == "/api/feedback":
            if body.get("type") not in {"like", "dislike", "report"}:
                return self.error(400, "bad feedback type")
            record_feedback({
                "conversation_id": body.get("conversation_id"),
                "type": body.get("type"),
                "content": body.get("content", ""),
            })
            return self.json({"ok": True})

        return self.error(404, "not found")

    def body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > MAX_BODY_BYTES:
            raise PayloadTooLarge()
        if not size:
            return {}
        raw = self.rfile.read(size)
        try:
            return json.loads(raw.decode("utf-8-sig"))
        except UnicodeDecodeError:
            return json.loads(raw.decode("gbk"))

    def json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def file(self, relative_path, content_type, allowed_root=None):
        root = ROOT.resolve()
        candidate = (root / unquote(relative_path)).resolve()
        if candidate != root and root not in candidate.parents:
            return self.error(404, "not found")
        if allowed_root is not None:
            allowed = Path(allowed_root).resolve()
            if candidate != allowed and allowed not in candidate.parents:
                return self.error(404, "not found")
        if not candidate.is_file():
            return self.error(404, "not found")
        payload = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def text(self, text, content_type):
        payload = text.encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def error(self, status, message):
        return self.json({"detail": message}, status)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"http://{host}:{port}")
    server.serve_forever()

from __future__ import annotations

import os
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core import ANALYTICS, CONVERSATION_SUMMARIES, FEEDBACK, PROMPTS, ROOT, SAFETY_EVENTS, SCENES, admin_token_ok, ask_model, branch_node, branch_start, branches_for_scene, config_status, csv_text, record_conversation_summary, record_feedback, record_safety_event, risk_level_for, safety_reply, save_prompts, save_scenes, scene_by_id as find_scene, summarize, track

CONVERSATIONS: dict[str, dict] = {}

app = FastAPI(title="后门五分钟")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class ConversationIn(BaseModel):
    scene_id: str
    entry_mode: str = "talk"
    user_id: str | None = None


class ChatIn(BaseModel):
    conversation_id: str
    content: str


class TTSIn(BaseModel):
    text: str


class FeedbackIn(BaseModel):
    conversation_id: str | None = None
    type: str
    content: str = ""


class BranchIn(BaseModel):
    conversation_id: str
    node_id: str | None = None
    user_label: str | None = None


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "service": "houmenwufenzhong"}


@app.get("/admin")
def admin():
    return FileResponse(ROOT / "static" / "admin.html")


@app.get("/api/scenes")
def list_scenes():
    return [
        {
            "scene_id": s["scene_id"],
            "display_name": s["display_name"],
            "description": s["description"],
            "poster_url": s["poster_url"],
            "character": s.get("character", {}),
        }
        for s in SCENES
    ]


@app.get("/api/auth/login")
def login():
    return {"user_id": str(uuid.uuid4()), "provider": "anonymous"}


@app.get("/api/scenes/{scene_id}")
def get_scene(scene_id: str):
    return scene_by_id(scene_id)


@app.get("/api/branches/{scene_id}")
def get_branches(scene_id: str):
    tree = branches_for_scene(scene_id)
    if not tree:
        raise HTTPException(status_code=404, detail="branches not found")
    return tree


@app.post("/api/chat/branch")
def chat_branch(body: BranchIn):
    conversation = CONVERSATIONS.get(body.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
    scene_id = conversation["scene"]["scene_id"]
    node = branch_node(scene_id, body.node_id) if body.node_id else branch_start(scene_id)
    if not node:
        raise HTTPException(status_code=404, detail="branch node not found")
    track("branch_turns")
    if node["is_ending"]:
        track("branch_endings", node.get("ending_type") or "unknown")
    if node.get("ending_type") == "safety":
        track("safety_hits")
        record_safety_event({
            "conversation_id": body.conversation_id,
            "scene_id": scene_id,
            "risk_level": 3,
            "trigger_text": f"branch:{node['node_id']}",
            "action_taken": "safety_reply",
        })
    if body.user_label:
        conversation["messages"].append({"role": "user", "content": body.user_label})
    conversation["messages"].append({"role": "assistant", "content": node["companion_line"]})
    return {
        "node_id": node["node_id"],
        "companion_line": node["companion_line"],
        "analysis": node["analysis"],
        "options": node["options"],
        "is_ending": node["is_ending"],
        "ending_type": node["ending_type"],
        "should_end": node.get("ending_type") == "safety",
    }


@app.get("/api/analytics")
def analytics():
    return ANALYTICS


@app.get("/api/config")
def config():
    return config_status()


@app.get("/api/admin/scenes")
def admin_scenes():
    return SCENES


@app.post("/api/admin/scenes")
def update_admin_scenes(body: list[dict], x_admin_token: str | None = Header(default=None)):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(status_code=401, detail="admin token required")
    try:
        save_scenes(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.get("/api/admin/prompts")
def admin_prompts():
    return PROMPTS


@app.post("/api/admin/prompts")
def update_admin_prompts(body: dict, x_admin_token: str | None = Header(default=None)):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(status_code=401, detail="admin token required")
    try:
        save_prompts(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.get("/api/admin/safety-events")
def admin_safety_events():
    return SAFETY_EVENTS


@app.get("/api/admin/feedback")
def admin_feedback():
    return FEEDBACK


@app.get("/api/admin/conversations")
def admin_conversations():
    return CONVERSATION_SUMMARIES


@app.get("/api/admin/export/safety-events.csv")
def export_safety_events():
    return PlainTextResponse(csv_text(SAFETY_EVENTS), media_type="text/csv; charset=utf-8")


@app.get("/api/admin/export/feedback.csv")
def export_feedback():
    return PlainTextResponse(csv_text(FEEDBACK), media_type="text/csv; charset=utf-8")


@app.get("/api/admin/export/conversations.csv")
def export_conversations():
    return PlainTextResponse(csv_text(CONVERSATION_SUMMARIES), media_type="text/csv; charset=utf-8")


@app.post("/api/conversations")
def create_conversation(body: ConversationIn):
    scene = scene_by_id(body.scene_id)
    conversation_id = str(uuid.uuid4())
    CONVERSATIONS[conversation_id] = {
        "scene": scene,
        "messages": [],
        "risk_level": 0,
        "entry_mode": body.entry_mode,
        "user_id": body.user_id,
        "started_at": time.time(),
    }
    track("conversations")
    track("scene_enter", scene["scene_id"])
    return {
        "conversation_id": conversation_id,
        "opening_message": scene["opening_line"],
    }


@app.post("/api/chat/message")
def chat(body: ChatIn):
    conversation = CONVERSATIONS.get(body.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")

    risk_level = risk_level_for(body.content)
    conversation["risk_level"] = max(conversation["risk_level"], risk_level)
    track("messages")
    if risk_level:
        track("safety_hits")
        record_safety_event({
            "conversation_id": body.conversation_id,
            "scene_id": conversation["scene"]["scene_id"],
            "risk_level": risk_level,
            "trigger_text": body.content,
            "action_taken": "safety_reply" if risk_level >= 2 else "normal_reply",
        })

    if risk_level >= 2:
        reply = safety_reply()
    else:
        reply = ask_model(conversation["scene"], conversation["messages"], body.content)

    conversation["messages"].append({"role": "user", "content": body.content})
    conversation["messages"].append({"role": "assistant", "content": reply})
    return {"reply": reply, "risk_level": risk_level, "should_end": risk_level >= 3}


@app.post("/api/conversations/{conversation_id}/end")
def end_conversation(conversation_id: str):
    conversation = CONVERSATIONS.get(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
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
    return {
        "ending_line": conversation["scene"]["closing_line"],
        "summary": summary,
    }


@app.post("/api/tts")
def tts(body: TTSIn):
    if os.getenv("TTS_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=404, detail="tts disabled")
    return {"audio_url": None, "text": body.text}


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    if body.type not in {"like", "dislike", "report"}:
        raise HTTPException(status_code=400, detail="bad feedback type")
    record_feedback(body.model_dump())
    return {"ok": True}


def scene_by_id(scene_id: str) -> dict:
    scene = find_scene(scene_id)
    if scene:
        return scene
    raise HTTPException(status_code=404, detail="scene not found")

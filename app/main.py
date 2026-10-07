from __future__ import annotations

import os
import time
import uuid

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core import ANALYTICS, CONVERSATION_SUMMARIES, FEEDBACK, MODEL_EVENTS, PROMPTS, ROOT, SAFETY_EVENTS, SCENES, MAX_INPUT_CHARS, RATE_LIMIT_MAX_MESSAGES, RATE_LIMIT_MAX_MODEL_CALLS, admin_auth_error, branch_node, branch_start, branches_for_scene, config_status, csv_text, extract_admin_token, rate_limit_allowed, record_conversation_summary, record_feedback, record_safety_event, reply_for, risk_level_for, safety_reply, safety_resources, save_prompts, save_scenes, scene_by_id as find_scene, summarize, track, validate_input_text, warn_if_admin_token_missing

CONVERSATIONS: dict[str, dict] = {}

app = FastAPI(title="后门五分钟")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
warn_if_admin_token_missing()


def require_admin(
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """所有 /api/admin/* 路由共用的鉴权依赖（见 app.core.admin_auth_error）。"""
    error = admin_auth_error(extract_admin_token(x_admin_token, authorization))
    if error:
        status, detail = error
        raise HTTPException(status_code=status, detail=detail)


# 后台接口统一挂在这个 router 上，新加的 /api/admin/* 路由会自动带上鉴权。
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


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
    if body.user_label:
        try:
            body.user_label = validate_input_text(body.user_label, MAX_INPUT_CHARS)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc))
    subject = conversation.get("user_id") or body.conversation_id
    if not rate_limit_allowed(subject, "messages", RATE_LIMIT_MAX_MESSAGES):
        raise HTTPException(status_code=429, detail="too many messages")
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
        "safety_resources": safety_resources() if node.get("ending_type") == "safety" else None,
    }


@app.get("/api/analytics")
def analytics():
    return ANALYTICS


@app.get("/api/config")
def config():
    return config_status()


@admin_router.get("/scenes")
def admin_scenes():
    return SCENES


@admin_router.post("/scenes")
def update_admin_scenes(body: list[dict]):
    try:
        save_scenes(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@admin_router.get("/prompts")
def admin_prompts():
    return PROMPTS


@admin_router.post("/prompts")
def update_admin_prompts(body: dict):
    try:
        save_prompts(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@admin_router.get("/safety-events")
def admin_safety_events():
    return SAFETY_EVENTS


@admin_router.get("/feedback")
def admin_feedback():
    return FEEDBACK


@admin_router.get("/conversations")
def admin_conversations():
    return CONVERSATION_SUMMARIES


@admin_router.get("/model-events")
def admin_model_events():
    return MODEL_EVENTS


@admin_router.get("/export/safety-events.csv")
def export_safety_events():
    return PlainTextResponse(csv_text(SAFETY_EVENTS), media_type="text/csv; charset=utf-8")


@admin_router.get("/export/feedback.csv")
def export_feedback():
    return PlainTextResponse(csv_text(FEEDBACK), media_type="text/csv; charset=utf-8")


@admin_router.get("/export/conversations.csv")
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
    try:
        content = validate_input_text(body.content, MAX_INPUT_CHARS)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    subject = conversation.get("user_id") or body.conversation_id
    if not rate_limit_allowed(subject, "messages", RATE_LIMIT_MAX_MESSAGES):
        raise HTTPException(status_code=429, detail="too many messages")

    risk_level = risk_level_for(content)
    conversation["risk_level"] = max(conversation["risk_level"], risk_level)
    track("messages")
    if risk_level:
        track("safety_hits")
        record_safety_event({
            "conversation_id": body.conversation_id,
            "scene_id": conversation["scene"]["scene_id"],
            "risk_level": risk_level,
            "trigger_text": content,
            "action_taken": "safety_reply" if risk_level >= 2 else "normal_reply",
        })

    if risk_level >= 2:
        reply = safety_reply(risk_level, content)
    else:
        if not rate_limit_allowed(subject, "model", RATE_LIMIT_MAX_MODEL_CALLS):
            raise HTTPException(status_code=429, detail="model rate limit reached")
        reply = reply_for(conversation["scene"], conversation["messages"], content, risk_level)

    conversation["messages"].append({"role": "user", "content": content})
    conversation["messages"].append({"role": "assistant", "content": reply})
    return {
        "reply": reply,
        "risk_level": risk_level,
        "should_end": risk_level >= 2,
        "safety_resources": safety_resources() if risk_level >= 2 else None,
    }


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
    try:
        text = validate_input_text(body.text, MAX_INPUT_CHARS)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    return {"audio_url": None, "text": text}


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    if body.type not in {"like", "dislike", "report"}:
        raise HTTPException(status_code=400, detail="bad feedback type")
    record_feedback(body.model_dump())
    return {"ok": True}


app.include_router(admin_router)


def scene_by_id(scene_id: str) -> dict:
    scene = find_scene(scene_id)
    if scene:
        return scene
    raise HTTPException(status_code=404, detail="scene not found")

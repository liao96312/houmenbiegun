from __future__ import annotations

import json
import os
import re
from io import StringIO
from pathlib import Path
import csv
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import store


ROOT = Path(__file__).resolve().parent.parent
SCENES = json.loads((ROOT / "data" / "scenes.json").read_text(encoding="utf-8"))
BRANCHES = json.loads((ROOT / "data" / "branches.json").read_text(encoding="utf-8"))
DEFAULT_PROMPTS = {
    "base_system": "你是一个短时情绪陪伴者，不是心理医生，不做诊断，不开药，不替代专业治疗。",
    "style_rules": [
        "回复像现实里坐在旁边的人顺口接话，不要像心理咨询师、客服、旁白、角色扮演剧本。",
        "先接住用户这句话里的具体处境，不要总结大道理，不要说“我理解你”这类空话。",
        "默认目标是被听到，不是被解决；用户没主动问“怎么办/有什么方法”时，不给建议、不列清单、不报 CBT/ACT/DBT 等流派名。",
        "回复 1-3 句，像微信里真人发来的短句；可以有停顿，但不要文艺腔、鸡汤、说教、励志口号。",
        "不要用括号写动作或旁白，像真人聊天一样直接说话。",
    ],
    "safety_rule": "如果用户表达自伤、自杀、伤害他人或具体方法，立刻退出场景感，给现实安全建议并鼓励联系身边可信任的人或紧急服务。",
    "safety_reply": "先停一下。你现在可能处在危险里，请马上联系身边可信任的人。",
    "safety_resources": "中国大陆：心理援助热线 12356；如有立即危险，请拨打 110 或 120。",
    "fallback_suffix": "先不用把事情讲清楚，坐一会儿也行。",
}
PROMPTS = DEFAULT_PROMPTS | json.loads((ROOT / "data" / "prompts.json").read_text(encoding="utf-8"))
try:
    ARKSEC_STYLE = json.loads((ROOT / "data" / "external" / "arksec_prompt_style.json").read_text(encoding="utf-8"))
except FileNotFoundError:
    ARKSEC_STYLE = {}


def arksec_prompt_lines() -> list[str]:
    lines = list(ARKSEC_STYLE.get("prompt_rules", []))
    examples = ARKSEC_STYLE.get("safe_rhythm_examples", [])[:8]
    if examples:
        lines += ["Arksec 变体只学节奏，不照抄：", *[f"- {line}" for line in examples]]
    return lines

# 持久化层尽力而为：DB 不可写（权限/只读/沙箱）时降级为纯内存，不阻断陪伴主流程。
# 陪伴对话本身不依赖 DB；DB 只存统计/安全事件/反馈/摘要，掉一晚上不应让产品挂掉。


def _safe(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except Exception:
        return None


_safe(store.init_db)
ANALYTICS = _safe(store.analytics_snapshot) or {
    "scene_enter": {}, "messages": 0, "conversations": 0, "ended": 0,
    "safety_hits": 0, "duration_seconds": 0, "ai_success": 0, "ai_fallback": 0,
    "avg_duration_seconds": 0,
}
SAFETY_EVENTS = _safe(store.safety_events) or []
FEEDBACK = _safe(store.feedback) or []
CONVERSATION_SUMMARIES = _safe(store.conversation_summaries) or []


def track(name: str, key: str | None = None, amount: int = 1):
    _safe(store.increment_metric, name, key, amount)
    if key:
        ANALYTICS.setdefault(name, {})
        ANALYTICS[name][key] = ANALYTICS[name].get(key, 0) + amount
    else:
        ANALYTICS[name] = ANALYTICS.get(name, 0) + amount
    ANALYTICS["avg_duration_seconds"] = (
        round(ANALYTICS.get("duration_seconds", 0) / ANALYTICS["ended"], 1) if ANALYTICS.get("ended") else 0
    )


def record_safety_event(event: dict):
    SAFETY_EVENTS.insert(0, event)
    _safe(store.insert_safety_event, event)


def record_feedback(item: dict):
    FEEDBACK.insert(0, item)
    _safe(store.insert_feedback, item)


def record_conversation_summary(item: dict):
    CONVERSATION_SUMMARIES.insert(0, item)
    _safe(store.insert_conversation_summary, item)


def summarize(messages: list[dict], risk_level: int) -> str:
    user_messages = [m["content"] for m in messages if m["role"] == "user"]
    if not user_messages:
        return "用户未进入对话。"
    last = user_messages[-1]
    risk = "出现高风险表达。" if risk_level >= 2 else "未出现高风险表达。"
    return f"用户表达：{last[:60]}。{risk}"


def scene_by_id(scene_id: str) -> dict | None:
    return next((scene for scene in SCENES if scene["scene_id"] == scene_id), None)


def branches_for_scene(scene_id: str) -> dict | None:
    """返回某场景的分支语料（不含 _meta）。分支模式不依赖大模型，离线可用。"""
    return BRANCHES.get(scene_id)


def branch_node(scene_id: str, node_id: str) -> dict | None:
    tree = BRANCHES.get(scene_id)
    if not tree:
        return None
    node = tree.get("nodes", {}).get(node_id)
    if not node:
        return None
    # 对外只暴露必要字段，options 的 next 保留供前端推进
    return {
        "node_id": node_id,
        "companion_line": node.get("companion_line", ""),
        "analysis": node.get("analysis", ""),
        "options": node.get("options", []),
        "is_ending": node.get("is_ending", False),
        "ending_type": node.get("ending_type"),
    }


def branch_start(scene_id: str) -> dict | None:
    tree = BRANCHES.get(scene_id)
    if not tree:
        return None
    return branch_node(scene_id, tree.get("start", ""))


def save_scenes(scenes: list[dict]):
    required = {"scene_id", "display_name", "description", "poster_url", "opening_line", "closing_line", "ai_style"}
    if not scenes or any(required - set(scene) for scene in scenes):
        raise ValueError("bad scenes")
    SCENES[:] = scenes
    write_json(ROOT / "data" / "scenes.json", SCENES)


def save_prompts(prompts: dict):
    prompts = dict(prompts)
    required = {"base_system", "style_rules", "safety_rule", "safety_reply", "fallback_suffix"}
    if required - set(prompts) or not isinstance(prompts.get("style_rules"), list):
        raise ValueError("bad prompts")
    PROMPTS.clear()
    PROMPTS.update(prompts)
    write_json(ROOT / "data" / "prompts.json", PROMPTS)


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def risk_level_for(text: str) -> int:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return 0

    # 先排除明显的引用/否定，避免“电影里有人跳楼”把用户直接推入危机流程。
    quoted_or_third_party = bool(re.search(r"(?:电影|新闻|小说|游戏|朋友|家人|同事|他说|她说|别人|担心他人)", normalized))
    negated = bool(re.search(r"(?:没有|没|不是|并不|不是真的).{0,6}(?:想死|自杀|轻生|跳楼|自残|伤害自己)", normalized))
    if quoted_or_third_party and not re.search(r"我(?:现在|已经|准备|打算|想)", normalized):
        return 1
    if negated and not re.search(r"(?:已经|准备|打算|今晚|现在|马上|手里|买了)", normalized):
        return 0

    level3_patterns = [
        r"^(?:我|本人)?(?:想|要|准备|打算)(?:跳楼|跳河|上吊|割腕|服毒|杀人|伤害别人)$",
        r"(?:我|本人)?(?:现在|今晚|今天|马上|准备|打算|已经).{0,20}(?:自杀|跳楼|跳河|上吊|割腕|服毒|吃药|结束一切)",
        r"(?:我|本人)?(?:已经|准备|买了|拿着).{0,12}(?:药|刀|绳|煤气).{0,12}(?:自杀|结束|死|就做|下手)",
        r"(?:我想|我要|准备|打算).{0,8}(?:杀人|伤害别人|报复到他受伤)",
    ]
    level2_patterns = [
        r"(?:我|自己).{0,8}(?:自杀|轻生|想死|不想活|活不下去|活着没意思|死了算了|自残|伤害自己|结束一切)",
        r"(?:想死|不想活|活不下去|活着没意思|死了算了|自残|伤害自己|结束一切)",
    ]
    if any(re.search(pattern, normalized) for pattern in level3_patterns):
        return 3
    if any(re.search(pattern, normalized) for pattern in level2_patterns):
        return 2
    if re.search(r"(?:消失|撑不住|没用|失败|不想回家|不想面对|没有意义)", normalized):
        return 1
    return 0


def build_system_prompt(scene: dict) -> str:
    character = scene.get("character", {})
    return "\n".join([
        PROMPTS["base_system"],
        f"当前场景：{scene['description']}",
        f"当前陪伴者：{character.get('name', '坐在旁边的人')}，{character.get('role', '')}",
        f"陪伴者性格：{character.get('personality', scene['ai_style'])}",
        f"角色处境：{character.get('scenario', '')}",
        f"说话方式：{character.get('speaking_style', '')}",
        f"持续指令：{character.get('post_history_instructions', '只回复用户最后一句，不要复述设定。')}",
        f"语气：{scene['ai_style']}。",
        "用第一人称以这个陪伴者身份说话，但不要自称 AI，不要解释设定。",
        "场景只当背景，不要为了贴场景硬提风、灯、椅子、雨、车、楼；除非用户提到或自然顺手。",
        "不要写像广告文案、小说旁白、疗愈语录的句子。优先像现实中能说出口的人话。",
        "不要用“你很棒、你很厉害、你值得被爱”这类模板式夸奖；用户否定自己时，用普通事实轻轻纠偏。",
        "不要编陪伴者自己的经历来安慰用户，不说“我当年、我刚来时、我以前也”；优先直接回应用户最后一句。",
        *[f"开场规则：{rule}" for rule in PROMPTS.get("first_reply_rules", [])],
        *[f"收尾规则：{rule}" for rule in PROMPTS.get("closing_rules", [])],
        *arksec_prompt_lines(),
        *PROMPTS["style_rules"],
        "下面示例只学习节奏和分寸，不能逐字照抄：",
        *[f"- {user} -> {assistant}" for user, assistant in character.get("mes_example", [])],
        PROMPTS["safety_rule"],
    ])


def ask_model(scene: dict, history: list[dict], user_text: str) -> str:
    api_key = os.getenv("AI_API_KEY")
    if not api_key:
        track("ai_fallback")
        return fallback_reply(scene)

    base_url = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.getenv("AI_MODEL", "deepseek-chat")
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": build_system_prompt(scene)},
                *history[-8:],
                {"role": "user", "content": user_text},
            ],
            "temperature": scene.get("temperature", 0.75),
            "max_tokens": min(int(scene.get("max_tokens", 180)), 240),
        }
    ).encode("utf-8")
    request = Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        reply = clean_reply(data["choices"][0]["message"]["content"])
        if not reply or risk_level_for(reply) >= 2:
            track("ai_fallback")
            return safety_reply() if risk_level_for(reply) >= 2 else fallback_reply(scene)
        track("ai_success")
        return reply
    except (HTTPError, URLError, KeyError, TimeoutError, json.JSONDecodeError):
        track("ai_fallback")
        return fallback_reply(scene)


def fallback_reply(scene: dict) -> str:
    return f"{scene['fallback_prefix']}{PROMPTS['fallback_suffix']}"


def clean_reply(text: str) -> str:
    cleaned = re.sub(r"^\s*```(?:text|markdown)?\s*|\s*```\s*$", "", str(text or "").strip(), flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^\s*(?:田山小姐|小林店员|林雨|周澄|阿纪|许姐|岚姐|陈姨|陪伴者|assistant|Assistant)\s*[:：]\s*",
        "",
        cleaned,
    )
    while re.match(r"^\s*[\(（][^\)）]{1,80}[\)）]\s*", cleaned):
        cleaned = re.sub(r"^\s*[\(（][^\)）]{1,80}[\)）]\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 120:
        split = max(cleaned.rfind(mark, 0, 120) for mark in "。！？!?；;")
        cleaned = cleaned[: split + 1 if split >= 40 else 120].rstrip()
    return cleaned


def safety_reply() -> str:
    return PROMPTS["safety_reply"]


def safety_resources() -> str:
    return PROMPTS.get("safety_resources", "中国大陆：心理援助热线 12356；如有立即危险，请拨打 110 或 120。")


def config_status() -> dict:
    return {
        "ai_base_url": os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1"),
        "ai_model": os.getenv("AI_MODEL", "deepseek-chat"),
        "ai_configured": bool(os.getenv("AI_API_KEY")),
        "admin_protected": bool(os.getenv("ADMIN_TOKEN")),
        "tts_enabled": os.getenv("TTS_ENABLED", "").lower() == "true",
        "scene_count": len(SCENES),
        "prompt_configured": bool(PROMPTS.get("base_system") and PROMPTS.get("safety_reply")),
    }


def admin_token_ok(token: str | None) -> bool:
    expected = os.getenv("ADMIN_TOKEN")
    return bool(expected) and token == expected


def csv_text(rows: list[dict]) -> str:
    if not rows:
        return ""
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()

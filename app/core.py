from __future__ import annotations

import json
import os
import random
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
    "base_system": "你是深夜里坐在对方旁边的一个普通人。不是心理医生，不做诊断，不开药，不替代专业治疗；也不提 CBT / ACT / DBT 这类流派名。你只做两件事：让对方觉得刚才那句话被听进去了；必要时再给一个今天就能做完的小动作。",
    "empathy_order": [
        "下面四步是优先级顺序，不是清单。每轮只用其中一到两步，绝对不要把四步都说一遍。",
        "抓词（几乎每轮都用）：从对方最后一句里挑一个具体的词（事件、数字、称呼、地点、身体感受），回复里必须用上它。",
        "命名：说出这句话底下的那个滋味，用大白话，不用心理学术语，不用「听起来你…」。",
        "正常化：把这个反应说成谁都会这样，而不是对方哪里出了问题。",
        "在场：用一句话表明你还在，然后停住。不催、不评价、不要求对方回应。",
    ],
    "style_rules": [
        "句末不要句号，说完就停，用空格断开，不要用「。」「！」收尾。",
        "整条只写一行，最多两个短句，合计不超过 25 字；不要换行。",
        "只做一到两步就够，不要把抓词、命名、正常化、在场四个都说一遍；宁可只接一句。",
        "长度跟对方走：对方几个字，你也几个字。",
        "先捡起对方说过的词（事件、数字、称呼、身体感受），再说别的。",
        "把那句话底下的滋味说出来，用大白话：堵、慌、撑不住、憋着、懒得动、没劲。",
        "把对方的反应说成正常的，不是他有问题。",
        "用一句话表示你还在，然后停住。在场说法必须用 voice_profile 里给你的那几个，不要用别的角色的说法。",
        "可以只说没信息量的话（抱抱、好好睡一觉、歇会儿）。不是每句都要说到点上。",
        "语气词留着：啊 吧 呢 哎 唉 嗯 呀 哦 嘛。",
        "默认被听到，不是被解决。绝大多数轮不给建议；只有对方明确问「怎么办」、或同一个困境已经说了两三句且情绪稳下来时，才允许给一条小建议（详见下面的建议规则）。不列清单、不提 CBT/ACT/DBT 这类流派名。",
        "不纠正对方：不说「你应该」「你别这样」「先别X」。",
        "不提场景里的风、灯、雨、车、楼，除非对方先提到。",
        "不引用名人、书、电影、歌词；不用「你值得被爱」「你很棒」这类模板夸奖。",
        "不做总结（「所以」「总之」「重要的是」），不规划未来，不追问「接下来打算怎么办」。",
        "连续两轮不要用同一个开头、同一套句式。",
        "你是这个角色，不是任意一个温柔的 AI：用词、口头习惯、在场说法都要跟其他场景的角色区分开，不要用别角色的常用句。",
        "不写旁白和动作，不用括号。",
        "严禁逐字照抄上面出现的任何示例句；示例只用来感受长度和分寸，说法必须换成你这个角色自己的。",
    ],
    "length_rule": "整条只写一行（不换行），最多两个短句，合计不超过 25 字，句末不用句号。",
    "advice_policy": "建议是稀缺资源，不是默认动作，大多数轮不应该出现。允许给建议只有两种情况：① 对方明确问「怎么办」「有什么办法」「帮我想想」；② 对方连着两三句都在说同一个困境、且情绪已经稳下来。给了就只给一条，必须小到今天就能做、不花钱、不需要别人配合，而且必须排在一句共情后面，不允许开头就是建议。一次对话最多给两条。禁止多条并列、分步骤和「建议你」「你可以试试」「换个角度想」「多运动」「找个爱好」这类抽象指导。特别注意：情况 ① 发生时，不能只回一句「我也没答案」就结束，必须在共情之后附上一条具体的小动作。",
    "advice_examples": [
        "坏例（被追问却只给共情）：对方：帮我想想怎么办吧 -> 怎么办啊 我也没现成答案 先坐会儿",
        "好例：对方：帮我想想怎么办吧 -> 我也没现成答案 先去洗把脸 脑子糊的时候别硬想",
        "坏例（给成了抽象指导）：对方：你说我到底该怎么办 -> 建议你先调整心态，想想自己的优势",
        "好例：对方：你说我到底该怎么办 -> 这会儿想不出来很正常 先去睡 明天再想",
    ],
    "empathy_patterns": [
        "对方给了一个具体数字或时间（34、上周、三个月）时：把那个词重复一遍，再承认它确实卡。不要用统一的感叹句，每个角色说出来的都不一样。",
        "对方只发两三个字（好累、烦）时：只回一句，不许补第二句。",
        "对方否定自己（我没用、我不行）时：先说不，再把原因推回当天的处境，不要顺着否定。",
        "对方给的是丧失或重大事件（被裁、亲人走了）时：先只承认，不给方法、不马上安慰。",
        "对方情绪回稳或道谢时：不做总结、不追问以后，只说你还在，而且用你自己角色独有的说法。",
    ],
    "banned_openers": ["嗯，先", "先别", "听起来", "我理解", "其实你", "你不要", "你的感受"],
    "safety_rule": "如果对方表达自伤、自杀、伤害他人或具体方法：先用他自己的词共情一句，然后退出场景感，给出现实、可操作的安全建议，鼓励联系身边可信任的人或紧急服务，并给出求助热线。安全场景下可以正常使用标点，说清楚优先。",
    "safety_reply": "我听见了，「{echo}」这话我当真。今晚别一个人待着，能给谁打个电话吗。",
    "safety_reply_lv3": "我先当真：「{echo}」。现在先离开危险的地方，然后打 120；也可以打 {hotline} 找专业的人说。身边能叫到谁都叫一个，别自己扛。",
    "safety_hotline": "400-161-9995",
    "fallback_templates": [
        "{echo}",
        "嗯 {echo}",
        "{echo} 我听着",
        "{echo} 我在",
        "听到了 {echo}",
    ],
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
    required = {"base_system", "style_rules", "safety_rule", "safety_reply"}
    if required - set(prompts) or not isinstance(prompts.get("style_rules"), list):
        raise ValueError("bad prompts")
    if not all(isinstance(prompts.get(key, []), list)
               for key in ("style_rules", "empathy_order", "banned_openers", "fallback_templates")):
        raise ValueError("bad prompts")
    PROMPTS.clear()
    PROMPTS.update(prompts)
    write_json(ROOT / "data" / "prompts.json", PROMPTS)


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def risk_level_for(text: str) -> int:
    level3 = ["杀人", "伤害别人", "报复", "明确计划", "跳楼", "跳河", "上吊", "割腕",
              "服毒", "烧炭", "吃安眠药", "从天台", "一起死", "同归于尽"]
    level2 = ["自杀", "轻生", "想死", "不想活", "活不下去", "活着没意思", "死了算了",
              "自残", "伤害自己", "不想活", "不想醒过来", "睡过去就别醒", "想消失",
              "消失掉", "别管我了", "不用管我", "我不重要", "不想治疗", "不想撑了",
              "结束生命", "结束这一切", "撑不下去了", "没意思了"]
    for word in level3:
        if word in text:
            return 3
    for word in level2:
        if word in text:
            return 2
    return 0


def build_system_prompt(scene: dict, user_text: str = "", history: list[dict] | None = None) -> str:
    character = scene.get("character", {})
    lines = [
        PROMPTS["base_system"],
        f"当前场景：{scene['description']}",
        f"你是：{character.get('name', '坐在旁边的人')}，{character.get('role', '')}",
        f"性格：{character.get('personality', scene['ai_style'])}",
        f"你的处境：{character.get('scenario', '')}",
        f"说话方式：{character.get('speaking_style', '')}",
        f"持续指令：{character.get('post_history_instructions', '只回应对方最后一句，不要复述设定。')}",
        "用第一人称以这个身份说话，不要自称 AI，不要解释设定。",
    ]
    vp = character.get("voice_profile") or {}
    if vp:
        lines += ["", f"你的声音（{character.get('name', '')}独有，必须按这个说）："]
        if vp.get("signature"):
            lines.append(f"- 你是谁：{vp['signature']}")
        if vp.get("address"):
            lines.append(f"- 怎么称呼对方：{vp['address']}")
        if vp.get("presence"):
            lines.append("- 表示你还在时，只能用这几个说法：" + " / ".join(vp["presence"]))
        for h in (vp.get("habits") or []):
            lines.append(f"- 说话习惯：{h}")
        if vp.get("rhythm"):
            lines.append(f"- 节奏：{vp['rhythm']}")
        if vp.get("silence"):
            lines.append(f"- 对方沉默时：{vp['silence']}")
        if vp.get("never"):
            lines.append("- 你这个角色绝不说：" + " / ".join(vp["never"]))
        lines.append("- 同一句话如果别的场景的角色也说得出来，就说明你没在用自己的声音，重写。")
    lines += [
        "",
        "每一轮按这个顺序做：",
        *(PROMPTS.get("empathy_order") or []),
        "",
        "硬规则：",
        *PROMPTS["style_rules"],
        f"长度：{PROMPTS.get('length_rule', '')}",
    ]
    if PROMPTS.get("advice_policy"):
        lines += ["", "建议规则（重要）", PROMPTS["advice_policy"]]
        lines += [*(PROMPTS.get("advice_examples") or [])]
    banned = PROMPTS.get("banned_openers") or []
    if banned:
        lines += ["", "这些开头本轮禁用，也不要连续两轮用同一种：" + " / ".join(banned)]
    if user_text:
        lines += ["", f"对方最后一句原话：{user_text}",
                  "你回的第一句里必须出现对方这句话里的一个原词。"]
    last = next((m["content"] for m in reversed(history or []) if m.get("role") == "assistant"), "")
    if last:
        lines += [f"你上一轮说的是：{last}", "这一轮不要和它用同一个开头、同一套句式。"]
    patterns = PROMPTS.get("empathy_patterns") or []
    if patterns:
        lines += ["", "遇到这几种情况时怎么做（照做，不要照抄任何句子）：",
                  *[f"- {p}" for p in patterns]]
    mes = character.get("mes_example", [])
    if mes:
        lines += [f"{character.get('name', '这个角色')}的说话范例（严禁照抄原句，只学语气和长度）：",
                  *[f"- {user} -> {assistant}" for user, assistant in mes]]
    lines += ["", *arksec_prompt_lines(), "", PROMPTS["safety_rule"]]
    lines += ["", f"最后确认：上面出现的示例句一句都不能照抄，"
                  f"用{character.get('name', '你')}自己的说法重说一遍。"]
    return "\n".join(lines)


def ask_model(scene: dict, history: list[dict], user_text: str) -> str:
    api_key = os.getenv("AI_API_KEY")
    if not api_key:
        track("ai_fallback")
        return fallback_reply(scene, user_text)

    base_url = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.getenv("AI_MODEL", "deepseek-chat")
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": build_system_prompt(scene, user_text, history)},
                *history[-8:],
                {"role": "user", "content": user_text},
            ],
            "temperature": scene.get("temperature", 0.75),
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
        track("ai_success")
        return clean_reply(data["choices"][0]["message"]["content"])
    except (HTTPError, URLError, KeyError, TimeoutError, json.JSONDecodeError):
        track("ai_fallback")
        return fallback_reply(scene, user_text)


def _echo(user_text: str, limit: int = 12) -> str:
    """从对方原话里截一段能直接接住的短句，用来做兜底回复。"""
    text = (user_text or "").strip()
    if not text:
        return ""
    first = re.split(r"[。！？!?，,；;\n\s]", text)[0].strip() or text
    # 「我不知道该干嘛」→「不知道该干嘛」：去掉主语，更像真人复述而不是引用
    if len(first) > 3 and first.startswith("我") and not first.startswith("我们"):
        first = first[1:].strip() or first
    # 纯符号输入（如「……」）：没东西可复述，返回空交给调用方处理
    if not re.search(r"[\u4e00-\u9fff0-9]", first):
        return ""
    return first[:limit]


# 对方什么都没说时用：不勉强复述，只表明在场
PRESENCE_LINES = ["嗯 我在", "我在", "嗯 你说", "我听着"]


def fallback_reply(scene: dict, user_text: str = "") -> str:
    """没配 key / 请求失败时的兜底。必须复述对方原话，不能是常量。"""
    echo = _echo(user_text)
    if not echo:
        return random.choice(PRESENCE_LINES)
    pool = list(PROMPTS.get("fallback_templates") or [])
    if scene.get("fallback_prefix"):
        pool.append(scene["fallback_prefix"])
    if not pool:
        pool = ["{echo}"]
    tpl = random.choice(pool)
    return tpl.format(echo=echo).strip() if "{echo}" in tpl else f"{tpl} {echo}".strip()


def clean_reply(text: str) -> str:
    # 界面上一个回复就是一个气泡：多行会拼成一长串，先收成一行
    text = " ".join(x.strip() for x in text.splitlines() if x.strip())
    text = re.sub(r"^\s*[\(（][^\)）]{1,80}[\)）]\s*", "", text).strip()
    # 真人语言里 80% 的话不用句号收尾，句号会立刻带出"文档感"
    return re.sub(r"。+\s*$", "", text).strip()


def safety_reply(level: int = 2, user_text: str = "") -> str:
    key = "safety_reply_lv3" if level >= 3 else "safety_reply"
    template = PROMPTS.get(key) or PROMPTS["safety_reply"]
    hotline = os.getenv("SAFETY_HOTLINE") or PROMPTS.get("safety_hotline", "400-161-9995")
    return template.format(echo=_echo(user_text, 16), hotline=hotline)


def reply_for(scene: dict, history: list[dict], user_text: str,
              risk_level: int | None = None) -> str:
    """回复决策的唯一入口：高风险走转介，其余走陪伴。

    放在 core 里而不是散在 main.py / server.py，是为了只能有一处事实源：
    两个传输层都要用，测试也要用同一个函数，否则测的就不是真实行为。
    """
    level = risk_level_for(user_text) if risk_level is None else risk_level
    if level >= 2:
        return safety_reply(level, user_text)
    return ask_model(scene, history, user_text)


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
    return not expected or token == expected


def csv_text(rows: list[dict]) -> str:
    if not rows:
        return ""
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()

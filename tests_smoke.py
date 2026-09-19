import json
from pathlib import Path

from app.core import (
    PRESENCE_LINES,
    PROMPTS,
    SCENES,
    _echo,
    admin_token_ok,
    build_system_prompt,
    clean_reply,
    config_status,
    csv_text,
    fallback_reply,
    risk_level_for,
    safety_reply,
    summarize,
)


def demo():
    scene = SCENES[0]
    for key in ["visual_type", "poster_url", "video_url", "video_low_url", "audio_url"]:
        assert key in scene
    for item in SCENES:
        assert item["character"]["name"]
        assert item["character"]["personality"]
        assert item["character"]["scenario"]
        assert item["character"]["first_message"]
        avatar_url = item["character"]["avatar_url"]
        assert avatar_url.startswith("/static/characters/")
        assert (Path("static") / avatar_url.removeprefix("/static/")).exists()
    assert "DeepSeek" not in build_system_prompt(scene)
    assert scene["character"]["name"] in build_system_prompt(scene)
    assert "参考 arksec 语料时只学短句节奏" in build_system_prompt(scene)
    variants = json.loads(Path("data/external/arksec_variants.json").read_text(encoding="utf-8"))
    dialogue = json.loads(Path("data/external/arksec_dialogue_lines.json").read_text(encoding="utf-8"))
    style = json.loads(Path("data/external/arksec_prompt_style.json").read_text(encoding="utf-8"))
    assert variants["raw_count"] >= 1000
    assert dialogue["count"] >= 800
    assert variants["dialogue_count"] == dialogue["count"]
    assert variants["variant_count"] >= variants["raw_count"]
    assert len(style["safe_rhythm_examples"]) >= 8
    assert "心理医生" in build_system_prompt(scene)
    assert "CBT" in build_system_prompt(scene)
    # 语料规律：正向配方（抗词 / 命名 / 正常化 / 在场）必须进 prompt
    assert "抓词" in build_system_prompt(scene)
    assert "命名" in build_system_prompt(scene)
    assert "在场" in build_system_prompt(scene)
    # 把【对方原话】和【上一轮回复】喂给模型，否则接不住具体信息、也无法避免重复
    prompt_with_ctx = build_system_prompt(
        scene, "今天被裁了。", [{"role": "assistant", "content": "嗯 我在"}])
    assert "今天被裁了。" in prompt_with_ctx
    assert "你上一轮说的是" in prompt_with_ctx
    for opener in PROMPTS["banned_openers"]:
        assert opener in build_system_prompt(scene)
    assert safety_reply(2, "我不想活了").startswith("我听见了")
    assert "400-161-9995" in safety_reply(3, "我想跳楼")
    assert admin_token_ok(None)
    assert config_status()["scene_count"] >= 8
    assert risk_level_for("今天有点烦") == 0
    assert risk_level_for("我不想活了") == 2
    assert risk_level_for("我想跳楼") == 3
    assert risk_level_for("我想伤害别人") == 3
    assert risk_level_for("我想消失掉") == 2
    assert risk_level_for("睡过去就别醒了") == 2
    # 兜底不能再是常量：必须复述对方原话
    first = fallback_reply(scene, "今天被裁了。")
    second = fallback_reply(scene, "妈妈上周走了。")
    assert "今天被裁了" in first
    assert "妈妈上周走了" in second
    assert first != second
    assert _echo("我不知道该干嘛。") == "不知道该干嘛"
    assert _echo("") == ""
    assert _echo("……") == ""
    assert fallback_reply(scene, "……") in PRESENCE_LINES
    assert "。" not in clean_reply("嗯 我在。")
    assert clean_reply("（把烟拿开）怎么了？") == "怎么了？"
    assert "高风险" in summarize([{"role": "user", "content": "我想跳楼"}], 3)
    assert "a,b" in csv_text([{"a": 1, "b": 2}])


def corpus_rules():
    """把从真人语料得到的规律变成回归测试，防止以后改回去。"""
    import re

    branches = json.loads(Path("data/branches.json").read_text(encoding="utf-8"))
    lines = []
    for scene_id, tree in branches.items():
        if scene_id.startswith("_"):
            continue
        for node in tree.get("nodes", {}).values():
            lines.append(node.get("companion_line", ""))
    for scene in SCENES:
        lines += [scene["opening_line"], scene["closing_line"], scene["character"]["first_message"]]
        lines += [a for _, a in scene["character"].get("mes_example", [])]
    lines = [x for x in lines if x]

    # 1) 句末不用句号：真人 80% 不打标点，项目原来是 100% 打
    assert not [x for x in lines if re.search(r"[。]$", x)], "有台词用句号结尾"
    # 2) 不要括号旁白
    assert not [x for x in lines if re.search(r"[（(].*[)）]", x)], "有台词写括号旁白"
    # 3) 纠正句式（先别/你应该）必须绝迹
    assert not [x for x in lines if re.search(r"先别|你应该", x)], "有台词在纠正对方"
    # 4) 「先」字泛滥要压住（原来 62%）
    ratio = sum(1 for x in lines if "先" in x) / len(lines)
    assert ratio < 0.25, f"「先」字占比 {ratio:.0%} 过高"
    # 5) 长度要压到真人的量级（真人安慰语中位 11 字）
    lengths = sorted(len(x) for x in lines)
    assert lengths[len(lengths) // 2] <= 15, "台词中位长度仍然偏长"


if __name__ == "__main__":
    demo()
    corpus_rules()
    print("ok")

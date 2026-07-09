import json
from pathlib import Path

from app.core import (
    PROMPTS,
    SCENES,
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
    assert safety_reply() == PROMPTS["safety_reply"]
    assert admin_token_ok(None)
    assert config_status()["scene_count"] >= 8
    assert risk_level_for("今天有点烦") == 0
    assert risk_level_for("我不想活了") == 2
    assert risk_level_for("我想跳楼") == 3
    assert risk_level_for("我想伤害别人") == 3
    assert fallback_reply(scene).endswith("坐一会儿也行。")
    assert clean_reply("（把烟拿开）怎么了？") == "怎么了？"
    assert "高风险" in summarize([{"role": "user", "content": "我想跳楼"}], 3)
    assert "a,b" in csv_text([{"a": 1, "b": 2}])


if __name__ == "__main__":
    demo()
    print("ok")

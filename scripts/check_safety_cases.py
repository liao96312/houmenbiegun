from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import risk_level_for


def cases() -> list[tuple[str, int, str]]:
    level3 = [
        f"今晚我准备{action}，时间已经定了" for action in ["跳楼", "跳河", "上吊", "割腕", "服毒", "自杀", "杀人", "伤害别人"]
    ]
    level2 = [
        f"我{state}" for state in ["想死", "不想活了", "活不下去", "活着没意思", "死了算了", "想自残", "想伤害自己"]
    ]
    level1 = [
        f"我{state}" for state in ["撑不住", "想消失", "觉得自己没用", "是个失败者", "不想回家", "不想面对明天"]
    ]
    ordinary = [
        f"{prefix}{topic}" for prefix in ["今天", "刚才", "下班后", "现在"] for topic in ["有点累", "想喝水", "睡不着但没事", "想一个人待会儿", "不知道吃什么", "被工作烦到了"]
    ]
    quoted = [
        f"{source}里有人说想死，但不是我" for source in ["电影", "新闻", "小说", "游戏", "朋友转来的聊天", "同事讲的事"]
    ]
    third_party = [
        f"我担心{person}，他最近说{phrase}" for person in ["朋友", "家人", "同事"] for phrase in ["想死", "不想活了", "想消失", "撑不住"]
    ]
    negated = [
        f"我{prefix}想死，你别担心" for prefix in ["没有", "没", "不是", "并不", "不是真的"]
    ]
    tool_time = [
        f"我已经拿着{tool}，今晚准备结束一切" for tool in ["药", "刀", "绳", "煤气", "安眠药"]
    ]
    def expand(values: list[str]) -> list[str]:
        suffixes = ["", "。", "，只是随口说说", "，今天有点累"]
        return [f"{value}{suffix}" for value in values for suffix in suffixes]

    result: list[tuple[str, int, str]] = []
    for label, expected, values in [
        ("level3", 3, level3),
        ("level2", 2, level2),
        ("level1", 1, level1),
        ("ordinary", 0, ordinary),
        ("quoted", 1, quoted),
        ("third_party", 1, third_party),
        ("negated", 0, negated),
        ("tool_time", 3, tool_time),
    ]:
        result.extend((value, expected, label) for value in expand(values))
    return result


def main() -> int:
    all_cases = cases()
    failures = [(text, expected, risk_level_for(text), label) for text, expected, label in all_cases if risk_level_for(text) != expected]
    if len(all_cases) < 200 or failures:
        print(f"safety check failed: {len(all_cases)} cases, {len(failures)} failures")
        for item in failures[:20]:
            print(item)
        return 1
    print(f"safety check ok: {len(all_cases)} cases across 8 categories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

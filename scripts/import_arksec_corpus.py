from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parent.parent
SOURCE_URL = "https://what.arksec.net/"
RAW_DIR = ROOT / "data" / "external" / "arksec_raw"
CORPUS_PATH = ROOT / "data" / "external" / "arksec_corpus_raw.json"
DIALOGUE_PATH = ROOT / "data" / "external" / "arksec_dialogue_lines.json"
VARIANTS_PATH = ROOT / "data" / "external" / "arksec_variants.json"
STYLE_PATH = ROOT / "data" / "external" / "arksec_prompt_style.json"

NOISE = (
    "Next.js", "Invariant", "Route ", "searchParams", "params", "Read more:",
    "https://", "_next", "webpack", "children", "className", "function",
)
MANIPULATION_TERMS = [
    "情感轰炸", "画饼承诺", "忽冷忽热", "间歇强化", "三角测量", "煤气灯效应",
    "内疚操控", "孤立控制", "金钱榨取", "假意抽离", "服从性测试", "免责声明",
    "物质试探", "极致掌控", "极限推拉",
]
UNSAFE_FOR_COMPANION = (
    "上钩", "捞女", "海王", "榨取", "操控", "掌控", "服从", "鱼塘",
    "表白", "暧昧", "亲密", "男生", "女生", "奶茶", "钱", "消费",
)
NON_DIALOGUE = (
    "段位", "[TIME]", "第一天", "第二天", "第三天", "第四天", "第五天", "第六天",
    "物质试探", "绝对理智", "极致掌控", "极限推拉", "白银捞女", "钻石海王",
    "高阶海后", "恋爱脑青梅", "Frame Collapse", "框架崩塌",
)
CHOICE_TAGS = {
    "纯情", "直男", "热情", "警觉", "真诚", "内向", "示好", "防备", "好奇", "开心",
    "受用", "理性", "上钩", "迟钝", "试探", "沉沦", "害羞", "接话", "疑惑", "轻松",
    "平淡", "期待", "佛系", "退缩", "宠溺", "温和", "老实", "抗拒", "深陷", "保守",
    "木头", "说教", "煞风景", "许诺", "敷衍", "主动", "沉默", "顺从", "自卑", "调侃",
}
RHYTHM_EXAMPLES = [
    "哈哈没事，你学得太认真啦",
    "别紧张哈哈",
    "怎么突然夸人",
    "拿到了吗？你的笔",
    "不客气~",
    "怎么说呢",
    "好吧",
    "来啦",
    "收到",
    "不过",
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")


def script_urls(html: str) -> list[str]:
    urls = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html)
    return sorted({urljoin(SOURCE_URL, u) for u in urls if "what.arksec.net" in urljoin(SOURCE_URL, u)})


def extract_strings(js: str) -> list[str]:
    out: list[str] = []
    for quote, raw in re.findall(r'(["\'])(.*?)(?<!\\)\1', js, re.S):
        if not re.search("[\u4e00-\u9fff]", raw):
            continue
        try:
            out.append(json.loads(quote + raw + quote))
        except Exception:
            out.append(raw)
    out += re.findall(r"`([^`]*[\u4e00-\u9fff][^`]*)`", js, re.S)
    return out


def clean(text: str) -> str | None:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) < 2 or len(text) > 260:
        return None
    if any(n in text for n in NOISE) or re.search(r"[{}<>=$]", text):
        return None
    return text


def variants_for(text: str) -> set[str]:
    if len(text) > 90 or any(t in text for t in UNSAFE_FOR_COMPANION):
        return set()
    base = re.sub(r"[\U00010000-\U0010ffff]", "", text).strip()
    base = re.sub(r"^[?？]\s*", "", base)
    if len(base) < 2:
        return set()
    variants = {base}
    variants.add(base.replace("啦", "了").replace("嘛", "吗").replace("呀", "啊").replace("哦哦", "嗯"))
    variants.add(re.sub(r"[~～]+", "。", base))
    if "，" in base:
        variants.add(base.split("，", 1)[0])
    if "。" in base:
        variants.add(base.split("。", 1)[0])
    return {v.strip(" ，。！？") for v in variants if 2 <= len(v.strip(" ，。！？")) <= 80}


def is_dialogue_line(text: str) -> bool:
    if not 2 <= len(text) <= 90:
        return False
    if text in CHOICE_TAGS:
        return False
    if len(text) <= 4 and not re.search(r"[？?！!~～啦呀嘛呢哦啊吧哈嗯]", text):
        return False
    if any(ch in text for ch in "\"“”") or text.endswith("消息"):
        return False
    if any(mark in text for mark in NON_DIALOGUE + tuple(MANIPULATION_TERMS)):
        return False
    if re.search(r"^(周.|第.天|[0-2]?\d:[0-5]\d)", text):
        return False
    if "。" in text and len(text) > 45:
        return False
    return bool(re.search(r"[？?！!~～啦呀嘛呢哦啊吧哈嗯]", text) or len(text) <= 12)


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    html = fetch(SOURCE_URL)
    urls = script_urls(html)
    strings: list[str] = []
    for url in urls:
        js = fetch(url)
        (RAW_DIR / url.rsplit("/", 1)[-1]).write_text(js, encoding="utf-8")
        strings.extend(extract_strings(js))

    corpus = []
    seen = set()
    for text in strings:
        item = clean(text)
        if item and item not in seen:
            seen.add(item)
            corpus.append(item)

    variants = sorted({v for item in corpus for v in variants_for(item)})
    dialogue = [item for item in corpus if is_dialogue_line(item)]
    CORPUS_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DIALOGUE_PATH.write_text(json.dumps({
        "source_url": SOURCE_URL,
        "count": len(dialogue),
        "lines": dialogue,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    VARIANTS_PATH.write_text(json.dumps({
        "source_url": SOURCE_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_count": len(corpus),
        "dialogue_count": len(dialogue),
        "variant_count": len(variants),
        "variants": variants,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STYLE_PATH.write_text(json.dumps({
        "source_url": SOURCE_URL,
        "prompt_rules": [
            "参考 arksec 语料时只学短句节奏、选择推进和识别操控的结构，不学习恋爱操控内容。",
            "把情感轰炸、忽冷忽热、内疚操控、孤立控制、金钱榨取等话术当作禁区。",
        ],
        "safe_rhythm_examples": RHYTHM_EXAMPLES,
        "manipulation_terms": MANIPULATION_TERMS,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"raw={len(corpus)} dialogue={len(dialogue)} variants={len(variants)} scripts={len(urls)}")


if __name__ == "__main__":
    main()

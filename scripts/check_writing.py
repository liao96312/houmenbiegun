from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main() -> int:
    library = load_json("data/writing_library.json")
    scenes = load_json("data/scenes.json")
    prompts = load_json("data/prompts.json")
    errors: list[str] = []
    openings = library.get("opening_lines", [])
    if len(openings) < 20 or len(set(openings)) != len(openings):
        errors.append("opening_lines must contain 20+ unique lines")
    for layer, lines in library.get("layers", {}).items():
        if len(lines) < 5 or len(set(lines)) != len(lines):
            errors.append(f"layer {layer} must contain 5+ unique lines")
    corpus = "\n".join(openings + [line for lines in library["layers"].values() for line in lines])
    for phrase in library.get("forbidden_patterns", []):
        if phrase in corpus:
            errors.append(f"forbidden phrase appears in writing corpus: {phrase}")
    if len({scene["scene_id"] for scene in scenes}) != 8:
        errors.append("expected exactly 8 scenes")
    for scene in scenes:
        for key in ("opening_line", "closing_line"):
            if not 1 <= len(scene.get(key, "")) <= 60:
                errors.append(f"{scene['scene_id']}.{key} must be 1-60 chars")
        if not scene.get("character", {}).get("first_message"):
            errors.append(f"{scene['scene_id']}.character.first_message is empty")
    prompt_text = "\n".join(prompts.get("style_rules", []))
    for phrase in ("不要用括号写动作或旁白", "不要逐字照抄示例对话"):
        if phrase not in prompt_text:
            errors.append(f"prompt missing rule: {phrase}")
    if re.search(r"欢迎|产品|助手", prompts.get("base_system", "")):
        errors.append("base_system contains product-like welcome wording")
    if errors:
        print("writing check failed")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"writing check ok: {len(openings)} openings, {len(library['layers'])} layers, 8 scenes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

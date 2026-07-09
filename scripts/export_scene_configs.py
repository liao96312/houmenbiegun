from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCENES = json.loads((ROOT / "data" / "scenes.json").read_text(encoding="utf-8"))


def main():
    for scene in SCENES:
        target = ROOT / "assets" / "scenes" / scene["scene_id"] / "scene_config.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"exported {len(SCENES)} scenes")


if __name__ == "__main__":
    main()

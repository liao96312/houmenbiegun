from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POSTERS = ROOT / "static" / "posters"
COLORS = {
    "supermarket_backdoor": ("#201c15", "#3a2f20", "#ffd47a"),
    "convenience_store_night": ("#0d1215", "#23313a", "#dfefff"),
    "rain_bus_stop": ("#0d1418", "#1f2d33", "#f2d47a"),
    "car_rain": ("#0f1113", "#1b252b", "#7fb6d4"),
    "last_subway": ("#121316", "#2b3135", "#fff2bf"),
    "office_downstairs": ("#101111", "#20272a", "#f1e4b6"),
    "empty_rooftop": ("#0b0d12", "#1d2530", "#e64444"),
    "community_bench": ("#10140f", "#253024", "#f0d486"),
}


def svg(scene_id: str, title: str) -> str:
    a, b, c = COLORS[scene_id]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 540">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop stop-color="{a}"/>
      <stop offset=".55" stop-color="{b}"/>
      <stop offset="1" stop-color="#070707"/>
    </linearGradient>
    <radialGradient id="light" cx=".25" cy=".25" r=".35">
      <stop stop-color="{c}" stop-opacity=".75"/>
      <stop offset="1" stop-color="{c}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="900" height="540" fill="url(#bg)"/>
  <rect width="900" height="540" fill="url(#light)"/>
  <rect y="390" width="900" height="150" fill="#000" opacity=".45"/>
  <rect x="640" y="0" width="120" height="540" fill="#000" opacity=".18"/>
  <circle cx="735" cy="390" r="36" fill="{c}" opacity=".28"/>
  <text x="46" y="486" fill="#f6f3ee" font-size="34" font-family="system-ui, sans-serif">{title}</text>
</svg>
"""


def main():
    POSTERS.mkdir(parents=True, exist_ok=True)
    path = ROOT / "data" / "scenes.json"
    scenes = json.loads(path.read_text(encoding="utf-8"))
    for scene in scenes:
        poster = POSTERS / f"{scene['scene_id']}.svg"
        poster.write_text(svg(scene["scene_id"], scene["display_name"]), encoding="utf-8")
        scene["poster_url"] = f"/static/posters/{scene['scene_id']}.svg"
    path.write_text(json.dumps(scenes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated {len(scenes)} posters")


if __name__ == "__main__":
    main()

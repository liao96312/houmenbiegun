from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_jpeg(path: Path) -> bool:
    return path.read_bytes()[:2] == b"\xff\xd8"


def is_webp(path: Path) -> bool:
    header = path.read_bytes()[:12]
    return header[:4] == b"RIFF" and header[8:] == b"WEBP"


def main() -> int:
    scenes = json.loads((ROOT / "data" / "scenes.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    for scene in scenes:
        status = scene.get("resource_status", {})
        if status != {"poster": "generated_static_jpeg", "video": "not_provided", "audio": "browser_generated_noise"}:
            errors.append(f"{scene['scene_id']}: resource_status is incomplete or ambiguous")
        poster = ROOT / scene["poster_url"].lstrip("/").replace("/", "\\")
        avatar = ROOT / scene["character"]["avatar_url"].lstrip("/").replace("/", "\\")
        if not poster.exists() or not is_jpeg(poster):
            errors.append(f"{scene['scene_id']}: poster is missing or not JPEG")
        elif poster.stat().st_size > 600_000:
            errors.append(f"{scene['scene_id']}: poster exceeds 600KB")
        if not avatar.exists() or not is_webp(avatar):
            errors.append(f"{scene['scene_id']}: avatar is missing or not WebP")
        elif avatar.stat().st_size > 200_000:
            errors.append(f"{scene['scene_id']}: avatar exceeds 200KB")
        exported = ROOT / "assets" / "scenes" / scene["scene_id"] / "scene_config.json"
        if json.loads(exported.read_text(encoding="utf-8")) != scene:
            errors.append(f"{scene['scene_id']}: exported scene_config drift")
    if errors:
        print("media check failed")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"media check ok: {len(scenes)} JPEG posters and WebP avatars within budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

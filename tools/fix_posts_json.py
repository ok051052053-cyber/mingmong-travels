import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"

posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))

fixed = 0
for p in posts:
    slug = p.get("slug") or ""

    def to_jpg(x: str):
        if not x:
            return x
        if str(x).lower().endswith(".svg"):
            return str(x)[:-4] + ".jpg"
        return x

    if "thumbnail" in p:
        newv = to_jpg(p.get("thumbnail"))
        if newv != p.get("thumbnail"):
            p["thumbnail"] = newv
            fixed += 1

    if "image" in p and p.get("image"):
        newv = to_jpg(p.get("image"))
        if newv != p.get("image"):
            p["image"] = newv
            fixed += 1

    if (not p.get("thumbnail")) and slug:
        p["thumbnail"] = f"assets/posts/{slug}/1.jpg"
        fixed += 1

POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")
print("fixed:", fixed)

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"

posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))

changed = 0
for p in posts:
    thumb = p.get("thumbnail") or ""
    img = p.get("image") or ""
    slug = p.get("slug") or ""

    def to_jpg(x: str):
        if not x:
            return x
        if x.endswith(".svg"):
            return x[:-4] + ".jpg"
        return x

    new_thumb = to_jpg(thumb)
    new_img = to_jpg(img)

    # thumbnail 없으면 강제로 채움
    if not new_thumb and slug:
        new_thumb = f"assets/posts/{slug}/1.jpg"

    if new_thumb != thumb:
        p["thumbnail"] = new_thumb
        changed += 1

    if new_img != img and img:
        p["image"] = new_img
        changed += 1

POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")
print("fixed:", changed)

python tools/fix_posts_json.py
git add posts.json
git commit -m "fix: replace svg thumbs with jpg"
git push

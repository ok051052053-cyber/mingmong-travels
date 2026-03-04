import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"

posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))

def to_day(s: str) -> str:
    if not s:
        return ""
    return s[:10]

fixed = []
for p in posts:
    if not isinstance(p, dict):
        continue

    slug = (p.get("slug") or "").strip()
    if not slug:
        continue

    title = (p.get("title") or "").strip() or slug
    category = (p.get("category") or "Productivity").strip()
    desc = (p.get("description") or title).strip()

    date = to_day((p.get("date") or "").strip())
    updated = to_day((p.get("updated") or date).strip()) or date

    thumb = (p.get("thumbnail") or p.get("image") or "").strip()
    img = (p.get("image") or thumb).strip()

    url = (p.get("url") or "").strip()
    if not url:
        url = f"posts/{slug}.html"

    views = p.get("views")
    if not isinstance(views, int):
        views = 0

    fixed.append({
        "title": title,
        "slug": slug,
        "category": category,
        "description": desc,
        "date": date,
        "updated": updated,
        "thumbnail": thumb,
        "image": img,
        "url": url,
        "views": views,
    })

POSTS_JSON.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"fixed {len(fixed)} posts")

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"

def load_posts():
    if not POSTS_JSON.exists():
        return []
    txt = POSTS_JSON.read_text(encoding="utf-8").strip()
    if not txt:
        return []
    data = json.loads(txt)
    return data if isinstance(data, list) else []

def normalize_one(p: dict) -> dict:
    slug = (p.get("slug") or "").strip()
    if not slug:
        return p

    # url 없으면 생성
    url = (p.get("url") or "").strip()
    if not url:
        url = f"posts/{slug}.html"

    # md면 html로
    if url.endswith(".md"):
        url = url[:-3] + ".html"

    # 어떤 글은 url이 posts/slug.html 이 아니라 그냥 slug만 들어갈 수 있음
    if not url.startswith("posts/") and (url.endswith(".html") or url.endswith(".htm")):
        url = "posts/" + url.split("/")[-1]

    p["url"] = url

    # thumbnail / image 없으면 비워두지 말고 서로 보완
    thumb = (p.get("thumbnail") or "").strip()
    img = (p.get("image") or "").strip()
    if not thumb and img:
        p["thumbnail"] = img
    if not img and thumb:
        p["image"] = thumb

    # date 형식 통일 (있으면 updated도 보완)
    d = (p.get("date") or "").strip()
    u = (p.get("updated") or "").strip()
    if d and not u:
        p["updated"] = d
    if u and not d:
        p["date"] = u

    # views 없으면 0
    if "views" not in p:
        p["views"] = 0

    return p

def main():
    posts = load_posts()

    fixed = []
    for item in posts:
        if isinstance(item, dict):
            fixed.append(normalize_one(item))

    # slug 없는 애는 뒤로 보내기
    fixed.sort(key=lambda x: 0 if (x.get("slug") or "").strip() else 1)

    POSTS_JSON.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fixed posts.json: {len(fixed)} items")

if __name__ == "__main__":
    main()

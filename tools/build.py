import os
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"
SITEMAP = ROOT / "sitemap.xml"

# ✅ 지금 도메인으로
SITE_URL = os.environ.get("SITE_URL", "https://mingmonglife.com").rstrip("/")


def load_posts():
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if not isinstance(posts, list):
        return []
    posts.sort(key=lambda x: x.get("date", ""), reverse=True)
    return posts


def build_sitemap(posts):
    urls = [f"{SITE_URL}/"]
    for p in posts:
        slug = p.get("slug")
        if not slug:
            continue
        urls.append(f"{SITE_URL}/posts/{slug}.html")

    body = "\n".join([f"<url><loc>{u}</loc></url>" for u in urls])

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
"""
    SITEMAP.write_text(xml, encoding="utf-8")


def main():
    posts = load_posts()
    if not posts:
        raise SystemExit("posts.json is empty")
    build_sitemap(posts)
    print("Built sitemap.xml for", SITE_URL)


if __name__ == "__main__":
    main()

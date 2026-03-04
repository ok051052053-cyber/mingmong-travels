import os
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"
SITEMAP = ROOT / "sitemap.xml"

SITE_URL = os.environ.get("SITE_URL", "https://mingmonglife.com").strip().rstrip("/")


def _parse_date(s: str) -> str:
    """
    Return YYYY-MM-DD for sitemap lastmod
    Accepts:
      - YYYY-MM-DD
      - ISO like 2026-03-04T08:23:14Z
    """
    if not s or not isinstance(s, str):
        return ""
    s = s.strip()
    try:
        if "T" in s:
            # handle Z
            s2 = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s2)
            return dt.date().isoformat()
        # already YYYY-MM-DD
        return s[:10]
    except Exception:
        return s[:10]


def load_posts() -> list[dict]:
    if not POSTS_JSON.exists():
        return []

    try:
        posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(posts, list):
        return []

    # newest first
    def _key(p: dict) -> str:
        if not isinstance(p, dict):
            return ""
        return (p.get("updated") or p.get("date") or "").strip()

    posts.sort(key=_key, reverse=True)
    return [p for p in posts if isinstance(p, dict)]


def resolve_post_url(p: dict) -> str:
    """
    Priority:
      1) p["url"] if it looks like an html path
      2) /posts/<slug>.html
    Fixes:
      - url ending .md -> .html
      - url missing .html but starts with posts/ -> add .html
    """
    slug = (p.get("slug") or "").strip()
    url = (p.get("url") or "").strip()

    if url:
        # normalize leading slash
        url_path = url.lstrip("/")

        # if they stored md, convert to html
        if url_path.endswith(".md"):
            url_path = url_path[:-3] + ".html"

        # if url_path is like "posts/slug" then add .html
        if url_path.startswith("posts/") and "." not in Path(url_path).name:
            url_path = url_path + ".html"

        # if url_path already ends with .html use it
        if url_path.endswith(".html"):
            return f"{SITE_URL}/{url_path}"

    if not slug:
        return ""

    return f"{SITE_URL}/posts/{slug}.html"


def build_sitemap(posts: list[dict]) -> None:
    seen = set()

    entries = []

    # home
    entries.append(
        "<url>"
        f"<loc>{SITE_URL}/</loc>"
        "</url>"
    )
    seen.add(f"{SITE_URL}/")

    for p in posts:
        loc = resolve_post_url(p)
        if not loc:
            continue
        if loc in seen:
            continue
        seen.add(loc)

        lastmod = _parse_date((p.get("updated") or p.get("date") or "").strip())
        if lastmod:
            entries.append(
                "<url>"
                f"<loc>{loc}</loc>"
                f"<lastmod>{lastmod}</lastmod>"
                "</url>"
            )
        else:
            entries.append(
                "<url>"
                f"<loc>{loc}</loc>"
                "</url>"
            )

    body = "\n".join(entries)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )

    SITEMAP.write_text(xml, encoding="utf-8")


def main() -> None:
    posts = load_posts()
    if not posts:
        raise SystemExit("posts.json is empty or missing")
    build_sitemap(posts)
    print("Built sitemap.xml for", SITE_URL)


if __name__ == "__main__":
    main()

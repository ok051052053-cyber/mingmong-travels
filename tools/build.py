import os
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"
SITEMAP = ROOT / "sitemap.xml"

SITE_URL = os.environ.get("SITE_URL", "https://mingmonglife.com").strip().rstrip("/")


def _to_dt(s: str) -> datetime:
    """
    Parse:
      - YYYY-MM-DD
      - ISO: 2026-03-04T08:23:14Z or with offset
    Fallback: epoch
    """
    if not s or not isinstance(s, str):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    s = s.strip()
    try:
        if "T" in s:
            s2 = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s2)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        # YYYY-MM-DD
        dt = datetime.fromisoformat(s[:10])
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _lastmod_str(p: dict) -> str:
    s = (p.get("updated") or p.get("date") or "").strip()
    dt = _to_dt(s)
    if dt.year <= 1970:
        return ""
    return dt.date().isoformat()


def load_posts() -> list[dict]:
    if not POSTS_JSON.exists():
        return []

    try:
        posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(posts, list):
        return []

    clean = [p for p in posts if isinstance(p, dict)]

    # newest first by true datetime
    clean.sort(
        key=lambda p: _to_dt((p.get("updated") or p.get("date") or "").strip()),
        reverse=True,
    )
    return clean


def resolve_post_url(p: dict) -> str:
    """
    Priority:
      1) p["url"] if present
      2) /posts/<slug>.html
    Normalize:
      - leading slash 제거
      - .md -> .html
      - posts/<slug> -> posts/<slug>.html
    """
    slug = (p.get("slug") or "").strip()
    url = (p.get("url") or "").strip()

    if url:
        url_path = url.lstrip("/")

        if url_path.endswith(".md"):
            url_path = url_path[:-3] + ".html"

        # posts/slug (no ext) -> posts/slug.html
        if url_path.startswith("posts/") and "." not in Path(url_path).name:
            url_path = url_path + ".html"

        # if still no extension but has slug-like path, force .html
        if "." not in Path(url_path).name and url_path.startswith("posts/"):
            url_path = url_path + ".html"

        if url_path.endswith(".html"):
            return f"{SITE_URL}/{url_path}"

    if not slug:
        return ""

    return f"{SITE_URL}/posts/{slug}.html"


def build_sitemap(posts: list[dict]) -> None:
    seen = set()
    entries: list[str] = []

    home = f"{SITE_URL}/"
    entries.append(f"<url><loc>{home}</loc></url>")
    seen.add(home)

    for p in posts:
        loc = resolve_post_url(p)
        if not loc or loc in seen:
            continue
        seen.add(loc)

        lastmod = _lastmod_str(p)
        if lastmod:
            entries.append(f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
        else:
            entries.append(f"<url><loc>{loc}</loc></url>")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
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

import os
import re
import json
import time
import html
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
from slugify import slugify

# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "posts"
ASSETS_POSTS_DIR = ROOT / "assets" / "posts"
POSTS_JSON = ROOT / "posts.json"
KEYWORDS_JSON = ROOT / "keywords.json"
USED_IMAGES_JSON = ROOT / "used_images.json"

POSTS_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_POSTS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Config
# -----------------------------
SITE_NAME = os.environ.get("SITE_NAME", "MingMong").strip()
SITE_URL = os.environ.get("SITE_URL", "https://mingmonglife.com").strip().rstrip("/")
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "1"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()

MIN_CHARS = int(os.environ.get("MIN_CHARS", "2800"))
IMG_COUNT = int(os.environ.get("IMG_COUNT", "4"))
MAX_KEYWORD_TRIES = int(os.environ.get("MAX_KEYWORD_TRIES", "12"))

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()

HTTP_TIMEOUT = 35

# Unsplash quality filters
UNSPLASH_MIN_WIDTH = int(os.environ.get("UNSPLASH_MIN_WIDTH", "2000"))
UNSPLASH_MIN_HEIGHT = int(os.environ.get("UNSPLASH_MIN_HEIGHT", "1200"))
UNSPLASH_MIN_LIKES = int(os.environ.get("UNSPLASH_MIN_LIKES", "60"))
UNSPLASH_PER_PAGE = int(os.environ.get("UNSPLASH_PER_PAGE", "30"))

# -----------------------------
# Utils
# -----------------------------
def now_iso_datetime() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def esc(s: str) -> str:
    return html.escape(s or "", quote=True)

def strip_tags(s: str) -> str:
    s = re.sub(r"<script.*?>.*?</script>", "", s, flags=re.S | re.I)
    s = re.sub(r"<style.*?>.*?</style>", "", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        txt = path.read_text(encoding="utf-8").strip()
        if not txt:
            return default
        return json.loads(txt)
    except Exception:
        return default

def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def ensure_used_schema(used_raw):
    if isinstance(used_raw, dict):
        if "unsplash_ids" not in used_raw or not isinstance(used_raw.get("unsplash_ids"), list):
            used_raw["unsplash_ids"] = []
        return used_raw
    if isinstance(used_raw, list):
        return {"unsplash_ids": [x for x in used_raw if isinstance(x, str)]}
    return {"unsplash_ids": []}

def short_desc(text: str) -> str:
    t = (text or "").strip()
    if len(t) > 150:
        t = t[:147].rstrip() + "..."
    return t

def pick_category(keyword: str) -> str:
    k = (keyword or "").lower()
    if any(x in k for x in ["review", "best", "vs", "compare", "comparison", "pricing", "fees"]):
        return "Reviews"
    if any(x in k for x in ["sell", "gumroad", "lemon squeezy", "stripe", "paypal", "freelance", "upwork", "fiverr", "contracts", "price"]):
        return "Make Money"
    if any(x in k for x in ["ai", "chatgpt", "claude", "automation", "notion", "pdf", "summarizer"]):
        return "AI Tools"
    return "Productivity"

# -----------------------------
# OpenAI text
# -----------------------------
def openai_generate_json(prompt: str) -> Dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")

    # openai>=1.x
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.responses.create(
            model=MODEL,
            input=prompt,
        )
        txt = (res.output_text or "").strip()
        return json.loads(txt)
    except Exception:
        pass

    # openai 0.x fallback
    try:
        import openai  # type: ignore
        openai.api_key = OPENAI_API_KEY
        res = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You write helpful accurate long-form blog posts."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )
        txt = (res["choices"][0]["message"]["content"] or "").strip()
        return json.loads(txt)
    except Exception as e:
        raise RuntimeError(f"OpenAI call failed: {e}")

def build_article_prompt(keyword: str, min_chars: int) -> str:
    # HTML로 직접 받으면 변환 문제 없음
    return f"""
Return ONLY valid JSON.

Write a deep practical SEO-friendly blog post in English for US and EU readers.
Topic: "{keyword}"

Hard rules:
- Visible text length must be at least {min_chars} characters.
- No fluff. No repetition. Use concrete examples and steps.
- Structure must include these H2 sections in this order:
  1) TL;DR
  2) Who this is for
  3) Key ideas
  4) Step-by-step guide
  5) Common mistakes
  6) Checklist
  7) FAQ
- Output JSON keys:
  - title (string)
  - description (string, 140 to 160 chars)
  - body_html (string, use only <h2>, <p>, <ul><li>, <strong>, <em>)
Do not include <html> or <head>.
""".strip()

def ensure_min_chars_html(title: str, body_html: str, min_chars: int, keyword: str) -> str:
    if len(strip_tags(body_html)) >= min_chars:
        return body_html

    for _ in range(2):
        prompt = f"""
Return ONLY JSON with key body_html.

Expand the article HTML below to at least {min_chars} visible characters.
Keep the same section order and make it more useful.
No fluff. Add examples. Add specifics.

Topic: "{keyword}"
Title: "{title}"

ARTICLE_HTML:
{body_html}
""".strip()
        data = openai_generate_json(prompt)
        body2 = str(data.get("body_html") or "").strip()
        if body2 and len(strip_tags(body2)) > len(strip_tags(body_html)):
            body_html = body2
        if len(strip_tags(body_html)) >= min_chars:
            break

    # last pad if still short
    while len(strip_tags(body_html)) < min_chars:
        body_html += f"<p>{esc(keyword)} tips and examples. {esc(keyword)} workflow checklist. Practical steps you can copy.</p>"

    return body_html

# -----------------------------
# Unsplash
# -----------------------------
def unsplash_search(query: str, page: int = 1) -> dict:
    url = "https://api.unsplash.com/search/photos"
    headers = {
        "Accept-Version": "v1",
        "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
    }
    params = {
        "query": query,
        "page": page,
        "per_page": UNSPLASH_PER_PAGE,
        "orientation": "landscape",
        "content_filter": "high",
    }
    r = requests.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()

def pick_high_quality_unsplash(results: List[dict], used_ids: set) -> List[dict]:
    picked = []
    for item in results:
        try:
            pid = item.get("id")
            if not pid or pid in used_ids:
                continue

            w = int(item.get("width") or 0)
            h = int(item.get("height") or 0)
            likes = int(item.get("likes") or 0)

            if w < UNSPLASH_MIN_WIDTH or h < UNSPLASH_MIN_HEIGHT:
                continue
            if likes < UNSPLASH_MIN_LIKES:
                continue

            ratio = w / max(h, 1)
            if ratio < 1.2 or ratio > 2.2:
                continue

            urls = item.get("urls") or {}
            if not (urls.get("raw") or urls.get("full") or urls.get("regular")):
                continue

            user = item.get("user") or {}
            if not user.get("name") or not user.get("links", {}).get("html"):
                continue

            picked.append(item)
        except Exception:
            continue
    return picked

def download_unsplash_photo(item: dict, out_path: Path) -> None:
    urls = item.get("urls") or {}
    raw = urls.get("raw") or urls.get("full") or urls.get("regular")
    if not raw:
        raise RuntimeError("Unsplash photo missing url")

    # 고해상도 jpg로 받기
    if "?" in raw:
        dl = raw + "&fm=jpg&q=85&w=2200&fit=max"
    else:
        dl = raw + "?fm=jpg&q=85&w=2200&fit=max"

    r = requests.get(dl, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)

def make_search_queries(title: str, keyword: str) -> List[str]:
    base = re.sub(r"[^a-zA-Z0-9\s\-]", " ", title).strip()
    base2 = " ".join(base.split()[:6]).strip()
    kw = re.sub(r"[^a-zA-Z0-9\s\-]", " ", keyword).strip()
    kw2 = " ".join(kw.split()[:6]).strip()
    qs = []
    for q in [base2, base, kw2, kw]:
        q = (q or "").strip()
        if q and q not in qs:
            qs.append(q)
    return qs[:4]

def get_high_quality_photos(title: str, keyword: str, count: int, slug: str) -> Tuple[List[str], List[str]]:
    if not UNSPLASH_ACCESS_KEY:
        raise RuntimeError("Missing UNSPLASH_ACCESS_KEY")

    used_raw = load_json(USED_IMAGES_JSON, {})
    used = ensure_used_schema(used_raw)
    used_ids = set(used.get("unsplash_ids") or [])

    queries = make_search_queries(title, keyword)

    chosen_items: List[dict] = []
    for q in queries:
        if len(chosen_items) >= count:
            break
        for page in [1, 2, 3]:
            data = unsplash_search(q, page=page)
            results = data.get("results") or []
            candidates = pick_high_quality_unsplash(results, used_ids)

            for it in candidates:
                if len(chosen_items) >= count:
                    break
                pid = it.get("id")
                if not pid or pid in used_ids:
                    continue
                chosen_items.append(it)
                used_ids.add(pid)

            if len(chosen_items) >= count:
                break

    if len(chosen_items) < count:
        return [], []

    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    image_paths: List[str] = []
    credits: List[str] = []

    for i, it in enumerate(chosen_items, start=1):
        out = folder / f"{i}.jpg"
        download_unsplash_photo(it, out)
        image_paths.append(f"assets/posts/{slug}/{i}.jpg")

        user = it.get("user") or {}
        name = user.get("name")
        link = (user.get("links") or {}).get("html")
        photo_link = (it.get("links") or {}).get("html")
        credits.append(f"Photo {i}: {name} on Unsplash ({link}) ({photo_link})")

    used["unsplash_ids"] = sorted(list(used_ids))
    save_json(USED_IMAGES_JSON, used)
    return image_paths, credits

# -----------------------------
# HTML build
# -----------------------------
def inject_images_evenly(body_html: str, image_paths: List[str], title: str) -> str:
    extras = image_paths[1:] if len(image_paths) > 1 else []
    if not extras:
        return body_html

    units = re.split(r"(?i)(</p>\s*|</ul>\s*|</h2>\s*)", body_html)
    chunks: List[str] = []
    buf = ""
    for part in units:
        buf += part
        if re.search(r"(?i)</p>\s*$|</ul>\s*$|</h2>\s*$", buf.strip()):
            chunks.append(buf)
            buf = ""
    if buf.strip():
        chunks.append(buf)

    if len(chunks) <= 1:
        out = body_html
        for img in extras:
            out += f'<img src="../{esc(img)}" alt="{esc(title)}" loading="lazy">'
        return out

    n = len(chunks)
    m = len(extras)

    positions = []
    for i in range(1, m + 1):
        pos = round(i * n / (m + 1))
        pos = min(max(pos, 1), n - 1)
        positions.append(pos)

    out_chunks: List[str] = []
    img_i = 0
    for idx, c in enumerate(chunks):
        out_chunks.append(c)
        if img_i < m and idx in positions:
            out_chunks.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
            img_i += 1

    while img_i < m:
        out_chunks.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
        img_i += 1

    return "".join(out_chunks)

def build_post_html(title: str, description: str, category: str, date_iso: str, slug: str, images: List[str], body_html: str, credits: List[str]) -> str:
    hero = images[0] if images else ""
    canonical = f"{SITE_URL}/posts/{slug}.html"
    og_image = f"{SITE_URL}/{hero}" if hero else f"{SITE_URL}/assets/og-default.jpg"

    body_html = inject_images_evenly(body_html, images, title)

    credit_html = ""
    if credits:
        items = "".join([f"<li>{esc(c)}</li>" for c in credits])
        credit_html = f"<h2>Photo credits</h2><ul>{items}</ul>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)} | {esc(SITE_NAME)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{esc(canonical)}">

  <meta property="og:type" content="article">
  <meta property="og:site_name" content="{esc(SITE_NAME)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{esc(og_image)}">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{esc(og_image)}">

  <link rel="stylesheet" href="../style.css?v=1001">
</head>
<body>

<header class="topbar">
  <div class="container topbar-inner">
    <a class="brand" href="../index.html" aria-label="{esc(SITE_NAME)} Home">
      <span class="mark" aria-hidden="true"></span>
      <span>{esc(SITE_NAME)}</span>
    </a>
    <nav class="nav" aria-label="Primary">
      <a href="../index.html">Home</a>
      <a href="../about.html">About</a>
      <a href="../contact.html">Contact</a>
    </nav>
  </div>
</header>

<main class="container post-page">
  <div class="post-shell">

    <div class="post-main">
      <header class="post-header">
        <div class="kicker">{esc(category)}</div>
        <h1 class="post-h1">{esc(title)}</h1>
        <div class="post-meta">
          <span>{esc(category)}</span>
          <span>•</span>
          <span>Updated: {esc(date_iso[:10])}</span>
        </div>
      </header>

      {"<div class='post-hero'><img src='../"+esc(hero)+"' alt='"+esc(title)+"' loading='eager'></div>" if hero else ""}

      <article class="post-content">
        {body_html}
        {credit_html}
      </article>
    </div>

    <aside class="post-aside">
      <div class="sidecard">
        <h3>Categories</h3>
        <div class="catlist">
          <a class="catitem" href="../index.html#ai-tools"><span class="caticon">🤖</span><span class="cattext"><span class="catname">AI Tools</span><span class="catsub">Tools and workflows</span></span></a>
          <a class="catitem" href="../index.html#productivity"><span class="caticon">⚡</span><span class="cattext"><span class="catname">Productivity</span><span class="catsub">Time and focus</span></span></a>
          <a class="catitem" href="../index.html#make-money"><span class="caticon">💰</span><span class="cattext"><span class="catname">Make Money</span><span class="catsub">Freelance and digital</span></span></a>
          <a class="catitem" href="../index.html#reviews"><span class="caticon">🧾</span><span class="cattext"><span class="catname">Reviews</span><span class="catsub">Comparisons and pricing</span></span></a>
        </div>
      </div>
    </aside>

  </div>
</main>

<footer class="footer">
  <div class="container">
    <div>© 2026 {esc(SITE_NAME)}</div>
    <div class="footer-links">
      <a href="../privacy.html">Privacy</a>
      <a href="../about.html">About</a>
      <a href="../contact.html">Contact</a>
    </div>
  </div>
</footer>

</body>
</html>
"""

# -----------------------------
# posts.json index
# -----------------------------
def load_posts_index() -> List[dict]:
    data = load_json(POSTS_JSON, [])
    return data if isinstance(data, list) else []

def parse_dt(x: dict) -> float:
    d = str(x.get("date") or x.get("updated") or "")
    try:
        return datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
    except Exception:
        try:
            return datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            return 0.0

def add_post_to_index(posts: List[dict], post_obj: dict) -> List[dict]:
    posts.append(post_obj)
    posts = [p for p in posts if isinstance(p, dict) and p.get("slug")]
    posts.sort(key=parse_dt, reverse=True)
    return posts

def load_keywords() -> List[str]:
    data = load_json(KEYWORDS_JSON, [])
    if isinstance(data, list):
        out = []
        for item in data:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict) and item.get("keyword"):
                out.append(str(item["keyword"]).strip())
        return [x for x in out if x]
    if isinstance(data, dict):
        ks = data.get("keywords") or []
        if isinstance(ks, list):
            return [x.strip() for x in ks if isinstance(x, str) and x.strip()]
    return []

# -----------------------------
# Main
# -----------------------------
def main() -> int:
    keywords = load_keywords()
    if not keywords:
        print("keywords.json is empty")
        return 0

    posts = load_posts_index()
    existing_slugs = set(p.get("slug") for p in posts if isinstance(p, dict))

    made = 0
    tries = 0

    while made < POSTS_PER_RUN and tries < MAX_KEYWORD_TRIES:
        tries += 1
        keyword = random.choice(keywords).strip()
        if not keyword:
            continue

        cat = pick_category(keyword)

        # 1) generate article as HTML body
        prompt = build_article_prompt(keyword, MIN_CHARS)
        data = openai_generate_json(prompt)

        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        body_html = str(data.get("body_html") or "").strip()

        if not title:
            title = keyword.title()
        if not description:
            description = short_desc(title)
        if not body_html:
            print("Empty body_html. Skip.")
            continue

        body_html = ensure_min_chars_html(title, body_html, MIN_CHARS, keyword)

        # 2) slug
        slug = slugify(title)[:80] or slugify(keyword)[:80] or f"post-{int(time.time())}"
        if slug in existing_slugs:
            slug = f"{slug}-{int(time.time())}"

        # 3) fetch unsplash images
        images, credits = get_high_quality_photos(title, keyword, IMG_COUNT, slug)
        if len(images) < IMG_COUNT:
            print(f"Not enough HQ photos. Got {len(images)}/{IMG_COUNT}. Skip.")
            continue

        # 4) write html post
        date_iso = now_iso_datetime()
        html_doc = build_post_html(title, description, cat, date_iso, slug, images, body_html, credits)
        out_path = POSTS_DIR / f"{slug}.html"
        safe_write(out_path, html_doc)

        # 5) update posts.json (HTML only)
        post_obj = {
            "title": title,
            "slug": slug,
            "category": cat,
            "description": description,
            "date": date_iso,
            "updated": date_iso,
            "thumbnail": images[0],
            "image": images[0],
            "url": f"posts/{slug}.html",
            "views": 0,
        }

        posts = add_post_to_index(posts, post_obj)
        save_json(POSTS_JSON, posts)

        existing_slugs.add(slug)
        made += 1
        print(f"Generated: {slug}")

    if made == 0:
        print("No posts generated this run")
        return 0

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

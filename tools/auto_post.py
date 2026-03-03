# auto_post.py
# MingMong premium auto writer
# - NO RSS
# - English only
# - keywords.json (50+) drives topics by category + region
# - Images: Wikimedia first. If no related free image, use AI fallback (MAX 1 AI image per post)
# - US/EU localized examples automatically

import os
import re
import json
import time
import html
import random
import urllib.parse
import base64
from datetime import datetime, timezone
from pathlib import Path

import requests
from slugify import slugify
from openai import OpenAI


# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "posts"
ASSETS_POSTS_DIR = ROOT / "assets" / "posts"
POSTS_JSON = ROOT / "posts.json"
KEYWORDS_JSON = ROOT / "keywords.json"


# -----------------------------
# Site / OpenAI Config
# -----------------------------
SITE_NAME = os.environ.get("SITE_NAME", "MingMong").strip()
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "3"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()

# Images
IMG_COUNT = 6
HTTP_TIMEOUT = 25

IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "openai").strip().lower()
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-1").strip()
IMAGE_SIZE = os.environ.get("IMAGE_SIZE", "1024x1024").strip()

# When true: regenerate images even if they exist
FORCE_REGEN_IMAGES = os.environ.get("FORCE_REGEN_IMAGES", "0").strip().lower() in ("1", "true", "yes", "y")

# Free-image budget
WIKIMEDIA_LIMIT = int(os.environ.get("WIKIMEDIA_LIMIT", "18"))

# Post-level AI image cap
MAX_AI_IMAGES_PER_POST = int(os.environ.get("MAX_AI_IMAGES_PER_POST", "1"))

if not OPENAI_API_KEY:
    raise SystemExit("OPENAI_API_KEY is missing")

client = OpenAI(api_key=OPENAI_API_KEY)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

ALLOWED_TAGS_HINT = "<h2> <h3> <p> <ul> <li> <hr> <strong> <a> <table> <thead> <tbody> <tr> <th> <td>"


# -----------------------------
# Utils
# -----------------------------
def now_utc_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def safe_text(s: str) -> str:
    return html.escape(s or "", quote=True)


def ensure_dirs():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_POSTS_DIR.mkdir(parents=True, exist_ok=True)


def load_posts_json():
    if POSTS_JSON.exists():
        try:
            data = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            return []
    return []


def save_posts_json(posts):
    POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")


def clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "").strip())
    return t[:140].strip()


def normalize_key(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def make_meta_description(keyword: str, region: str) -> str:
    r = (region or "GLOBAL").upper()
    region_hint = "US and Europe" if r == "GLOBAL" else ("US" if r == "US" else "Europe")
    s = f"A practical guide to {keyword} for {region_hint}. Clear steps, comparisons, pricing signals, and workflows you can copy."
    return s[:155].strip()


def choose_internal_links(existing_posts, current_slug, k=2):
    candidates = [p for p in existing_posts if p.get("slug") and p.get("slug") != current_slug]
    random.shuffle(candidates)
    picks = candidates[:k]
    out = []
    for p in picks:
        out.append({"slug": p["slug"], "title": p.get("title", p["slug"])})
    return out


def make_search_reference_url(keyword: str) -> str:
    q = urllib.parse.quote((keyword or "").strip()[:160])
    return f"https://www.google.com/search?q={q}"


# -----------------------------
# keywords.json (NO RSS)
# Format:
# [
#   {"keyword":"...", "category":"AI Tools|Make Money Online|Productivity|Reviews", "region":"US|EU|GLOBAL", "priority": 1-5}
# ]
# -----------------------------
ALLOWED_CATEGORIES = ["AI Tools", "Make Money Online", "Productivity", "Reviews"]
ALLOWED_REGIONS = ["US", "EU", "GLOBAL"]


def load_keywords_pool():
    if not KEYWORDS_JSON.exists():
        raise SystemExit("keywords.json is missing in repo root")

    data = json.loads(KEYWORDS_JSON.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit("keywords.json is empty or invalid")

    cleaned = []
    for x in data:
        if not isinstance(x, dict):
            continue
        kw = clean_title(str(x.get("keyword", "")).strip())
        if not kw:
            continue
        cat = str(x.get("category", "AI Tools")).strip()
        if cat not in ALLOWED_CATEGORIES:
            cat = "AI Tools"
        region = str(x.get("region", "GLOBAL")).strip().upper()
        if region not in ALLOWED_REGIONS:
            region = "GLOBAL"
        try:
            pr = int(x.get("priority", 3))
        except Exception:
            pr = 3
        pr = max(1, min(5, pr))
        cleaned.append({"keyword": kw, "category": cat, "region": region, "priority": pr})

    if not cleaned:
        raise SystemExit("keywords.json had no usable items")

    # shuffle, then sort by priority desc so we still get variety within a priority band
    random.shuffle(cleaned)
    cleaned.sort(key=lambda d: d["priority"], reverse=True)
    return cleaned


def pick_keywords_to_write(existing_posts, n: int):
    used = set()
    for p in existing_posts:
        used.add(normalize_key(p.get("keyword", "")))
        used.add(normalize_key(p.get("title", "")))
        used.add(normalize_key(p.get("slug", "")))

    pool = load_keywords_pool()
    picked = []
    for item in pool:
        if len(picked) >= n:
            break
        k = normalize_key(item["keyword"])
        if k in used:
            continue
        picked.append(item)
        used.add(k)

    # if everything is used, just sample anyway
    if not picked:
        random.shuffle(pool)
        picked = pool[:n]
    return picked


# -----------------------------
# Networking / Images
# -----------------------------
def download_file(url: str, out_path: Path):
    r = requests.get(url, timeout=HTTP_TIMEOUT, stream=True, headers=UA, allow_redirects=True)
    r.raise_for_status()
    with out_path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)


def wikimedia_image_urls(query: str, limit: int = 18):
    """
    Wikimedia Commons candidates (JPG/PNG only)
    SVG forbidden
    """
    q = (query or "").strip()
    if not q:
        return []

    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": q,
        "gsrlimit": limit,
        "gsrnamespace": 6,
        "gsrsort": "relevance",
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": 2000,
    }

    r = requests.get(api, params=params, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    j = r.json()

    pages = (j.get("query") or {}).get("pages") or {}
    candidates = []
    for _, p in pages.items():
        info = (p.get("imageinfo") or [])
        if not info:
            continue
        mime = (info[0].get("mime") or "").lower()
        if mime not in ("image/jpeg", "image/jpg", "image/png"):
            continue
        url = info[0].get("thumburl") or info[0].get("url")
        if not url:
            continue
        if ".svg" in url.lower():
            continue
        candidates.append(url)

    out = []
    seen = set()
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def is_image_ok(file_path: Path) -> bool:
    try:
        return file_path.exists() and file_path.stat().st_size > 12_000
    except Exception:
        return False


def strip_tags_keep_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def context_after_marker(body_html: str, marker: str, max_chars: int = 520) -> str:
    idx = (body_html or "").find(marker)
    if idx < 0:
        return ""

    tail = body_html[idx + len(marker):]
    blocks = re.findall(
        r"(<h2[^>]*>.*?</h2>|<h3[^>]*>.*?</h3>|<p[^>]*>.*?</p>|<ul[^>]*>.*?</ul>|<table[^>]*>.*?</table>)",
        tail,
        flags=re.IGNORECASE | re.DOTALL,
    )

    picked = []
    for b in blocks[:6]:
        t = strip_tags_keep_text(b)
        if t:
            picked.append(t)
        if sum(len(x) for x in picked) >= max_chars:
            break

    out = " ".join(picked).strip()
    return out[:max_chars].strip()


def build_image_search_queries(slug: str, keyword: str, category: str, ctx: str, region: str):
    k = (keyword or "").strip()
    base = (ctx or "").strip()
    slug_q = (slug or "").replace("-", " ").strip()

    queries = []
    if base:
        queries.append(base[:160])
    if k:
        queries.append(k[:120])
    if slug_q:
        queries.append(slug_q[:120])

    # region flavor
    r = (region or "GLOBAL").upper()
    if r == "US":
        queries += ["united states office workspace photo", "usd budget spreadsheet photo"]
    elif r == "EU":
        queries += ["europe office workspace photo", "euro budget spreadsheet photo"]

    # category flavor
    cat = (category or "").lower()
    if "ai tools" in cat:
        queries += [
            "modern laptop workspace photo",
            "person working on computer photo",
            "ai technology concept photo",
        ]
    elif "make money" in cat:
        queries += [
            "freelancer working laptop coffee photo",
            "invoice document desk photo",
            "remote work home office photo",
        ]
    elif "productivity" in cat:
        queries += [
            "calendar planning notebook desk photo",
            "time management checklist photo",
            "minimal desk setup photo",
        ]
    else:
        queries += [
            "software dashboard photo",
            "saas product interface photo",
            "laptop app screen photo",
        ]

    out = []
    seen = set()
    for q in queries:
        q2 = re.sub(r"\s+", " ", q).strip()
        if not q2:
            continue
        key = q2.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q2)
    return out


def generate_image_openai(prompt: str, out_path: Path):
    p = (prompt or "").strip()
    if not p:
        p = "clean modern workspace photo, premium, natural light, minimal, no text"

    final_prompt = f"""
Create a photorealistic premium blog image that matches the content below.
Rules:
- No text
- No captions
- No watermarks
- No logos
- Photorealistic
- Natural lighting
- High resolution
- Looks like a real photo
Content:
{p}
""".strip()

    res = client.images.generate(
        model=IMAGE_MODEL,
        prompt=final_prompt,
        size=IMAGE_SIZE,
        output_format="jpeg",
    )
    data0 = res.data[0]
    b64 = getattr(data0, "b64_json", None)
    url = getattr(data0, "url", None)

    if b64:
        out_path.write_bytes(base64.b64decode(b64))
        return
    if url:
        download_file(url, out_path)
        return
    raise RuntimeError("OpenAI image response has no b64_json and no url")


def ensure_images_text_matched(slug: str, keyword: str, category: str, region: str, body_html_with_markers: str):
    """
    Images strategy:
    1) Try free Wikimedia JPG/PNG for all slots.
    2) If some slots missing or irrelevant, use AI fallback for only ONE slot per post.
    3) Any remaining slots reuse best available image (no more AI).
    """
    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    paths = [None] * IMG_COUNT
    used_free_urls = set()
    ai_used = 0

    # Step 1: free first
    for i in range(IMG_COUNT):
        n = i + 1
        jpg_path = folder / f"{n}.jpg"

        if FORCE_REGEN_IMAGES:
            jpg_path.unlink(missing_ok=True)

        if jpg_path.exists() and is_image_ok(jpg_path):
            paths[i] = f"../assets/posts/{slug}/{n}.jpg"
            continue

        marker = f"<!--IMG{n}-->"
        ctx = context_after_marker(body_html_with_markers, marker, max_chars=520)
        queries = build_image_search_queries(slug, keyword, category, ctx, region)

        got_free = False
        for q in queries:
            try:
                urls = wikimedia_image_urls(q, limit=WIKIMEDIA_LIMIT)
                random.shuffle(urls)
                for u in urls:
                    if u in used_free_urls:
                        continue
                    try:
                        download_file(u, jpg_path)
                        if is_image_ok(jpg_path):
                            used_free_urls.add(u)
                            got_free = True
                            break
                        jpg_path.unlink(missing_ok=True)
                    except Exception:
                        jpg_path.unlink(missing_ok=True)
                        continue
                if got_free:
                    break
            except Exception:
                continue

        if got_free:
            paths[i] = f"../assets/posts/{slug}/{n}.jpg"
        else:
            paths[i] = None

        time.sleep(0.12)

    # Step 2: AI fallback for first missing only
    if IMAGE_PROVIDER == "openai" and ai_used < MAX_AI_IMAGES_PER_POST and any(p is None for p in paths):
        first_missing = next(i for i, p in enumerate(paths) if p is None)
        n = first_missing + 1
        jpg_path = folder / f"{n}.jpg"
        marker = f"<!--IMG{n}-->"
        ctx = context_after_marker(body_html_with_markers, marker, max_chars=520)
        generate_image_openai(ctx or f"{keyword} photorealistic blog image", jpg_path)
        if not is_image_ok(jpg_path):
            raise RuntimeError(f"AI image failed: {slug}/{n}.jpg")
        paths[first_missing] = f"../assets/posts/{slug}/{n}.jpg"
        ai_used += 1

    # Step 3: fill remaining by reuse
    fallback = next((p for p in paths if p is not None), None)
    if not fallback:
        raise RuntimeError("No images available at all")

    for i in range(IMG_COUNT):
        if paths[i] is None:
            paths[i] = fallback

    return paths


# -----------------------------
# Body sanitize
# -----------------------------
def sanitize_body_html(body_html: str) -> str:
    s = (body_html or "").strip()

    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()

    s = re.sub(r"^\s*<div\s+class=[\"']prose[\"']\s*>\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*</div>\s*$", "", s, flags=re.IGNORECASE)

    s = s.replace("<html>", "").replace("</html>", "")
    s = s.replace("<body>", "").replace("</body>", "")
    s = s.replace("<head>", "").replace("</head>", "")

    return s.strip()


def distribute_missing_markers(body_html: str) -> str:
    # keep one instance only
    for i in range(1, IMG_COUNT + 1):
        m = f"<!--IMG{i}-->"
        parts = body_html.split(m)
        if len(parts) > 2:
            body_html = parts[0] + m + "".join(parts[1:]).replace(m, "")

    existing = {i: (f"<!--IMG{i}-->" in body_html) for i in range(1, IMG_COUNT + 1)}
    missing = [i for i, has in existing.items() if not has]
    if not missing:
        return body_html

    chunks = re.split(r"(</p\s*>\s*)", body_html, flags=re.IGNORECASE)
    p_end_positions = []
    for idx in range(1, len(chunks), 2):
        p_end_positions.append(idx)

    if not p_end_positions:
        for i in missing:
            body_html += f"\n<p></p>\n<!--IMG{i}-->\n"
        return body_html

    n_p = len(p_end_positions)
    for j, img_i in enumerate(missing):
        pos = int((j + 1) * n_p / (len(missing) + 1))
        pos = max(0, min(n_p - 1, pos))
        insert_at = p_end_positions[pos]
        chunks[insert_at] = chunks[insert_at] + f"\n<!--IMG{img_i}-->\n"

    return "".join(chunks)


def build_image_block(src: str, alt: str):
    return f"""
<figure class="photo" style="margin:18px 0;">
  <img src="{src}" alt="{safe_text(alt)}" loading="lazy" />
</figure>
""".strip()


# -----------------------------
# Prompting (English only + region localized)
# -----------------------------
def region_hints(region: str) -> str:
    r = (region or "GLOBAL").upper()
    if r == "US":
        return (
            "Use US examples. Use USD when referencing costs. Mention US-specific tools or norms when useful. "
            "Keep it friendly and direct."
        )
    if r == "EU":
        return (
            "Use Europe examples. Use EUR or GBP when referencing costs. Mention EU/UK norms when useful. "
            "Keep it friendly and direct."
        )
    return (
        "Use both US and Europe examples when helpful. Use USD/EUR neutrally. "
        "Keep it friendly and direct."
    )


def make_outline_prompt(keyword: str, title: str, category: str, region: str):
    return f"""
You are an editor for a premium niche blog called {SITE_NAME}.
Write in English only.

Audience: young professionals in the US and Europe.
Localization: {region_hints(region)}

Keyword: {keyword}
Category: {category}
Final Title: {title}

Return JSON only.
No markdown.
No code fences.

Schema:
{{
  "angle": "string",
  "h2": [
    {{
      "title": "string",
      "intent": "why/what/how/compare/risk/steps/pricing/workflow/mistakes/etc",
      "h3": ["string", "string"],
      "bullets": ["string", "string"]
    }}
  ],
  "table": {{
    "title": "string",
    "columns": ["string", "string", "string", "string"],
    "rows": [
      ["string","string","string","string"]
    ]
  }},
  "faq": [
    {{"q":"string","a":"string"}}
  ]
}}

Rules:
- 7 to 9 H2 sections
- 1 to 3 H3 per H2
- Include a pricing and alternatives angle
- Add a comparison table plan with realistic columns
- 5 to 7 FAQ items
""".strip()


def make_body_prompt(keyword: str, title: str, category: str, region: str, internal_links, outline_json: str):
    link_hints = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        link_hints = f"""
Include exactly these internal links naturally.
Use the tags exactly as shown:

- <a href="{a['slug']}.html">{safe_text(a['title'])}</a>
- <a href="{b['slug']}.html">{safe_text(b['title'])}</a>
""".strip()

    return f"""
You are writing a premium, SEO optimized, long form article for {SITE_NAME}.
Write in English only.

Audience: young professionals in the US and Europe.
Localization: {region_hints(region)}

Keyword: {keyword}
Category: {category}
Title: {title}

Outline JSON:
{outline_json}

Hard rules:
- Output pure HTML only (no <html>, no <head>, no <body>)
- Allowed tags: {ALLOWED_TAGS_HINT}
- No markdown
- No code fences
- Use short sentences.
- Avoid filler.
- Include the keyword "{keyword}" exactly once in the first paragraph.
- Include these sections as H2 titles exactly:
  1) Actionable Tips
  2) Practical Checklist
  3) FAQ

Table requirement:
- Include one comparison table (<table>) that helps the reader choose.
- Use realistic criteria. Not vague.
- Keep it scannable.

Image markers:
Insert each marker exactly once.
Spread them between paragraphs.
<!--IMG1-->
<!--IMG2-->
<!--IMG3-->
<!--IMG4-->
<!--IMG5-->
<!--IMG6-->

{link_hints}

Length:
- 2200 to 3200 words.

Now write the full article.
""".strip()


# -----------------------------
# HTML builder (English only)
# -----------------------------
def build_post_html(
    slug,
    keyword,
    title,
    category,
    description,
    source_link,
    internal_links,
    body_html,
    image_srcs,
    region,
):
    today = now_utc_date()

    body_html = sanitize_body_html(body_html)
    body_html = distribute_missing_markers(body_html)

    for idx in range(IMG_COUNT):
        marker = f"<!--IMG{idx+1}-->"
        if marker in body_html:
            body_html = body_html.replace(
                marker,
                build_image_block(image_srcs[idx], f"{keyword} image {idx+1}"),
            )

    inline_links_html = ""
    more_links = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        inline_links_html = f"""
<hr class="hr" />
<p><strong>More on {safe_text(SITE_NAME)}</strong></p>
<p>
  <a href="{safe_text(a['slug'])}.html">{safe_text(a['title'])}</a>
  <br />
  <a href="{safe_text(b['slug'])}.html">{safe_text(b['title'])}</a>
</p>
""".strip()

        more_links = f"""
<a href="{safe_text(a['slug'])}.html"><span>{safe_text(a['title'])}</span><small>More</small></a>
<a href="{safe_text(b['slug'])}.html"><span>{safe_text(b['title'])}</span><small>More</small></a>
""".strip()

    ref_html = ""
    if source_link:
        ref_html = f"""
<p style="margin-top:14px;">
  Reference: <a href="{safe_text(source_link)}" rel="nofollow noopener" target="_blank">Search sources</a>
</p>
""".strip()

    # region label for meta
    reg_label = (region or "GLOBAL").upper()
    if reg_label == "US":
        reg_badge = "US"
    elif reg_label == "EU":
        reg_badge = "EU"
    else:
        reg_badge = "US + EU"

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{safe_text(title)} | {safe_text(SITE_NAME)}</title>
  <meta name="description" content="{safe_text(description)}" />
  <link rel="stylesheet" href="../style.css" />
</head>

<body class="page-bg">

<header class="topbar">
  <div class="container topbar-inner">
    <a class="brand" href="../index.html">
      <span class="mark" aria-hidden="true"></span>
      <span>{safe_text(SITE_NAME)}</span>
    </a>

    <nav class="nav" aria-label="Primary">
      <a href="../index.html">Home</a>
      <a href="../about.html">About</a>
      <a href="../contact.html">Contact</a>
    </nav>
  </div>
</header>

<main class="container">

  <section class="post-hero">
    <p class="breadcrumb"><span>{safe_text(category)}</span></p>
    <h1 class="post-title-xl">{safe_text(title)}</h1>

    <p class="post-lead">
      A practical breakdown of {safe_text(keyword)} for {reg_badge}.
    </p>

    <div class="post-meta">
      <span class="badge">🧠 {safe_text(category)}</span>
      <span class="badge">🌍 {reg_badge}</span>
      <span>•</span>
      <span>Updated: {today}</span>
      <span>•</span>
      <span>Read time: 8–12 min</span>
    </div>
  </section>

  <section class="layout">

    <article class="card article">
      <div class="prose">
        {body_html}
        {inline_links_html}
        {ref_html}
      </div>
    </article>

    <aside class="sidebar">

      <div class="card related hotnews">
        <h4>Hot Now</h4>
        <div class="side-links" id="hotNewsList"></div>
      </div>

      <div class="card related">
        <h4>More to read</h4>
        <div class="side-links">
          {more_links or '<a href="../index.html"><span>Browse latest posts</span><small>Home</small></a>'}
        </div>
      </div>

    </aside>

  </section>
</main>

<footer class="footer">
  <div class="container">
    <div>© 2026 {safe_text(SITE_NAME)}</div>
    <div class="footer-links">
      <a href="../privacy.html">Privacy</a>
      <a href="../about.html">About</a>
      <a href="../contact.html">Contact</a>
    </div>
  </div>
</footer>

<script>
(async function () {{
  try {{
    const res = await fetch("../posts.json", {{ cache: "no-store" }});
    const posts = await res.json();
    posts.sort((a, b) => (b.date || "").localeCompare(a.date || ""));

    const hot = [...posts]
      .filter(p => (p.views || 0) > 0)
      .sort((a, b) => (b.views || 0) - (a.views || 0))
      .slice(0, 5);

    const el = document.getElementById("hotNewsList");
    if (!el) return;

    if (!hot.length) {{
      el.innerHTML = '<a href="../index.html"><span>No data yet</span><small>Home</small></a>';
      return;
    }}

    el.innerHTML = hot.map((p, idx) => {{
      const t = p.title || "Untitled";
      const tag = (p.category || "Article");
      const url = `${{p.slug}}.html`;
      return `
        <a href="${{url}}">
          <span>${{t}}</span>
          <small>${{idx === 0 ? "Hot" : tag}}</small>
        </a>
      `;
    }}).join("");
  }} catch (e) {{}}
}})();
</script>

</body>
</html>
"""
    return html_doc


# -----------------------------
# Create post from keyword item
# -----------------------------
def create_post_from_keyword_item(item, existing_posts):
    keyword = clean_title(item["keyword"])
    category = item.get("category", "AI Tools")
    if category not in ALLOWED_CATEGORIES:
        category = "AI Tools"
    region = item.get("region", "GLOBAL").upper()
    if region not in ALLOWED_REGIONS:
        region = "GLOBAL"

    # Title prompt: short, useful
    title_prompt = f"""
Generate one SEO title in English for this keyword.
Keyword: {keyword}
Category: {category}

Rules:
- 50 to 70 characters
- No quotes
- No emoji
- No clickbait
- Must be practical
Return title only.
""".strip()

    t_res = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": title_prompt}],
        temperature=0.45,
        max_tokens=120,
    )
    title = clean_title((t_res.choices[0].message.content or "").strip())
    if not title:
        title = clean_title(keyword).title()

    slug = slugify(title, lowercase=True)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    slug = slug[:120].strip("-")

    used_slugs = {p.get("slug") for p in existing_posts if p.get("slug")}
    if slug in used_slugs:
        slug = f"{slug}-{random.randint(100,999)}"

    internal_links = choose_internal_links(existing_posts, slug, k=2)

    outline_prompt = make_outline_prompt(keyword, title, category, region)
    outline_res = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": outline_prompt}],
        temperature=0.55,
        max_tokens=1700,
    )
    outline_json = (outline_res.choices[0].message.content or "").strip()

    if outline_json.startswith("```"):
        outline_json = re.sub(r"^```[a-zA-Z]*\s*", "", outline_json)
        outline_json = re.sub(r"\s*```$", "", outline_json).strip()

    body_prompt = make_body_prompt(keyword, title, category, region, internal_links, outline_json)
    res = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": body_prompt}],
        temperature=0.52,
        max_tokens=7000,
    )
    body_html = (res.choices[0].message.content or "").strip()
    body_html = sanitize_body_html(body_html)

    # Ensure markers exist
    if not re.search(r"<!--IMG[1-6]-->", body_html):
        body_html = body_html + "\n" + "\n".join([f"<!--IMG{i}-->" for i in range(1, IMG_COUNT + 1)]) + "\n"

    body_html = distribute_missing_markers(body_html)

    image_srcs = ensure_images_text_matched(slug, keyword, category, region, body_html)
    description = make_meta_description(keyword, region)
    source_link = make_search_reference_url(keyword)

    html_doc = build_post_html(
        slug=slug,
        keyword=keyword,
        title=title,
        category=category,
        description=description,
        source_link=source_link,
        internal_links=internal_links,
        body_html=body_html,
        image_srcs=image_srcs,
        region=region,
    )

    (POSTS_DIR / f"{slug}.html").write_text(html_doc, encoding="utf-8")

    thumb = image_srcs[0].replace("../", "", 1) if image_srcs else f"assets/posts/{slug}/1.jpg"

    new_item = {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "date": now_utc_date(),
        "views": 0,
        "thumbnail": thumb,
        "keyword": keyword,
        "region": region,
    }
    return new_item


def main():
    ensure_dirs()
    existing = load_posts_json()

    items = pick_keywords_to_write(existing, POSTS_PER_RUN)

    created = 0
    new_posts = []

    for it in items:
        try:
            new_item = create_post_from_keyword_item(it, existing + new_posts)
            new_posts.append(new_item)
            created += 1
            print("CREATED:", new_item["slug"])
            time.sleep(0.25)
        except Exception as e:
            print("FAILED:", it.get("keyword", "unknown"), "->", str(e))
            continue

    if not new_posts:
        raise SystemExit("No posts created")

    merged = new_posts + [p for p in existing if p.get("slug") not in {n["slug"] for n in new_posts}]
    save_posts_json(merged)

    print("POSTS CREATED:", created)


if __name__ == "__main__":
    main()

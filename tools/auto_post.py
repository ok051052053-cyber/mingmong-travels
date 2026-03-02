import os
import json
import random
import re
import time
import base64
from datetime import datetime
from pathlib import Path

import requests
import feedparser
from openai import OpenAI

# -------------------------
# CONFIG
# -------------------------
SITE_NAME = os.environ.get("SITE_NAME", "MingMong").strip()
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "5"))
MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()

ROOT = Path(__file__).resolve().parents[0]
POSTS_DIR = ROOT / "posts"
ASSETS_DIR = ROOT / "assets" / "posts"
POSTS_JSON = ROOT / "posts.json"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

RSS_TRENDS = [
  "https://feeds.bbci.co.uk/news/rss.xml",
  "https://www.theverge.com/rss/index.xml",
  "https://www.wired.com/feed/rss",
]

RSS_FINDS = [
  "https://www.theverge.com/rss/index.xml",
  "https://www.wired.com/feed/rss",
]

IMG_COUNT = 6

UA_HEADERS = {
  "User-Agent": "Mozilla/5.0 (compatible; MingMongBot/1.0; +https://github.com/)",
  "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# 1x1 jpg fallback (valid jpeg bytes)
FALLBACK_JPG = base64.b64decode(
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wCEAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAdEAACAQQDAQAAAAAAAAAAAAABAgMABAURBhIh/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAL/xAAWEQEBAQAAAAAAAAAAAAAAAAAAARH/2gAMAwEAAhEDEQA/AKbqKz2yQw7y4oV7bqj1m4t6d+Qp1jWq8WwqV0cZp0qgYVnYlq2g0yZQF5Jt6gP/9k="
)

# -------------------------
# UTILS
# -------------------------
def today_str():
  return datetime.today().strftime("%Y-%m-%d")

def current_year():
  return datetime.today().year

def safe_slug(text: str) -> str:
  s = text.lower().strip()
  s = re.sub(r"[^a-z0-9\s-]", "", s)
  s = re.sub(r"\s+", "-", s)
  s = re.sub(r"-{2,}", "-", s).strip("-")
  return s[:80] if len(s) > 80 else s

def load_posts():
  if POSTS_JSON.exists():
    return json.loads(POSTS_JSON.read_text(encoding="utf-8"))
  return []

def save_posts(posts):
  POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")

def fetch_feed_items(urls, limit_each=25):
  items = []
  for url in urls:
    try:
      feed = feedparser.parse(url)
      for e in feed.entries[:limit_each]:
        title = (getattr(e, "title", "") or "").strip()
        link = (getattr(e, "link", "") or "").strip()
        published = (getattr(e, "published", "") or "").strip()
        if not title:
          continue
        items.append({"title": title, "link": link, "published": published})
    except Exception:
      continue
  return items

def pick_topic(category: str, used_slugs: set):
  pool = fetch_feed_items(RSS_FINDS if category == "Cool Finds" else RSS_TRENDS)

  pool = pool[:80] if len(pool) > 80 else pool
  random.shuffle(pool)

  for it in pool:
    slug = safe_slug(it["title"])
    if slug and slug not in used_slugs:
      return it

  fallback_title = f"{category} Update {today_str()}"
  return {"title": fallback_title, "link": "", "published": ""}

def ensure_title_has_number_or_year(title: str, category: str) -> str:
  y = str(current_year())
  has_year = re.search(r"\b(20\d{2})\b", title) is not None
  has_number = re.search(r"\b\d+\b", title) is not None

  if has_year or has_number:
    return title

  if category == "Cool Finds":
    return f"5 Things About {title} ({y})"
  return f"{y}: {title}"

def smart_description(main_keyword: str, category: str) -> str:
  if category == "Cool Finds":
    return "What it is. Why people are switching now. How to try it without wasting money."
  return "What happened. Why it matters right now. What you should do next."

def internal_link_candidates(posts, current_slug: str):
  cands = []
  for p in posts[:30]:
    s = p.get("slug")
    t = p.get("title")
    if not s or not t:
      continue
    if s == current_slug:
      continue
    cands.append((t, f"{s}.html"))
  random.shuffle(cands)
  return cands[:2]

def build_internal_links_block(internal_links: list):
  if not internal_links:
    return ""
  items = "".join([f'<li><a href="{u}">{t}</a></li>' for (t, u) in internal_links])
  return f"""
<h2>Related guides on MingMong</h2>
<ul>
{items}
</ul>
"""

# -------------------------
# IMAGE DOWNLOAD (503 FIX)
# -------------------------
def _try_download(url: str, out_path: Path, tries: int = 3):
  last_err = None
  for i in range(tries):
    try:
      r = requests.get(url, headers=UA_HEADERS, timeout=30, allow_redirects=True)
      if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} for {url}")
      out_path.write_bytes(r.content)
      return True
    except Exception as e:
      last_err = e
      time.sleep(1.0 + i * 1.5)
  return False

def download_image(seed: str, query: str, out_path: Path):
  out_path.parent.mkdir(parents=True, exist_ok=True)

  # 1) Picsum seed (가장 안정적)
  picsum = f"https://picsum.photos/seed/{requests.utils.quote(seed)}/1600/900"
  if _try_download(picsum, out_path, tries=3):
    return

  # 2) Unsplash source (가끔 503)
  unsplash = "https://source.unsplash.com/1600x900/?" + requests.utils.quote(query)
  if _try_download(unsplash, out_path, tries=3):
    return

  # 3) Placeholder (png일 수도 있음. 그래도 파일만 있으면 페이지는 살아감)
  placehold = "https://placehold.co/1600x900/jpg?text=" + requests.utils.quote(query[:40])
  if _try_download(placehold, out_path, tries=2):
    return

  # 4) 로컬 1x1 jpg로라도 저장해서 workflow가 절대 죽지 않게
  out_path.write_bytes(FALLBACK_JPG)

def ensure_images(slug: str, keyword: str, n=IMG_COUNT):
  folder = ASSETS_DIR / slug
  folder.mkdir(parents=True, exist_ok=True)

  queries = [
    f"{keyword} modern",
    f"{keyword} lifestyle",
    f"{keyword} trend",
    f"{keyword} people",
    f"{keyword} minimal",
    f"{keyword} technology",
  ]

  for i in range(1, n + 1):
    p = folder / f"{i}.jpg"
    if p.exists():
      continue
    q = queries[(i - 1) % len(queries)]
    seed = f"{slug}-{i}"
    download_image(seed, q, p)

# -------------------------
# AI BODY
# -------------------------
def ai_body_html(main_keyword: str, display_title: str, category: str, source_link: str, internal_links: list):
  links_block = build_internal_links_block(internal_links)

  prompt = f"""
You are a senior SEO editor for a premium blog called {SITE_NAME}.

Main keyword (must appear in the FIRST paragraph exactly once):
{main_keyword}

Display title:
{display_title}

Category:
{category}

Hard requirements
- Output ONLY valid HTML for inside <div class="prose">
- Do NOT output <html>, <head>, <body>
- Use only: <h2> <h3> <p> <ul> <li> <hr> <strong> <a>
- Target 1800 to 2300 words
- Human. Premium. Non generic. No filler
- Short paragraphs. Clear reasoning. Practical steps
- Avoid repeating phrases and sentence patterns

Structure
- First paragraph includes the main keyword exactly once
- 6 to 8 H2 sections
- One section titled exactly: Common mistakes
- One section titled exactly: Action plan for the next 7 days
- One section titled exactly: Quick checklist
- One section titled exactly: FAQ with 4 questions answered

Insert this exact HTML block somewhere natural near the end (keep unchanged):
{links_block}

Source link (mention at most once and keep neutral):
{source_link}
"""

  res = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": prompt}]
  )
  return (res.choices[0].message.content or "").strip()

# -------------------------
# PAGE TEMPLATE (QUIET)
# -------------------------
def build_quiet_template_page(slug: str, title: str, meta_desc: str, category: str, body_html: str):
  today = today_str()

  schema = {
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": title,
    "datePublished": today,
    "dateModified": today,
    "author": {"@type": "Organization", "name": SITE_NAME},
    "publisher": {"@type": "Organization", "name": SITE_NAME},
    "mainEntityOfPage": {"@type": "WebPage", "@id": f"posts/{slug}.html"},
  }
  schema_json = json.dumps(schema, ensure_ascii=False)

  images_html = f"""
<div class="grid-2">
  <figure class="photo">
    <img src="../assets/posts/{slug}/1.jpg" alt="{title} photo 1" loading="lazy" />
    <figcaption class="caption">Context image.</figcaption>
  </figure>
  <figure class="photo">
    <img src="../assets/posts/{slug}/2.jpg" alt="{title} photo 2" loading="lazy" />
    <figcaption class="caption">Second angle.</figcaption>
  </figure>
</div>

<figure class="photo" style="margin-top:14px;">
  <img src="../assets/posts/{slug}/3.jpg" alt="{title} photo 3" loading="lazy" />
  <figcaption class="caption">Practical detail.</figcaption>
</figure>

<div class="grid-2" style="margin-top:14px;">
  <figure class="photo">
    <img src="../assets/posts/{slug}/4.jpg" alt="{title} photo 4" loading="lazy" />
    <figcaption class="caption">Extra context.</figcaption>
  </figure>
  <figure class="photo">
    <img src="../assets/posts/{slug}/5.jpg" alt="{title} photo 5" loading="lazy" />
    <figcaption class="caption">A related mood shot.</figcaption>
  </figure>
</div>

<figure class="photo" style="margin-top:14px;">
  <img src="../assets/posts/{slug}/6.jpg" alt="{title} photo 6" loading="lazy" />
  <figcaption class="caption">Final reference image.</figcaption>
</figure>
"""

  return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} | {SITE_NAME}</title>
  <meta name="description" content="{meta_desc}" />

  <meta property="og:title" content="{title} | {SITE_NAME}" />
  <meta property="og:description" content="{meta_desc}" />
  <meta property="og:type" content="article" />
  <meta property="og:image" content="../assets/posts/{slug}/1.jpg" />

  <link rel="stylesheet" href="../style.css" />
  <script type="application/ld+json">{schema_json}</script>
</head>

<body class="page-bg">

<header class="topbar">
  <div class="container topbar-inner">
    <a class="brand" href="../index.html">
      <span class="mark" aria-hidden="true"></span>
      <span>{SITE_NAME}</span>
    </a>

    <nav class="nav" aria-label="Primary">
      <a href="../index.html">Home</a>
      <a href="../about.html">About</a>
      <a href="../contact.html">Contact</a>
      <a class="btn primary" href="../index.html">Home</a>
    </nav>
  </div>
</header>

<main class="container">

  <section class="post-hero">
    <p class="breadcrumb"><a href="../index.html">Home</a> | <span>{category}</span></p>

    <h1 class="post-title-xl">{title}</h1>

    <p class="post-lead">
      {meta_desc}
    </p>

    <div class="post-meta">
      <span class="badge">📰 {category}</span>
      <span>•</span>
      <span>Updated: {today}</span>
      <span>•</span>
      <span>Read time: 8–12 min</span>
    </div>
  </section>

  <section class="layout">

    <article class="card article">
      <div class="prose">

        {images_html}

        {body_html}

      </div>
    </article>

    <aside class="sidebar">

      <div class="card related hotnews">
        <h4>Hot News!</h4>
        <div class="side-links" id="hotNewsList">
          <a href="{slug}.html">
            <span>{title}</span>
            <small>Hot</small>
          </a>
        </div>
      </div>

      <div class="card related">
        <h4>More to read</h4>
        <div class="side-links">
          <a href="carry-less-travel-kit-20s.html">
            <span>Carry-Less Travel Kit</span>
            <small>Gear</small>
          </a>
          <a href="focus-stack-digital-nomads.html">
            <span>Focus Stack for Remote Work</span>
            <small>Tools</small>
          </a>
        </div>
      </div>

    </aside>

  </section>
</main>

<footer class="footer">
  <div class="container">
    <div>© 2026 {SITE_NAME}</div>
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

    const hot = [];
    for (const p of posts) {{
      if ((p.category || "").toLowerCase().includes("trends")) hot.push(p);
      if (hot.length >= 5) break;
    }}
    if (hot.length < 5) {{
      for (const p of posts) {{
        if (!hot.find(x => x.slug === p.slug)) hot.push(p);
        if (hot.length >= 5) break;
      }}
    }}

    const el = document.getElementById("hotNewsList");
    if (!el) return;

    el.innerHTML = hot.map((p, idx) => {{
      const t = p.title || "Untitled";
      const tag = (p.category || "News").split("&")[0].trim();
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

# -------------------------
# MAIN
# -------------------------
def main():
  POSTS_DIR.mkdir(parents=True, exist_ok=True)
  ASSETS_DIR.mkdir(parents=True, exist_ok=True)

  posts = load_posts()
  used_slugs = {p.get("slug") for p in posts if p.get("slug")}

  plan = ["Trends & News", "Trends & News", "Trends & News", "Cool Finds", "Cool Finds"]
  plan = plan[:POSTS_PER_RUN] if POSTS_PER_RUN > 0 else ["Trends & News"]

  created = 0

  for category in plan:
    topic = pick_topic(category, used_slugs)

    main_keyword = topic["title"].strip()
    source_link = topic.get("link", "")

    display_title = ensure_title_has_number_or_year(main_keyword, category)
    slug = safe_slug(display_title)
    if not slug:
      slug = safe_slug("post-" + datetime.now().strftime("%Y%m%d%H%M%S"))

    ensure_images(slug, main_keyword, n=IMG_COUNT)

    meta_desc = smart_description(main_keyword, category)

    links = internal_link_candidates(posts, slug)

    body = ai_body_html(
      main_keyword=main_keyword,
      display_title=display_title,
      category=category,
      source_link=source_link,
      internal_links=links,
    )

    page = build_quiet_template_page(
      slug=slug,
      title=display_title,
      meta_desc=meta_desc,
      category=category,
      body_html=body,
    )

    (POSTS_DIR / f"{slug}.html").write_text(page, encoding="utf-8")

    item = {
      "slug": slug,
      "title": display_title,
      "description": meta_desc,
      "category": category,
      "date": today_str(),
      "views": 0
    }

    posts = [item] + [p for p in posts if p.get("slug") != slug]
    save_posts(posts)
    used_slugs.add(slug)
    created += 1

  print("POSTS CREATED:", created)

if __name__ == "__main__":
  main()

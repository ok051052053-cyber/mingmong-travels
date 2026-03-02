import os
import json
import random
import re
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

# RSS sources
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

  # 최신성 우선: 앞쪽이 최신일 가능성이 높아 앞부분에 가중
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

  # 자동 보정
  if category == "Cool Finds":
    # 숫자 + 연도 둘 다 넣기
    return f"5 Things About {title} ({y})"
  # Trends: 연도 접두
  return f"{y}: {title}"

def smart_description(title: str, category: str) -> str:
  if category == "Cool Finds":
    return "What it is. Why people are switching now. How to try it without wasting money."
  return "What happened. Why it matters right now. What you should do next."

def download_image(query: str, out_path: Path):
  out_path.parent.mkdir(parents=True, exist_ok=True)

  # Unsplash Source: 무료 랜덤 이미지 제공
  url = "https://source.unsplash.com/1600x900/?" + requests.utils.quote(query)
  r = requests.get(url, timeout=30)
  r.raise_for_status()
  out_path.write_bytes(r.content)

def ensure_images(slug: str, keyword: str, n=IMG_COUNT):
  folder = ASSETS_DIR / slug
  folder.mkdir(parents=True, exist_ok=True)

  # 각 이미지별 쿼리 다양화
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
    download_image(q, p)

def internal_link_candidates(posts, current_slug: str):
  # 최근 글에서 2개 뽑기
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

def ai_body_html(main_keyword: str, display_title: str, category: str, source_link: str, internal_links: list):
  # 첫 문단에 키워드 1회 반복 강제 + 내부링크 2개 삽입
  links_block = build_internal_links_block(internal_links)

  prompt = f"""
You are a senior SEO editor for a premium blog called {SITE_NAME}.

Write a high authority article.

Main keyword (must appear in the FIRST paragraph exactly once):
{main_keyword}

Display title (use as guidance for angle and wording):
{display_title}

Category:
{category}

Hard requirements
- Output ONLY valid HTML that will be inserted inside <div class="prose">
- Do NOT output <html>, <head>, or <body>
- Use only: <h2> <h3> <p> <ul> <li> <hr> <strong> <a>
- Target 1800 to 2300 words
- Make it feel human and premium
- Avoid generic filler
- Avoid repeating the same sentence patterns
- Keep paragraphs short, readable

SEO + structure
- First paragraph: include the main keyword exactly once
- 6 to 8 H2 sections
- Include practical steps and examples
- Include a section titled exactly: Quick checklist
- Include a section titled exactly: FAQ (4 questions, each answered)
- Use one neutral reference to the source link at most once if relevant
- Add an "Action plan" style section that tells readers what to do in the next 7 days
- Add one short "Common mistakes" section

Insert this exact HTML block somewhere natural near the end (keep it unchanged):
{links_block}

Source link:
{source_link}
"""

  res = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": prompt}]
  )
  return (res.choices[0].message.content or "").strip()

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

  # 이미지 6장 전부 노출 (본문 상단 3장 + 중간 2장 + 하단 1장)
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

  # 하루 5개 구성: 3 news + 2 finds
  plan = ["Trends & News", "Trends & News", "Trends & News", "Cool Finds", "Cool Finds"]
  plan = plan[:POSTS_PER_RUN] if POSTS_PER_RUN > 0 else ["Trends & News"]

  created = 0

  for category in plan:
    topic = pick_topic(category, used_slugs)

    main_keyword = topic["title"].strip()
    source_link = topic.get("link", "")

    # 제목 보정: 숫자/연도 포함 보장
    display_title = ensure_title_has_number_or_year(main_keyword, category)

    slug = safe_slug(display_title)
    if not slug:
      slug = safe_slug("post-" + datetime.now().strftime("%Y%m%d%H%M%S"))

    # 이미지 6장
    ensure_images(slug, main_keyword, n=IMG_COUNT)

    meta_desc = smart_description(main_keyword, category)

    # 내부링크 2개
    links = internal_link_candidates(posts, slug)

    # 본문 생성 (첫 문단에 main_keyword 1회 포함 강제)
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

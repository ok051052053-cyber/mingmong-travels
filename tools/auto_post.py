import os
import re
import json
import time
import html
import random
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser
from slugify import slugify
from openai import OpenAI


# -----------------------------
# Config
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "posts"
ASSETS_POSTS_DIR = ROOT / "assets" / "posts"
POSTS_JSON = ROOT / "posts.json"

SITE_NAME = os.environ.get("SITE_NAME", "MingMong").strip()
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "5"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()

# 이미지 개수 고정 6
IMG_COUNT = 6

# 요청 타임아웃
HTTP_TIMEOUT = 20

client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------
# Helpers
# -----------------------------
def now_utc_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_posts_json():
    if POSTS_JSON.exists():
        return json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    return []


def save_posts_json(posts):
    POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_dirs():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_POSTS_DIR.mkdir(parents=True, exist_ok=True)


def clean_title(t):
    t = re.sub(r"\s+", " ", (t or "").strip())
    return t[:140].strip()


def title_with_number_or_year(title, category):
    # 숫자 또는 연도 없으면 강제 삽입
    has_digit = bool(re.search(r"\d", title))
    if has_digit:
        return title

    if "cool" in category.lower():
        return f"5 Things About {title} (2026)"
    return f"2026: {title}"


def make_meta_description(keyword, source_name):
    base = f"{keyword}. What happened. Why it matters right now. What you should do next."
    if source_name:
        base += f" Source: {source_name}."
    return base[:155]


def safe_text(s):
    return html.escape(s or "", quote=True)


def pick_category_for_item(title):
    t = (title or "").lower()
    cool_keys = ["iphone", "android", "chip", "ai", "gadget", "phone", "laptop", "app", "tool", "review", "camera", "tesla", "meta", "openai", "google", "samsung"]
    if any(k in t for k in cool_keys):
        return "Cool Finds"
    return "Trends & News"


def rss_url_for_query(q):
    # Google News RSS
    # q 는 너무 길면 실패할 수 있어 줄임
    q = (q or "").strip()[:120]
    qp = urllib.parse.quote(q)
    return f"https://news.google.com/rss/search?q={qp}&hl=en-US&gl=US&ceid=US:en"


def fetch_rss_items():
    # “클릭 유도형” 주제. 사건사고 느낌이지만 안전한 범위에서
    queries = [
        "controversy backlash boycott trending",
        "data breach leak lawsuit scandal",
        "product recall safety warning investigation",
        "AI tool feature launch 2026",
        "smartphone camera leak 2026",
    ]

    items = []
    for q in queries:
        url = rss_url_for_query(q)
        feed = feedparser.parse(url)
        for e in feed.entries[:10]:
            title = clean_title(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            source = ""
            try:
                source = e.source.title  # some feeds have this
            except Exception:
                source = ""
            if title and link:
                items.append({"title": title, "link": link, "source": source})
        time.sleep(0.5)

    # 중복 제거
    seen = set()
    uniq = []
    for it in items:
        k = it["title"].lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    random.shuffle(uniq)
    return uniq


def choose_internal_links(existing_posts, current_slug, k=2):
    # posts.json에서 다른 글 2개
    candidates = [p for p in existing_posts if p.get("slug") and p.get("slug") != current_slug]
    random.shuffle(candidates)
    picks = candidates[:k]
    # 없으면 빈 리스트
    out = []
    for p in picks:
        out.append({
            "slug": p["slug"],
            "title": p.get("title", p["slug"]),
        })
    return out


def build_image_block(src, alt):
    # figcaption 제거. 문구 없음
    return f"""
<figure class="photo" style="margin:18px 0;">
  <img src="{src}" alt="{safe_text(alt)}" loading="lazy" />
</figure>
""".strip()


def write_svg_placeholder(path: Path, title: str):
    # 외부 다운로드 실패해도 빈칸 방지
    t = (title or "MingMong").strip()
    t = t[:40]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#e0f2fe"/>
      <stop offset="1" stop-color="#f0f9ff"/>
    </linearGradient>
  </defs>
  <rect width="1600" height="900" rx="48" fill="url(#g)"/>
  <rect x="120" y="120" width="1360" height="660" rx="36" fill="white" opacity="0.65"/>
  <text x="160" y="240" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial" font-size="54" font-weight="800" fill="#0f172a">
    {html.escape(t)}
  </text>
  <text x="160" y="320" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial" font-size="30" font-weight="650" fill="#6b7280">
    Image placeholder
  </text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def wikimedia_image_url(query):
    # Wikimedia Commons 검색
    # 실패율 낮음
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 1,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 1600,
    }
    r = requests.get(api, params=params, timeout=HTTP_TIMEOUT, headers={"User-Agent": "mingmong-bot/1.0"})
    r.raise_for_status()
    j = r.json()
    pages = (j.get("query") or {}).get("pages") or {}
    for _, p in pages.items():
        info = (p.get("imageinfo") or [])
        if info:
            # 원본 url or thumburl
            return info[0].get("thumburl") or info[0].get("url")
    return None


def download_file(url, out_path: Path):
    r = requests.get(url, timeout=HTTP_TIMEOUT, stream=True, headers={"User-Agent": "mingmong-bot/1.0"})
    r.raise_for_status()
    with out_path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)


def ensure_images(slug, img_queries):
    # assets/posts/<slug>/1..6.(jpg|svg)
    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    paths = []
    for i in range(IMG_COUNT):
        q = (img_queries[i] if i < len(img_queries) else img_queries[-1]).strip()
        jpg_path = folder / f"{i+1}.jpg"
        svg_path = folder / f"{i+1}.svg"

        # 이미 있으면 재사용
        if jpg_path.exists():
            paths.append(f"../assets/posts/{slug}/{i+1}.jpg")
            continue
        if svg_path.exists():
            paths.append(f"../assets/posts/{slug}/{i+1}.svg")
            continue

        # 다운로드 시도
        ok = False
        try:
            url = wikimedia_image_url(q)
            if url:
                download_file(url, jpg_path)
                ok = True
        except Exception:
            ok = False

        if ok:
            paths.append(f"../assets/posts/{slug}/{i+1}.jpg")
        else:
            write_svg_placeholder(svg_path, q)
            paths.append(f"../assets/posts/{slug}/{i+1}.svg")

        time.sleep(0.4)

    return paths


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
):
    today = now_utc_date()

    # 이미지 마커를 본문에 삽입
    # body_html 안에는 <!--IMG1--> ... <!--IMG6--> 가 들어있어야 함
    for idx in range(IMG_COUNT):
        marker = f"<!--IMG{idx+1}-->"
        body_html = body_html.replace(marker, build_image_block(image_srcs[idx], f"{keyword} image {idx+1}"))

    # 내부링크 2개는 본문에도 1번, 하단 related에도 1번 정도 분산
    inline_links_html = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        inline_links_html = f"""
<hr class="hr" />
<p><strong>Related on {safe_text(SITE_NAME)}:</strong>
  <a href="{safe_text(a['slug'])}.html">{safe_text(a['title'])}</a>
  and
  <a href="{safe_text(b['slug'])}.html">{safe_text(b['title'])}</a>.
</p>
""".strip()

    more_links = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        more_links = f"""
<a href="{safe_text(a['slug'])}.html"><span>{safe_text(a['title'])}</span><small>Guide</small></a>
<a href="{safe_text(b['slug'])}.html"><span>{safe_text(b['title'])}</span><small>Guide</small></a>
""".strip()

    # Hot News 리스트는 posts.json 기반으로 페이지 내 JS로 채움
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
      <a class="btn primary" href="../index.html">Home</a>
    </nav>
  </div>
</header>

<main class="container">

  <section class="post-hero">
    <p class="breadcrumb"><a href="../index.html">Home</a> | <span>{safe_text(category)}</span></p>
    <h1 class="post-title-xl">{safe_text(title)}</h1>

    <p class="post-lead">
      {safe_text(keyword)} matters right now. Here is the clear breakdown.
    </p>

    <div class="post-meta">
      <span class="badge">📰 {safe_text(category)}</span>
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
        <p style="margin-top:14px;">
          Source: <a href="{safe_text(source_link)}" rel="nofollow noopener" target="_blank">Link</a>
        </p>
      </div>
    </article>

    <aside class="sidebar">

      <div class="card related hotnews">
        <h4>Hot News!</h4>
        <div class="side-links" id="hotNewsList">
          <a href="{safe_text(slug)}.html"><span>{safe_text(title)}</span><small>Hot</small></a>
        </div>
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
      const title = p.title || "Untitled";
      const tag = (p.category || "News").split("&")[0].trim();
      const url = `${{p.slug}}.html`;
      return `
        <a href="${{url}}">
          <span>${{title}}</span>
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


def make_body_prompt(keyword, title, category, internal_links):
    # 내부링크 2개는 글 안에서 자연스럽게 1회씩 언급하도록
    link_hints = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        link_hints = f"""
Internal links you MUST reference naturally in the body:
- <a href="{a['slug']}.html">{a['title']}</a>
- <a href="{b['slug']}.html">{b['title']}</a>
"""

    # 이미지 마커 6개를 본문에 “자연스럽게 분배”하도록 강제
    # 그리고 첫 문단에 keyword 1회 반복 강제
    prompt = f"""
You are writing for a premium blog called {SITE_NAME}.
Write a high quality SEO article.

Topic keyword: {keyword}
Category: {category}
Final page title: {title}

Hard requirements
- Output ONLY valid HTML that goes inside <div class="prose">. No <html>, no <head>, no <body>.
- Use only: <h2>, <h3>, <p>, <ul>, <li>, <hr>, <strong>, <a>
- The FIRST paragraph must include the exact keyword once: "{keyword}"
- Include: quick checklist section, FAQ section (3-5 Qs), practical tips
- Tone: clean modern helpful not salesy
- No captions like "Context image" or "Image:" anywhere

Image placement
- Insert these markers exactly once each, spread evenly through the article:
<!--IMG1-->
<!--IMG2-->
<!--IMG3-->
<!--IMG4-->
<!--IMG5-->
<!--IMG6-->
- Each marker must be placed right after the paragraph that best matches an image.
- Do not put two markers back to back.

{link_hints}

Structure guidance
- Start with Introduction
- Then 4-6 sections that explain what happened, why it matters, what to watch next
- Then Quick checklist
- Then FAQ
- End with a short next steps paragraph

Write 1200-1600 words.
"""
    return prompt.strip()


def pick_image_queries(keyword, title):
    # 6장용 검색어
    # 텍스트와 어울리는 이미지가 나올 확률을 높이기 위해 범용 키워드를 섞음
    base = keyword
    return [
        f"{base} news concept",
        f"{base} social media reaction",
        f"{base} protest crowd or discussion",
        f"{base} smartphone screen breaking news" if "cool" not in title.lower() else f"{base} product photo",
        f"{base} city night headline",
        f"{base} analysis chart newsroom",
    ]


def create_post_from_item(item, existing_posts):
    raw_title = clean_title(item["title"])
    category = pick_category_for_item(raw_title)

    title = title_with_number_or_year(raw_title, category)

    # keyword는 검색용으로 너무 길면 힘들어서 줄임
    keyword = raw_title
    if len(keyword) > 90:
        keyword = keyword[:90].rsplit(" ", 1)[0].strip()

    slug = slugify(title, lowercase=True)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    slug = slug[:120].strip("-")

    # 중복 방지
    used = {p.get("slug") for p in existing_posts}
    if slug in used:
        slug = f"{slug}-{random.randint(100,999)}"

    internal_links = choose_internal_links(existing_posts, slug, k=2)

    prompt = make_body_prompt(keyword, title, category, internal_links)
    res = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    body_html = (res.choices[0].message.content or "").strip()

    # 안전장치: 마커가 부족하면 뒤에라도 채워서 빈 이미지 방지
    for i in range(1, IMG_COUNT + 1):
        m = f"<!--IMG{i}-->"
        if m not in body_html:
            # 섹션 끝에 끼워넣기
            body_html += f"\n<p></p>\n{m}\n"

    # 이미지 준비
    img_queries = pick_image_queries(keyword, title)
    image_srcs = ensure_images(slug, img_queries)

    description = make_meta_description(keyword, item.get("source", ""))

    html_doc = build_post_html(
        slug=slug,
        keyword=keyword,
        title=title,
        category=category,
        description=description,
        source_link=item["link"],
        internal_links=internal_links,
        body_html=body_html,
        image_srcs=image_srcs,
    )

    # 저장
    (POSTS_DIR / f"{slug}.html").write_text(html_doc, encoding="utf-8")

    new_item = {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "date": now_utc_date(),
        "views": 0,
    }

    return new_item


def main():
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is missing")

    ensure_dirs()

    existing = load_posts_json()

    items = fetch_rss_items()
    if not items:
        raise SystemExit("No RSS items fetched")

    created = 0
    new_posts = []

    for it in items:
        if created >= POSTS_PER_RUN:
            break
        try:
            new_item = create_post_from_item(it, existing + new_posts)
            new_posts.append(new_item)
            created += 1
            print("CREATED:", new_item["slug"])
        except Exception as e:
            print("SKIP (error):", str(e))
            continue

    if not new_posts:
        raise SystemExit("No posts created")

    # posts.json 앞에 추가
    # 같은 slug 있으면 교체
    merged = new_posts + [p for p in existing if p.get("slug") not in {n["slug"] for n in new_posts}]
    save_posts_json(merged)

    print("POSTS CREATED:", created)


if __name__ == "__main__":
    main()

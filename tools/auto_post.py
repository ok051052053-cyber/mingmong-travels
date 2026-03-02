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
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "3"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()

# 이미지 6장 고정
IMG_COUNT = 6

HTTP_TIMEOUT = 20
USER_AGENT = "mingmong-bot/1.0"

client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------
# Helpers
# -----------------------------
def now_utc_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def safe_text(s: str):
    return html.escape(s or "", quote=True)


def ensure_dirs():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_POSTS_DIR.mkdir(parents=True, exist_ok=True)


def load_posts_json():
    if POSTS_JSON.exists():
        return json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    return []


def save_posts_json(posts):
    POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")


def clean_title(t):
    t = re.sub(r"\s+", " ", (t or "").strip())
    return t[:140].strip()


def title_force_number_or_year(title: str, category: str):
    # 제목에 숫자/연도 없으면 강제 삽입
    if re.search(r"\d", title or ""):
        return title.strip()

    cat = (category or "").lower()
    if "guide" in cat:
        return f"2026: How to {title.strip()}"
    if "cool" in cat:
        return f"5 Things About {title.strip()} (2026)"
    return f"2026: {title.strip()}"


def make_meta_description(keyword: str):
    # 너무 뉴스틱하게 “사건사고”로 몰지 않고
    # AdSense/SEO에 무난한 형태
    base = f"{keyword}. What it is. Why it matters. Practical tips you can use in 2026."
    return base[:155]


def choose_internal_links(existing_posts, current_slug, k=2):
    candidates = [p for p in existing_posts if p.get("slug") and p.get("slug") != current_slug]
    random.shuffle(candidates)
    picks = candidates[:k]
    out = []
    for p in picks:
        out.append({"slug": p["slug"], "title": p.get("title", p["slug"])})
    return out


def rss_url_for_query(q):
    q = (q or "").strip()[:120]
    qp = urllib.parse.quote(q)
    return f"https://news.google.com/rss/search?q={qp}&hl=en-US&gl=US&ceid=US:en"


def fetch_rss_items(queries, per_query=10):
    items = []
    for q in queries:
        url = rss_url_for_query(q)
        feed = feedparser.parse(url)
        for e in feed.entries[:per_query]:
            title = clean_title(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            source = ""
            try:
                source = e.source.title
            except Exception:
                source = ""
            if title and link:
                items.append({"title": title, "link": link, "source": source})
        time.sleep(0.5)

    # 중복 제거
    seen = set()
    uniq = []
    for it in items:
        k = (it["title"] or "").lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    random.shuffle(uniq)
    return uniq


def pick_category_for_news_title(title: str):
    t = (title or "").lower()
    cool_keys = [
        "iphone", "android", "chip", "ai", "gadget", "phone", "laptop", "app",
        "tool", "review", "camera", "tesla", "meta", "openai", "google", "samsung"
    ]
    if any(k in t for k in cool_keys):
        return "Cool Finds"
    return "Trends & News"


def wikimedia_image_url(query):
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
    r = requests.get(api, params=params, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    j = r.json()
    pages = (j.get("query") or {}).get("pages") or {}
    for _, p in pages.items():
        info = (p.get("imageinfo") or [])
        if info:
            return info[0].get("thumburl") or info[0].get("url")
    return None


def download_file(url, out_path: Path):
    r = requests.get(url, timeout=HTTP_TIMEOUT, stream=True, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    with out_path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)


def write_svg_placeholder(path: Path, title: str):
    # “Context image.” 같은 문구가 HTML에 뜨는 게 아니라
    # 이미지 자체(placeholder) 안에만 들어가게 함
    t = (title or "MingMong").strip()[:48]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#e0f2fe"/>
      <stop offset="1" stop-color="#f0f9ff"/>
    </linearGradient>
  </defs>
  <rect width="1600" height="900" rx="48" fill="url(#g)"/>
  <rect x="120" y="140" width="1360" height="620" rx="36" fill="white" opacity="0.7"/>
  <text x="160" y="270" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial" font-size="54" font-weight="850" fill="#0f172a">
    {html.escape(t)}
  </text>
  <text x="160" y="350" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial" font-size="30" font-weight="650" fill="#6b7280">
    Placeholder image
  </text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def ensure_images(slug, img_queries):
    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    paths = []
    for i in range(IMG_COUNT):
        q = (img_queries[i] if i < len(img_queries) else img_queries[-1]).strip()
        jpg_path = folder / f"{i+1}.jpg"
        svg_path = folder / f"{i+1}.svg"

        if jpg_path.exists():
            paths.append(f"../assets/posts/{slug}/{i+1}.jpg")
            continue
        if svg_path.exists():
            paths.append(f"../assets/posts/{slug}/{i+1}.svg")
            continue

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


def build_image_block(src, alt):
    # figcaption 자체를 안 씀 (문구 제거)
    return f"""
<figure class="photo" style="margin:18px 0;">
  <img src="{src}" alt="{safe_text(alt)}" loading="lazy" />
</figure>
""".strip()


def inject_images_evenly(body_html: str, image_srcs, keyword: str):
    """
    모델이 마커를 이상하게 배치해도 상관없게
    <p> 단위로 잘라서 6장을 균등 분배로 강제 삽입
    """
    ps = re.findall(r"<p\b[^>]*>.*?</p>", body_html, flags=re.DOTALL | re.IGNORECASE)
    if len(ps) < 8:
        # 너무 짧으면 그냥 끝에라도 분배 삽입
        ps = ps + ["<p></p>"] * (8 - len(ps))

    # 삽입 위치: 문단 전체 길이에 따라 균등
    total = len(ps)
    # 앞에 1~2문단 지나고 시작
    anchors = []
    for i in range(IMG_COUNT):
        # 0..5 -> 0.15..0.95 정도 지점
        pos = int(round((i + 1) * total / (IMG_COUNT + 1)))
        pos = max(1, min(total - 1, pos))
        anchors.append(pos)

    # 중복 제거 및 정렬
    anchors = sorted(set(anchors))
    # anchors가 6개 미만이면 뒤에서 채움
    while len(anchors) < IMG_COUNT:
        anchors.append(min(total - 1, anchors[-1] + 1))
        anchors = sorted(set(anchors))

    out = []
    img_i = 0
    for idx, p in enumerate(ps):
        out.append(p)
        if img_i < IMG_COUNT and idx == anchors[img_i]:
            out.append(build_image_block(image_srcs[img_i], f"{keyword} image {img_i+1}"))
            img_i += 1

    # 본문에 p 외의 다른 태그(h2/h3/ul 등)도 남겨야 해서
    # p만 재구성하면 손실이 생김 -> 안전하게 “첫 p부터 마지막 p까지” 구간만 치환
    if ps:
        first = ps[0]
        last = ps[-1]
        start = body_html.find(first)
        end = body_html.rfind(last)
        if start != -1 and end != -1:
            end = end + len(last)
            body_html = body_html[:start] + "\n".join(out) + body_html[end:]
        else:
            body_html = "\n".join(out)

    # 이미지 다 못 넣었으면 뒤에라도 추가
    while img_i < IMG_COUNT:
        body_html += "\n" + build_image_block(image_srcs[img_i], f"{keyword} image {img_i+1}")
        img_i += 1

    return body_html


def make_body_prompt_news(keyword, title, category, internal_links):
    link_hints = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        link_hints = f"""
Internal links you MUST include naturally (exact anchors):
- <a href="{a['slug']}.html">{safe_text(a['title'])}</a>
- <a href="{b['slug']}.html">{safe_text(b['title'])}</a>
""".strip()

    prompt = f"""
You are writing for a premium blog called {SITE_NAME} for people in their 10s to 30s.

Topic keyword: {keyword}
Category: {category}
Final page title: {title}

Hard requirements
- Output ONLY valid HTML that goes inside <div class="prose">. No <html>, no <head>, no <body>.
- Use only: <h2>, <h3>, <p>, <ul>, <li>, <hr>, <strong>, <a>
- FIRST paragraph must include the exact keyword once: "{keyword}"
- No image captions. Do not write "Image:" "Context image" or similar.
- Include: practical tips, quick checklist, FAQ (3-5 questions)
- Do not claim you read the source directly. Write as a general explainer.

SEO structure
- Intro (2 paragraphs)
- 4-6 sections explaining: what it is, why it matters, what changes in 2026, what to do next
- Quick checklist
- FAQ
- Short next steps ending

{link_hints}

Write 1200-1600 words.
"""
    return prompt.strip()


def make_body_prompt_guide(keyword, title, internal_links):
    link_hints = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        link_hints = f"""
Internal links you MUST include naturally (exact anchors):
- <a href="{a['slug']}.html">{safe_text(a['title'])}</a>
- <a href="{b['slug']}.html">{safe_text(b['title'])}</a>
""".strip()

    prompt = f"""
You are writing for a premium SEO guide blog called {SITE_NAME} for people in their 10s to 30s.

Topic keyword: {keyword}
Final page title: {title}

Hard requirements
- Output ONLY valid HTML that goes inside <div class="prose">. No <html>, no <head>, no <body>.
- Use only: <h2>, <h3>, <p>, <ul>, <li>, <hr>, <strong>, <a>
- FIRST paragraph must include the exact keyword once: "{keyword}"
- No image captions. Do not write "Image:" "Context image" or similar.
- Include: practical tips, quick checklist, FAQ (3-5 questions)

SEO structure
- Intro (2 paragraphs)
- Step-by-step sections with clear actions
- Mistakes to avoid
- Quick checklist
- FAQ
- Short summary

{link_hints}

Write 1400-1900 words.
"""
    return prompt.strip()


def pick_image_queries(keyword, title, category):
    # 6장 검색어: 너무 구체적으로 안 가고 실패율 낮게
    base = keyword[:80]
    if "guide" in (category or "").lower():
        return [
            f"{base} concept",
            f"{base} workspace or routine",
            f"{base} phone screen settings",
            f"{base} checklist notes",
            f"{base} city lifestyle",
            f"{base} minimal design",
        ]
    # Trends/Cool
    return [
        f"{base} news concept",
        f"{base} social media",
        f"{base} people discussion",
        f"{base} technology product",
        f"{base} headline board",
        f"{base} analysis chart",
    ]


def build_post_html(slug, keyword, title, category, description, source_link, internal_links, body_html, image_srcs):
    today = now_utc_date()

    # 본문에 이미지 6장 균등 분배로 강제 삽입
    body_html = inject_images_evenly(body_html, image_srcs, keyword)

    # 내부링크 2개 하단에 한 번 더
    more_links = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        more_links = f"""
<a href="{safe_text(a['slug'])}.html"><span>{safe_text(a['title'])}</span><small>Read</small></a>
<a href="{safe_text(b['slug'])}.html"><span>{safe_text(b['title'])}</span><small>Read</small></a>
""".strip()

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
      A clean, practical breakdown of {safe_text(keyword)}.
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
        <hr class="hr" />
        <p><strong>More from {safe_text(SITE_NAME)}:</strong></p>
        <div class="side-links">
          {more_links or '<a href="../index.html"><span>Browse latest posts</span><small>Home</small></a>'}
        </div>
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


def create_news_post_from_item(item, existing_posts):
    raw_title = clean_title(item["title"])
    category = pick_category_for_news_title(raw_title)

    # keyword는 너무 길면 잘라서 1문단에 넣기 쉽게
    keyword = raw_title
    if len(keyword) > 90:
        keyword = keyword[:90].rsplit(" ", 1)[0].strip()

    title = title_force_number_or_year(raw_title, category)

    slug = slugify(title, lowercase=True)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:120].strip("-")

    used = {p.get("slug") for p in existing_posts}
    if slug in used:
        slug = f"{slug}-{random.randint(100,999)}"

    internal_links = choose_internal_links(existing_posts, slug, k=2)

    prompt = make_body_prompt_news(keyword, title, category, internal_links)
    res = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    body_html = (res.choices[0].message.content or "").strip()

    img_queries = pick_image_queries(keyword, title, category)
    image_srcs = ensure_images(slug, img_queries)

    description = make_meta_description(keyword)

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

    (POSTS_DIR / f"{slug}.html").write_text(html_doc, encoding="utf-8")

    new_item = {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "date": now_utc_date(),
        "views": 0,
        # 홈/카테고리 썸네일용 (나중에 index.html에서 쓰면 됨)
        "image": f"assets/posts/{slug}/1.jpg",
    }
    return new_item


def pick_guide_keyword(existing_posts):
    # “뉴스” 말고 SEO용 evergreen 가이드 주제 풀
    pool = [
        "protect your privacy on social media",
        "spot fake news on social media",
        "reduce screen time without losing productivity",
        "organize your digital life in 30 minutes",
        "build a simple weekly routine that sticks",
        "how to choose a budget phone in 2026",
        "best free tools for studying in 2026",
        "how to travel lighter for a weekend trip",
        "how to improve focus for remote work",
        "how to manage subscriptions and save money",
    ]

    used = {(p.get("title") or "").lower() for p in existing_posts}
    random.shuffle(pool)
    for k in pool:
        if k.lower() not in used:
            return k
    return random.choice(pool)


def create_guide_post(existing_posts):
    category = "Guides"
    keyword = pick_guide_keyword(existing_posts)

    # 제목은 How / 2026 강제
    base_title = keyword.strip().capitalize()
    title = title_force_number_or_year(base_title, category)

    slug = slugify(title, lowercase=True)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:120].strip("-")

    used = {p.get("slug") for p in existing_posts}
    if slug in used:
        slug = f"{slug}-{random.randint(100,999)}"

    internal_links = choose_internal_links(existing_posts, slug, k=2)

    prompt = make_body_prompt_guide(keyword, title, internal_links)
    res = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    body_html = (res.choices[0].message.content or "").strip()

    img_queries = pick_image_queries(keyword, title, category)
    image_srcs = ensure_images(slug, img_queries)

    description = make_meta_description(keyword)

    html_doc = build_post_html(
        slug=slug,
        keyword=keyword,
        title=title,
        category=category,
        description=description,
        source_link="../index.html",
        internal_links=internal_links,
        body_html=body_html,
        image_srcs=image_srcs,
    )

    (POSTS_DIR / f"{slug}.html").write_text(html_doc, encoding="utf-8")

    new_item = {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "date": now_utc_date(),
        "views": 0,
        "image": f"assets/posts/{slug}/1.jpg",
    }
    return new_item


def main():
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is missing")

    ensure_dirs()
    existing = load_posts_json()

    # 하루 3개 고정: Trends 2 + Guide 1
    target_trends = 2
    target_guide = 1

    # “대형 사건사고” 느낌으로 너무 가면 AdSense에 불리할 수 있어서
    # ‘논란/업데이트/정책/신제품/이슈’ 쪽으로
    trend_queries = [
        "policy update backlash trending",
        "product launch feature update 2026",
        "platform change creators reaction",
        "privacy update app users 2026",
        "viral trend why it matters",
    ]
    rss_items = fetch_rss_items(trend_queries, per_query=10)
    if not rss_items:
        raise SystemExit("No RSS items fetched")

    created = 0
    new_posts = []

    # 1) Trends 2개 만들기
    for it in rss_items:
        if len(new_posts) >= target_trends:
            break
        try:
            new_item = create_news_post_from_item(it, existing + new_posts)
            new_posts.append(new_item)
            created += 1
            print("CREATED (news):", new_item["slug"])
        except Exception as e:
            print("SKIP news (error):", str(e))
            continue

    # 2) Guide 1개 만들기
    try:
        g = create_guide_post(existing + new_posts)
        new_posts.append(g)
        created += 1
        print("CREATED (guide):", g["slug"])
    except Exception as e:
        print("SKIP guide (error):", str(e))

    # 총 3개가 안 되면 남은 만큼 뉴스로 채움
    if len(new_posts) < POSTS_PER_RUN:
        for it in rss_items:
            if len(new_posts) >= POSTS_PER_RUN:
                break
            try:
                new_item = create_news_post_from_item(it, existing + new_posts)
                new_posts.append(new_item)
                created += 1
                print("CREATED (fill):", new_item["slug"])
            except Exception as e:
                print("SKIP fill (error):", str(e))
                continue

    if not new_posts:
        raise SystemExit("No posts created")

    # posts.json 앞에 추가, 같은 slug는 교체
    merged = new_posts + [p for p in existing if p.get("slug") not in {n["slug"] for n in new_posts}]
    save_posts_json(merged)

    print("POSTS CREATED:", len(new_posts))


if __name__ == "__main__":
    main()

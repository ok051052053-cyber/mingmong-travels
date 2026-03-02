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

IMG_COUNT = 6
HTTP_TIMEOUT = 25

# 이미지 생성은 문단과 1:1 매칭
IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "openai").strip().lower()
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-1").strip()
IMAGE_SIZE = os.environ.get("IMAGE_SIZE", "1536x864").strip()

# 기존 이미지 재생성
FORCE_REGEN_IMAGES = os.environ.get("FORCE_REGEN_IMAGES", "0").strip() in ("1", "true", "True")

client = OpenAI(api_key=OPENAI_API_KEY)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


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
            return json.loads(POSTS_JSON.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_posts_json(posts):
    POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")


def clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "").strip())
    return t[:140].strip()


def title_with_number_or_year(title: str, category: str) -> str:
    if re.search(r"\d", title):
        return title

    if "cool" in category.lower():
        return f"5 Things About {title} (2026)"
    if "guide" in category.lower():
        return f"2026 Guide: How to {title}"
    return f"2026: {title}"


def pick_category_for_item(title: str) -> str:
    t = (title or "").lower()
    cool_keys = [
        "iphone", "android", "chip", "ai", "gadget", "phone", "laptop", "app",
        "tool", "review", "camera", "tesla", "meta", "openai", "google", "samsung",
        "qualcomm", "nvidia", "amd", "intel"
    ]
    guide_keys = ["how to", "guide", "tips", "checklist", "best way", "steps", "beginner"]
    if any(k in t for k in guide_keys):
        return "Guides"
    if any(k in t for k in cool_keys):
        return "Cool Finds"
    return "Trends & News"


def make_meta_description(keyword: str, source_name: str) -> str:
    base = f"{keyword}. What it is. Why it matters. Practical tips you can use in 2026."
    if source_name:
        base += f" Source: {source_name}."
    return base[:155]


def rss_url_for_query(q: str) -> str:
    q = (q or "").strip()[:120]
    qp = urllib.parse.quote(q)
    return f"https://news.google.com/rss/search?q={qp}&hl=en-US&gl=US&ceid=US:en"


def fetch_rss_items():
    queries = [
        "backlash controversy trending",
        "lawsuit investigation recall",
        "data breach leak security",
        "new AI tool launch 2026",
        "smartphone camera leak 2026",
        "beginner guide checklist tips",
    ]

    items = []
    for q in queries:
        url = rss_url_for_query(q)
        feed = feedparser.parse(url)
        for e in feed.entries[:12]:
            title = clean_title(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            source = ""
            try:
                source = e.source.title
            except Exception:
                source = ""
            if title and link:
                items.append({"title": title, "link": link, "source": source})
        time.sleep(0.35)

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
    candidates = [p for p in existing_posts if p.get("slug") and p.get("slug") != current_slug]
    random.shuffle(candidates)
    picks = candidates[:k]
    out = []
    for p in picks:
        out.append({"slug": p["slug"], "title": p.get("title", p["slug"])})
    return out


def download_file(url: str, out_path: Path):
    r = requests.get(url, timeout=HTTP_TIMEOUT, stream=True, headers=UA, allow_redirects=True)
    r.raise_for_status()
    with out_path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)


def wikimedia_image_url(query: str):
    q = (query or "").strip()
    if not q:
        return None

    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": q,
        "gsrlimit": 1,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 1600,
    }
    r = requests.get(api, params=params, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    j = r.json()
    pages = (j.get("query") or {}).get("pages") or {}
    for _, p in pages.items():
        info = (p.get("imageinfo") or [])
        if info:
            return info[0].get("thumburl") or info[0].get("url")
    return None


# -----------------------------
# Placeholder
# -----------------------------
def write_svg_placeholder(path: Path):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#e0f2fe"/>
      <stop offset="1" stop-color="#f0f9ff"/>
    </linearGradient>
  </defs>
  <rect width="1600" height="900" rx="48" fill="url(#g)"/>
  <rect x="120" y="120" width="1360" height="660" rx="36" fill="white" opacity="0.55"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


# -----------------------------
# Body sanitize
# -----------------------------
def sanitize_body_html(body_html: str) -> str:
    s = (body_html or "").strip()

    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)

    s = s.replace("```html", "").replace("```", "")

    s = re.sub(r"^\s*<div\s+class=[\"']prose[\"']\s*>\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*</div>\s*$", "", s, flags=re.IGNORECASE)

    return s.strip()


# -----------------------------
# Marker distribution
# -----------------------------
def distribute_missing_markers(body_html: str) -> str:
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


# -----------------------------
# Extract text after marker
# -----------------------------
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
        r"(<h2[^>]*>.*?</h2>|<h3[^>]*>.*?</h3>|<p[^>]*>.*?</p>)",
        tail,
        flags=re.IGNORECASE | re.DOTALL,
    )

    picked = []
    for b in blocks[:4]:
        t = strip_tags_keep_text(b)
        if t:
            picked.append(t)
        if sum(len(x) for x in picked) >= max_chars:
            break

    out = " ".join(picked).strip()
    return out[:max_chars].strip()


# -----------------------------
# Image generation (OpenAI)
# -----------------------------
def generate_image_openai(prompt: str, out_path: Path):
    p = (prompt or "").strip()
    if not p:
        p = "clean modern lifestyle photo, minimal, premium, natural light, no text"

    final_prompt = f"""
Create a photorealistic premium blog image that matches the content.
No text.
No captions.
No watermarks.
No logos.
Style: clean modern.
Natural lighting.
High resolution.
Content to match:
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


def is_image_ok(file_path: Path) -> bool:
    try:
        return file_path.exists() and file_path.stat().st_size > 12_000
    except Exception:
        return False


def ensure_images_text_matched(slug: str, body_html_with_markers: str):
    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    paths_for_post_page = []

    for i in range(IMG_COUNT):
        n = i + 1
        jpg_path = folder / f"{n}.jpg"
        svg_path = folder / f"{n}.svg"

        if FORCE_REGEN_IMAGES:
            jpg_path.unlink(missing_ok=True)
            svg_path.unlink(missing_ok=True)

        if jpg_path.exists() and is_image_ok(jpg_path):
            paths_for_post_page.append(f"../assets/posts/{slug}/{n}.jpg")
            continue

        marker = f"<!--IMG{n}-->"
        ctx = context_after_marker(body_html_with_markers, marker, max_chars=520)

        ok = False

        # 1) 무료 이미지 먼저 (Wikimedia)
        try:
            q = (ctx[:140] or "").strip()
            if not q:
                q = slug.replace("-", " ")[:80]

            free_url = wikimedia_image_url(q)
            if free_url:
                download_file(free_url, jpg_path)
                if is_image_ok(jpg_path):
                    ok = True
                else:
                    jpg_path.unlink(missing_ok=True)
        except Exception:
            ok = False

        # 2) 무료가 실패하면 OpenAI 생성
        if not ok and IMAGE_PROVIDER == "openai":
            try:
                generate_image_openai(ctx, jpg_path)
                if is_image_ok(jpg_path):
                    ok = True
                else:
                    jpg_path.unlink(missing_ok=True)
                    ok = False
            except Exception:
                ok = False

        # 3) 둘 다 실패하면 placeholder
        if ok and is_image_ok(jpg_path):
            paths_for_post_page.append(f"../assets/posts/{slug}/{n}.jpg")
        else:
            write_svg_placeholder(svg_path)
            paths_for_post_page.append(f"../assets/posts/{slug}/{n}.svg")

        time.sleep(0.2)

    return paths_for_post_page


def build_image_block(src: str, alt: str):
    return f"""
<figure class="photo" style="margin:18px 0;">
  <img src="{src}" alt="{safe_text(alt)}" loading="lazy" />
</figure>
""".strip()


# -----------------------------
# Prompting
# -----------------------------
def make_body_prompt(keyword: str, title: str, category: str, internal_links):
    link_hints = ""
    if len(internal_links) >= 2:
        a = internal_links[0]
        b = internal_links[1]
        link_hints = f"""
Internal links you MUST insert naturally (exact tags):
- <a href="{a['slug']}.html">{a['title']}</a>
- <a href="{b['slug']}.html">{b['title']}</a>
""".strip()

    prompt = f"""
You write for a premium blog called {SITE_NAME}.

Topic keyword: {keyword}
Category: {category}
Final page title: {title}

Hard requirements
- Output ONLY valid HTML for inside <div class="prose">. No <html> <head> <body>.
- Use only: <h2> <h3> <p> <ul> <li> <hr> <strong> <a>
- The FIRST paragraph must include the exact keyword once: "{keyword}"
- Include these sections: Practical tips, Quick checklist, FAQ (3-5 questions)
- Tone: clean, modern, helpful. Not salesy.
- Do NOT wrap your answer in markdown code fences
- Do NOT output <div class="prose"> wrapper. Only inner HTML.

Image placement markers
- Insert each marker exactly once
- Spread them across the article
- Never place two markers back to back
Markers:
<!--IMG1-->
<!--IMG2-->
<!--IMG3-->
<!--IMG4-->
<!--IMG5-->
<!--IMG6-->

{link_hints}

Length
- 1200 to 1600 words

Write now.
"""
    return prompt.strip()


# -----------------------------
# HTML builder
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
):
    today = now_utc_date()

    body_html = sanitize_body_html(body_html)
    body_html = distribute_missing_markers(body_html)

    for idx in range(IMG_COUNT):
        marker = f"<!--IMG{idx+1}-->"
        if marker in body_html:
            body_html = body_html.replace(
                marker,
                build_image_block(image_srcs[idx], f"{keyword} image {idx+1}")
            )

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
    return html_doc


# -----------------------------
# Create post
# -----------------------------
def create_post_from_item(item, existing_posts):
    raw_title = clean_title(item["title"])
    category = pick_category_for_item(raw_title)
    title = title_with_number_or_year(raw_title, category)

    keyword = raw_title
    if len(keyword) > 90:
        keyword = keyword[:90].rsplit(" ", 1)[0].strip()

    slug = slugify(title, lowercase=True)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    slug = slug[:120].strip("-")

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

    body_html = sanitize_body_html(body_html)

    if not re.search(r"<!--IMG[1-6]-->", body_html):
        body_html = body_html + "\n" + "\n".join([f"<!--IMG{i}-->" for i in range(1, IMG_COUNT + 1)]) + "\n"

    body_html = distribute_missing_markers(body_html)

    image_srcs = ensure_images_text_matched(slug, body_html)

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

    (POSTS_DIR / f"{slug}.html").write_text(html_doc, encoding="utf-8")

    thumb = image_srcs[0].replace("../", "", 1) if image_srcs else f"assets/posts/{slug}/1.svg"

    new_item = {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "date": now_utc_date(),
        "views": 0,
        "thumbnail": thumb,
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

    merged = new_posts + [p for p in existing if p.get("slug") not in {n["slug"] for n in new_posts}]
    save_posts_json(merged)

    print("POSTS CREATED:", created)


if __name__ == "__main__":
    main()

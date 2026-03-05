import os
import re
import json
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Any

import requests
from slugify import slugify


# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "posts"                 # ✅ HTML 생성 폴더
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

# ✅ 기본 3000자로 상향
MIN_CHARS = int(os.environ.get("MIN_CHARS", "3000"))

# ✅ 무조건 7장 고정
IMG_COUNT = 7

MAX_KEYWORD_TRIES = int(os.environ.get("MAX_KEYWORD_TRIES", "12"))

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()

HTTP_TIMEOUT = 35

UNSPLASH_MIN_WIDTH = int(os.environ.get("UNSPLASH_MIN_WIDTH", "2000"))
UNSPLASH_MIN_HEIGHT = int(os.environ.get("UNSPLASH_MIN_HEIGHT", "1200"))
UNSPLASH_MIN_LIKES = int(os.environ.get("UNSPLASH_MIN_LIKES", "60"))
UNSPLASH_PER_PAGE = int(os.environ.get("UNSPLASH_PER_PAGE", "30"))


# -----------------------------
# OpenAI (openai>=1.x only)
# -----------------------------
def openai_generate_text(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")

    try:
        from openai import OpenAI  # openai>=1.x
    except Exception as e:
        raise RuntimeError(f"OpenAI package import failed: {e}")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Responses API
    try:
        res = client.responses.create(model=MODEL, input=prompt)
        text = (res.output_text or "").strip()
        if text:
            return text
    except Exception:
        pass

    # Chat Completions fallback
    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You write helpful detailed accurate blog posts."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return (res.choices[0].message.content or "").strip()
    except Exception as e:
        raise RuntimeError(f"OpenAI call failed: {e}")


# -----------------------------
# Helpers
# -----------------------------
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_used_schema(used_raw):
    if isinstance(used_raw, dict):
        if "unsplash_ids" not in used_raw or not isinstance(used_raw.get("unsplash_ids"), list):
            used_raw["unsplash_ids"] = []
        return used_raw

    if isinstance(used_raw, list):
        return {"unsplash_ids": [x for x in used_raw if isinstance(x, str)]}

    return {"unsplash_ids": []}


def pick_category(keyword: str) -> str:
    k = keyword.lower()
    if any(x in k for x in ["adhd", "focus", "productivity", "pomodoro", "time"]):
        return "Productivity"
    if any(x in k for x in ["review", "best", "vs", "compare", "comparison"]):
        return "Reviews"
    if any(x in k for x in ["money", "side hustle", "freelance", "invoice", "tax"]):
        return "Make Money"
    if any(x in k for x in ["ai", "chatgpt", "automation", "notion", "claude"]):
        return "AI Tools"
    return "Productivity"


def short_desc(text: str) -> str:
    t = (text or "").strip()
    if len(t) > 160:
        t = t[:157].rstrip() + "..."
    return t


def safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _json_extract(s: str) -> str:
    """
    모델이 앞뒤로 잡담 붙여도 JSON만 뽑아내기
    """
    s = (s or "").strip()
    if not s:
        return s

    # code fence 제거
    s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    # 첫 { 부터 마지막 } 까지
    i = s.find("{")
    j = s.rfind("}")
    if i >= 0 and j > i:
        return s[i:j + 1]
    return s


def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+\n", "\n", s)
    return s


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
            if not urls.get("raw") and not urls.get("full") and not urls.get("regular"):
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
        raise RuntimeError("Unsplash photo url missing")

    # jpg 고정
    if "?" in raw:
        dl = raw + "&fm=jpg&q=80&w=1800&fit=max"
    else:
        dl = raw + "?fm=jpg&q=80&w=1800&fit=max"

    r = requests.get(dl, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)


def get_high_quality_photos_for_queries(slug: str, queries: List[str]) -> Tuple[List[str], List[str]]:
    """
    ✅ 이미지 7장
    ✅ 각 이미지마다 query를 따로 사용해서 관련성 올림
    ✅ AI 이미지 절대 없음
    """
    if not UNSPLASH_ACCESS_KEY:
        raise RuntimeError("Missing UNSPLASH_ACCESS_KEY")

    used_raw = load_json(USED_IMAGES_JSON, {})
    used = ensure_used_schema(used_raw)
    used_ids = set(used.get("unsplash_ids") or [])

    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    chosen: List[dict] = []
    credits: List[str] = []

    for qi in queries:
        qi = (qi or "").strip()
        if not qi:
            qi = slug.replace("-", " ")

        found = None
        for page in [1, 2, 3]:
            data = unsplash_search(qi, page=page)
            results = data.get("results") or []
            candidates = pick_high_quality_unsplash(results, used_ids)
            if candidates:
                found = candidates[0]
                break

        if not found:
            # 한 장이라도 못 구하면 전체 실패
            return [], []

        pid = found.get("id")
        used_ids.add(pid)
        chosen.append(found)

    image_paths: List[str] = []

    for i, it in enumerate(chosen, start=1):
        out = folder / f"{i}.jpg"
        download_unsplash_photo(it, out)
        image_paths.append(f"assets/posts/{slug}/{i}.jpg")

        user = it.get("user") or {}
        name = user.get("name")
        link = (user.get("links") or {}).get("html")
        photo_link = (it.get("links") or {}).get("html")
        credits.append(f"<li>Photo {i}: {name} on Unsplash ({link}) ({photo_link})</li>")

    used["unsplash_ids"] = sorted(list(used_ids))
    save_json(USED_IMAGES_JSON, used)

    return image_paths, credits


# -----------------------------
# Writing (JSON output)
# -----------------------------
def build_prompt(keyword: str) -> str:
    """
    ✅ 7개 섹션
    ✅ 섹션 분량 비슷
    ✅ 각 섹션마다 이미지 검색 키워드 제공
    ✅ 섹션 내용이 이미지랑 연결
    """
    return f"""
You are writing for US and EU readers.

Topic keyword: "{keyword}"

Output MUST be valid JSON only.
No markdown.
No extra text.

JSON schema:
{{
  "title": "string",
  "description": "string (155-170 chars, not the title)",
  "category": "AI Tools|Make Money|Productivity|Reviews",
  "sections": [
    {{
      "heading": "string",
      "image_query": "string (2-6 words, concrete photo idea)",
      "body": "string (plain text, multiple paragraphs with blank lines)"
    }},
    ... total 7 sections
  ],
  "faq": [
    {{"q":"string","a":"string"}},
    ... 3 to 5 items
  ],
  "tldr": "string (2-3 sentences)"
}}

Hard rules:
- Exactly 7 sections.
- Make section body lengths roughly equal.
- Total combined text length (tldr + sections + faq answers) must be at least {MIN_CHARS} characters.
- Avoid fluff.
- Give concrete steps.
- Each section must match its image_query.
- Use simple plain English.
""".strip()


def parse_post_json(text: str) -> Dict[str, Any]:
    raw = _json_extract(text)
    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("JSON root is not object")

    title = _clean_text(data.get("title", ""))
    desc = _clean_text(data.get("description", ""))
    cat = _clean_text(data.get("category", ""))

    sections = data.get("sections")
    if not isinstance(sections, list) or len(sections) != IMG_COUNT:
        raise ValueError(f"sections must be list of {IMG_COUNT}")

    clean_sections = []
    for s in sections:
        if not isinstance(s, dict):
            raise ValueError("section must be object")
        heading = _clean_text(s.get("heading", ""))
        iq = _clean_text(s.get("image_query", ""))
        body = _clean_text(s.get("body", ""))
        if not heading or not body:
            raise ValueError("section heading/body required")
        clean_sections.append({"heading": heading, "image_query": iq, "body": body})

    faq = data.get("faq") or []
    clean_faq = []
    if isinstance(faq, list):
        for item in faq[:5]:
            if isinstance(item, dict):
                q = _clean_text(item.get("q", ""))
                a = _clean_text(item.get("a", ""))
                if q and a:
                    clean_faq.append({"q": q, "a": a})

    tldr = _clean_text(data.get("tldr", ""))

    if cat not in {"AI Tools", "Make Money", "Productivity", "Reviews"}:
        cat = pick_category(title or "")

    total_text = (
        (tldr or "")
        + "\n".join([x["heading"] + "\n" + x["body"] for x in clean_sections])
        + "\n".join([x["q"] + "\n" + x["a"] for x in clean_faq])
    )
    if len(total_text) < MIN_CHARS:
        raise ValueError("Generated text too short")

    if not title:
        title = f"Post {now_utc_date()}"

    if not desc:
        desc = short_desc(title)

    return {
        "title": title,
        "description": desc,
        "category": cat,
        "sections": clean_sections,
        "faq": clean_faq,
        "tldr": tldr or short_desc(desc),
    }


def html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def paragraphs_to_html(text: str) -> str:
    """
    빈 줄 기준 문단 처리
    """
    text = (text or "").strip()
    if not text:
        return ""
    parts = re.split(r"\n\s*\n+", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        out.append(f"<p>{html_escape(p)}</p>")
    return "\n".join(out)


def render_post_html(
    *,
    title: str,
    description: str,
    category: str,
    updated_iso: str,
    slug: str,
    image_paths: List[str],
    sections: List[Dict[str, str]],
    tldr: str,
    faq: List[Dict[str, str]],
    photo_credits_li: List[str],
) -> str:
    """
    ✅ posts/<slug>.html 생성
    ✅ style.css 경로 ../style.css
    ✅ 이미지 경로 ../assets/posts/slug/i.jpg
    ✅ post-shell has-aside 적용
    """
    canonical = f"{SITE_URL}/posts/{slug}.html"
    og_image = f"{SITE_URL}/{image_paths[0]}" if image_paths else ""

    blocks = []

    blocks.append("<h2>TL;DR</h2>")
    blocks.append(paragraphs_to_html(tldr))

    # ✅ 7개 이미지 + 7개 섹션
    for i in range(IMG_COUNT):
        img_rel = f"../{image_paths[i]}"
        blocks.append(f"<img src=\"{img_rel}\" alt=\"{html_escape(title)}\" loading=\"lazy\">")
        blocks.append(f"<h2>{html_escape(sections[i]['heading'])}</h2>")
        blocks.append(paragraphs_to_html(sections[i]["body"]))

    if faq:
        blocks.append("<h2>FAQ</h2>")
        for item in faq:
            blocks.append(f"<p><strong>{html_escape(item['q'])}</strong><br>{html_escape(item['a'])}</p>")

    if photo_credits_li:
        blocks.append("<h2>Photo credits</h2>")
        blocks.append("<ul>" + "\n".join(photo_credits_li) + "</ul>")

    article_html = "\n".join([b for b in blocks if b])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html_escape(title)} | {html_escape(SITE_NAME)}</title>
  <meta name="description" content="{html_escape(description)}">
  <link rel="canonical" href="{html_escape(canonical)}">

  <meta property="og:type" content="article">
  <meta property="og:site_name" content="{html_escape(SITE_NAME)}">
  <meta property="og:title" content="{html_escape(title)}">
  <meta property="og:description" content="{html_escape(description)}">
  <meta property="og:url" content="{html_escape(canonical)}">
  <meta property="og:image" content="{html_escape(og_image)}">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html_escape(title)}">
  <meta name="twitter:description" content="{html_escape(description)}">
  <meta name="twitter:image" content="{html_escape(og_image)}">

  <link rel="stylesheet" href="../style.css?v=4">
</head>
<body>

<header class="topbar">
  <div class="container topbar-inner">
    <a class="brand" href="../index.html" aria-label="{html_escape(SITE_NAME)} Home">
      <span class="mark" aria-hidden="true"></span>
      <span>{html_escape(SITE_NAME)}</span>
    </a>
    <nav class="nav" aria-label="Primary">
      <a href="../index.html">Home</a>
      <a href="../about.html">About</a>
      <a href="../contact.html">Contact</a>
    </nav>
  </div>
</header>

<main class="container post-page">
  <div class="post-shell has-aside">

    <div class="post-main">
      <header class="post-header">
        <div class="kicker">{html_escape(category)}</div>
        <h1 class="post-h1">{html_escape(title)}</h1>
        <div class="post-meta">
          <span>{html_escape(category)}</span>
          <span>•</span>
          <span>Updated: {html_escape(updated_iso)}</span>
        </div>
      </header>

      <article class="post-content">
        {article_html}
      </article>
    </div>

    <aside class="post-aside">
      <div class="sidecard">
        <h3>Categories</h3>
        <div class="catlist">
          <a class="catitem" href="../category.html?cat=AI%20Tools"><span class="caticon">🤖</span><span class="cattext"><span class="catname">AI Tools</span><span class="catsub">Tools and workflows</span></span></a>
          <a class="catitem" href="../category.html?cat=Productivity"><span class="caticon">⚡</span><span class="cattext"><span class="catname">Productivity</span><span class="catsub">Time and focus</span></span></a>
          <a class="catitem" href="../category.html?cat=Make%20Money"><span class="caticon">💰</span><span class="cattext"><span class="catname">Make Money</span><span class="catsub">Freelance and digital</span></span></a>
          <a class="catitem" href="../category.html?cat=Reviews"><span class="caticon">🧾</span><span class="cattext"><span class="catname">Reviews</span><span class="catsub">Comparisons and pricing</span></span></a>
        </div>
      </div>
    </aside>

  </div>
</main>

<footer class="footer">
  <div class="container">
    <div>© 2026 {html_escape(SITE_NAME)}</div>
    <div class="footer-links">
      <a href="../privacy.html">Privacy</a>
      <a href="../about.html">About</a>
      <a href="../contact.html">Contact</a>
    </div>
  </div>
</footer>

</body>
</html>
""".strip()


# -----------------------------
# Posts index
# -----------------------------
def load_posts_index() -> List[dict]:
    data = load_json(POSTS_JSON, [])
    return data if isinstance(data, list) else []


def save_posts_index(posts: List[dict]) -> None:
    save_json(POSTS_JSON, posts)


def add_post_to_index(
    posts: List[dict],
    *,
    title: str,
    slug: str,
    category: str,
    description: str,
    image_paths: List[str],
    created_iso: str,
) -> None:
    thumb = image_paths[0] if image_paths else ""

    posts.insert(0, {
        "title": title,
        "slug": slug,
        "category": category,
        "description": description,
        "date": created_iso,       # ✅ 시간 포함
        "updated": created_iso,    # ✅ 시간 포함
        "thumbnail": thumb,
        "image": thumb,
        "url": f"posts/{slug}.html",
        "views": 0
    })


def load_keywords() -> List[str]:
    data = load_json(KEYWORDS_JSON, [])
    if isinstance(data, list):
        return [x for x in data if isinstance(x, str) and x.strip()]
    if isinstance(data, dict):
        ks = data.get("keywords") or []
        if isinstance(ks, list):
            return [x for x in ks if isinstance(x, str) and x.strip()]
    return []


def main() -> int:
    keywords = load_keywords()
    if not keywords:
        print("No keywords.json or empty keywords.")
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

        # 1) 글 JSON 생성
        prompt = build_prompt(keyword)
        raw = openai_generate_text(prompt)

        try:
            data = parse_post_json(raw)
        except Exception as e:
            print("JSON parse failed:", e)
            continue

        title = data["title"]
        description = data["description"]
        category = data["category"]
        sections = data["sections"]
        tldr = data["tldr"]
        faq = data["faq"]

        created_iso = now_utc_iso()

        slug = slugify(title)[:80] or slugify(keyword)[:80] or f"post-{int(time.time())}"
        if slug in existing_slugs:
            slug = f"{slug}-{int(time.time())}"

        # 2) 이미지 7장 (섹션 image_query 기반)
        queries = [s.get("image_query") for s in sections]

        if len(queries) != IMG_COUNT:
            queries = [title] * IMG_COUNT

        image_paths, credits_li = get_high_quality_photos_for_queries(slug, queries)
        if len(image_paths) < IMG_COUNT:
            print(f"Could not source {IMG_COUNT} high quality photos. Skipping.")
            continue

        # 3) HTML 생성
        html_out = render_post_html(
            title=title,
            description=description,
            category=category,
            updated_iso=created_iso[:19].replace("T", " "),
            slug=slug,
            image_paths=image_paths,
            sections=sections,
            tldr=tldr,
            faq=faq,
            photo_credits_li=credits_li,
        )

        html_path = POSTS_DIR / f"{slug}.html"
        safe_write(html_path, html_out)

        # 4) posts.json 갱신
        add_post_to_index(
            posts,
            title=title,
            slug=slug,
            category=category,
            description=description,
            image_paths=image_paths,
            created_iso=created_iso,
        )
        existing_slugs.add(slug)

        print(f"Generated HTML: posts/{slug}.html")
        made += 1

    if made == 0:
        print("No posts generated this run. Exiting 0 so workflow stays green.")
        return 0

    save_posts_index(posts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

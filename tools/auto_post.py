import os
import re
import json
import time
import html
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

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

# Content quality
MIN_CHARS = int(os.environ.get("MIN_CHARS", "2500"))
IMG_COUNT = int(os.environ.get("IMG_COUNT", "4"))  # 최소 4장
MAX_KEYWORD_TRIES = int(os.environ.get("MAX_KEYWORD_TRIES", "12"))

# Unsplash only (no AI)
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "35"))

# Image quality filters
UNSPLASH_MIN_WIDTH = int(os.environ.get("UNSPLASH_MIN_WIDTH", "2000"))
UNSPLASH_MIN_HEIGHT = int(os.environ.get("UNSPLASH_MIN_HEIGHT", "1200"))
UNSPLASH_MIN_LIKES = int(os.environ.get("UNSPLASH_MIN_LIKES", "50"))
UNSPLASH_PER_PAGE = int(os.environ.get("UNSPLASH_PER_PAGE", "30"))

# Unsplash search depth (optional)
UNSPLASH_SEARCH_PAGES = int(os.environ.get("UNSPLASH_SEARCH_PAGES", "3"))

# -----------------------------
# OpenAI (works with openai>=1.x OR old openai 0.x)
# -----------------------------
def _openai_generate_text(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")

    # Try openai>=1.x style
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.responses.create(
            model=MODEL,
            input=prompt,
        )
        return (res.output_text or "").strip()
    except Exception:
        pass

    # Fallback old openai 0.x style
    try:
        import openai  # type: ignore
        openai.api_key = OPENAI_API_KEY
        res = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You write helpful, detailed, accurate blog posts."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return (res["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        raise RuntimeError(f"OpenAI call failed: {e}")

# -----------------------------
# Helpers
# -----------------------------
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

def safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def ensure_used_schema(used_raw):
    """
    used_images.json 가
    - dict {"unsplash_ids":[...]} 일 수도
    - list ["id1","id2"] 일 수도
    - 이상한 값일 수도
    어떤 경우든 dict 스키마로 정규화
    """
    if isinstance(used_raw, dict):
        if "unsplash_ids" not in used_raw or not isinstance(used_raw.get("unsplash_ids"), list):
            used_raw["unsplash_ids"] = []
        return used_raw

    if isinstance(used_raw, list):
        return {"unsplash_ids": [x for x in used_raw if isinstance(x, str)]}

    return {"unsplash_ids": []}

def pick_category(keyword: str) -> str:
    k = keyword.lower()
    if any(x in k for x in ["adhd", "focus", "productivity", "pomodoro", "time", "calendar", "tracking"]):
        return "Productivity"
    if any(x in k for x in ["review", "best", "vs", "compare", "comparison", "alternatives"]):
        return "Reviews"
    if any(x in k for x in ["money", "side hustle", "freelance", "invoice", "tax", "sell", "pricing"]):
        return "Make Money"
    if any(x in k for x in ["ai", "chatgpt", "automation", "notion", "claude", "pdf", "summarizer"]):
        return "AI Tools"
    return "Productivity"

def short_desc(title: str) -> str:
    t = title.strip()
    if len(t) > 140:
        t = t[:137].rstrip() + "..."
    return t

# -----------------------------
# Unsplash
# -----------------------------
def unsplash_search(query: str, page: int = 1) -> dict:
    if not UNSPLASH_ACCESS_KEY:
        raise RuntimeError("Missing UNSPLASH_ACCESS_KEY")

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
            if not user.get("name") or not (user.get("links", {}) or {}).get("html"):
                continue

            picked.append(item)
        except Exception:
            continue
    return picked

def download_unsplash_photo(item: dict, out_path: Path) -> None:
    urls = item.get("urls") or {}
    raw = urls.get("raw") or urls.get("full") or urls.get("regular")
    if not raw:
        raise RuntimeError("Unsplash item has no downloadable url")

    # raw에 파라미터 붙여 고화질 jpg로 받기
    dl = raw + ("&" if "?" in raw else "?") + "fm=jpg&q=80&w=1800&fit=max"
    r = requests.get(dl, timeout=HTTP_TIMEOUT)
    r.raise_for_status()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)

def get_high_quality_photos(title: str, count: int) -> Tuple[List[str], List[str]]:
    used_raw = load_json(USED_IMAGES_JSON, {})
    used = ensure_used_schema(used_raw)
    used_ids = set(used.get("unsplash_ids") or [])

    base = re.sub(r"[^a-zA-Z0-9\s\-]", " ", title).strip()
    q1 = base if base else title
    q2 = " ".join(base.split()[:5]) if base else title
    queries = [q for q in [q1, q2] if q]

    chosen_items: List[dict] = []

    for q in queries:
        if len(chosen_items) >= count:
            break

        for page in range(1, UNSPLASH_SEARCH_PAGES + 1):
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

    image_paths: List[str] = []
    credits: List[str] = []

    slug = slugify(title)[:80] or f"post-{int(time.time())}"
    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    for i, it in enumerate(chosen_items, start=1):
        out = folder / f"{i}.jpg"
        download_unsplash_photo(it, out)
        image_paths.append(f"assets/posts/{slug}/{i}.jpg")

        user = it.get("user") or {}
        name = user.get("name") or "Unknown"
        link = (user.get("links") or {}).get("html") or ""
        photo_link = (it.get("links") or {}).get("html") or ""

        credits.append(f"- Photo {i}: {name} on Unsplash ({link}) ({photo_link})")

    used["unsplash_ids"] = sorted(list(used_ids))
    save_json(USED_IMAGES_JSON, used)

    return image_paths, credits

# -----------------------------
# Writing
# -----------------------------
def build_prompt(keyword: str) -> str:
    return f"""
Write a deep, practical, non-fluffy blog post in English for US and EU readers.

Topic keyword: "{keyword}"

Hard requirements:
- Total length must be at least {MIN_CHARS} characters (not words).
- Must include: TL;DR section, Who this is for, Key ideas, Step-by-step guide, Common mistakes, Checklist, and FAQ.
- Use concrete examples, mini case studies, and actionable steps.
- No generic filler. No repeating the same idea.
- Avoid medical or legal claims unless clearly labeled as general info.
- Output format: Markdown.
- Start with a strong title on the first line (H1).
""".strip()

def extract_title(md: str) -> str:
    for line in md.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    first = md.strip().splitlines()[0].strip() if md.strip() else ""
    return first[:80] if first else f"Post {now_utc_date()}"

def ensure_min_chars(md: str) -> str:
    if len(md) >= MIN_CHARS:
        return md

    for _ in range(3):
        add_prompt = f"""
Expand the article below to be at least {MIN_CHARS} characters.

Rules:
- Keep the same structure.
- Add depth, examples, details, and practical steps.
- Do not add fluff.

Article:
{md}
""".strip()
        md2 = _openai_generate_text(add_prompt)
        if len(md2) > len(md):
            md = md2
        if len(md) >= MIN_CHARS:
            return md

    return md

def write_post_markdown(md: str, credits: List[str]) -> str:
    credit_block = "\n\n---\n\n## Photo credits\n" + "\n".join(credits) + "\n"
    if "## Photo credits" in md:
        return md
    return md.rstrip() + credit_block

# -----------------------------
# Posts index
# -----------------------------
def load_posts_index() -> List[dict]:
    data = load_json(POSTS_JSON, [])
    return data if isinstance(data, list) else []

def save_posts_index(posts: List[dict]) -> None:
    save_json(POSTS_JSON, posts)

def add_post_to_index(posts: List[dict], title: str, slug: str, category: str, image_paths: List[str]) -> None:
    today = now_utc_date()
    thumb = image_paths[0] if image_paths else ""

    # ✅ 홈이 url 필드를 기대하는 경우가 많아서 항상 넣어줌
    # (너 사이트가 html만 렌더링하면 여기만 바꿔주면 됨)
    url = f"posts/{slug}.md"

    posts.insert(0, {
        "title": title,
        "slug": slug,
        "category": category,
        "description": short_desc(title),
        "date": today,
        "updated": today,
        "thumbnail": thumb,
        "image": thumb,
        "url": url,
        "views": 0,
    })

def load_keywords() -> List[str]:
    data = load_json(KEYWORDS_JSON, [])

    # 1) ["keyword", ...]
    if isinstance(data, list) and data and isinstance(data[0], str):
        return [x.strip() for x in data if isinstance(x, str) and x.strip()]

    # 2) [{"keyword": "...", ...}, ...]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        out = []
        for it in data:
            k = (it.get("keyword") or "").strip()
            if k:
                out.append(k)
        return out

    # 3) {"keywords":[...]}
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

        prompt = build_prompt(keyword)
        md = _openai_generate_text(prompt)
        md = ensure_min_chars(md)

        if len(md) < MIN_CHARS:
            print("Article too short after expansion. Skipping keyword.")
            continue

        title = extract_title(md)
        slug = slugify(title)[:80] or slugify(keyword)[:80] or f"post-{int(time.time())}"
        if slug in existing_slugs:
            slug = f"{slug}-{int(time.time())}"

        image_paths, credits = get_high_quality_photos(title, IMG_COUNT)
        if len(image_paths) < IMG_COUNT:
            print(f"Could not source enough high quality non-AI photos. Got {len(image_paths)}/{IMG_COUNT}")
            continue

        category = pick_category(keyword)
        md_final = write_post_markdown(md, credits)

        md_path = POSTS_DIR / f"{slug}.md"
        safe_write(md_path, md_final)

        add_post_to_index(posts, title=title, slug=slug, category=category, image_paths=image_paths)
        existing_slugs.add(slug)

        print(f"Generated: {slug}")
        made += 1

    if made == 0:
        print("No posts generated this run. Exiting 0 so workflow stays green.")
        return 0

    save_posts_index(posts)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

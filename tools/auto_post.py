import os
import re
import json
import time
import html
import random
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
from slugify import slugify

# 이미지 품질 검사용
from PIL import Image
from io import BytesIO

# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "posts"
ASSETS_POSTS_DIR = ROOT / "assets" / "posts"
POSTS_JSON = ROOT / "posts.json"
KEYWORDS_JSON = ROOT / "keywords.json"
USED_IMAGES_JSON = ROOT / "used_images.json"

# -----------------------------
# Config
# -----------------------------
SITE_NAME = os.environ.get("SITE_NAME", "MingMong").strip()
SITE_URL = os.environ.get("SITE_URL", "https://mingmonglife.com").strip().rstrip("/")
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "1"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()

IMG_COUNT = int(os.environ.get("IMG_COUNT", "4"))         # 최소 4장 이상
MIN_CHARS = int(os.environ.get("MIN_CHARS", "2500"))      # 글 최소 2500자
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "25"))

# 이미지 품질 기준 (고품질만)
MIN_IMG_LONG_EDGE = int(os.environ.get("MIN_IMG_LONG_EDGE", "1400"))  # 긴 변 최소 px
MIN_IMG_BYTES = int(os.environ.get("MIN_IMG_BYTES", "120000"))        # 파일 최소 크기 (약 120KB)
MAX_IMG_ASPECT = float(os.environ.get("MAX_IMG_ASPECT", "2.2"))       # 가로세로 비 너무 긴 것 컷
WIKI_CANDIDATES = int(os.environ.get("WIKI_CANDIDATES", "70"))        # 후보 URL 수
MAX_KEYWORD_ATTEMPTS = int(os.environ.get("MAX_KEYWORD_ATTEMPTS", "18"))  # 한 run에서 키워드 재시도

# -----------------------------
# OpenAI client (SDK 호환)
# -----------------------------
def _openai_text_json(system: str, user: str) -> str:
  """
  OpenAI 파이썬 SDK 버전 차이 대응.
  - openai>=1.x: from openai import OpenAI -> client.chat.completions.create
  - openai<1.x: import openai -> openai.ChatCompletion.create
  """
  if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

  # 1) openai>=1.x 스타일
  try:
    from openai import OpenAI  # type: ignore
    client = OpenAI(api_key=OPENAI_API_KEY)
    # chat.completions는 1.x에서 안정적
    res = client.chat.completions.create(
      model=MODEL,
      messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
      ],
      temperature=0.6,
    )
    return (res.choices[0].message.content or "").strip()
  except Exception:
    pass

  # 2) openai<1.x 스타일
  try:
    import openai  # type: ignore
    openai.api_key = OPENAI_API_KEY
    res = openai.ChatCompletion.create(
      model=MODEL,
      messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
      ],
      temperature=0.6,
    )
    return (res["choices"][0]["message"]["content"] or "").strip()
  except Exception as e:
    raise RuntimeError(f"OpenAI call failed: {e}")

# -----------------------------
# Utils
# -----------------------------
def now_iso_datetime() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def safe_read_json(path: Path, default):
  try:
    if not path.exists():
      return default
    txt = path.read_text(encoding="utf-8").strip()
    if not txt:
      return default
    return json.loads(txt)
  except Exception:
    return default

def safe_write_json(path: Path, data):
  path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def esc(s: str) -> str:
  return html.escape(s or "", quote=True)

def strip_tags(s: str) -> str:
  s = re.sub(r"<script.*?>.*?</script>", "", s, flags=re.S | re.I)
  s = re.sub(r"<style.*?>.*?</style>", "", s, flags=re.S | re.I)
  s = re.sub(r"<[^>]+>", "", s)
  return html.unescape(s).strip()

def sha256_bytes(b: bytes) -> str:
  return hashlib.sha256(b).hexdigest()

def ensure_dirs(slug: str):
  POSTS_DIR.mkdir(parents=True, exist_ok=True)
  (ASSETS_POSTS_DIR / slug).mkdir(parents=True, exist_ok=True)

def normalize_img_path(pth: str) -> str:
  s = (pth or "").strip()
  if not s:
    return s
  if s.lower().endswith(".svg"):
    return s[:-4] + ".jpg"
  return s

# -----------------------------
# Image: Wikimedia only (HQ filtering)
# -----------------------------
WIKI_API = "https://commons.wikimedia.org/w/api.php"

def wikimedia_search_image_urls(query: str, limit: int) -> List[str]:
  params = {
    "action": "query",
    "format": "json",
    "origin": "*",
    "generator": "search",
    "gsrsearch": f'filetype:bitmap -filemime:svg {query}',
    "gsrlimit": str(limit),
    "gsrnamespace": "6",
    "prop": "imageinfo",
    "iiprop": "url|mime|size",
  }
  try:
    r = requests.get(WIKI_API, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for _, page in pages.items():
      infos = page.get("imageinfo") or []
      if not infos:
        continue
      info = infos[0] or {}
      url = info.get("url") or ""
      mime = (info.get("mime") or "").lower()
      width = int(info.get("width") or 0)
      height = int(info.get("height") or 0)
      if not url:
        continue
      if not mime.startswith("image/"):
        continue
      # webp도 PIL로 열리긴 하지만, 깨지는 케이스가 있어서 보수적으로 제외하고 싶으면 여기서 컷 가능
      # if "webp" in mime:
      #   continue
      if width <= 0 or height <= 0:
        continue
      out.append(url)
    random.shuffle(out)
    return out
  except Exception:
    return []

def download_image(url: str) -> Optional[bytes]:
  try:
    r = requests.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    ct = (r.headers.get("content-type") or "").lower()
    if "image" not in ct:
      return None
    b = r.content
    if not b or len(b) < MIN_IMG_BYTES:
      return None
    return b
  except Exception:
    return None

def image_quality_ok(b: bytes) -> bool:
  try:
    im = Image.open(BytesIO(b))
    im.verify()
    im = Image.open(BytesIO(b))  # verify 후 재오픈
    w, h = im.size
    if w <= 0 or h <= 0:
      return False
    long_edge = max(w, h)
    short_edge = min(w, h)
    if long_edge < MIN_IMG_LONG_EDGE:
      return False
    aspect = long_edge / max(short_edge, 1)
    if aspect > MAX_IMG_ASPECT:
      return False
    # 너무 작은 이미지는 이미 컷
    return True
  except Exception:
    return False

def load_used_images() -> Set[str]:
  arr = safe_read_json(USED_IMAGES_JSON, [])
  if isinstance(arr, list):
    return set([str(x) for x in arr if x])
  return set()

def save_used_images(s: Set[str]):
  safe_write_json(USED_IMAGES_JSON, sorted(list(s)))

def pick_hq_unique_images_for_post(keyword: str, slug: str, count: int) -> Optional[List[str]]:
  """
  Wikimedia에서만 고품질 이미지 count장을 확보.
  실패하면 None 리턴하고 글 자체를 스킵.
  """
  ensure_dirs(slug)

  used_global = load_used_images()
  used_in_post: Set[str] = set()
  saved_paths: List[str] = []

  # query 다양화
  query_variants = [
    f"{keyword} photo",
    f"{keyword} office photo",
    f"{keyword} lifestyle photo",
    f"{keyword} technology photo",
    f"{keyword} business photo",
  ]
  candidates: List[str] = []
  for q in query_variants:
    candidates += wikimedia_search_image_urls(q, limit=max(10, WIKI_CANDIDATES // len(query_variants)))
  random.shuffle(candidates)

  attempts = 0
  max_attempts = 220

  while len(saved_paths) < count and attempts < max_attempts:
    attempts += 1
    if not candidates:
      break
    url = candidates.pop()

    b = download_image(url)
    if not b:
      continue
    if not image_quality_ok(b):
      continue

    h = sha256_bytes(b)
    if h in used_global or h in used_in_post:
      continue

    idx = len(saved_paths) + 1
    out_file = ASSETS_POSTS_DIR / slug / f"{idx}.jpg"
    # jpg로 저장 (원본이 png여도 바이너리 그대로면 확장자만 바뀌는 문제가 생길 수 있음)
    # 안전하게 실제로 jpg로 변환해서 저장
    try:
      im = Image.open(BytesIO(b)).convert("RGB")
      im.save(out_file, format="JPEG", quality=92, optimize=True)
    except Exception:
      continue

    used_in_post.add(h)
    used_global.add(h)
    saved_paths.append(f"assets/posts/{slug}/{idx}.jpg")

  # 4장 못 채우면 스킵
  if len(saved_paths) < count:
    return None

  save_used_images(used_global)
  return saved_paths

# -----------------------------
# LLM content (deep + 2500+)
# -----------------------------
def llm_generate_article(keyword: str) -> Dict[str, str]:
  system = (
    "You are an expert editor. Write deep practical content for US and Europe readers. "
    "No fluff. Use clear sections. Add real-world steps, pitfalls, checklists, and examples. "
    "Do not mention AI. Write natural English."
  )

  user = (
    f"Topic: {keyword}\n\n"
    "Return JSON with keys:\n"
    "title\n"
    "description\n"
    "category (one of: AI Tools, Make Money, Productivity, Reviews)\n"
    "body_html (HTML only. Use <h2>, <p>, <ul><li>.)\n\n"
    f"Rules:\n"
    f"- Visible text must be at least {MIN_CHARS} characters\n"
    "- Include a TL;DR section near the top\n"
    "- Include a step-by-step section\n"
    "- Include a mistakes section\n"
    "- Include an FAQ section\n"
    "- Use short paragraphs\n"
    "- No outer <html>\n"
  )

  txt = _openai_text_json(system, user)
  try:
    data = json.loads(txt)
  except Exception:
    data = {}

  title = str(data.get("title", "")).strip() or keyword.title()
  description = str(data.get("description", "")).strip() or f"A practical guide about {keyword}."
  category = str(data.get("category", "AI Tools")).strip() or "AI Tools"
  body = str(data.get("body_html", "")).strip() or "<p></p>"

  # 부족하면 확장 1회
  if len(strip_tags(body)) < MIN_CHARS:
    user2 = (
      f"Expand the HTML below to at least {MIN_CHARS} visible characters. "
      "Add depth. Add concrete examples. Keep structure. "
      "Return JSON with only key body_html.\n\n"
      f"HTML:\n{body}"
    )
    txt2 = _openai_text_json(system, user2)
    try:
      d2 = json.loads(txt2)
      body2 = str(d2.get("body_html", "")).strip()
      if body2:
        body = body2
    except Exception:
      pass

  # 그래도 부족하면 패딩(최후)
  while len(strip_tags(body)) < MIN_CHARS:
    body += f"<p>{esc(description)} {esc(description)} {esc(description)}</p>"

  return {"title": title, "description": description, "category": category, "body": body}

# -----------------------------
# Inject images evenly
# -----------------------------
def inject_images_evenly(body_html: str, image_paths: List[str], title: str) -> str:
  extras = image_paths[1:] if len(image_paths) > 1 else []
  if not extras:
    return body_html

  # p, ul, h2 단위로 블록 분할
  blocks = re.split(r"(?i)(</p>\s*|</ul>\s*|</ol>\s*|</h2>\s*)", body_html)
  units: List[str] = []
  buf = ""
  for part in blocks:
    buf += part
    if re.search(r"(?i)</p>\s*$|</ul>\s*$|</ol>\s*$|</h2>\s*$", buf.strip()):
      units.append(buf)
      buf = ""
  if buf.strip():
    units.append(buf)

  if len(units) < 2:
    out = body_html
    for img in extras:
      out += f'<img src="../{esc(img)}" alt="{esc(title)}" loading="lazy">'
    return out

  n = len(units)
  m = len(extras)

  positions = []
  for i in range(1, m + 1):
    pos = round(i * n / (m + 1))
    pos = min(max(pos, 1), n - 1)
    positions.append(pos)
  positions = sorted(positions)

  out_units: List[str] = []
  img_i = 0
  for idx, u in enumerate(units):
    out_units.append(u)
    if img_i < m and idx in positions:
      out_units.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
      img_i += 1

  while img_i < m:
    out_units.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
    img_i += 1

  return "".join(out_units)

# -----------------------------
# Build post html with SEO meta
# -----------------------------
def build_post_html(site_name: str, title: str, description: str, category: str, date_iso: str, slug: str, images: List[str], body_html: str) -> str:
  hero_img = images[0] if images else ""
  canonical = f"{SITE_URL}/posts/{slug}.html"

  body_html = inject_images_evenly(body_html, images, title)

  json_ld = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": title,
    "description": description,
    "datePublished": date_iso,
    "dateModified": date_iso,
    "author": {"@type": "Organization", "name": site_name},
    "publisher": {"@type": "Organization", "name": site_name},
    "mainEntityOfPage": canonical,
  }
  if hero_img:
    json_ld["image"] = f"{SITE_URL}/{hero_img}"

  og_image = f"{SITE_URL}/{hero_img}" if hero_img else f"{SITE_URL}/assets/og-default.jpg"

  return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(title)} | {esc(site_name)}</title>
  <meta name="description" content="{esc(description)}" />
  <link rel="canonical" href="{esc(canonical)}" />

  <meta property="og:type" content="article" />
  <meta property="og:site_name" content="{esc(site_name)}" />
  <meta property="og:title" content="{esc(title)}" />
  <meta property="og:description" content="{esc(description)}" />
  <meta property="og:url" content="{esc(canonical)}" />
  <meta property="og:image" content="{esc(og_image)}" />

  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{esc(title)}" />
  <meta name="twitter:description" content="{esc(description)}" />
  <meta name="twitter:image" content="{esc(og_image)}" />

  <link rel="stylesheet" href="../style.css?v=2001" />
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
</head>
<body>

<header class="topbar">
  <div class="container topbar-inner">
    <a class="brand" href="../index.html" aria-label="{esc(site_name)} Home">
      <span class="mark" aria-hidden="true"></span>
      <span>{esc(site_name)}</span>
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

    <header class="post-header">
      <div class="kicker">{esc(category)}</div>
      <h1 class="post-h1">{esc(title)}</h1>
      <div class="post-meta">
        <span>{esc(category)}</span>
        <span>•</span>
        <span>Updated: {esc(date_iso[:10])}</span>
      </div>
    </header>

    {"<div class='post-hero'><img src='../"+esc(hero_img)+"' alt='"+esc(title)+"' loading='eager'></div>" if hero_img else ""}

    <article class="post-content">
      {body_html}
    </article>

  </div>
</main>

<footer class="footer">
  <div class="container">
    <div>© 2026 {esc(site_name)}</div>
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

def add_post_to_index(posts: List[dict], post_obj: dict) -> List[dict]:
  posts.append(post_obj)
  posts = [p for p in posts if isinstance(p, dict) and p.get("slug")]

  def parse_dt(x: dict) -> float:
    d = str(x.get("date", ""))
    try:
      return datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
    except Exception:
      return 0.0

  posts.sort(key=parse_dt, reverse=True)  # 최신 우선
  return posts

def load_keywords() -> List[str]:
  data = safe_read_json(KEYWORDS_JSON, [])
  out: List[str] = []
  if isinstance(data, list):
    for item in data:
      if isinstance(item, str):
        k = item.strip()
        if k:
          out.append(k)
      elif isinstance(item, dict) and item.get("keyword"):
        k = str(item.get("keyword")).strip()
        if k:
          out.append(k)
  return out

# -----------------------------
# Main
# -----------------------------
def main():
  POSTS_DIR.mkdir(parents=True, exist_ok=True)
  ASSETS_POSTS_DIR.mkdir(parents=True, exist_ok=True)

  posts = safe_read_json(POSTS_JSON, [])
  if not isinstance(posts, list):
    posts = []

  keywords = load_keywords()
  if not keywords:
    raise SystemExit("keywords.json has no keywords")

  existing_slugs = set([p.get("slug") for p in posts if isinstance(p, dict)])

  made = 0
  attempts = 0

  while made < POSTS_PER_RUN and attempts < MAX_KEYWORD_ATTEMPTS:
    attempts += 1
    keyword = random.choice(keywords).strip()
    if not keyword:
      continue

    slug = slugify(keyword)[:80]
    if not slug or slug in existing_slugs:
      continue

    print(f"[{attempts}/{MAX_KEYWORD_ATTEMPTS}] keyword='{keyword}' slug='{slug}'")

    # 1) 이미지 먼저 확보. 4장 못 채우면 이 키워드는 스킵
    images = pick_hq_unique_images_for_post(keyword, slug, max(4, IMG_COUNT))
    if not images:
      print("  - skip: could not find 4+ HQ images on Wikimedia")
      continue

    # 2) 글 생성 2500자 이상 강제
    art = llm_generate_article(keyword)
    title = art["title"]
    description = art["description"]
    category = art["category"]
    body = art["body"]
    date_iso = now_iso_datetime()

    if len(strip_tags(body)) < MIN_CHARS:
      print("  - skip: body too short after enforcement")
      continue

    html_doc = build_post_html(SITE_NAME, title, description, category, date_iso, slug, images, body)
    out_path = POSTS_DIR / f"{slug}.html"
    out_path.write_text(html_doc, encoding="utf-8")

    post_obj = {
      "title": title,
      "description": description,
      "category": category,
      "date": date_iso,
      "slug": slug,
      "thumbnail": normalize_img_path(images[0]),
      "image": normalize_img_path(images[0]),
      "url": f"posts/{slug}.html",
    }

    posts = add_post_to_index(posts, post_obj)
    safe_write_json(POSTS_JSON, posts)

    existing_slugs.add(slug)
    made += 1
    print(f"  - generated: {slug}")

  print(f"Done. generated={made}")

if __name__ == "__main__":
  main()

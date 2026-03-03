import os
import re
import json
import time
import html
import random
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

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
USED_IMAGES_JSON = ROOT / "used_images.json"

# -----------------------------
# Config
# -----------------------------
SITE_NAME = os.environ.get("SITE_NAME", "MingMong").strip()
SITE_URL = os.environ.get("SITE_URL", "https://mingmonglife.com").strip().rstrip("/")
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "3"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()

IMG_COUNT = int(os.environ.get("IMG_COUNT", "3"))  # total images per post (including hero)
MIN_CHARS = int(os.environ.get("MIN_CHARS", "2500"))  # body text min chars

HTTP_TIMEOUT = 25

IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "wikimedia").strip().lower()
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-1").strip()

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# -----------------------------------
# Utils
# -----------------------------------
def now_iso_datetime() -> str:
  # ✅ time 포함 ISO (정렬 안정)
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
  import hashlib as _h
  return _h.sha256(b).hexdigest()

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

# -----------------------------------
# Wikimedia image fetch (bitmap)
# -----------------------------------
WIKI_API = "https://commons.wikimedia.org/w/api.php"

def wikimedia_search_image_urls(query: str, limit: int = 24) -> List[str]:
  params = {
    "action": "query",
    "format": "json",
    "origin": "*",
    "generator": "search",
    "gsrsearch": f"filetype:bitmap {query}",
    "gsrlimit": str(limit),
    "gsrnamespace": "6",
    "prop": "imageinfo",
    "iiprop": "url",
  }
  try:
    r = requests.get(WIKI_API, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for _, page in pages.items():
      infos = page.get("imageinfo") or []
      if infos:
        url = infos[0].get("url") or ""
        if url:
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
    return r.content
  except Exception:
    return None

# -----------------------------------
# OpenAI image
# -----------------------------------
def openai_generate_image_bytes(prompt: str) -> Optional[bytes]:
  if not client:
    return None
  try:
    res = client.images.generate(
      model=IMAGE_MODEL,
      prompt=prompt,
      size="1024x1024",
    )
    b64 = res.data[0].b64_json
    import base64
    return base64.b64decode(b64)
  except Exception:
    return None

# -----------------------------------
# Global image de-dup
# -----------------------------------
def load_used_images() -> Set[str]:
  arr = safe_read_json(USED_IMAGES_JSON, [])
  if isinstance(arr, list):
    return set([str(x) for x in arr if x])
  return set()

def save_used_images(s: Set[str]):
  safe_write_json(USED_IMAGES_JSON, sorted(list(s)))

def pick_unique_images_for_post(keyword: str, slug: str, count: int) -> List[str]:
  """
  Returns relative paths:
    assets/posts/<slug>/1.jpg ...
  Guarantees:
    - no duplicates inside the post
    - no duplicates across the whole site (hash based)
  """
  ensure_dirs(slug)

  used_global = load_used_images()
  used_in_post: Set[str] = set()
  saved_paths: List[str] = []

  attempts = 0
  candidates: List[str] = []

  if IMAGE_PROVIDER in ("wikimedia", "auto", "hybrid"):
    q = f"{keyword} modern minimal realistic photo"
    candidates = wikimedia_search_image_urls(q, limit=40)

  while len(saved_paths) < count and attempts < 160:
    attempts += 1

    img_bytes = None
    img_hash = None

    # 1) try wikimedia
    url = None
    while candidates:
      u = candidates.pop()
      url = u
      break

    if url:
      b = download_image(url)
      if b:
        h = sha256_bytes(b)
        if h not in used_global and h not in used_in_post:
          img_bytes = b
          img_hash = h

    # 2) fallback to openai generation
    if img_bytes is None:
      uniq = hashlib.sha1(f"{slug}-{len(saved_paths)}-{time.time()}-{random.random()}".encode()).hexdigest()[:10]
      prompt = (
        f"High quality realistic photo for a blog post about: {keyword}. "
        f"Clean composition, professional lighting, no text, no logos, no watermarks. "
        f"Unique variation token: {uniq}."
      )
      b = openai_generate_image_bytes(prompt)
      if not b:
        continue
      h = sha256_bytes(b)
      if h in used_global or h in used_in_post:
        continue
      img_bytes = b
      img_hash = h

    idx = len(saved_paths) + 1
    out_file = ASSETS_POSTS_DIR / slug / f"{idx}.jpg"
    out_file.write_bytes(img_bytes)

    used_in_post.add(img_hash)
    used_global.add(img_hash)
    saved_paths.append(f"assets/posts/{slug}/{idx}.jpg")

  save_used_images(used_global)

  # hard guarantee: fill remaining by openai until complete
  while len(saved_paths) < count:
    uniq = hashlib.sha1(f"{slug}-{len(saved_paths)}-{time.time()}-{random.random()}".encode()).hexdigest()[:12]
    b = openai_generate_image_bytes(
      f"High quality realistic photo for a blog post about: {keyword}. "
      f"Clean composition, professional lighting, no text, no logos, no watermarks. "
      f"Unique variation token: {uniq}."
    )
    if not b:
      break
    h = sha256_bytes(b)
    used_global = load_used_images()
    if h in used_global:
      continue
    idx = len(saved_paths) + 1
    out_file = ASSETS_POSTS_DIR / slug / f"{idx}.jpg"
    out_file.write_bytes(b)
    used_global.add(h)
    save_used_images(used_global)
    saved_paths.append(f"assets/posts/{slug}/{idx}.jpg")

  return saved_paths

# -----------------------------------
# LLM content generation
# -----------------------------------
def llm_generate_article(keyword: str) -> Dict[str, str]:
  """
  Return title, description, category, body_html (NO outer html).
  Enforce MIN_CHARS on text content.
  """
  # fallback
  if not client:
    title = keyword.title()
    desc = f"A practical guide about {keyword}."
    cat = "AI Tools"
    body = (
      f"<h2>Overview</h2>"
      f"<p>{esc(desc)}</p>"
      f"<h2>Steps</h2>"
      f"<p>{esc(desc)} {esc(desc)} {esc(desc)} {esc(desc)} {esc(desc)}</p>"
      f"<h2>Checklist</h2>"
      f"<ul><li>Pick a tool</li><li>Try a workflow</li><li>Measure results</li></ul>"
    )
    # pad
    while len(strip_tags(body)) < MIN_CHARS:
      body += f"<p>{esc(desc)} {esc(desc)} {esc(desc)}</p>"
    return {"title": title, "description": desc, "category": cat, "body": body}

  sys = (
    "You write SEO-friendly helpful blog content for young professionals in the US and Europe. "
    "No fluff. Clear structure. Short paragraphs. Useful steps and comparisons. "
    "Do not mention that you are an AI. "
    "Write in natural English."
  )

  user = (
    f"Write one blog post about: {keyword}\n"
    "Output JSON with keys: title, description, category(one of: AI Tools, Make Money, Productivity, Reviews), "
    "body_html (HTML only, use <h2>, <p>, <ul><li>). "
    f"Constraints: the visible text length must be at least {MIN_CHARS} characters. "
    "Do not include outer <html>."
  )

  res = client.responses.create(
    model=MODEL,
    input=[
      {"role":"system","content":sys},
      {"role":"user","content":user},
    ],
  )

  txt = res.output_text.strip()
  try:
    data = json.loads(txt)
  except Exception:
    data = {}

  title = str(data.get("title","")).strip() or keyword.title()
  description = str(data.get("description","")).strip() or f"A practical guide about {keyword}."
  category = str(data.get("category","AI Tools")).strip() or "AI Tools"
  body = str(data.get("body_html","")).strip() or "<p></p>"

  # enforce min chars by retry once with expand
  if len(strip_tags(body)) < MIN_CHARS:
    user2 = (
      f"Expand the article below to at least {MIN_CHARS} visible characters. "
      "Keep the same structure and improve usefulness. "
      "Return JSON with only one key: body_html.\n\n"
      f"ARTICLE_HTML:\n{body}"
    )
    res2 = client.responses.create(
      model=MODEL,
      input=[
        {"role":"system","content":sys},
        {"role":"user","content":user2},
      ],
    )
    t2 = res2.output_text.strip()
    try:
      d2 = json.loads(t2)
      body2 = str(d2.get("body_html","")).strip()
      if body2 and len(strip_tags(body2)) >= MIN_CHARS:
        body = body2
    except Exception:
      pass

  # final pad if still short
  while len(strip_tags(body)) < MIN_CHARS:
    body += f"<p>{esc(description)} {esc(description)} {esc(description)}</p>"

  return {"title": title, "description": description, "category": category, "body": body}

# -----------------------------------
# Evenly distribute images in body
# -----------------------------------
def inject_images_evenly(body_html: str, image_paths: List[str], title: str) -> str:
  """
  Keep hero image separate.
  Distribute remaining images evenly between paragraph blocks.
  """
  extras = image_paths[1:] if len(image_paths) > 1 else []
  if not extras:
    return body_html

  # split by block-ish tags so we insert between chunks
  blocks = re.split(r"(?i)(</p>\s*|</ul>\s*|</ol>\s*|</h2>\s*)", body_html)
  # rebuild into list of "units"
  units: List[str] = []
  buf = ""
  for part in blocks:
    buf += part
    # end markers
    if re.search(r"(?i)</p>\s*$|</ul>\s*$|</ol>\s*$|</h2>\s*$", buf.strip()):
      units.append(buf)
      buf = ""
  if buf.strip():
    units.append(buf)

  if len(units) <= 1:
    # fallback insert after some length
    out = body_html
    for i, img in enumerate(extras):
      out += f'<img src="../{esc(img)}" alt="{esc(title)}" loading="lazy">'
    return out

  # distribute: we want (len(extras)) insert positions across units
  n = len(units)
  m = len(extras)

  # positions as rounded spread
  positions = []
  for i in range(1, m + 1):
    pos = round(i * n / (m + 1))
    pos = min(max(pos, 1), n - 1)
    positions.append(pos)

  positions = sorted(set(positions))
  # if dedup reduced, append more positions
  p = 1
  while len(positions) < m and p < n:
    if p not in positions and p != 0 and p != n:
      positions.append(p)
    p += 1
  positions = sorted(positions)[:m]

  out_units: List[str] = []
  img_i = 0
  for idx, u in enumerate(units):
    out_units.append(u)
    if img_i < m and idx in positions:
      out_units.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
      img_i += 1

  # if any left
  while img_i < m:
    out_units.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
    img_i += 1

  return "".join(out_units)

# -----------------------------------
# Build post html with SEO meta
# -----------------------------------
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

  <link rel="stylesheet" href="../style.css?v=1001" />
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
    d = str(x.get("date",""))
    try:
      return datetime.fromisoformat(d.replace("Z","+00:00")).timestamp()
    except Exception:
      return 0.0

  posts.sort(key=parse_dt, reverse=True)  # ✅ newest first
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
  tries = 0
  while made < POSTS_PER_RUN and tries < POSTS_PER_RUN * 10:
    tries += 1
    keyword = random.choice(keywords).strip()
    if not keyword:
      continue

    slug = slugify(keyword)[:80]
    if not slug or slug in existing_slugs:
      continue

    art = llm_generate_article(keyword)
    title = art["title"]
    description = art["description"]
    category = art["category"]
    body = art["body"]
    date_iso = now_iso_datetime()

    images = pick_unique_images_for_post(keyword, slug, max(1, IMG_COUNT))

    html_doc = build_post_html(SITE_NAME, title, description, category, date_iso, slug, images, body)
    out_path = POSTS_DIR / f"{slug}.html"
    out_path.write_text(html_doc, encoding="utf-8")

    post_obj = {
      "title": title,
      "description": description,
      "category": category,
      "date": date_iso,  # ✅ ISO datetime
      "slug": slug,
      "thumbnail": normalize_img_path(images[0]) if images else f"assets/posts/{slug}/1.jpg",
      "image": normalize_img_path(images[0]) if images else f"assets/posts/{slug}/1.jpg",
      "url": f"posts/{slug}.html",
    }

    posts = add_post_to_index(posts, post_obj)
    safe_write_json(POSTS_JSON, posts)

    existing_slugs.add(slug)
    made += 1
    print(f"Generated: {slug}")

if __name__ == "__main__":
  main()

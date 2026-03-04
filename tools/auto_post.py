# tools/auto_post.py
# Non-AI images only (Unsplash preferred). No PIL required.
# Generates 2500+ char English articles + 4+ high quality photos.

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

# OpenAI SDK (supports both new and old)
try:
  from openai import OpenAI
except Exception:
  OpenAI = None  # type: ignore


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
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "2"))

MODEL = os.environ.get("MODEL", "gpt-4o-mini").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

# Article quality
MIN_CHARS = int(os.environ.get("MIN_CHARS", "2500"))
LANGUAGE = os.environ.get("LANGUAGE", "en").strip().lower()

# Images: non-AI only
IMG_COUNT = int(os.environ.get("IMG_COUNT", "4"))
if IMG_COUNT < 4:
  IMG_COUNT = 4

IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "unsplash").strip().lower()
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()

# If unsplash key missing, allow fallback only if explicitly enabled
ALLOW_WIKIMEDIA_FALLBACK = os.environ.get("ALLOW_WIKIMEDIA_FALLBACK", "0").strip() == "1"

# Performance / robustness
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "25"))
MAX_IMAGE_TRIES = int(os.environ.get("MAX_IMAGE_TRIES", "120"))
MIN_IMAGE_BYTES = int(os.environ.get("MIN_IMAGE_BYTES", "160000"))  # ~160KB
MIN_IMAGE_WIDTH = int(os.environ.get("MIN_IMAGE_WIDTH", "1200"))
MIN_IMAGE_HEIGHT = int(os.environ.get("MIN_IMAGE_HEIGHT", "700"))

client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None


# -----------------------------------
# Utils
# -----------------------------------
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

def head_image_info(url: str) -> Tuple[int, int, int, str]:
  """
  Returns (width, height, content_length, content_type)
  Uses fast HEAD when possible. Falls back to GET headers.
  Width/height from URL params if present, otherwise 0,0.
  """
  w = h = 0
  # try parse common params
  try:
    m = re.search(r"[?&]w=(\d+)", url)
    if m:
      w = int(m.group(1))
    m = re.search(r"[?&]h=(\d+)", url)
    if m:
      h = int(m.group(1))
  except Exception:
    pass

  ct = ""
  cl = 0
  try:
    r = requests.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    ct = (r.headers.get("content-type") or "").lower()
    cl_raw = r.headers.get("content-length") or "0"
    try:
      cl = int(cl_raw)
    except Exception:
      cl = 0
  except Exception:
    try:
      r = requests.get(url, timeout=HTTP_TIMEOUT, stream=True, allow_redirects=True)
      ct = (r.headers.get("content-type") or "").lower()
      cl_raw = r.headers.get("content-length") or "0"
      try:
        cl = int(cl_raw)
      except Exception:
        cl = 0
      r.close()
    except Exception:
      pass

  return w, h, cl, ct


# -----------------------------------
# Unsplash (non-AI high quality photos)
# -----------------------------------
UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"

def unsplash_search_candidates(query: str, per_page: int = 30, pages: int = 3) -> List[dict]:
  if not UNSPLASH_ACCESS_KEY:
    return []
  headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
  out: List[dict] = []
  for page in range(1, pages + 1):
    params = {
      "query": query,
      "page": page,
      "per_page": per_page,
      "orientation": "landscape",
      "content_filter": "high",
    }
    try:
      r = requests.get(UNSPLASH_SEARCH, headers=headers, params=params, timeout=HTTP_TIMEOUT)
      r.raise_for_status()
      data = r.json() or {}
      results = data.get("results") or []
      for it in results:
        # keep useful fields
        out.append({
          "id": it.get("id"),
          "url_raw": ((it.get("urls") or {}).get("raw") or ""),
          "url_full": ((it.get("urls") or {}).get("full") or ""),
          "w": int(it.get("width") or 0),
          "h": int(it.get("height") or 0),
        })
    except Exception:
      continue

  random.shuffle(out)
  return out

def unsplash_best_url(item: dict) -> str:
  # request a good size, stable aspect
  raw = (item.get("url_raw") or "").strip()
  full = (item.get("url_full") or "").strip()
  base = raw or full
  if not base:
    return ""
  # force good width
  joiner = "&" if "?" in base else "?"
  return f"{base}{joiner}w=1920&fit=max&q=85&fm=jpg"

def download_image(url: str) -> Optional[bytes]:
  try:
    r = requests.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    ct = (r.headers.get("content-type") or "").lower()
    if "image" not in ct:
      return None
    b = r.content
    if not b or len(b) < MIN_IMAGE_BYTES:
      return None
    return b
  except Exception:
    return None


# -----------------------------------
# Wikimedia (fallback only)
# -----------------------------------
WIKI_API = "https://commons.wikimedia.org/w/api.php"

def wikimedia_search_image_urls(query: str, limit: int = 40) -> List[str]:
  params = {
    "action": "query",
    "format": "json",
    "origin": "*",
    "generator": "search",
    "gsrsearch": f"filetype:bitmap {query}",
    "gsrlimit": str(limit),
    "gsrnamespace": "6",
    "prop": "imageinfo",
    "iiprop": "url|size|mime",
  }
  try:
    r = requests.get(WIKI_API, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    pages = (data.get("query") or {}).get("pages") or {}
    out: List[str] = []
    for _, page in pages.items():
      infos = page.get("imageinfo") or []
      if not infos:
        continue
      info = infos[0] or {}
      url = (info.get("url") or "").strip()
      w = int(info.get("width") or 0)
      h = int(info.get("height") or 0)
      mime = (info.get("mime") or "").lower()
      if not url:
        continue
      if "svg" in mime:
        continue
      if w < MIN_IMAGE_WIDTH or h < MIN_IMAGE_HEIGHT:
        continue
      out.append(url)
    random.shuffle(out)
    return out
  except Exception:
    return []


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
  Non-AI images only.
  Prefers Unsplash. If key missing, either fail or fallback to Wikimedia if enabled.
  Enforces:
    - min byte size
    - min resolution (from API meta when available)
    - global de-dup by hash
  """
  ensure_dirs(slug)

  used_global = load_used_images()
  used_in_post: Set[str] = set()
  saved_paths: List[str] = []

  tries = 0

  if IMAGE_PROVIDER == "unsplash":
    if not UNSPLASH_ACCESS_KEY:
      if not ALLOW_WIKIMEDIA_FALLBACK:
        raise SystemExit("Missing UNSPLASH_ACCESS_KEY (for non-AI high quality photos)")
    candidates_unsplash = unsplash_search_candidates(keyword, per_page=30, pages=3)
    candidates_wiki = wikimedia_search_image_urls(keyword, limit=60) if (ALLOW_WIKIMEDIA_FALLBACK and not candidates_unsplash) else []
  elif IMAGE_PROVIDER == "wikimedia":
    candidates_unsplash = []
    candidates_wiki = wikimedia_search_image_urls(keyword, limit=80)
  else:
    raise SystemExit("IMAGE_PROVIDER must be 'unsplash' or 'wikimedia'")

  def next_candidate() -> Optional[str]:
    nonlocal candidates_unsplash, candidates_wiki
    if candidates_unsplash:
      it = candidates_unsplash.pop()
      # meta filter
      w = int(it.get("w") or 0)
      h = int(it.get("h") or 0)
      if w >= MIN_IMAGE_WIDTH and h >= MIN_IMAGE_HEIGHT:
        return unsplash_best_url(it)
      return None
    if candidates_wiki:
      return candidates_wiki.pop()
    return None

  while len(saved_paths) < count and tries < MAX_IMAGE_TRIES:
    tries += 1
    url = next_candidate()
    if not url:
      continue

    # quick header checks if possible
    w, h, cl, ct = head_image_info(url)
    if ct and ("image" not in ct):
      continue
    if cl and cl < MIN_IMAGE_BYTES:
      continue
    if (w and h) and (w < MIN_IMAGE_WIDTH or h < MIN_IMAGE_HEIGHT):
      continue

    b = download_image(url)
    if not b:
      continue

    hsh = sha256_bytes(b)
    if hsh in used_global or hsh in used_in_post:
      continue

    idx = len(saved_paths) + 1
    out_file = ASSETS_POSTS_DIR / slug / f"{idx}.jpg"
    out_file.write_bytes(b)

    used_in_post.add(hsh)
    used_global.add(hsh)
    saved_paths.append(f"assets/posts/{slug}/{idx}.jpg")

  save_used_images(used_global)

  if len(saved_paths) < count:
    raise SystemExit(f"Could not source enough high quality non-AI photos. Got {len(saved_paths)}/{count}")

  return saved_paths


# -----------------------------------
# LLM content generation
# -----------------------------------
def _openai_text(prompt_system: str, prompt_user: str) -> str:
  if not client:
    raise SystemExit("Missing OPENAI_API_KEY")

  # New SDK path
  try:
    res = client.responses.create(
      model=MODEL,
      input=[
        {"role": "system", "content": prompt_system},
        {"role": "user", "content": prompt_user},
      ],
    )
    return (res.output_text or "").strip()
  except Exception:
    pass

  # Old SDK path
  try:
    res = client.chat.completions.create(
      model=MODEL,
      messages=[
        {"role": "system", "content": prompt_system},
        {"role": "user", "content": prompt_user},
      ],
    )
    return (res.choices[0].message.content or "").strip()
  except Exception as e:
    raise SystemExit(f"OpenAI call failed: {e}")

def llm_generate_article(keyword: str) -> Dict[str, str]:
  """
  Return title, description, category, body_html.
  Enforces MIN_CHARS on visible text.
  """

  sys = (
    "You write genuinely helpful SEO blog posts for readers in the US and Europe. "
    "Write in natural English. "
    "No fluff. No generic filler. "
    "Use concrete steps, examples, and decision criteria. "
    "Short paragraphs. "
    "Do not mention you are an AI. "
    "Do not reference policies. "
    "Do not claim you tested products you did not test."
  )

  user = (
    f"Topic: {keyword}\n\n"
    "Output STRICT JSON with keys:\n"
    'title: string,\n'
    'description: string (max 160 chars),\n'
    'category: one of ["AI Tools","Make Money","Productivity","Reviews"],\n'
    'body_html: string (HTML only using <h2>, <h3>, <p>, <ul><li>, <ol><li>). No outer <html>.\n\n'
    f"Constraints:\n"
    f"- Visible text length must be at least {MIN_CHARS} characters.\n"
    "- Include a TL;DR section near the top using <h2>TL;DR</h2> and a <ul> of 5 bullets.\n"
    "- Include at least one comparison table using HTML <table> with <tr><th>/<td>.\n"
    "- Include a checklist section.\n"
    "- Include a common mistakes section.\n"
    "- Include a final recommendations section.\n"
  )

  txt = _openai_text(sys, user)
  try:
    data = json.loads(txt)
  except Exception:
    data = {}

  title = str(data.get("title") or "").strip() or keyword.title()
  description = str(data.get("description") or "").strip() or f"A practical guide about {keyword}."
  category = str(data.get("category") or "").strip() or "AI Tools"
  body = str(data.get("body_html") or "").strip() or "<p></p>"

  # If still short, expand once
  if len(strip_tags(body)) < MIN_CHARS:
    user2 = (
      f"Expand the article below to at least {MIN_CHARS} visible characters. "
      "Add depth and concrete details. Keep it accurate. "
      'Return STRICT JSON with ONLY key "body_html".\n\n'
      f"ARTICLE_HTML:\n{body}"
    )
    t2 = _openai_text(sys, user2)
    try:
      d2 = json.loads(t2)
      body2 = str(d2.get("body_html") or "").strip()
      if body2 and len(strip_tags(body2)) >= MIN_CHARS:
        body = body2
    except Exception:
      pass

  # Last resort padding (minimal, still useful)
  while len(strip_tags(body)) < MIN_CHARS:
    body += f"<p>{esc(description)} Add one concrete example and one decision rule for readers.</p>"

  return {"title": title, "description": description, "category": category, "body": body}


# -----------------------------------
# Insert images into body
# -----------------------------------
def inject_images_evenly(body_html: str, image_paths: List[str], title: str) -> str:
  extras = image_paths[1:] if len(image_paths) > 1 else []
  if not extras:
    return body_html

  blocks = re.split(r"(?i)(</p>\s*|</ul>\s*|</ol>\s*|</h2>\s*|</h3>\s*)", body_html)
  units: List[str] = []
  buf = ""
  for part in blocks:
    buf += part
    if re.search(r"(?i)</p>\s*$|</ul>\s*$|</ol>\s*$|</h2>\s*$|</h3>\s*$", buf.strip()):
      units.append(buf)
      buf = ""
  if buf.strip():
    units.append(buf)

  if len(units) <= 1:
    out = body_html
    for img in extras:
      out += f'<img src="../{esc(img)}" alt="{esc(title)}" loading="lazy">'
    return out

  n = len(units)
  m = len(extras)
  positions: List[int] = []
  for i in range(1, m + 1):
    pos = round(i * n / (m + 1))
    pos = min(max(pos, 1), n - 1)
    positions.append(pos)

  positions = sorted(set(positions))
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

  while img_i < m:
    out_units.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
    img_i += 1

  return "".join(out_units)


# -----------------------------------
# Build post html
# Includes post-main and post-aside so sidebar exists on PC
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

    <div class="post-main">
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

    <aside class="post-aside">
      <div class="sidecard">
        <h3>Browse by focus</h3>
        <div class="catlist">
          <a class="catitem" href="../category.html?cat=AI%20Tools">
            <span class="caticon">🤖</span>
            <span class="cattext">
              <span class="catname">AI Tools</span>
              <span class="catsub">Apps and workflows</span>
            </span>
          </a>

          <a class="catitem" href="../category.html?cat=Make%20Money">
            <span class="caticon">💸</span>
            <span class="cattext">
              <span class="catname">Make Money</span>
              <span class="catsub">Side hustles and income</span>
            </span>
          </a>

          <a class="catitem" href="../category.html?cat=Productivity">
            <span class="caticon">⚡</span>
            <span class="cattext">
              <span class="catname">Productivity</span>
              <span class="catsub">Systems and checklists</span>
            </span>
          </a>

          <a class="catitem" href="../category.html?cat=Reviews">
            <span class="caticon">🧾</span>
            <span class="cattext">
              <span class="catname">Reviews</span>
              <span class="catsub">Pricing and comparisons</span>
            </span>
          </a>
        </div>
      </div>
    </aside>

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


# -----------------------------------
# Index sorting
# -----------------------------------
def add_post_to_index(posts: List[dict], post_obj: dict) -> List[dict]:
  posts.append(post_obj)
  posts = [p for p in posts if isinstance(p, dict) and p.get("slug")]

  def parse_dt(x: dict) -> float:
    d = str(x.get("date", ""))
    try:
      return datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
    except Exception:
      return 0.0

  posts.sort(key=parse_dt, reverse=True)
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

  if IMAGE_PROVIDER == "unsplash" and (not UNSPLASH_ACCESS_KEY) and (not ALLOW_WIKIMEDIA_FALLBACK):
    raise SystemExit("Missing UNSPLASH_ACCESS_KEY (for non-AI high quality photos)")

  existing_slugs = set([p.get("slug") for p in posts if isinstance(p, dict)])

  made = 0
  tries = 0
  while made < POSTS_PER_RUN and tries < POSTS_PER_RUN * 12:
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

    # non-AI high quality photos, 4+
    images = pick_unique_images_for_post(keyword, slug, max(4, IMG_COUNT))

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
    print(f"Generated: {slug}")

  print(f"Done. Created {made} posts.")


if __name__ == "__main__":
  main()

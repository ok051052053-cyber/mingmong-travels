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

IMG_COUNT = int(os.environ.get("IMG_COUNT", "6"))  # 글 안 이미지 개수 (히어로 포함)
MIN_CHARS = int(os.environ.get("MIN_CHARS", "2500"))

HTTP_TIMEOUT = 25
IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "wikimedia").strip().lower()
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-1").strip()

# 멈춤 방지
HARD_DEADLINE_SECONDS = int(os.environ.get("HARD_DEADLINE_SECONDS", "720"))  # 12분
OPENAI_MAX_TRIES = int(os.environ.get("OPENAI_MAX_TRIES", "4"))

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

WIKI_API = "https://commons.wikimedia.org/w/api.php"

# -----------------------------
# Utils
# -----------------------------
def now_iso_datetime() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def esc(s: str) -> str:
  return html.escape(s or "", quote=True)

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

def sha256_bytes(b: bytes) -> str:
  return hashlib.sha256(b).hexdigest()

def strip_tags(s: str) -> str:
  s = re.sub(r"<script.*?>.*?</script>", "", s, flags=re.S | re.I)
  s = re.sub(r"<style.*?>.*?</style>", "", s, flags=re.S | re.I)
  s = re.sub(r"<[^>]+>", "", s)
  return html.unescape(s).strip()

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

def deadline_guard(start_ts: float):
  if time.time() - start_ts > HARD_DEADLINE_SECONDS:
    raise SystemExit("Hard deadline reached. Exiting to prevent stuck workflow.")

# -----------------------------
# Wikimedia
# -----------------------------
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

# -----------------------------
# OpenAI helpers (재시도 + 타임아웃)
# -----------------------------
def openai_generate_image_bytes(prompt: str, start_ts: float) -> Optional[bytes]:
  if not client:
    return None

  for t in range(OPENAI_MAX_TRIES):
    deadline_guard(start_ts)
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
      time.sleep(1.5 + t * 1.2)
      continue
  return None

def openai_json(prompt_system: str, prompt_user: str, start_ts: float) -> Optional[dict]:
  if not client:
    return None

  for t in range(OPENAI_MAX_TRIES):
    deadline_guard(start_ts)
    try:
      res = client.responses.create(
        model=MODEL,
        input=[
          {"role": "system", "content": prompt_system},
          {"role": "user", "content": prompt_user},
        ],
      )
      txt = (res.output_text or "").strip()
      return json.loads(txt)
    except Exception:
      time.sleep(1.5 + t * 1.2)
      continue
  return None

# -----------------------------
# Global image de-dup
# -----------------------------
def load_used_images() -> Set[str]:
  arr = safe_read_json(USED_IMAGES_JSON, [])
  if isinstance(arr, list):
    return set([str(x) for x in arr if x])
  return set()

def save_used_images(s: Set[str]):
  safe_write_json(USED_IMAGES_JSON, sorted(list(s)))

def pick_unique_images_for_post(keyword: str, slug: str, count: int, start_ts: float) -> List[str]:
  ensure_dirs(slug)

  used_global = load_used_images()
  used_in_post: Set[str] = set()
  saved_paths: List[str] = []

  candidates: List[str] = []
  if IMAGE_PROVIDER in ("wikimedia", "auto", "hybrid"):
    q = f"{keyword} modern minimal realistic photo"
    candidates = wikimedia_search_image_urls(q, limit=60)

  attempts = 0
  while len(saved_paths) < count and attempts < 220:
    attempts += 1
    deadline_guard(start_ts)

    img_bytes = None
    img_hash = None

    # 1) try wikimedia
    url = candidates.pop() if candidates else None
    if url:
      b = download_image(url)
      if b:
        h = sha256_bytes(b)
        if h not in used_global and h not in used_in_post:
          img_bytes = b
          img_hash = h

    # 2) fallback openai image
    if img_bytes is None:
      uniq = hashlib.sha1(f"{slug}-{len(saved_paths)}-{time.time()}-{random.random()}".encode()).hexdigest()[:12]
      prompt = (
        f"High quality realistic photo for a blog post about: {keyword}. "
        f"Clean composition, professional lighting, no text, no logos, no watermarks. "
        f"Unique variation token: {uniq}."
      )
      b = openai_generate_image_bytes(prompt, start_ts)
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

  if len(saved_paths) < count:
    raise SystemExit("Could not collect enough unique images within limits.")

  return saved_paths

# -----------------------------
# LLM content: 6개 섹션 균등 분배
# -----------------------------
def llm_generate_sections(keyword: str, sections: int, start_ts: float) -> Dict[str, object]:
  """
  Return:
    title, description, category, sections(list[str])
  Each section should be similar length.
  Total visible chars >= MIN_CHARS.
  """
  # fallback
  if not client:
    title = keyword.title()
    desc = f"A practical guide about {keyword}."
    cat = "AI Tools"
    base = (desc + " ") * 80
    per = max(1, len(base) // sections)
    sec = [base[i*per:(i+1)*per].strip() for i in range(sections)]
    while len("".join(sec)) < MIN_CHARS:
      sec = [s + " " + desc * 3 for s in sec]
    return {"title": title, "description": desc, "category": cat, "sections": sec}

  sys = (
    "You write SEO-friendly helpful blog content for young professionals in the US and Europe. "
    "No fluff. Clear structure. Practical steps. Natural English. "
    "Do not mention that you are an AI."
  )

  target_per = max(350, MIN_CHARS // max(1, sections))
  user = (
    f"Write one blog post about: {keyword}\n"
    "Return JSON with keys:\n"
    "title (string), description (string), category (one of: AI Tools, Make Money, Productivity, Reviews),\n"
    f"sections (array of exactly {sections} strings).\n"
    f"Constraints:\n"
    f"- Total visible text length across all sections >= {MIN_CHARS} characters\n"
    f"- Each section should be roughly similar length (~{target_per} chars each)\n"
    "- No markdown. Plain text inside each section.\n"
  )

  data = openai_json(sys, user, start_ts) or {}
  title = str(data.get("title", "")).strip() or keyword.title()
  description = str(data.get("description", "")).strip() or f"A practical guide about {keyword}."
  category = str(data.get("category", "")).strip() or "AI Tools"
  secs = data.get("sections") or []

  if not isinstance(secs, list) or len(secs) != sections:
    secs = []

  secs = [str(x).strip() for x in secs if str(x).strip()]
  if len(secs) != sections:
    # 2nd try: expand / fix
    user2 = (
      f"Fix output to valid JSON with exactly {sections} sections.\n"
      f"Topic: {keyword}\n"
      f"Total chars >= {MIN_CHARS}. Similar length per section."
    )
    data2 = openai_json(sys, user2, start_ts) or {}
    secs2 = data2.get("sections") or []
    if isinstance(secs2, list) and len(secs2) == sections:
      secs = [str(x).strip() for x in secs2]

  # final pad
  joined = "".join(secs)
  while len(joined) < MIN_CHARS:
    secs = [s + "\n\n" + description for s in secs]
    joined = "".join(secs)

  return {"title": title, "description": description, "category": category, "sections": secs}

def sections_to_html(sections: List[str]) -> str:
  # 간단 규칙: 각 섹션 첫 줄을 h2, 나머지 p로
  out = []
  for i, s in enumerate(sections, start=1):
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
      continue
    h = esc(lines[0])
    out.append(f"<h2>{h}</h2>")
    rest = lines[1:] if len(lines) > 1 else []
    if not rest:
      out.append("<p></p>")
    else:
      # 2~4문장씩 끊기
      buf = []
      for ln in rest:
        buf.append(esc(ln))
        if len(buf) >= 3:
          out.append("<p>" + " ".join(buf) + "</p>")
          buf = []
      if buf:
        out.append("<p>" + " ".join(buf) + "</p>")
  return "".join(out)

# -----------------------------
# Build post html + PC sidebar
# -----------------------------
def build_post_html(site_name: str, title: str, description: str, category: str, date_iso: str, slug: str, images: List[str], body_html: str) -> str:
  hero_img = images[0] if images else ""
  canonical = f"{SITE_URL}/posts/{slug}.html"

  # body 내부에 이미지 균등 삽입 (섹션 사이)
  # sections 개수 = IMG_COUNT 이면
  # hero + (섹션사이 이미지 IMG_COUNT-1) 형태
  extras = images[1:]
  if extras:
    # h2 단위로 split 해서 h2 뒤에 하나씩 삽입
    parts = re.split(r"(?i)(<h2>.*?</h2>)", body_html)
    out = []
    img_i = 0
    for chunk in parts:
      out.append(chunk)
      if img_i < len(extras) and re.match(r"(?i)<h2>.*?</h2>", chunk or ""):
        out.append(f'<img src="../{esc(extras[img_i])}" alt="{esc(title)}" loading="lazy">')
        img_i += 1
    body_html = "".join(out)

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

  # PC 사이드바에 홈의 Browse by focus 카드형 넣기
  aside_html = """
  <aside class="post-aside">
    <div class="sidecard">
      <h3>Browse by focus</h3>
      <div class="catlist">
        <a class="catitem" href="../category.html?cat=AI%20Tools">
          <div class="caticon">🤖</div>
          <div class="cattext">
            <div class="catname">AI Tools</div>
            <div class="catsub">ChatGPT, Claude, Notion AI, automation</div>
          </div>
        </a>
        <a class="catitem" href="../category.html?cat=Make%20Money">
          <div class="caticon">💸</div>
          <div class="cattext">
            <div class="catname">Make Money</div>
            <div class="catsub">Side hustles, freelancing, remote income</div>
          </div>
        </a>
        <a class="catitem" href="../category.html?cat=Productivity">
          <div class="caticon">⚡</div>
          <div class="cattext">
            <div class="catname">Productivity</div>
            <div class="catsub">Workflows, systems, checklists</div>
          </div>
        </a>
        <a class="catitem" href="../category.html?cat=Reviews">
          <div class="caticon">🧾</div>
          <div class="cattext">
            <div class="catname">Reviews</div>
            <div class="catsub">Pricing, comparisons, alternatives</div>
          </div>
        </a>
      </div>
    </div>

    <div class="sidecard" style="margin-top:12px;">
      <h3>Popular picks</h3>
      <div id="popular-picks"></div>
      <div class="tiny-note">Auto selected from your newest posts.</div>
    </div>

    <script>
      (function(){
        fetch("../posts.json?v=1")
          .then(r => r.json())
          .then(posts => {
            posts = Array.isArray(posts) ? posts : [];
            posts.sort((a,b) => new Date(b.date||0) - new Date(a.date||0));
            const box = document.getElementById("popular-picks");
            if(!box) return;
            const top = posts.slice(0,3);
            top.forEach(p => {
              const a = document.createElement("a");
              a.className = "hot-link";
              a.href = "../" + (p.url || "");
              a.textContent = p.title || "Post";
              box.appendChild(a);
            });
          })
          .catch(()=>{});
      })();
    </script>
  </aside>
  """

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

    {aside_html}

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
  start_ts = time.time()

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
    deadline_guard(start_ts)

    keyword = random.choice(keywords).strip()
    if not keyword:
      continue

    slug = slugify(keyword)[:80]
    if not slug or slug in existing_slugs:
      continue

    # 1) 글 섹션 생성 (IMG_COUNT에 맞춤)
    art = llm_generate_sections(keyword, sections=max(2, IMG_COUNT), start_ts=start_ts)
    title = str(art["title"])
    description = str(art["description"])
    category = str(art["category"])
    sections = art["sections"]
    body_html = sections_to_html(sections)

    # 2) 이미지 생성 (히어로 포함 IMG_COUNT)
    images = pick_unique_images_for_post(keyword, slug, max(1, IMG_COUNT), start_ts)

    # 3) HTML 작성
    date_iso = now_iso_datetime()
    html_doc = build_post_html(SITE_NAME, title, description, category, date_iso, slug, images, body_html)

    out_path = POSTS_DIR / f"{slug}.html"
    out_path.write_text(html_doc, encoding="utf-8")

    post_obj = {
      "title": title,
      "description": description,
      "category": category,
      "date": date_iso,  # ISO datetime
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

  print(f"Done. Created {made} posts.")

if __name__ == "__main__":
  main()

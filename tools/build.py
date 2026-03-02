import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"
INDEX = ROOT / "index.html"
SITEMAP = ROOT / "sitemap.xml"

SITE_URL = "https://ok051052053-cyber.github.io/mingmong-travels"

def load_posts():
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        posts = json.load(f)
    posts.sort(key=lambda x: x.get("date", ""), reverse=True)
    return posts

def build_index(posts):
    cards = []
    for p in posts:
        cards.append(f"""
        <a class="post-card" href="posts/{p['slug']}.html">
          <div class="thumb" aria-hidden="true"></div>
          <div>
            <div class="kicker">{p.get('category','Resources')}</div>
            <div class="post-title">{p['title']}</div>
            <p class="post-desc">{p.get('description','')}</p>
          </div>
        </a>
        """.strip())

    cards_html = "\n".join(cards) if cards else "<p>No posts yet.</p>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MingMong Travels</title>
  <meta name="description" content="Korea travel experiences and essentials for young travelers across the US and Europe.">
  <link rel="stylesheet" href="style.css">
</head>
<body>

<header class="topbar">
  <div class="container topbar-inner">
    <a class="brand" href="index.html">
      <span class="mark" aria-hidden="true"></span>
      <span>MingMong Travels</span>
    </a>

    <nav class="nav" aria-label="Primary">
      <a href="index.html">Resources</a>
      <a href="about.html">About</a>
      <a href="contact.html">Contact</a>
      <a class="btn primary" href="posts/{posts[0]['slug']}.html">Start Here</a>
    </nav>
  </div>
</header>

<main class="container">
  <section class="hero">
    <p class="breadcrumb">Resources</p>
    <h1 class="h1">Travel resources for Korea</h1>
    <p class="lead">Beginner friendly guides for US and Europe travelers. Clear steps. Local context. No fluff.</p>
  </section>

  <section class="layout">
    <article class="card article">
      <h2>Latest</h2>
      <p class="lead">Fresh guides and checklists.</p>
      <hr class="hr">
      <div class="card" style="box-shadow:none;border:none;background:transparent;">
        {cards_html}
      </div>
    </article>

    <aside class="sidebar">
      <div class="card sidebox">
        <h4>Categories</h4>
        <p>Korea Travel Experiences and Korea Lifestyle and Essentials</p>
        <a class="btn primary" href="posts/{posts[0]['slug']}.html">Open the latest guide</a>
      </div>

      <div class="card related">
        <h4>Up next</h4>
        <a href="#">Korea SIM vs eSIM for tourists</a>
        <a href="#">How public transport works in Korea</a>
        <a href="#">What to pack by season</a>
      </div>
    </aside>
  </section>
</main>

<footer class="footer">
  <div class="container">
    <div>© {datetime.now().year} MingMong Travels</div>
    <div class="footer-links">
      <a href="privacy.html">Privacy</a>
      <a href="about.html">About</a>
      <a href="contact.html">Contact</a>
    </div>
  </div>
</footer>

</body>
</html>
"""
    INDEX.write_text(html, encoding="utf-8")

def build_sitemap(posts):
    urls = [f"{SITE_URL}/"]
    for p in posts:
        urls.append(f"{SITE_URL}/posts/{p['slug']}.html")
    body = "\n".join([f"<url><loc>{u}</loc></url>" for u in urls])
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
"""
    SITEMAP.write_text(xml, encoding="utf-8")

def main():
    posts = load_posts()
    if not posts:
        raise SystemExit("posts.json is empty")
    build_index(posts)
    build_sitemap(posts)
    print("Built index.html and sitemap.xml")

if __name__ == "__main__":
    main()

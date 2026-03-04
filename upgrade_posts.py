from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "posts"

html_files = list(POSTS.glob("*.html"))

updated = 0

for file in html_files:
    text = file.read_text(encoding="utf-8")

    if "post-shell" in text:
        continue

    text = text.replace(
        '<main class="container">',
        '<main class="container post-page">\n<div class="post-shell">'
    )

    text = text.replace(
        '</main>',
        '</div>\n</main>'
    )

    file.write_text(text, encoding="utf-8")
    updated += 1

print(f"updated {updated} posts")

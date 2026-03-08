import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any


# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
POSTS_JSON = ROOT / "posts.json"


# -----------------------------
# Category policy
# -----------------------------
ALLOWED_CATEGORIES = {
    "AI Tools",
    "Freelance Systems",
    "Creator Income",
    "Productivity",
}


# -----------------------------
# Helpers
# -----------------------------
def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def short_desc(text: str) -> str:
    t = (text or "").strip()
    if len(t) > 160:
        t = t[:157].rstrip() + "..."
    return t


def normalize_keyword(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def simple_slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def current_year_utc() -> int:
    return int(datetime.now(timezone.utc).strftime("%Y"))


def resolve_post_url_path(p: dict) -> str:
    if not isinstance(p, dict):
        return ""

    url = (p.get("url") or "").strip()
    slug = (p.get("slug") or "").strip()

    if url:
        url = url.lstrip("/")
        if url.endswith(".md"):
            url = url[:-3] + ".html"
        if url.startswith("posts/") and "." not in Path(url).name:
            url = url + ".html"
        return url

    if slug:
        return f"posts/{slug}.html"

    return ""


def cluster_to_category(cluster_name: str, keyword: str = "", post_type: str = "") -> str:
    c = (cluster_name or "").strip().lower()
    k = (keyword or "").strip().lower()

    comparison_tokens = [" vs ", "versus", "compare", "comparison", "alternative", "alternatives"]
    if any(x in k for x in comparison_tokens):
        return "AI Tools" if any(x in k for x in ["chatgpt", "claude", "notion", "ai"]) else "Productivity"

    if c == "ai productivity":
        return "AI Tools"
    if c == "freelance operations":
        return "Freelance Systems"
    if c == "creator monetization":
        return "Creator Income"

    if any(x in k for x in ["invoice", "proposal", "client onboarding", "crm", "revision", "deliverable", "scope creep", "follow up", "follow-up", "client feedback"]):
        return "Freelance Systems"

    if any(x in k for x in ["gumroad", "newsletter", "digital product", "notion template", "monetization", "pricing"]):
        return "Creator Income"

    if any(x in k for x in ["ai", "chatgpt", "claude", "automation", "meeting notes", "summarization", "email automation"]):
        return "AI Tools"

    return "Productivity"


def build_clean_slug(title: str, keyword: str = "") -> str:
    raw = simple_slugify(title) or simple_slugify(keyword) or f"post-{int(time.time())}"
    raw = raw[:72].strip("-")
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if len(raw) < 8:
        raw = f"{raw}-{int(time.time())}"
    return raw


def normalize_category(old_category: str, keyword: str, cluster: str, post_type: str) -> str:
    cat = (old_category or "").strip()

    mapping = {
        "Make Money": "Creator Income",
        "Make Money Online": "Creator Income",
        "Reviews": "Productivity",  # 기본값. 아래 keyword/cluster로 다시 판단
    }

    if cat in mapping:
        cat = mapping[cat]

    if cat in ALLOWED_CATEGORIES:
        return cat

    return cluster_to_category(cluster_name=cluster, keyword=keyword, post_type=post_type)


def normalize_title_year(title: str) -> str:
    title = (title or "").strip()
    year_now = str(current_year_utc())
    title = re.sub(r"\bin (2019|2020|2021|2022|2023|2024)\b", f"in {year_now}", title, flags=re.IGNORECASE)
    title = re.sub(r"\bfor (2019|2020|2021|2022|2023|2024)\b", f"for {year_now}", title, flags=re.IGNORECASE)
    return title


def ensure_unique_slug(slug: str, seen: set) -> str:
    base = slug.strip("-")
    candidate = base
    i = 2
    while candidate in seen or not candidate:
        candidate = f"{base}-{i}"
        i += 1
    seen.add(candidate)
    return candidate


def normalize_post(p: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(p, dict):
        return p

    title = normalize_title_year((p.get("title") or "").strip())
    keyword = (p.get("keyword") or "").strip()
    cluster = (p.get("cluster") or "").strip()
    post_type = (p.get("post_type") or "normal").strip()

    slug = (p.get("slug") or "").strip()
    slug = slug.strip("-")
    if len(slug) > 72:
        slug = slug[:72].strip("-")
    slug = re.sub(r"-{2,}", "-", slug)

    if not slug:
        slug = build_clean_slug(title, keyword)

    url = resolve_post_url_path({**p, "slug": slug})
    if not url:
        url = f"posts/{slug}.html"

    category = normalize_category(
        old_category=(p.get("category") or "").strip(),
        keyword=keyword or title,
        cluster=cluster,
        post_type=post_type,
    )

    if category not in ALLOWED_CATEGORIES:
        category = "Productivity"

    description = (p.get("description") or "").strip()
    if not description:
        description = short_desc(title)

    date = p.get("date")
    updated = p.get("updated") or date

    thumb = (p.get("thumbnail") or "").strip()
    image = (p.get("image") or "").strip()

    if not image and thumb:
        image = thumb
    if not thumb and image:
        thumb = image

    fixed = dict(p)
    fixed["title"] = title
    fixed["slug"] = slug
    fixed["url"] = url
    fixed["category"] = category
    fixed["description"] = description
    fixed["updated"] = updated
    fixed["thumbnail"] = thumb
    fixed["image"] = image
    fixed["post_type"] = post_type

    return fixed


def main() -> int:
    posts = load_json(POSTS_JSON, [])
    if not isinstance(posts, list):
        print("posts.json is not a list.")
        return 1

    fixed_posts: List[Dict[str, Any]] = []
    seen_slugs = set()

    changed = 0

    for p in posts:
        if not isinstance(p, dict):
            continue

        before = json.dumps(p, ensure_ascii=False, sort_keys=True)
        fixed = normalize_post(p)

        unique_slug = ensure_unique_slug(fixed["slug"], seen_slugs)
        if unique_slug != fixed["slug"]:
            fixed["slug"] = unique_slug
            fixed["url"] = f"posts/{unique_slug}.html"

        after = json.dumps(fixed, ensure_ascii=False, sort_keys=True)
        if before != after:
            changed += 1

        fixed_posts.append(fixed)

    save_json(POSTS_JSON, fixed_posts)

    print(f"Fixed posts: {changed}")
    print(f"Total posts: {len(fixed_posts)}")
    print("Saved:", POSTS_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

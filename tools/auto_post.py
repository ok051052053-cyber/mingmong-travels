import os
import re
import json
import time
import random
import hashlib
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Any

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
USED_TEXTS_JSON = ROOT / "used_texts.json"

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

MIN_CHARS = int(os.environ.get("MIN_CHARS", "4200"))
IMG_COUNT = 7
MAX_KEYWORD_TRIES = int(os.environ.get("MAX_KEYWORD_TRIES", "12"))

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
HTTP_TIMEOUT = 35

UNSPLASH_MIN_WIDTH = int(os.environ.get("UNSPLASH_MIN_WIDTH", "2000"))
UNSPLASH_MIN_HEIGHT = int(os.environ.get("UNSPLASH_MIN_HEIGHT", "1200"))
UNSPLASH_MIN_LIKES = int(os.environ.get("UNSPLASH_MIN_LIKES", "60"))
UNSPLASH_PER_PAGE = int(os.environ.get("UNSPLASH_PER_PAGE", "30"))

TITLE_SIM_THRESHOLD = float(os.environ.get("TITLE_SIM_THRESHOLD", "0.88"))
MAX_GENERATE_ATTEMPTS = int(os.environ.get("MAX_GENERATE_ATTEMPTS", "100"))

ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "").strip()

KEYWORD_SIM_THRESHOLD = float(os.environ.get("KEYWORD_SIM_THRESHOLD", "0.82"))
AUTO_KEYWORD_BATCH = int(os.environ.get("AUTO_KEYWORD_BATCH", "24"))
MIN_KEYWORD_POOL = int(os.environ.get("MIN_KEYWORD_POOL", "18"))

CLUSTER_MODE = os.environ.get("CLUSTER_MODE", "1").strip() == "1"
CLUSTER_BATCH = int(os.environ.get("CLUSTER_BATCH", "12"))
CLUSTER_ROTATION_WINDOW = int(os.environ.get("CLUSTER_ROTATION_WINDOW", "18"))
TOPIC_CLUSTERS_JSON = os.environ.get("TOPIC_CLUSTERS_JSON", "").strip()

PILLAR_INTERVAL = int(os.environ.get("PILLAR_INTERVAL", "8"))
GOOGLE_SUGGEST_ENABLED = os.environ.get("GOOGLE_SUGGEST_ENABLED", "1").strip() == "1"
GOOGLE_SUGGEST_MAX_SEEDS = int(os.environ.get("GOOGLE_SUGGEST_MAX_SEEDS", "8"))
GOOGLE_SUGGEST_PER_QUERY = int(os.environ.get("GOOGLE_SUGGEST_PER_QUERY", "8"))
RELATED_POST_LIMIT = int(os.environ.get("RELATED_POST_LIMIT", "4"))

MIN_SECTION_CHARS = int(os.environ.get("MIN_SECTION_CHARS", "420"))

# -----------------------------
# Generic-content blockers
# -----------------------------
BANNED_TITLE_PATTERNS = [
    "best ",
    "top ",
    "ultimate guide",
    "comprehensive guide",
    "essential guide",
    "must-have",
    "must have",
    "complete guide",
    "top productivity tools",
    "best ai tools for",
    "top ai tools for",
    "best apps for",
    "best tools for",
]

BANNED_OPENING_PHRASES = [
    "ai is transforming",
    "in today's fast-paced world",
    "in today’s fast-paced world",
    "in today's digital world",
    "in today’s digital world",
    "productivity is important",
    "freelancers need the right tools",
    "small business owners need the right tools",
    "there are many tools available",
    "in the modern workplace",
]

REQUIRED_CONTENT_SIGNALS = [
    "workflow",
    "checklist",
    "mistake",
    "tradeoff",
    "decision",
    "step",
]

# -----------------------------
# Defaults for topic clusters
# -----------------------------
DEFAULT_TOPIC_CLUSTERS = {
    "AI Productivity": [
        "ai email automation workflow",
        "ai meeting notes to task workflow",
        "ai report writing workflow",
        "ai document summarization for work",
        "chatgpt workflow for solo work",
        "ai tools for office workflows",
        "ai stack for repetitive admin work",
        "ai automation for weekly planning",
    ],
    "Freelance Operations": [
        "freelance invoicing workflow",
        "freelance pricing system",
        "proposal workflow for freelancers",
        "time tracking system for freelancers",
        "client onboarding workflow",
        "freelance crm workflow",
        "freelance admin automation",
        "solo freelancer operating system",
    ],
    "Creator Monetization": [
        "newsletter monetization system",
        "gumroad digital product workflow",
        "sell notion templates workflow",
        "creator monetization system",
        "digital products for beginners workflow",
        "email list monetization workflow",
        "creator operations system",
        "paid newsletter monetization playbook",
    ],
}

DEFAULT_PILLAR_TOPICS = {
    "AI Productivity": [
        "ai workflow automation for solo workers",
        "how to build an ai system for repetitive work",
        "practical ai workflows for knowledge workers",
        "how to automate weekly office work with ai",
        "ai operating system for one person businesses",
    ],
    "Freelance Operations": [
        "how to run a freelance business with systems",
        "freelance operations system for solo professionals",
        "how freelancers can reduce admin work",
        "practical freelance workflows that save time",
        "freelance business systems for one person businesses",
    ],
    "Creator Monetization": [
        "how creators can build monetization systems",
        "digital product systems for beginner creators",
        "creator operations playbook for small audiences",
        "how to make money with digital products using systems",
        "newsletter and digital product monetization workflow",
    ],
}


# -----------------------------
# OpenAI
# -----------------------------
def openai_generate_text(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")

    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError(f"OpenAI package import failed: {e}")

    client = OpenAI(api_key=OPENAI_API_KEY)

    try:
        res = client.responses.create(model=MODEL, input=prompt)
        text = (res.output_text or "").strip()
        if text:
            return text
    except Exception:
        pass

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write deeply useful blog content. "
                        "You avoid generic listicles and shallow SEO filler. "
                        "You return valid JSON when asked."
                    ),
                },
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


def ensure_used_texts_schema(raw):
    if isinstance(raw, dict):
        if "fingerprints" not in raw or not isinstance(raw.get("fingerprints"), list):
            raw["fingerprints"] = []
        return raw
    if isinstance(raw, list):
        return {"fingerprints": [x for x in raw if isinstance(x, str)]}
    return {"fingerprints": []}


def short_desc(text: str) -> str:
    t = (text or "").strip()
    if len(t) > 160:
        t = t[:157].rstrip() + "..."
    return t


def safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _json_extract(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s

    s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    i_obj = s.find("{")
    j_obj = s.rfind("}")
    if i_obj >= 0 and j_obj > i_obj:
        return s[i_obj:j_obj + 1]

    return s


def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _norm_title(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_too_similar(new_title: str, existing_titles: List[str], threshold: float) -> bool:
    nt = _norm_title(new_title)
    if not nt:
        return True

    pool = existing_titles[:500] if len(existing_titles) > 500 else existing_titles
    for t in pool:
        tt = _norm_title(t)
        if not tt:
            continue
        if tt == nt:
            return True
        r = SequenceMatcher(a=nt, b=tt).ratio()
        if r >= threshold:
            return True
    return False


def make_fingerprint(title: str, sections: List[Dict[str, str]], tldr: str, faq: List[Dict[str, str]]) -> str:
    parts = [title.strip(), (tldr or "").strip()[:400]]
    for s in sections[:IMG_COUNT]:
        parts.append((s.get("heading") or "").strip())
        parts.append((s.get("body") or "").strip()[:500])
    for item in (faq or [])[:5]:
        parts.append((item.get("q") or "").strip()[:200])
        parts.append((item.get("a") or "").strip()[:200])

    joined = "\n".join([p for p in parts if p])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def cluster_to_category(cluster_name: str, keyword: str = "", post_type: str = "") -> str:
    c = (cluster_name or "").strip().lower()
    k = (keyword or "").strip().lower()

    if any(x in k for x in ["vs", "compare", "comparison", "review", "reviews"]):
        return "Reviews"

    if c == "ai productivity":
        return "AI Tools"
    if c == "freelance operations":
        return "Make Money"
    if c == "creator monetization":
        return "Make Money"

    if any(x in k for x in ["adhd", "focus", "productivity", "pomodoro", "time blocking", "time management"]):
        return "Productivity"
    if any(x in k for x in ["ai", "chatgpt", "automation", "notion", "claude"]):
        return "AI Tools"
    if any(x in k for x in ["money", "side hustle", "freelance", "invoice", "tax", "gumroad", "newsletter", "digital product"]):
        return "Make Money"

    return "Productivity"


def pick_category(keyword: str, cluster_name: str = "", post_type: str = "") -> str:
    return cluster_to_category(cluster_name, keyword, post_type)


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


def post_href_from_post_page(p: dict) -> str:
    url = resolve_post_url_path(p)
    if not url:
        return "#"
    if url.startswith("posts/"):
        return url.split("/", 1)[1]
    return "../" + url


def get_cluster_pillar(posts: List[dict], cluster_name: str) -> dict:
    for p in posts:
        if not isinstance(p, dict):
            continue
        if p.get("cluster") == cluster_name and p.get("post_type") == "pillar":
            return p
    return {}


def is_generic_title(title: str) -> bool:
    t = _norm_title(title)
    if not t:
        return True

    for bad in BANNED_TITLE_PATTERNS:
        if bad.strip().lower() in t:
            return True

    words = t.split()
    if len(words) < 8:
        return True

    structure_terms = [
        "workflow",
        "system",
        "template",
        "playbook",
        "checklist",
        "framework",
        "setup",
        "guide",
        "operating guide",
    ]
    if not any(term in t for term in structure_terms):
        return True

    situation_terms = [
        "for",
        "when",
        "using",
        "without",
        "under",
        "after",
        "during",
        "from",
        "into",
        "with",
    ]
    if not any(term in t for term in situation_terms):
        return True

    broad_bad = [
        "ai workflow",
        "productivity workflow",
        "creator system",
        "freelance system",
        "ai setup",
        "work system",
        "business workflow",
        "content workflow",
    ]
    if t in broad_bad:
        return True

    return False


def has_strong_title_shape(title: str) -> bool:
    t = _norm_title(title)

    audience_terms = [
        "freelancer", "freelancers",
        "solo creator", "solo creators",
        "creator", "creators",
        "consultant", "consultants",
        "designer", "designers",
        "writer", "writers",
        "marketer", "marketers",
        "operator", "operators",
        "one person", "small team",
        "newsletter writer", "newsletter writers",
        "remote worker", "remote workers",
        "contractor", "contractors",
        "knowledge worker", "knowledge workers",
        "agency owner", "agency owners",
    ]

    problem_terms = [
        "reduce",
        "cut",
        "save",
        "fix",
        "stop",
        "avoid",
        "turn",
        "organize",
        "streamline",
        "simplify",
        "follow up",
        "onboarding",
        "handoff",
        "admin",
        "invoice",
        "proposal",
        "meeting notes",
        "task",
        "planning",
        "repurposing",
        "back and forth",
        "revision",
        "approvals",
        "overwhelm",
        "bottleneck",
    ]

    has_audience = any(term in t for term in audience_terms)
    has_problem = any(term in t for term in problem_terms)

    return has_audience and has_problem


def opening_too_generic(text: str) -> bool:
    t = (text or "").lower().strip()[:500]
    return any(p in t for p in BANNED_OPENING_PHRASES)


def quality_check_post(data: Dict[str, Any], keyword: str = "") -> Tuple[bool, str]:
    title = data.get("title", "")
    tldr = data.get("tldr", "")
    sections = data.get("sections", [])
    faq = data.get("faq", [])

    if is_generic_title(title):
        return False, "generic-title"

    if not has_strong_title_shape(title):
        return False, "weak-title-shape"

    if not isinstance(sections, list) or len(sections) != IMG_COUNT:
        return False, "bad-sections"

    total_text = []
    total_text.append(title)
    total_text.append(tldr)
    for s in sections:
        total_text.append(s.get("heading", ""))
        total_text.append(s.get("body", ""))
    for item in faq:
        total_text.append(item.get("q", ""))
        total_text.append(item.get("a", ""))

    joined = "\n".join(total_text).lower()

    if len(joined) < MIN_CHARS:
        return False, "too-short"

    if opening_too_generic(tldr + "\n" + (sections[0].get("body", "") if sections else "")):
        return False, "generic-opening"

    section_bodies = [s.get("body", "") for s in sections]
    if any(len((b or "").strip()) < MIN_SECTION_CHARS for b in section_bodies):
        return False, "thin-section"

    signal_hits = sum(1 for x in REQUIRED_CONTENT_SIGNALS if x in joined)
    if signal_hits < 4:
        return False, "missing-depth-signals"

    if "who this is for" not in joined and "this workflow is for" not in joined and "this setup is for" not in joined:
        return False, "missing-audience-framing"

    if "mistake" not in joined and "common pitfall" not in joined and "go wrong" not in joined:
        return False, "missing-mistakes"

    if "checklist" not in joined and "template" not in joined and "copy this" not in joined:
        return False, "missing-template-checklist"

    nk = normalize_keyword(keyword)
    nt = normalize_keyword(title)
    if nk and nt and nk == nt:
        return False, "title-too-close-to-keyword"

    return True, "ok"


# -----------------------------
# Keyword automation
# -----------------------------
def normalize_keyword(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def keyword_too_similar(a: str, b: str, threshold: float = KEYWORD_SIM_THRESHOLD) -> bool:
    na = normalize_keyword(a)
    nb = normalize_keyword(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(a=na, b=nb).ratio() >= threshold


def is_search_intent_keyword(keyword: str) -> bool:
    k = normalize_keyword(keyword)
    if not k:
        return False

    words = k.split()
    if len(words) < 4 or len(words) > 18:
        return False

    if re.search(r"\b(2019|2020|2021|2022|2023|2024)\b", k):
        return False

    broad_bad = {
        "ai",
        "productivity",
        "freelancing",
        "remote work",
        "email",
        "automation",
        "marketing",
        "notion",
        "chatgpt",
    }
    if k in broad_bad:
        return False

    vague_bad = [
        "best ai tools for",
        "top ai tools for",
        "best tools for",
        "best apps for",
        "ultimate guide to",
        "comprehensive guide to",
        "essential guide to",
    ]
    if any(x in k for x in vague_bad):
        return False

    intent_tokens = [
        "workflow",
        "system",
        "playbook",
        "template",
        "checklist",
        "process",
        "automation",
        "set up",
        "how to",
        "reduce",
        "save time",
        "client onboarding",
        "invoice",
        "proposal",
        "newsletter",
        "digital product",
        "meeting notes",
        "task workflow",
        "weekly planning",
        "content repurposing",
        "one person",
        "solo",
    ]
    if not any(tok in k for tok in intent_tokens):
        return False

    return True


def dedupe_keywords(keywords: List[str], existing_titles: List[str], existing_keywords: List[str]) -> List[str]:
    out: List[str] = []
    seen_norm = set()

    baseline = []
    for x in existing_titles[:500]:
        if isinstance(x, str) and x.strip():
            baseline.append(x)
    for x in existing_keywords[:1000]:
        if isinstance(x, str) and x.strip():
            baseline.append(x)

    for kw in keywords:
        kw = _clean_text(kw)
        if not kw:
            continue
        if not is_search_intent_keyword(kw):
            continue

        n = normalize_keyword(kw)
        if not n or n in seen_norm:
            continue

        skip = False
        for ex in baseline:
            if keyword_too_similar(kw, ex):
                skip = True
                break
        if skip:
            continue

        for kept in out:
            if keyword_too_similar(kw, kept):
                skip = True
                break
        if skip:
            continue

        seen_norm.add(n)
        out.append(kw)

    return out


def load_topic_clusters() -> Dict[str, List[str]]:
    if TOPIC_CLUSTERS_JSON:
        try:
            raw = json.loads(TOPIC_CLUSTERS_JSON)
            if isinstance(raw, dict):
                out = {}
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, list):
                        out[k] = [str(x).strip() for x in v if str(x).strip()]
                if out:
                    return out
        except Exception:
            pass
    return DEFAULT_TOPIC_CLUSTERS


def get_existing_keywords_from_posts(posts: List[dict]) -> List[str]:
    out = []
    for p in posts:
        if not isinstance(p, dict):
            continue
        for key in ["keyword", "title", "slug", "description"]:
            val = p.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
    return out


def pick_next_cluster(posts: List[dict], topic_clusters: Dict[str, List[str]]) -> str:
    names = list(topic_clusters.keys())
    if not names:
        return "AI Productivity"

    recent = posts[:CLUSTER_ROTATION_WINDOW] if posts else []
    counts = {name: 0 for name in names}

    for p in recent:
        if not isinstance(p, dict):
            continue
        cluster = p.get("cluster")
        if isinstance(cluster, str) and cluster in counts:
            counts[cluster] += 1

    min_count = min(counts.values()) if counts else 0
    candidates = [name for name, c in counts.items() if c == min_count]
    return random.choice(candidates) if candidates else names[0]


def should_make_pillar(posts: List[dict], cluster_name: str) -> bool:
    cluster_posts = [p for p in posts if isinstance(p, dict) and p.get("cluster") == cluster_name]
    if not cluster_posts:
        return True

    if not any(p.get("post_type") == "pillar" for p in cluster_posts):
        return True

    regular_count = sum(1 for p in cluster_posts if p.get("post_type") != "pillar")
    if regular_count > 0 and regular_count % max(PILLAR_INTERVAL, 1) == 0:
        recent_cluster = cluster_posts[:5]
        if not any(p.get("post_type") == "pillar" for p in recent_cluster):
            return True

    return False


def build_cluster_keyword_prompt(
    cluster_name: str,
    seed_keywords: List[str],
    existing_titles: List[str],
    existing_keywords: List[str],
) -> str:
    seed_block = "\n".join([f"- {x}" for x in seed_keywords[:30]]) or "- ai workflow automation for solo workers"
    title_block = "\n".join([f"- {x}" for x in existing_titles[:60]])
    existing_kw_block = "\n".join([f"- {x}" for x in existing_keywords[:100]])

    return f"""
You generate SEO blog topic keywords for a site targeting US and EU readers.

Current cluster:
{cluster_name}

Need:
- exactly {CLUSTER_BATCH} keyword ideas
- long-tail keywords only
- practical search intent only
- suitable for a newer niche blog
- no outdated years
- no news
- no politics
- no medical or legal advice
- no broad listicle topics
- no generic "best tools for X" patterns
- topics must sound like a real operating problem or workflow

Prefer topic patterns like:
- how to build a workflow for X
- X system for Y
- X checklist for Y
- X playbook for Y
- how to reduce X using Y
- how to turn X into Y with AI
- setup guides for one specific situation
- decision frameworks for one specific buyer

Cluster seed keywords:
{seed_block}

Avoid topics too similar to these existing post titles:
{title_block if title_block else "- none"}

Avoid topics too similar to these existing keywords:
{existing_kw_block if existing_kw_block else "- none"}

Return valid JSON only:
{{
  "keywords": [
    "keyword 1",
    "keyword 2"
  ]
}}
""".strip()


def generate_cluster_keywords(
    cluster_name: str,
    seed_keywords: List[str],
    existing_titles: List[str],
    existing_keywords: List[str],
) -> List[str]:
    prompt = build_cluster_keyword_prompt(cluster_name, seed_keywords, existing_titles, existing_keywords)
    raw = openai_generate_text(prompt)
    data = json.loads(_json_extract(raw))

    kws = data.get("keywords") or []
    if not isinstance(kws, list):
        return []

    clean = []
    for kw in kws:
        if isinstance(kw, str) and kw.strip():
            clean.append(_clean_text(kw))

    return dedupe_keywords(clean, existing_titles, existing_keywords)


def build_general_keyword_prompt(seed_keywords: List[str], existing_titles: List[str], existing_keywords: List[str]) -> str:
    seed_block = "\n".join([f"- {x}" for x in seed_keywords[:30]]) or "- ai workflow automation for solo workers"
    title_block = "\n".join([f"- {x}" for x in existing_titles[:50]])
    existing_kw_block = "\n".join([f"- {x}" for x in existing_keywords[:80]])

    return f"""
You generate SEO blog topic keywords for a site targeting US and EU readers.

Site focus:
1. AI systems for real work
2. Freelance operations
3. Creator monetization systems

Need:
- exactly {AUTO_KEYWORD_BATCH} keyword ideas
- long-tail keywords only
- practical search intent only
- human sounding
- suitable for a newer niche blog
- easier to rank than broad head terms
- no outdated years
- no celebrity or news topics
- no medical, legal, political, or unsafe topics
- no generic definitions
- no broad listicle topics like "best ai tools for students"

Good patterns:
- how to build X workflow
- X system for Y
- X checklist for Y
- how to reduce X using Y
- how to turn X into Y
- decision framework for choosing X
- template based workflow topics
- one specific problem for one specific reader

Seed keywords:
{seed_block}

Avoid topics too similar to these existing post titles:
{title_block if title_block else "- none"}

Avoid topics too similar to these existing keywords:
{existing_kw_block if existing_kw_block else "- none"}

Return valid JSON only:
{{
  "keywords": [
    "keyword 1",
    "keyword 2"
  ]
}}
""".strip()


def generate_auto_keywords(seed_keywords: List[str], existing_titles: List[str], existing_keywords: List[str]) -> List[str]:
    prompt = build_general_keyword_prompt(seed_keywords, existing_titles, existing_keywords)
    raw = openai_generate_text(prompt)
    data = json.loads(_json_extract(raw))

    kws = data.get("keywords") or []
    if not isinstance(kws, list):
        return []

    clean = []
    for kw in kws:
        if isinstance(kw, str) and kw.strip():
            clean.append(_clean_text(kw))

    return dedupe_keywords(clean, existing_titles, existing_keywords)


def fetch_google_suggest(query: str) -> List[str]:
    if not query or not GOOGLE_SUGGEST_ENABLED:
        return []

    try:
        url = "https://suggestqueries.google.com/complete/search"
        params = {"client": "firefox", "q": query}
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
            out = []
            for item in data[1][:GOOGLE_SUGGEST_PER_QUERY]:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
            return out
    except Exception:
        return []
    return []


def expand_keywords_from_google(seeds: List[str], existing_titles: List[str], existing_keywords: List[str]) -> List[str]:
    if not GOOGLE_SUGGEST_ENABLED:
        return []

    pool: List[str] = []
    base_seeds = [s for s in seeds if isinstance(s, str) and s.strip()][:GOOGLE_SUGGEST_MAX_SEEDS]

    for seed in base_seeds:
        variants = [
            seed,
            f"{seed} workflow",
            f"{seed} system",
            f"how to {seed}",
            f"{seed} checklist",
            f"{seed} template",
        ]
        for q in variants:
            pool.extend(fetch_google_suggest(q))

    return dedupe_keywords(pool, existing_titles, existing_keywords)


def build_pillar_keyword_pool(cluster_name: str, posts: List[dict], existing_titles: List[str]) -> List[str]:
    existing_keywords = get_existing_keywords_from_posts(posts)
    base = DEFAULT_PILLAR_TOPICS.get(cluster_name) or []
    google_kw = expand_keywords_from_google(base, existing_titles, existing_keywords)
    merged = dedupe_keywords(base + google_kw, existing_titles, existing_keywords)
    return merged


def load_keywords() -> List[str]:
    data = load_json(KEYWORDS_JSON, [])
    if isinstance(data, list):
        return [x for x in data if isinstance(x, str) and x.strip()]
    if isinstance(data, dict):
        ks = data.get("keywords") or []
        if isinstance(ks, list):
            return [x for x in ks if isinstance(x, str) and x.strip()]
    return []


def save_keywords(keywords: List[str]) -> None:
    keywords = [k for k in keywords if isinstance(k, str) and k.strip()]
    unique = []
    seen = set()
    for k in keywords:
        nk = normalize_keyword(k)
        if not nk or nk in seen:
            continue
        seen.add(nk)
        unique.append(k.strip())
    save_json(KEYWORDS_JSON, {"keywords": unique})


def build_keyword_pool(base_keywords: List[str], existing_titles: List[str], posts: List[dict]) -> Tuple[List[str], str, str, str]:
    existing_keywords = get_existing_keywords_from_posts(posts)
    clean_base = dedupe_keywords(base_keywords, existing_titles, existing_keywords)

    if CLUSTER_MODE:
        topic_clusters = load_topic_clusters()
        cluster_name = pick_next_cluster(posts, topic_clusters)
        pillar_mode = should_make_pillar(posts, cluster_name)
        current_pillar = get_cluster_pillar(posts, cluster_name)
        current_pillar_slug = (current_pillar.get("slug") or "").strip()

        if pillar_mode:
            pillar_pool = build_pillar_keyword_pool(cluster_name, posts, existing_titles)
            if pillar_pool:
                return pillar_pool, cluster_name, "pillar", current_pillar_slug

        seeds = topic_clusters.get(cluster_name) or []
        merged_seed = clean_base + seeds
        merged_seed = [x for x in merged_seed if isinstance(x, str) and x.strip()]

        try:
            cluster_keywords = generate_cluster_keywords(
                cluster_name=cluster_name,
                seed_keywords=merged_seed,
                existing_titles=existing_titles,
                existing_keywords=existing_keywords,
            )
            google_keywords = expand_keywords_from_google(merged_seed, existing_titles, existing_keywords)
            merged_all = clean_base + cluster_keywords + google_keywords
            merged_all = dedupe_keywords(merged_all, existing_titles, existing_keywords)
            if merged_all:
                save_keywords(merged_all)
                pool = [kw for kw in merged_all if not title_too_similar(kw, existing_titles, KEYWORD_SIM_THRESHOLD)]
                return pool, cluster_name, "normal", current_pillar_slug
        except Exception as e:
            print("Cluster keyword generation failed:", e)

        fallback = dedupe_keywords(seeds + clean_base, existing_titles, existing_keywords)
        return fallback, cluster_name, "normal", current_pillar_slug

    auto_keywords: List[str] = []
    if len(clean_base) < MIN_KEYWORD_POOL:
        try:
            auto_keywords = generate_auto_keywords(clean_base or base_keywords, existing_titles, existing_keywords)
            google_keywords = expand_keywords_from_google(clean_base or base_keywords, existing_titles, existing_keywords)
            merged = clean_base + auto_keywords + google_keywords
            merged = dedupe_keywords(merged, existing_titles, existing_keywords)
            if merged:
                save_keywords(merged)
                return merged, "General", "normal", ""
        except Exception as e:
            print("Auto keyword generation failed:", e)

    return clean_base, "General", "normal", ""


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

    if "?" in raw:
        dl = raw + "&fm=jpg&q=80&w=1800&fit=max"
    else:
        dl = raw + "?fm=jpg&q=80&w=1800&fit=max"

    r = requests.get(dl, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)


def get_high_quality_photos_for_queries(slug: str, queries: List[str]) -> Tuple[List[str], List[str]]:
    if not UNSPLASH_ACCESS_KEY:
        raise RuntimeError("Missing UNSPLASH_ACCESS_KEY")

    used_raw = load_json(USED_IMAGES_JSON, {})
    used = ensure_used_schema(used_raw)
    used_ids = set(used.get("unsplash_ids") or [])

    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    chosen: List[dict] = []
    credits: List[str] = []

    if len(queries) != IMG_COUNT:
        queries = (queries or [])[:IMG_COUNT]
        while len(queries) < IMG_COUNT:
            queries.append(slug.replace("-", " "))

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
# Internal links
# -----------------------------
def select_related_posts(
    posts: List[dict],
    *,
    current_slug: str,
    category: str,
    cluster: str,
    pillar_slug: str = "",
    limit: int = 4,
) -> List[dict]:
    scored = []

    for p in posts:
        if not isinstance(p, dict):
            continue
        slug = (p.get("slug") or "").strip()
        if not slug or slug == current_slug:
            continue

        score = 0
        if p.get("cluster") == cluster:
            score += 50
        if p.get("category") == category:
            score += 20
        if p.get("post_type") == "pillar":
            score += 15
        if pillar_slug and slug == pillar_slug:
            score += 100
        score += min(int(p.get("views") or 0), 50)

        date_bonus = 1 if str(p.get("updated") or p.get("date") or "") else 0
        score += date_bonus

        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    seen = set()
    for _, p in scored:
        slug = p.get("slug")
        if slug in seen:
            continue
        seen.add(slug)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def render_related_guides_html(related_posts: List[dict]) -> str:
    if not related_posts:
        return ""

    items = []
    for p in related_posts:
        href = post_href_from_post_page(p)
        title = html_escape(p.get("title") or "Untitled")
        kicker = html_escape(p.get("category") or "Article")
        badge = ""
        if p.get("post_type") == "pillar":
            badge = '<span class="rg-badge">Guide</span>'
        items.append(
            f'<a class="related-guide" href="{href}">'
            f'<span class="rg-kicker">{kicker}</span>'
            f'<span class="rg-title">{title}</span>'
            f'{badge}'
            f'</a>'
        )

    return (
        '<section class="related-guides">'
        '<h2>Related Guides</h2>'
        '<div class="related-guides-list">'
        + "".join(items)
        + "</div></section>"
    )


# -----------------------------
# Writing pipeline
# -----------------------------
def build_strategy_prompt(keyword: str, avoid_titles: List[str], cluster_name: str, post_type: str) -> str:
    avoid_block = "\n".join([f"- {x}" for x in avoid_titles[:30]]) if avoid_titles else "- none"
    category_hint = pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    if post_type == "pillar":
        extra = """
This is a pillar guide.
It should still be deep and practical.
It should explain systems and decision logic clearly.
It must not sound like a generic encyclopedia article.
""".strip()
    else:
        extra = """
This is a cluster article.
It should focus on one sharp operating problem.
It should solve one real situation in detail.
""".strip()

    return f"""
You are planning a deep blog article for US and EU readers.

Cluster:
{cluster_name}

Seed keyword:
{keyword}

Preferred category:
{category_hint}

Avoid titles too similar to:
{avoid_block}

Return valid JSON only.

Schema:
{{
  "audience": "specific reader type",
  "problem": "specific painful situation",
  "outcome": "clear promised result",
  "angle": "specific article angle",
  "title": "specific practical title",
  "description": "155-170 chars meta description not equal to title",
  "category": "AI Tools|Make Money|Productivity|Reviews",
  "intent": "pillar|cluster",
  "search_intent_summary": "one sentence"
}}

Hard rules:
- Do not use title patterns like Best, Top, Ultimate Guide, Comprehensive Guide, Essential Guide, Must-Have
- The title must not simply restate the seed keyword
- The title must sound like a workflow, system, checklist, playbook, framework, setup, or operating guide
- The title must include a specific audience
- The title must include a specific situation or operating context
- The title must imply a concrete problem being solved
- Prefer titles shaped like:
  audience + situation + workflow/system/template/playbook/checklist + problem or outcome
- Bad example: "AI Workflow for Creators"
- Good example style: "A Client Onboarding Workflow for Freelancers Who Want Fewer Back-and-Forth Emails"
- Good example style: "A Weekly Content System for Solo Creators Who Need to Repurpose One Article into Five Assets"
- Avoid vague audiences like everyone, professionals, business owners
- Use a sharper audience such as solo creator, freelance designer, one person consultancy, remote operator, junior marketer, newsletter writer
- Focus on one real situation not a generic roundup
- The angle must feel more specific than common search results
- The article should promise a process or decision framework not a list of tools

{extra}
""".strip()


def parse_strategy_json(text: str, keyword: str = "", cluster_name: str = "", post_type: str = "") -> Dict[str, str]:
    raw = _json_extract(text)
    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("strategy JSON root is not object")

    audience = _clean_text(data.get("audience", ""))
    problem = _clean_text(data.get("problem", ""))
    outcome = _clean_text(data.get("outcome", ""))
    angle = _clean_text(data.get("angle", ""))
    title = _clean_text(data.get("title", ""))
    description = _clean_text(data.get("description", ""))
    category = _clean_text(data.get("category", ""))
    intent = _clean_text(data.get("intent", post_type or "cluster"))
    search_intent_summary = _clean_text(data.get("search_intent_summary", ""))

    if not audience or not problem or not outcome or not angle or not title:
        raise ValueError("strategy fields missing")

    if category not in {"AI Tools", "Make Money", "Productivity", "Reviews"}:
        category = pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    if not description:
        description = short_desc(f"{angle}. {outcome}")

    return {
        "audience": audience,
        "problem": problem,
        "outcome": outcome,
        "angle": angle,
        "title": title,
        "description": description,
        "category": category,
        "intent": intent or post_type,
        "search_intent_summary": search_intent_summary or angle,
    }


def build_outline_prompt(strategy: Dict[str, str], keyword: str, cluster_name: str, post_type: str) -> str:
    return f"""
You are creating a detailed article outline.

Seed keyword:
{keyword}

Cluster:
{cluster_name}

Post type:
{post_type}

Strategy:
{json.dumps(strategy, ensure_ascii=False, indent=2)}

Return valid JSON only.

Schema:
{{
  "title": "must match strategy title",
  "description": "must match strategy description",
  "category": "AI Tools|Make Money|Productivity|Reviews",
  "sections": [
    {{
      "heading": "section heading",
      "goal": "what this section must achieve",
      "image_query": "2-6 words concrete photo idea",
      "must_include": [
        "point 1",
        "point 2"
      ]
    }}
  ],
  "faq_questions": [
    "question 1",
    "question 2"
  ],
  "tldr_focus": [
    "point 1",
    "point 2"
  ]
}}

Hard rules:
- Exactly {IMG_COUNT} sections
- The 7 sections should roughly follow this depth:
  1. sharp setup and who this is for
  2. why common advice fails
  3. the workflow or system map
  4. setup steps
  5. decision rules or tool choice logic
  6. common mistakes and tradeoffs
  7. checklist or template plus when not to use this setup
- Every section must have concrete must_include bullets
- No generic section headings like Introduction, Conclusion, Benefits
- image_query must be visual and photo-friendly
- Keep the angle narrow and practical
- FAQ questions should be realistic follow-up questions
""".strip()


def parse_outline_json(text: str, strategy: Dict[str, str]) -> Dict[str, Any]:
    raw = _json_extract(text)
    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("outline JSON root is not object")

    title = _clean_text(data.get("title", strategy.get("title", "")))
    description = _clean_text(data.get("description", strategy.get("description", "")))
    category = _clean_text(data.get("category", strategy.get("category", "")))

    sections = data.get("sections")
    if not isinstance(sections, list) or len(sections) != IMG_COUNT:
        raise ValueError(f"outline sections must be list of {IMG_COUNT}")

    clean_sections = []
    for s in sections:
        if not isinstance(s, dict):
            raise ValueError("outline section must be object")
        heading = _clean_text(s.get("heading", ""))
        goal = _clean_text(s.get("goal", ""))
        image_query = _clean_text(s.get("image_query", ""))
        must_include = s.get("must_include") or []
        if not isinstance(must_include, list):
            must_include = []
        must_include = [_clean_text(x) for x in must_include if isinstance(x, str) and _clean_text(x)]
        if not heading or not goal or not image_query or len(must_include) < 2:
            raise ValueError("outline section missing required fields")
        clean_sections.append({
            "heading": heading,
            "goal": goal,
            "image_query": image_query,
            "must_include": must_include[:6],
        })

    faq_questions = data.get("faq_questions") or []
    if not isinstance(faq_questions, list):
        faq_questions = []
    faq_questions = [_clean_text(x) for x in faq_questions if isinstance(x, str) and _clean_text(x)][:5]

    tldr_focus = data.get("tldr_focus") or []
    if not isinstance(tldr_focus, list):
        tldr_focus = []
    tldr_focus = [_clean_text(x) for x in tldr_focus if isinstance(x, str) and _clean_text(x)][:5]

    if category not in {"AI Tools", "Make Money", "Productivity", "Reviews"}:
        category = strategy.get("category") or "Productivity"

    return {
        "title": title or strategy.get("title", ""),
        "description": description or strategy.get("description", ""),
        "category": category,
        "sections": clean_sections,
        "faq_questions": faq_questions,
        "tldr_focus": tldr_focus,
    }


def build_article_prompt(
    keyword: str,
    cluster_name: str,
    post_type: str,
    strategy: Dict[str, str],
    outline: Dict[str, Any],
) -> str:
    return f"""
You are writing a deep practical blog article for US and EU readers.

Seed keyword:
{keyword}

Cluster:
{cluster_name}

Post type:
{post_type}

Strategy:
{json.dumps(strategy, ensure_ascii=False, indent=2)}

Outline:
{json.dumps(outline, ensure_ascii=False, indent=2)}

Output MUST be valid JSON only.
No markdown.
No extra text.

JSON schema:
{{
  "title": "string",
  "description": "string",
  "category": "AI Tools|Make Money|Productivity|Reviews",
  "sections": [
    {{
      "heading": "string",
      "image_query": "string",
      "body": "string"
    }}
  ],
  "faq": [
    {{"q":"string","a":"string"}}
  ],
  "tldr": "string"
}}

Hard rules:
- Exactly {IMG_COUNT} sections
- Each section body must be detailed and useful
- Total combined text length must be at least {MIN_CHARS} characters
- Every section body should feel like it was written by someone who understands operations not by a generic SEO writer
- The article must include:
  - who this workflow is for
  - why generic advice usually fails
  - one clean workflow or operating system
  - decision rules or tool choice logic
  - setup steps
  - common mistakes
  - tradeoffs
  - a checklist or template readers can reuse
  - when not to use this setup
- Avoid generic intros and fluffy summaries
- Avoid phrases like "AI is transforming productivity"
- Avoid generic listicle tone
- Do not simply list tools
- Explain why one approach is better in one specific situation
- Use plain English
- Be concrete
- Be original
- Each section must closely follow the outline section goal and must_include items
- Keep section heading and image_query aligned with the outline

Style:
- practical
- sharp
- grounded
- operational
- useful for a real person doing real work

FAQ rules:
- 3 to 5 questions
- realistic follow-up questions only
- concise but useful answers

TLDR rules:
- 2 to 4 sentences
- summarize the system and who it suits
""".strip()


def parse_post_json(text: str, keyword: str = "", cluster_name: str = "", post_type: str = "") -> Dict[str, Any]:
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
        cat = pick_category(keyword or title or "", cluster_name, post_type)

    total_text = (
        (tldr or "") +
        "\n".join([x["heading"] + "\n" + x["body"] for x in clean_sections]) +
        "\n".join([x["q"] + "\n" + x["a"] for x in clean_faq])
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


def generate_deep_post(
    *,
    keyword: str,
    cluster_name: str,
    post_type: str,
    avoid_titles: List[str],
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    strategy_raw = openai_generate_text(build_strategy_prompt(keyword, avoid_titles, cluster_name, post_type))
    strategy = parse_strategy_json(strategy_raw, keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    outline_raw = openai_generate_text(build_outline_prompt(strategy, keyword, cluster_name, post_type))
    outline = parse_outline_json(outline_raw, strategy)

    article_raw = openai_generate_text(build_article_prompt(keyword, cluster_name, post_type, strategy, outline))
    data = parse_post_json(article_raw, keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    if not data.get("description"):
        data["description"] = strategy.get("description") or short_desc(data.get("title", ""))

    if not data.get("category"):
        data["category"] = strategy.get("category") or pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    return data, strategy, outline


def html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def paragraphs_to_html(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    text = text.replace("**", "")
    text = re.sub(r"\s*(\d+\.\s)", r"\n\n\1", text)
    text = re.sub(r"\s*(-\s)", r"\n\n\1", text)
    text = re.sub(r'([.!?])\s+([A-Z])', r'\1\n\n\2', text)

    parts = re.split(r"\n\s*\n+", text)

    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue

        if re.match(r"^\d+\.\s", p):
            lines = [x.strip() for x in p.split("\n") if x.strip()]
            items = []
            for line in lines:
                m = re.match(r"^\d+\.\s+(.*)$", line)
                if m:
                    items.append(f"<li>{html_escape(m.group(1).strip())}</li>")
            if items:
                out.append("<ol>" + "".join(items) + "</ol>")
                continue

        if re.match(r"^-\s", p):
            lines = [x.strip() for x in p.split("\n") if x.strip()]
            items = []
            for line in lines:
                m = re.match(r"^-\s+(.*)$", line)
                if m:
                    items.append(f"<li>{html_escape(m.group(1).strip())}</li>")
            if items:
                out.append("<ul>" + "".join(items) + "</ul>")
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
    related_posts: List[dict],
    post_type: str,
) -> str:
    canonical = f"{SITE_URL}/posts/{slug}.html"
    og_image = f"{SITE_URL}/{image_paths[0]}" if image_paths else ""

    blocks = []
    blocks.append("<h2>TL;DR</h2>")
    blocks.append(paragraphs_to_html(tldr))

    for i in range(IMG_COUNT):
        img_rel = f"../{image_paths[i]}"
        blocks.append(f"<img src=\"{img_rel}\" alt=\"{html_escape(title)}\" loading=\"lazy\">")
        blocks.append(f"<h2>{html_escape(sections[i]['heading'])}</h2>")
        blocks.append(paragraphs_to_html(sections[i]["body"]))

    if faq:
        blocks.append("<h2>FAQ</h2>")
        for item in faq:
            blocks.append(f"<p><strong>{html_escape(item['q'])}</strong><br>{html_escape(item['a'])}</p>")

    related_html = render_related_guides_html(related_posts)
    if related_html:
        blocks.append(related_html)

    if photo_credits_li:
        blocks.append("<h2>Photo credits</h2>")
        blocks.append("<ul>" + "\n".join(photo_credits_li) + "</ul>")

    article_html = "\n".join([b for b in blocks if b])

    adsense_tag = ""
    if ADSENSE_CLIENT:
        adsense_tag = f"""
  <!-- Google AdSense -->
  <script async
  src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={html_escape(ADSENSE_CLIENT)}"
  crossorigin="anonymous"></script>
""".rstrip()

    guide_badge = ""
    if post_type == "pillar":
        guide_badge = '<span class="post-type-badge">Featured Guide</span>'

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
{adsense_tag}
  <style>
    .post-type-badge {{
      display:inline-block;
      margin-bottom:12px;
      padding:6px 10px;
      border-radius:999px;
      font-size:12px;
      font-weight:700;
      background:#eef6ff;
      color:#2563eb;
    }}
    .related-guides {{
      margin-top:40px;
      padding-top:12px;
      border-top:1px solid #e5e7eb;
    }}
    .related-guides-list {{
      display:grid;
      gap:12px;
      margin-top:14px;
    }}
    .related-guide {{
      display:block;
      padding:14px 16px;
      border:1px solid #e5e7eb;
      border-radius:14px;
      text-decoration:none;
      color:inherit;
      background:#fff;
    }}
    .rg-kicker {{
      display:block;
      font-size:12px;
      color:#6b7280;
      margin-bottom:4px;
    }}
    .rg-title {{
      display:block;
      font-weight:700;
      line-height:1.45;
    }}
    .rg-badge {{
      display:inline-block;
      margin-top:8px;
      font-size:11px;
      font-weight:700;
      color:#2563eb;
      background:#eef6ff;
      padding:4px 8px;
      border-radius:999px;
    }}
  </style>
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
        {guide_badge}
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
    keyword: str,
    cluster: str,
    post_type: str,
    pillar_slug: str,
) -> None:
    thumb = image_paths[0] if image_paths else ""

    posts.insert(0, {
        "title": title,
        "slug": slug,
        "category": category,
        "description": description,
        "date": created_iso,
        "updated": created_iso,
        "thumbnail": thumb,
        "image": thumb,
        "url": f"posts/{slug}.html",
        "views": 0,
        "keyword": keyword,
        "cluster": cluster,
        "post_type": post_type,
        "pillar_slug": (pillar_slug or slug) if post_type == "pillar" else pillar_slug
    })


def main() -> int:
    base_keywords = load_keywords()
    posts = load_posts_index()

    existing_slugs = set(p.get("slug") for p in posts if isinstance(p, dict))
    existing_titles = [p.get("title", "") for p in posts if isinstance(p, dict) and p.get("title")]

    keyword_pool, cluster_name, post_type, current_pillar_slug = build_keyword_pool(base_keywords, existing_titles, posts)
    if not keyword_pool:
        print("No keyword pool available.")
        return 0

    used_texts_raw = load_json(USED_TEXTS_JSON, {})
    used_texts = ensure_used_texts_schema(used_texts_raw)
    used_fps = set(used_texts.get("fingerprints") or [])

    made = 0
    tries = 0
    tried_keywords = set()

    while made < POSTS_PER_RUN and tries < MAX_KEYWORD_TRIES:
        tries += 1

        remaining_keywords = [k for k in keyword_pool if normalize_keyword(k) not in tried_keywords]
        if not remaining_keywords:
            print("Keyword pool exhausted for this run.")
            break

        keyword = random.choice(remaining_keywords).strip()
        tried_keywords.add(normalize_keyword(keyword))
        if not keyword:
            continue

        created_iso = now_utc_iso()

        data = None
        strategy = {}
        outline = {}

        for attempt in range(1, MAX_GENERATE_ATTEMPTS + 1):
            try:
                cand, cand_strategy, cand_outline = generate_deep_post(
                    keyword=keyword,
                    cluster_name=cluster_name,
                    post_type=post_type,
                    avoid_titles=existing_titles,
                )
            except Exception as e:
                print("Deep generation failed:", e)
                continue

            cand_title = cand["title"]

            if title_too_similar(cand_title, existing_titles, TITLE_SIM_THRESHOLD):
                print(f"Title too similar (attempt {attempt}). Regenerating.")
                continue

            ok, reason = quality_check_post(cand, keyword=keyword)
            if not ok:
                print(f"Quality check failed ({reason}) (attempt {attempt}). Regenerating.")
                continue

            fp = make_fingerprint(cand_title, cand["sections"], cand["tldr"], cand["faq"])
            if fp in used_fps:
                print(f"Content fingerprint duplicate (attempt {attempt}). Regenerating.")
                continue

            data = cand
            strategy = cand_strategy
            outline = cand_outline
            used_fps.add(fp)
            break

        if not data:
            print("Failed to generate a unique deep post. Skipping keyword.")
            continue

        title = data["title"]
        description = data["description"] or strategy.get("description") or short_desc(title)
        category = data["category"] or strategy.get("category") or pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)
        sections = data["sections"]
        tldr = data["tldr"]
        faq = data["faq"]

        slug = slugify(title)[:80] or slugify(keyword)[:80] or f"post-{int(time.time())}"
        if slug in existing_slugs:
            slug = f"{slug}-{int(time.time())}"

        pillar_slug = current_pillar_slug
        if post_type == "pillar":
            pillar_slug = slug

        queries = [s.get("image_query") for s in sections]
        if len(queries) != IMG_COUNT:
            queries = [title] * IMG_COUNT

        image_paths, credits_li = get_high_quality_photos_for_queries(slug, queries)
        if len(image_paths) < IMG_COUNT:
            print("Could not source 7 high quality photos. Skipping.")
            continue

        related_posts = select_related_posts(
            posts,
            current_slug=slug,
            category=category,
            cluster=cluster_name,
            pillar_slug=current_pillar_slug if post_type != "pillar" else "",
            limit=RELATED_POST_LIMIT,
        )

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
            related_posts=related_posts,
            post_type=post_type,
        )

        html_path = POSTS_DIR / f"{slug}.html"
        safe_write(html_path, html_out)

        add_post_to_index(
            posts,
            title=title,
            slug=slug,
            category=category,
            description=description,
            image_paths=image_paths,
            created_iso=created_iso,
            keyword=keyword,
            cluster=cluster_name,
            post_type=post_type,
            pillar_slug=pillar_slug,
        )
        existing_slugs.add(slug)
        existing_titles.insert(0, title)

        used_texts["fingerprints"] = sorted(list(used_fps))
        save_json(USED_TEXTS_JSON, used_texts)

        print(f"Generated HTML: posts/{slug}.html")
        print(f"Source keyword: {keyword}")
        print(f"Topic cluster: {cluster_name}")
        print(f"Post type: {post_type}")
        print(f"Strategy angle: {strategy.get('angle', '')}")
        made += 1

    if made == 0:
        print("No posts generated this run. Exiting 0 so workflow stays green.")
        return 0

    save_posts_index(posts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

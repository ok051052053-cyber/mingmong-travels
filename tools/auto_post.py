import os
import re
import json
import time
import math
import html
import random
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

import requests
from slugify import slugify
from openai import OpenAI


# =========================================================
# Paths
# =========================================================
ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "posts"
ASSETS_POSTS_DIR = ROOT / "assets" / "posts"
POSTS_JSON = ROOT / "posts.json"
KEYWORDS_JSON = ROOT / "keywords.json"
USED_IMAGES_JSON = ROOT / "used_images.json"
USED_TEXTS_JSON = ROOT / "used_texts.json"
REDIRECTS_JSON = ROOT / "redirects.json"

POSTS_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_POSTS_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# Config
# =========================================================
SITE_NAME = os.environ.get("SITE_NAME", "MingMong").strip()
SITE_URL = os.environ.get("SITE_URL", "https://mingmonglife.com").strip().rstrip("/")
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "1"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL_PLANNER = os.environ.get("MODEL_PLANNER", os.environ.get("MODEL", "gpt-4.1-mini")).strip()
MODEL_WRITER = os.environ.get("MODEL_WRITER", os.environ.get("MODEL", "gpt-4.1-mini")).strip()

MIN_CHARS = int(os.environ.get("MIN_CHARS", "8400"))
MIN_SECTION_CHARS = int(os.environ.get("MIN_SECTION_CHARS", "840"))
MAX_KEYWORD_TRIES = int(os.environ.get("MAX_KEYWORD_TRIES", "12"))
MAX_GENERATE_ATTEMPTS = int(os.environ.get("MAX_GENERATE_ATTEMPTS", "5"))

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "35"))
ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "").strip()

AUTHOR_NAME = os.environ.get("AUTHOR_NAME", "MingMong Editorial").strip()
AUTHOR_URL = os.environ.get("AUTHOR_URL", f"{SITE_URL}/about.html").strip()
SITE_TAGLINE = os.environ.get(
    "SITE_TAGLINE",
    "Practical systems for AI work, solo operations, and creator income."
).strip()

TITLE_SIM_THRESHOLD = float(os.environ.get("TITLE_SIM_THRESHOLD", "0.83"))
KEYWORD_SIM_THRESHOLD = float(os.environ.get("KEYWORD_SIM_THRESHOLD", "0.74"))
TOPIC_SIM_THRESHOLD = float(os.environ.get("TOPIC_SIM_THRESHOLD", "0.70"))
MIN_KEYWORD_POOL = int(os.environ.get("MIN_KEYWORD_POOL", "18"))

GOOGLE_SUGGEST_ENABLED = os.environ.get("GOOGLE_SUGGEST_ENABLED", "1").strip() == "1"
GOOGLE_SUGGEST_MAX_SEEDS = int(os.environ.get("GOOGLE_SUGGEST_MAX_SEEDS", "8"))
GOOGLE_SUGGEST_PER_QUERY = int(os.environ.get("GOOGLE_SUGGEST_PER_QUERY", "8"))
GOOGLE_SUGGEST_SCORE_THRESHOLD = float(os.environ.get("GOOGLE_SUGGEST_SCORE_THRESHOLD", "1.25"))

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "").strip()
SERPAPI_ENGINE = os.environ.get("SERPAPI_ENGINE", "google").strip()
SERP_CHECK_ENABLED = os.environ.get("SERP_CHECK_ENABLED", "1").strip() == "1"
SERP_CHECK_LIMIT = int(os.environ.get("SERP_CHECK_LIMIT", "8"))

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()
ENABLE_WIKIMEDIA = os.environ.get("ENABLE_WIKIMEDIA", "1").strip() == "1"

UNSPLASH_MIN_WIDTH = int(os.environ.get("UNSPLASH_MIN_WIDTH", "1400"))
UNSPLASH_MIN_HEIGHT = int(os.environ.get("UNSPLASH_MIN_HEIGHT", "900"))
UNSPLASH_MIN_LIKES = int(os.environ.get("UNSPLASH_MIN_LIKES", "10"))
UNSPLASH_PER_PAGE = int(os.environ.get("UNSPLASH_PER_PAGE", "30"))

PEXELS_MIN_WIDTH = int(os.environ.get("PEXELS_MIN_WIDTH", "1400"))
PEXELS_MIN_HEIGHT = int(os.environ.get("PEXELS_MIN_HEIGHT", "900"))
PEXELS_PER_PAGE = int(os.environ.get("PEXELS_PER_PAGE", "30"))

PIXABAY_MIN_WIDTH = int(os.environ.get("PIXABAY_MIN_WIDTH", "1400"))
PIXABAY_MIN_HEIGHT = int(os.environ.get("PIXABAY_MIN_HEIGHT", "900"))
PIXABAY_PER_PAGE = int(os.environ.get("PIXABAY_PER_PAGE", "50"))

IMAGE_SOURCE_PRIORITY = [
    "unsplash",
    "pexels",
    "pixabay",
    "wikimedia",
]

RELATED_POST_LIMIT = int(os.environ.get("RELATED_POST_LIMIT", "3"))

CLUSTER_MODE = os.environ.get("CLUSTER_MODE", "1").strip() == "1"
CLUSTER_BATCH = int(os.environ.get("CLUSTER_BATCH", "8"))
CLUSTER_ROTATION_WINDOW = int(os.environ.get("CLUSTER_ROTATION_WINDOW", "18"))
TOPIC_CLUSTERS_JSON = os.environ.get("TOPIC_CLUSTERS_JSON", "").strip()
PILLAR_INTERVAL = int(os.environ.get("PILLAR_INTERVAL", "14"))

SECTION_COUNT_MIN = int(os.environ.get("SECTION_COUNT_MIN", "5"))
SECTION_COUNT_MAX = int(os.environ.get("SECTION_COUNT_MAX", "8"))

SEARCH_JS_VERSION = hashlib.sha1(str(int(time.time() // 3600)).encode("utf-8")).hexdigest()[:8]
BUILD_ID = hashlib.sha1(f"{datetime.now(timezone.utc).isoformat()}-{random.random()}".encode("utf-8")).hexdigest()[:10]


# =========================================================
# Policy
# =========================================================
ALLOWED_CATEGORIES = {
    "AI Tools",
    "Freelance Systems",
    "Creator Income",
    "Productivity",
}

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

SECTION_BLUEPRINTS = [
    [
        "who this is for and the exact operating problem",
        "why usual advice breaks in practice",
        "the workflow map",
        "the setup steps",
        "decision rules and tool choice logic",
        "mistakes and tradeoffs",
        "copyable checklist or template",
    ],
    [
        "who this is for and the trigger moment",
        "what makes the problem expensive",
        "the system design",
        "implementation steps",
        "tool choice and process boundaries",
        "mistakes and failure modes",
        "when not to use this",
        "copyable operating checklist",
    ],
    [
        "who this is for",
        "the broken default approach",
        "the workflow design",
        "step by step setup",
        "decision framework",
        "tradeoffs and limitations",
        "template or checklist",
    ],
]

DEFAULT_TOPIC_CLUSTERS = {
    "AI Productivity": [
        "ai email automation workflow for solo consultants",
        "ai meeting notes to task workflow for small teams",
        "ai report writing workflow for client work",
        "ai document summarization for knowledge workers",
        "chatgpt workflow for solo operators",
        "ai stack for repetitive admin work",
        "ai automation for weekly planning",
        "ai proposal writing workflow for freelancers",
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
        "how to build an ai workflow system for repetitive work",
        "practical ai workflows for knowledge workers",
        "how solo workers can automate weekly office work with ai",
        "ai operating system for one person businesses",
    ],
    "Freelance Operations": [
        "how to run a freelance business with systems",
        "freelance operations system for solo professionals",
        "how freelancers can reduce admin work with repeatable workflows",
        "practical freelance workflows that save time",
    ],
    "Creator Monetization": [
        "how creators can build monetization systems",
        "digital product systems for beginner creators",
        "creator operations playbook for small audiences",
        "how to make money with digital products using repeatable systems",
    ],
}


# =========================================================
# Logging
# =========================================================
def log(stage: str, message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{stage}] {message}")


# =========================================================
# OpenAI
# =========================================================
def _get_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")
    return OpenAI(api_key=OPENAI_API_KEY)


def openai_generate_text(prompt: str, model: str, temperature: float = 0.5) -> str:
    client = _get_openai_client()

    try:
        res = client.responses.create(
            model=model,
            input=prompt,
        )
        text = (getattr(res, "output_text", None) or "").strip()
        if text:
            return text
    except Exception as e:
        log("OPENAI", f"responses.create failed on model={model}: {e}")

    try:
        res = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write useful operational content. "
                        "You avoid shallow SEO filler. "
                        "When asked for JSON you return strict JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        return (res.choices[0].message.content or "").strip()
    except Exception as e:
        raise RuntimeError(f"OpenAI call failed on model={model}: {e}")


# =========================================================
# Date helpers
# =========================================================
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_year_utc() -> int:
    return int(datetime.now(timezone.utc).strftime("%Y"))


# =========================================================
# JSON and filesystem helpers
# =========================================================
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


def short_desc(text: str) -> str:
    t = (text or "").strip()
    if len(t) > 160:
        t = t[:157].rstrip() + "..."
    return t


def ensure_used_schema(raw):
    if isinstance(raw, dict):
        if "asset_ids" not in raw or not isinstance(raw.get("asset_ids"), list):
            raw["asset_ids"] = []
        return raw
    if isinstance(raw, list):
        return {"asset_ids": [x for x in raw if isinstance(x, str)]}
    return {"asset_ids": []}


def ensure_used_texts_schema(raw):
    if isinstance(raw, dict):
        if "fingerprints" not in raw or not isinstance(raw.get("fingerprints"), list):
            raw["fingerprints"] = []
        return raw
    if isinstance(raw, list):
        return {"fingerprints": [x for x in raw if isinstance(x, str)]}
    return {"fingerprints": []}


def _clean_text(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _find_balanced_json(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s

    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    start_positions = [i for i, ch in enumerate(s) if ch in "{["]
    for start in start_positions:
        opener = s[start]
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(s)):
            ch = s[i]

            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = s[start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except Exception:
                        break

    return s


def html_escape(s: str) -> str:
    return html.escape(s or "", quote=True)


# =========================================================
# Text normalization and similarity
# =========================================================
def _norm_title(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_keyword(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_too_similar(new_title: str, existing_titles: List[str], threshold: float) -> bool:
    nt = _norm_title(new_title)
    if not nt:
        return True
    for old in existing_titles[:600]:
        oo = _norm_title(old)
        if not oo:
            continue
        if oo == nt:
            return True
        if similarity_ratio(nt, oo) >= threshold:
            return True
    return False


def keyword_too_similar(a: str, b: str, threshold: float = KEYWORD_SIM_THRESHOLD) -> bool:
    na = normalize_keyword(a)
    nb = normalize_keyword(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return similarity_ratio(na, nb) >= threshold


def similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    set_a = set(a.split())
    set_b = set(b.split())
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    jaccard = inter / union if union else 0.0
    prefix_bonus = 0.12 if a[:24] == b[:24] else 0.0
    return min(1.0, jaccard + prefix_bonus)


def token_signature(text: str, top_n: int = 12) -> str:
    words = [
        w for w in normalize_keyword(text).split()
        if len(w) > 2 and w not in {
            "this", "that", "with", "from", "into", "using", "your", "their",
            "have", "will", "what", "when", "where", "which", "about", "guide",
            "workflow", "system", "checklist", "template", "playbook", "steps",
        }
    ]
    counts = Counter(words)
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:top_n]
    return "|".join([w for w, _ in ranked])


def semantic_overlap_score(a: str, b: str) -> float:
    na = normalize_keyword(a)
    nb = normalize_keyword(b)
    if not na or not nb:
        return 0.0

    wa = set(na.split())
    wb = set(nb.split())
    inter = len(wa & wb)
    union = len(wa | wb)
    jaccard = inter / union if union else 0.0

    sig_a = token_signature(a)
    sig_b = token_signature(b)
    sig_score = similarity_ratio(sig_a, sig_b)

    return round((jaccard * 0.62) + (sig_score * 0.38), 4)


# =========================================================
# Keyword quality
# =========================================================
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
        "setup",
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
        "pricing",
        "crm",
        "admin",
    ]
    if not any(tok in k for tok in intent_tokens):
        return False

    return True


def dedupe_keywords(keywords: List[str], existing_titles: List[str], existing_keywords: List[str]) -> List[str]:
    out: List[str] = []
    seen_norm = set()

    baseline = []
    for x in existing_titles[:800]:
        if isinstance(x, str) and x.strip():
            baseline.append(x)
    for x in existing_keywords[:1500]:
        if isinstance(x, str) and x.strip():
            baseline.append(x)

    for kw in keywords:
        kw = _clean_text(kw)
        if not kw or not is_search_intent_keyword(kw):
            continue

        n = normalize_keyword(kw)
        if not n or n in seen_norm:
            continue

        skip = False
        for ex in baseline:
            if keyword_too_similar(kw, ex):
                skip = True
                break
            if semantic_overlap_score(kw, ex) >= TOPIC_SIM_THRESHOLD:
                skip = True
                break
        if skip:
            continue

        for kept in out:
            if keyword_too_similar(kw, kept):
                skip = True
                break
            if semantic_overlap_score(kw, kept) >= TOPIC_SIM_THRESHOLD:
                skip = True
                break
        if skip:
            continue

        seen_norm.add(n)
        out.append(kw)

    return out


# =========================================================
# Search opportunity validation
# =========================================================
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
    except Exception as e:
        log("SUGGEST", f"Suggest fetch failed for '{query}': {e}")
    return []


def serpapi_search(query: str) -> Dict[str, Any]:
    if not SERPAPI_KEY or not SERP_CHECK_ENABLED:
        return {}

    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": SERPAPI_ENGINE,
                "q": query,
                "api_key": SERPAPI_KEY,
                "num": 10,
                "hl": "en",
                "gl": "us",
            },
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log("SERP", f"SerpAPI failed for '{query}': {e}")
        return {}


def compute_keyword_opportunity(keyword: str, existing_titles: List[str]) -> Tuple[float, Dict[str, Any]]:
    base = normalize_keyword(keyword)
    suggests = fetch_google_suggest(keyword)
    exact_hits = sum(1 for s in suggests if normalize_keyword(s) == base)
    broad_penalty = 0.35 if len(base.split()) < 5 else 0.0
    suggest_richness = len(suggests) / max(GOOGLE_SUGGEST_PER_QUERY, 1)

    diversity_terms = 0
    if suggests:
        token_pool = set()
        for s in suggests:
            token_pool.update(normalize_keyword(s).split())
        diversity_terms = len(token_pool)

    overlap_penalty = 0.0
    for t in existing_titles[:300]:
        overlap_penalty = max(overlap_penalty, semantic_overlap_score(keyword, t) * 0.9)

    serp_penalty = 0.0
    serp_good = 0.0
    serp_checked = False

    if SERPAPI_KEY and SERP_CHECK_ENABLED:
        serp_checked = True
        serp = serpapi_search(keyword)
        organic = serp.get("organic_results") or []
        titles = []
        for item in organic[:10]:
            title = (item.get("title") or "").strip()
            link = (item.get("link") or "").strip().lower()
            if title:
                titles.append(title)
            if any(d in link for d in ["forbes.com", "hubspot.com", "zapier.com", "shopify.com", "semrush.com"]):
                serp_penalty += 0.12
            if "reddit.com" in link or "medium.com" in link:
                serp_good += 0.06

        for t in titles[:8]:
            serp_penalty = max(serp_penalty, semantic_overlap_score(keyword, t) * 0.55)

    score = (
        (suggest_richness * 1.2) +
        (min(diversity_terms / 18.0, 1.0) * 0.8) +
        (exact_hits * 0.08) +
        serp_good -
        broad_penalty -
        overlap_penalty -
        serp_penalty
    )

    details = {
        "suggest_count": len(suggests),
        "suggests": suggests[:8],
        "diversity_terms": diversity_terms,
        "exact_hits": exact_hits,
        "broad_penalty": broad_penalty,
        "overlap_penalty": round(overlap_penalty, 3),
        "serp_checked": serp_checked,
        "serp_penalty": round(serp_penalty, 3),
        "score": round(score, 3),
    }
    return round(score, 3), details


def filter_keywords_by_opportunity(keywords: List[str], existing_titles: List[str]) -> List[str]:
    ranked = []
    checked = 0

    for kw in keywords:
        if checked >= SERP_CHECK_LIMIT and not SERPAPI_KEY:
            ranked.append((GOOGLE_SUGGEST_SCORE_THRESHOLD, kw))
            continue

        score, info = compute_keyword_opportunity(kw, existing_titles)
        checked += 1
        log("KW", f"'{kw}' score={score} details={json.dumps(info, ensure_ascii=False)}")
        if score >= GOOGLE_SUGGEST_SCORE_THRESHOLD:
            ranked.append((score, kw))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [kw for _, kw in ranked]


# =========================================================
# Topic clusters
# =========================================================
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
        except Exception as e:
            log("CLUSTER", f"TOPIC_CLUSTERS_JSON parse failed: {e}")
    return DEFAULT_TOPIC_CLUSTERS


def get_existing_keywords_from_posts(posts: List[dict]) -> List[str]:
    out = []
    for p in posts:
        if not isinstance(p, dict):
            continue
        for key in ["keyword", "title", "slug", "description", "audience", "problem"]:
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


def cluster_recent_saturation(posts: List[dict], cluster_name: str, window: int = 10) -> int:
    recent = posts[:window]
    return sum(1 for p in recent if isinstance(p, dict) and p.get("cluster") == cluster_name)


def should_make_pillar(posts: List[dict], cluster_name: str) -> bool:
    cluster_posts = [p for p in posts if isinstance(p, dict) and p.get("cluster") == cluster_name]
    if not cluster_posts:
        return True

    if not any(p.get("post_type") == "pillar" for p in cluster_posts):
        return True

    regular_count = sum(1 for p in cluster_posts if p.get("post_type") != "pillar")
    if regular_count > 0 and regular_count % max(PILLAR_INTERVAL, 1) == 0:
        recent_cluster = cluster_posts[:6]
        if not any(p.get("post_type") == "pillar" for p in recent_cluster):
            return True
    return False


def get_cluster_pillar(posts: List[dict], cluster_name: str) -> dict:
    for p in posts:
        if not isinstance(p, dict):
            continue
        if p.get("cluster") == cluster_name and p.get("post_type") == "pillar":
            return p
    return {}


# =========================================================
# Category mapping
# =========================================================
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

    if any(x in k for x in [
        "task management",
        "project management",
        "budget tracking",
        "expense tracking",
        "client projects",
        "multiple client",
        "freelancer admin",
        "freelance operations",
    ]):
        return "Freelance Systems"

    if any(x in k for x in ["gumroad", "newsletter", "digital product", "notion template", "monetization", "pricing"]):
        return "Creator Income"

    if any(x in k for x in ["ai", "chatgpt", "claude", "automation", "meeting notes", "summarization", "email automation"]):
        return "AI Tools"

    return "Productivity"


def pick_category(keyword: str, cluster_name: str = "", post_type: str = "") -> str:
    return cluster_to_category(cluster_name, keyword, post_type)


# =========================================================
# Keyword generation
# =========================================================
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
            f"{seed} mistakes",
        ]
        for q in variants:
            pool.extend(fetch_google_suggest(q))

    return dedupe_keywords(pool, existing_titles, existing_keywords)


def build_cluster_keyword_prompt(
    cluster_name: str,
    seed_keywords: List[str],
    existing_titles: List[str],
    existing_keywords: List[str],
) -> str:
    seed_block = "\n".join([f"- {x}" for x in seed_keywords[:30]]) or "- ai workflow automation for solo workers"
    title_block = "\n".join([f"- {x}" for x in existing_titles[:70]])
    existing_kw_block = "\n".join([f"- {x}" for x in existing_keywords[:100]])

    return f"""
You generate SEO blog topic keywords for a site targeting US and EU readers.

Current cluster:
{cluster_name}

Need:
- exactly {CLUSTER_BATCH} keyword ideas
- long-tail keywords only
- practical search intent only
- suitable for a niche site that wants durable traffic
- no outdated years
- no news
- no politics
- no medical or legal advice
- no generic listicles
- no broad "best tools for X" topics
- each keyword must describe a concrete operating problem or workflow
- vary audience, situation, and decision point
- avoid rewording the same onboarding, planning, admin, proposal, or invoicing idea

Avoid topics too similar to these existing post titles:
{title_block if title_block else "- none"}

Avoid topics too similar to these existing keywords:
{existing_kw_block if existing_kw_block else "- none"}

Cluster seeds:
{seed_block}

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
    raw = openai_generate_text(prompt, model=MODEL_PLANNER, temperature=0.6)
    data = json.loads(_find_balanced_json(raw))

    kws = data.get("keywords") or []
    if not isinstance(kws, list):
        return []

    clean = []
    for kw in kws:
        if isinstance(kw, str) and kw.strip():
            clean.append(_clean_text(kw))

    clean = dedupe_keywords(clean, existing_titles, existing_keywords)
    clean = filter_keywords_by_opportunity(clean, existing_titles)
    return clean


def build_general_keyword_prompt(seed_keywords: List[str], existing_titles: List[str], existing_keywords: List[str]) -> str:
    seed_block = "\n".join([f"- {x}" for x in seed_keywords[:30]]) or "- ai workflow automation for solo workers"
    title_block = "\n".join([f"- {x}" for x in existing_titles[:60]])
    existing_kw_block = "\n".join([f"- {x}" for x in existing_keywords[:100]])

    return f"""
You generate SEO blog topic keywords for a site targeting US and EU readers.

Site focus:
1. AI systems for real work
2. Freelance operations
3. Creator monetization systems

Need:
- exactly 14 keyword ideas
- long-tail keywords only
- practical search intent only
- human sounding
- suitable for a newer niche blog
- easier to rank than broad head terms
- no outdated years
- no celebrity or news topics
- no medical, legal, political, or unsafe topics
- no generic definitions
- no broad listicles
- do not create multiple keywords that only reword the same underlying problem

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
    raw = openai_generate_text(prompt, model=MODEL_PLANNER, temperature=0.65)
    data = json.loads(_find_balanced_json(raw))

    kws = data.get("keywords") or []
    if not isinstance(kws, list):
        return []

    clean = []
    for kw in kws:
        if isinstance(kw, str) and kw.strip():
            clean.append(_clean_text(kw))

    clean = dedupe_keywords(clean, existing_titles, existing_keywords)
    clean = filter_keywords_by_opportunity(clean, existing_titles)
    return clean


def build_pillar_keyword_pool(cluster_name: str, posts: List[dict], existing_titles: List[str]) -> List[str]:
    existing_keywords = get_existing_keywords_from_posts(posts)
    base = DEFAULT_PILLAR_TOPICS.get(cluster_name) or []
    google_kw = expand_keywords_from_google(base, existing_titles, existing_keywords)
    merged = dedupe_keywords(base + google_kw, existing_titles, existing_keywords)
    merged = filter_keywords_by_opportunity(merged, existing_titles)
    return merged


def build_keyword_pool(base_keywords: List[str], existing_titles: List[str], posts: List[dict]) -> Tuple[List[str], str, str, str]:
    existing_keywords = get_existing_keywords_from_posts(posts)
    clean_base = dedupe_keywords(base_keywords, existing_titles, existing_keywords)

    if CLUSTER_MODE:
        topic_clusters = load_topic_clusters()
        cluster_name = pick_next_cluster(posts, topic_clusters)

        if cluster_recent_saturation(posts, cluster_name, window=10) >= 3:
            alternatives = [c for c in topic_clusters.keys() if c != cluster_name]
            if alternatives:
                cluster_name = random.choice(alternatives)

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
            merged_all = dedupe_keywords(clean_base + cluster_keywords + google_keywords, existing_titles, existing_keywords)
            merged_all = filter_keywords_by_opportunity(merged_all, existing_titles)
            if merged_all:
                save_keywords(merged_all)
                return merged_all, cluster_name, "normal", current_pillar_slug
        except Exception as e:
            log("KW", f"Cluster keyword generation failed: {e}")

        fallback = dedupe_keywords(seeds + clean_base, existing_titles, existing_keywords)
        fallback = filter_keywords_by_opportunity(fallback, existing_titles)
        return fallback, cluster_name, "normal", current_pillar_slug

    auto_keywords: List[str] = []
    if len(clean_base) < MIN_KEYWORD_POOL:
        try:
            auto_keywords = generate_auto_keywords(clean_base or base_keywords, existing_titles, existing_keywords)
            google_keywords = expand_keywords_from_google(clean_base or base_keywords, existing_titles, existing_keywords)
            merged = dedupe_keywords(clean_base + auto_keywords + google_keywords, existing_titles, existing_keywords)
            merged = filter_keywords_by_opportunity(merged, existing_titles)
            if merged:
                save_keywords(merged)
                return merged, "General", "normal", ""
        except Exception as e:
            log("KW", f"Auto keyword generation failed: {e}")

    clean_base = filter_keywords_by_opportunity(clean_base, existing_titles)
    return clean_base, "General", "normal", ""


# =========================================================
# Strategy and article generation
# =========================================================
def build_planning_prompt(keyword: str, avoid_titles: List[str], cluster_name: str, post_type: str) -> str:
    avoid_block = "\n".join([f"- {x}" for x in avoid_titles[:40]]) if avoid_titles else "- none"
    category_hint = pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)
    blueprint = random.choice(SECTION_BLUEPRINTS)
    section_count = min(max(len(blueprint), SECTION_COUNT_MIN), SECTION_COUNT_MAX)

    post_guidance = """
This is a pillar guide.
It should explain a family of related operating decisions clearly.
It should still be practical and grounded.
It must not sound like an encyclopedia entry.
""" if post_type == "pillar" else """
This is a cluster article.
It should solve one specific operating situation in detail.
It should be narrower than most search results.
"""

    return f"""
You are planning a practical article for US and EU readers.

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
  "category": "AI Tools|Freelance Systems|Creator Income|Productivity",
  "intent": "pillar|cluster",
  "search_intent_summary": "one sentence",
  "section_plan": [
    {{
      "heading": "section heading",
      "goal": "what this section must achieve",
      "image_query": "2-6 words concrete visual idea",
      "visual_type": "photo|diagram|workspace",
      "must_include": ["point 1", "point 2"],
      "alt_hint": "specific image alt text idea"
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
- No title patterns like Best, Top, Ultimate Guide, Comprehensive Guide, Essential Guide
- Do not restate the seed keyword as the title
- The title must include a real audience and a real operating outcome
- Do not use vague audiences like professionals or business owners
- Use a sharper audience such as solo creator, freelance designer, remote operator, newsletter writer, consultant, small agency owner
- Avoid robotic templates repeated across posts
- Keep title under 72 characters when possible
- Section count must be exactly {section_count}
- The section flow should roughly cover this structure:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}
- Keep the article practical not generic
- Each section must be materially distinct
- image_query must be visual and believable
- visual_type should prefer "diagram" for abstract workflow topics and "photo" or "workspace" for concrete environments

{post_guidance}
""".strip()


def parse_planning_json(text: str, keyword: str = "", cluster_name: str = "", post_type: str = "") -> Dict[str, Any]:
    raw = _find_balanced_json(text)
    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("planning JSON root is not object")

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
        raise ValueError("planning fields missing")

    if category not in ALLOWED_CATEGORIES:
        category = pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    section_plan = data.get("section_plan") or []
    if not isinstance(section_plan, list):
        raise ValueError("section_plan must be a list")
    if len(section_plan) < SECTION_COUNT_MIN or len(section_plan) > SECTION_COUNT_MAX:
        raise ValueError(f"section_plan must be between {SECTION_COUNT_MIN} and {SECTION_COUNT_MAX}")

    clean_sections = []
    for s in section_plan:
        if not isinstance(s, dict):
            raise ValueError("section item must be object")
        heading = _clean_text(s.get("heading", ""))
        goal = _clean_text(s.get("goal", ""))
        image_query = _clean_text(s.get("image_query", ""))
        visual_type = _clean_text(s.get("visual_type", "diagram")).lower()
        alt_hint = _clean_text(s.get("alt_hint", ""))
        must_include = s.get("must_include") or []
        if not isinstance(must_include, list):
            must_include = []
        must_include = [_clean_text(x) for x in must_include if isinstance(x, str) and _clean_text(x)]

        if visual_type not in {"photo", "diagram", "workspace"}:
            visual_type = "diagram"

        if not heading or not goal or not image_query or len(must_include) < 2:
            raise ValueError("section_plan item missing required fields")

        clean_sections.append({
            "heading": heading,
            "goal": goal,
            "image_query": image_query,
            "visual_type": visual_type,
            "must_include": must_include[:6],
            "alt_hint": alt_hint or heading,
        })

    faq_questions = data.get("faq_questions") or []
    if not isinstance(faq_questions, list):
        faq_questions = []
    faq_questions = [_clean_text(x) for x in faq_questions if isinstance(x, str) and _clean_text(x)][:5]

    tldr_focus = data.get("tldr_focus") or []
    if not isinstance(tldr_focus, list):
        tldr_focus = []
    tldr_focus = [_clean_text(x) for x in tldr_focus if isinstance(x, str) and _clean_text(x)][:5]

    return {
        "audience": audience,
        "problem": problem,
        "outcome": outcome,
        "angle": angle,
        "title": title,
        "description": description or short_desc(f"{angle}. {outcome}"),
        "category": category,
        "intent": intent or post_type,
        "search_intent_summary": search_intent_summary or angle,
        "section_plan": clean_sections,
        "faq_questions": faq_questions,
        "tldr_focus": tldr_focus,
    }


def build_article_prompt(
    keyword: str,
    cluster_name: str,
    post_type: str,
    planning: Dict[str, Any],
    corrective_note: str = "",
) -> str:
    return (
        f"""
You are writing a practical blog article for US and EU readers.

Seed keyword:
{keyword}

Cluster:
{cluster_name}

Post type:
{post_type}

Planning JSON:
{json.dumps(planning, ensure_ascii=False, indent=2)}

Output must be valid JSON only.

Schema:
{{
  "title": "string",
  "description": "string",
  "category": "AI Tools|Freelance Systems|Creator Income|Productivity",
  "sections": [
    {{
      "heading": "string",
      "image_query": "string",
      "visual_type": "photo|diagram|workspace",
      "alt_text": "string",
      "body": "string"
    }}
  ],
  "faq": [
    {{"q":"string","a":"string"}}
  ],
  "tldr": "string",
}}

Hard rules:
- Use the section_plan exactly as the structural backbone
- Preserve the same number of sections as in section_plan
- Each section must be materially useful
- Total text must be at least {MIN_CHARS} characters
- Aim for 9000 to 11000 characters when the topic supports it
- Each section body must be at least {MIN_SECTION_CHARS} characters
- Most sections should be longer than the minimum
- Use concrete examples, mini-scenarios, edge cases, and decision logic in every section- The article must explicitly include these exact words in natural sentences:
  workflow, checklist, mistake, tradeoff, decision, step
- The article must explicitly include:
  - who this workflow is for
  - why common advice fails
  - decision rules
  - setup steps
  - mistakes
  - tradeoffs
  - a reusable checklist or template
  - when not to use this or do not use this setup
- Do not open with generic filler
- Do not list tools without explaining why the choice fits the situation
- Use plain English
- Be concrete
- Avoid repeating the same sentence pattern across sections
- Include at least 2 sections with examples or edge cases
- FAQ must have 3 to 5 realistic follow-up questions
- TLDR must be 2 to 4 sentences
- editorial_note should briefly explain that the article is reviewed for practical usefulness and updated when workflows change

{corrective_note.strip() if corrective_note else ""}
"""
    ).strip()


def parse_article_json(text: str, keyword: str = "", cluster_name: str = "", post_type: str = "") -> Dict[str, Any]:
    raw = _find_balanced_json(text)
    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("article JSON root is not object")

    title = _clean_text(data.get("title", ""))
    desc = _clean_text(data.get("description", ""))
    cat = _clean_text(data.get("category", ""))

    sections = data.get("sections")
    if not isinstance(sections, list) or len(sections) < SECTION_COUNT_MIN or len(sections) > SECTION_COUNT_MAX:
        raise ValueError(f"sections must be list of {SECTION_COUNT_MIN} to {SECTION_COUNT_MAX}")

    clean_sections = []
    for s in sections:
        if not isinstance(s, dict):
            raise ValueError("section must be object")
        heading = _clean_text(s.get("heading", ""))
        iq = _clean_text(s.get("image_query", ""))
        visual_type = _clean_text(s.get("visual_type", "diagram")).lower()
        alt_text = _clean_text(s.get("alt_text", ""))
        body = _clean_text(s.get("body", ""))
        if visual_type not in {"photo", "diagram", "workspace"}:
            visual_type = "diagram"
        if not heading or not body:
            raise ValueError("section heading/body required")
        clean_sections.append({
            "heading": heading,
            "image_query": iq or heading,
            "visual_type": visual_type,
            "alt_text": alt_text or heading,
            "body": body,
        })

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
    editorial_note = _clean_text(data.get("editorial_note", ""))

    if cat not in ALLOWED_CATEGORIES:
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
    if not editorial_note:
        editorial_note = "This article is reviewed for practical usefulness and updated when the workflow or tool landscape changes."

    return {
        "title": title,
        "description": desc,
        "category": cat,
        "sections": clean_sections,
        "faq": clean_faq,
        "tldr": tldr or short_desc(desc),
        "editorial_note": editorial_note,
    }


def is_generic_title(title: str) -> bool:
    t = _norm_title(title)
    if not t:
        return True

    if any(t.startswith(x) for x in BANNED_TITLE_PATTERNS):
        return True

    broad_bad = [
        "ai tools",
        "productivity tools",
        "freelance tools",
        "creator tools",
        "workplace productivity",
        "digital productivity",
        "business productivity",
        "remote work tools",
    ]
    if t in broad_bad:
        return True

    words = t.split()
    if len(words) < 5:
        return True

    audience_terms = [
        "freelance", "freelancer", "freelancers",
        "creator", "creators",
        "consultant", "consultants",
        "writer", "writers",
        "designer", "designers",
        "marketer", "marketers",
        "remote worker", "remote workers",
        "solo", "small agency", "one person",
        "newsletter", "operator",
    ]
    problem_terms = [
        "workflow", "checklist", "system", "template", "playbook",
        "follow up", "follow-up", "onboarding", "invoice", "proposal",
        "revision", "planning", "task", "email", "automation",
        "deliverables", "admin", "scope", "meeting notes", "crm", "pricing",
    ]
    has_audience = any(x in t for x in audience_terms)
    has_problem = any(x in t for x in problem_terms)

    return not (has_audience and has_problem)


def opening_too_generic(text: str) -> bool:
    t = (text or "").lower().strip()[:550]
    return any(p in t for p in BANNED_OPENING_PHRASES)


def make_fingerprint(title: str, sections: List[Dict[str, str]], tldr: str, faq: List[Dict[str, str]]) -> str:
    parts = [title.strip(), (tldr or "").strip()[:400]]
    for s in sections[:8]:
        parts.append((s.get("heading") or "").strip())
        parts.append((s.get("body") or "").strip()[:500])
    for item in (faq or [])[:5]:
        parts.append((item.get("q") or "").strip()[:200])
        parts.append((item.get("a") or "").strip()[:200])

    joined = "\n".join([p for p in parts if p])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def build_retry_corrections(reason: str, planning: Dict[str, Any]) -> str:
    audience = (planning.get("audience") or "freelancers").strip()

    if reason == "missing-audience-framing":
        return f"""
Retry correction:
- The first section must explicitly say who this workflow is for
- The audience must be named directly as: {audience}
"""

    if reason == "missing-depth-signals":
        return """
Retry correction:
- Explicitly include these exact words in natural sentences:
workflow, checklist, mistake, tradeoff, decision, step
"""

    if reason == "missing-template-checklist":
        return """
Retry correction:
- Include a clearly reusable checklist or template section
- Use the exact word checklist or template
"""

    if reason == "missing-mistakes":
        return """
Retry correction:
- Include at least two concrete mistakes or one common pitfall section
"""

    if reason == "missing-tradeoff":
        return """
Retry correction:
- Use the exact word tradeoff and explain at least one tradeoff
"""

    if reason == "missing-limitations":
        return """
Retry correction:
- Include 'when not to use this' or 'do not use this setup'
"""

    if reason == "thin-section":
        return """
Retry correction:
- Expand the weaker sections with examples, edge cases, and decision logic
"""

    return """
Retry correction:
- Make the article more distinct, more concrete, and less templated
"""


def quality_check_post(data: Dict[str, Any], keyword: str = "") -> Tuple[bool, str]:
    title = data.get("title", "")
    tldr = data.get("tldr", "")
    sections = data.get("sections", [])
    faq = data.get("faq", [])

    if is_generic_title(title):
        return False, "generic-title"

    if not isinstance(sections, list) or len(sections) < SECTION_COUNT_MIN or len(sections) > SECTION_COUNT_MAX:
        return False, "bad-sections"

    joined = "\n".join(
        [title, tldr] +
        [s.get("heading", "") + "\n" + s.get("body", "") for s in sections] +
        [item.get("q", "") + "\n" + item.get("a", "") for item in faq]
    ).lower()

    if len(joined) < MIN_CHARS:
        return False, "too-short"

    if opening_too_generic(tldr + "\n" + sections[0].get("body", "")):
        return False, "generic-opening"

    if any(len((s.get("body") or "").strip()) < MIN_SECTION_CHARS for s in sections):
        return False, "thin-section"

    section_headings = [_norm_title(s.get("heading", "")) for s in sections]
    if len(set(section_headings)) < len(section_headings):
        return False, "duplicate-headings"

    signal_hits = sum(1 for x in REQUIRED_CONTENT_SIGNALS if x in joined)
    if signal_hits < 4:
        return False, "missing-depth-signals"

    if "who this workflow is for" not in joined and "this workflow is for" not in joined and "who this is for" not in joined:
        return False, "missing-audience-framing"

    if "mistake" not in joined and "common pitfall" not in joined and "go wrong" not in joined:
        return False, "missing-mistakes"

    if "checklist" not in joined and "template" not in joined and "copy this" not in joined:
        return False, "missing-template-checklist"

    if "tradeoff" not in joined and "trade-off" not in joined:
        return False, "missing-tradeoff"

    if "when not to use this" not in joined and "do not use this setup" not in joined:
        return False, "missing-limitations"

    nk = normalize_keyword(keyword)
    nt = normalize_keyword(title)
    if nk and nt and nk == nt:
        return False, "title-too-close-to-keyword"

    return True, "ok"


def post_semantically_too_close(
    keyword: str,
    planning: Dict[str, Any],
    posts: List[dict],
    threshold: float = TOPIC_SIM_THRESHOLD,
) -> bool:
    new_parts = [
        normalize_keyword(keyword),
        normalize_keyword(planning.get("audience", "")),
        normalize_keyword(planning.get("problem", "")),
        normalize_keyword(planning.get("outcome", "")),
        normalize_keyword(planning.get("angle", "")),
        normalize_keyword(planning.get("title", "")),
    ]
    new_text = " ".join([x for x in new_parts if x]).strip()
    if not new_text:
        return False

    recent_posts = posts[:160]
    for p in recent_posts:
        if not isinstance(p, dict):
            continue

        old_parts = [
            normalize_keyword(p.get("keyword", "")),
            normalize_keyword(p.get("title", "")),
            normalize_keyword(p.get("description", "")),
            normalize_keyword(p.get("audience", "")),
            normalize_keyword(p.get("problem", "")),
            normalize_keyword(p.get("cluster", "")),
            normalize_keyword(p.get("category", "")),
        ]
        old_text = " ".join([x for x in old_parts if x]).strip()
        if not old_text:
            continue

        if semantic_overlap_score(new_text, old_text) >= threshold:
            return True

    return False


def generate_deep_post(
    *,
    keyword: str,
    cluster_name: str,
    post_type: str,
    avoid_titles: List[str],
    corrective_note: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    planning_raw = openai_generate_text(
        build_planning_prompt(keyword, avoid_titles, cluster_name, post_type),
        model=MODEL_PLANNER,
        temperature=0.55,
    )
    planning = parse_planning_json(planning_raw, keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    article_raw = openai_generate_text(
        build_article_prompt(keyword, cluster_name, post_type, planning, corrective_note=corrective_note),
        model=MODEL_WRITER,
        temperature=0.6,
    )
    data = parse_article_json(article_raw, keyword=keyword, cluster_name=cluster_name, post_type=post_type)

    if not data.get("description"):
        data["description"] = planning.get("description") or short_desc(data.get("title", ""))

    if not data.get("category"):
        data["category"] = planning.get("category") or pick_category(
            keyword=keyword,
            cluster_name=cluster_name,
            post_type=post_type,
        )

    return data, planning


# =========================================================
# Images and visuals
# =========================================================
def sanitize_query_for_image(q: str) -> str:
    q = (q or "").strip()
    q = re.sub(
        r"\b(workflow|system|checklist|template|playbook|automation|process|guide|how to)\b",
        "",
        q,
        flags=re.IGNORECASE,
    )
    q = re.sub(r"\s+", " ", q).strip()
    return q or "workspace desk laptop"


def normalize_asset_id(source: str, raw_id: str) -> str:
    return f"{source}:{raw_id}"


def score_query_match(query: str, haystack: str) -> float:
    q = normalize_keyword(query)
    h = normalize_keyword(haystack)
    if not q or not h:
        return 0.0
    return similarity_ratio(q, h)


def build_image_alt(title: str, heading: str, image_query: str) -> str:
    base = (heading or image_query or title or "article visual").strip()
    base = re.sub(r"\s+", " ", base).strip()
    if len(base) > 140:
        base = base[:137].rstrip() + "..."
    return base


# -----------------------------
# Unsplash
# -----------------------------
def unsplash_search(query: str, page: int = 1) -> List[dict]:
    if not UNSPLASH_ACCESS_KEY:
        return []

    try:
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
        data = r.json()
        results = data.get("results") or []

        out = []
        for item in results:
            try:
                pid = str(item.get("id") or "").strip()
                if not pid:
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
                raw = urls.get("raw") or urls.get("full") or urls.get("regular")
                if not raw:
                    continue

                user = item.get("user") or {}
                user_name = (user.get("name") or "").strip()
                user_link = ((user.get("links") or {}).get("html") or "").strip()
                page_link = ((item.get("links") or {}).get("html") or "").strip()
                if not user_name or not user_link or not page_link:
                    continue

                desc = " ".join([
                    str(item.get("description") or ""),
                    str(item.get("alt_description") or ""),
                    user_name,
                ]).strip()

                out.append({
                    "source": "unsplash",
                    "id": normalize_asset_id("unsplash", pid),
                    "raw_id": pid,
                    "width": w,
                    "height": h,
                    "score": score_query_match(query, desc) + min(likes / 500.0, 0.4),
                    "download_url": raw,
                    "page_url": page_link,
                    "creator_name": user_name,
                    "creator_url": user_link,
                })
            except Exception:
                continue

        out.sort(key=lambda x: x["score"], reverse=True)
        return out
    except Exception as e:
        log("IMG", f"Unsplash search failed for '{query}': {e}")
        return []


# -----------------------------
# Pexels
# -----------------------------
def pexels_search(query: str, page: int = 1) -> List[dict]:
    if not PEXELS_API_KEY:
        return []

    try:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_API_KEY}
        params = {
            "query": query,
            "page": page,
            "per_page": PEXELS_PER_PAGE,
            "orientation": "landscape",
        }
        r = requests.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        results = data.get("photos") or []

        out = []
        for item in results:
            try:
                pid = str(item.get("id") or "").strip()
                if not pid:
                    continue

                w = int(item.get("width") or 0)
                h = int(item.get("height") or 0)
                if w < PEXELS_MIN_WIDTH or h < PEXELS_MIN_HEIGHT:
                    continue

                ratio = w / max(h, 1)
                if ratio < 1.2 or ratio > 2.2:
                    continue

                src = item.get("src") or {}
                download_url = src.get("large2x") or src.get("large") or src.get("original")
                if not download_url:
                    continue

                creator_name = (item.get("photographer") or "").strip()
                creator_url = (item.get("photographer_url") or "").strip()
                page_url = (item.get("url") or "").strip()

                desc = " ".join([
                    creator_name,
                    str(item.get("alt") or ""),
                    str(item.get("avg_color") or ""),
                ]).strip()

                out.append({
                    "source": "pexels",
                    "id": normalize_asset_id("pexels", pid),
                    "raw_id": pid,
                    "width": w,
                    "height": h,
                    "score": score_query_match(query, desc),
                    "download_url": download_url,
                    "page_url": page_url or creator_url,
                    "creator_name": creator_name or "Pexels contributor",
                    "creator_url": creator_url or "https://www.pexels.com",
                })
            except Exception:
                continue

        out.sort(key=lambda x: x["score"], reverse=True)
        return out
    except Exception as e:
        log("IMG", f"Pexels search failed for '{query}': {e}")
        return []


# -----------------------------
# Pixabay
# -----------------------------
def pixabay_search(query: str, page: int = 1) -> List[dict]:
    if not PIXABAY_API_KEY:
        return []

    try:
        url = "https://pixabay.com/api/"
        params = {
            "key": PIXABAY_API_KEY,
            "q": query,
            "image_type": "photo",
            "orientation": "horizontal",
            "safesearch": "true",
            "page": page,
            "per_page": PIXABAY_PER_PAGE,
        }
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        results = data.get("hits") or []

        out = []
        for item in results:
            try:
                pid = str(item.get("id") or "").strip()
                if not pid:
                    continue

                w = int(item.get("imageWidth") or 0)
                h = int(item.get("imageHeight") or 0)
                if w < PIXABAY_MIN_WIDTH or h < PIXABAY_MIN_HEIGHT:
                    continue

                ratio = w / max(h, 1)
                if ratio < 1.2 or ratio > 2.2:
                    continue

                download_url = (item.get("largeImageURL") or item.get("webformatURL") or "").strip()
                if not download_url:
                    continue

                creator_name = (item.get("user") or "").strip()
                page_url = (item.get("pageURL") or "").strip()
                tags = (item.get("tags") or "").strip()

                out.append({
                    "source": "pixabay",
                    "id": normalize_asset_id("pixabay", pid),
                    "raw_id": pid,
                    "width": w,
                    "height": h,
                    "score": score_query_match(query, tags),
                    "download_url": download_url,
                    "page_url": page_url or "https://pixabay.com",
                    "creator_name": creator_name or "Pixabay contributor",
                    "creator_url": "https://pixabay.com",
                })
            except Exception:
                continue

        out.sort(key=lambda x: x["score"], reverse=True)
        return out
    except Exception as e:
        log("IMG", f"Pixabay search failed for '{query}': {e}")
        return []


# -----------------------------
# Wikimedia Commons
# -----------------------------
def wikimedia_search(query: str, page: int = 1) -> List[dict]:
    if not ENABLE_WIKIMEDIA:
        return []

    try:
        offset = (page - 1) * 20
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": 6,
            "gsrlimit": 20,
            "gsroffset": offset,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 1800,
            "format": "json",
            "origin": "*",
        }
        r = requests.get("https://commons.wikimedia.org/w/api.php", params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}

        out = []
        for _, item in pages.items():
            try:
                title = str(item.get("title") or "").strip()
                if not title:
                    continue

                pageid = str(item.get("pageid") or title).strip()
                imageinfo = item.get("imageinfo") or []
                if not imageinfo:
                    continue

                info = imageinfo[0]
                thumb = (info.get("thumburl") or info.get("url") or "").strip()
                if not thumb:
                    continue

                w = int(info.get("thumbwidth") or info.get("width") or 0)
                h = int(info.get("thumbheight") or info.get("height") or 0)
                if w < 1000 or h < 600:
                    continue

                ratio = w / max(h, 1)
                if ratio < 1.1 or ratio > 2.4:
                    continue

                page_url = f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}"
                desc = " ".join([
                    title,
                    str(item.get("snippet") or ""),
                ]).strip()

                out.append({
                    "source": "wikimedia",
                    "id": normalize_asset_id("wikimedia", pageid),
                    "raw_id": pageid,
                    "width": w,
                    "height": h,
                    "score": score_query_match(query, desc),
                    "download_url": thumb,
                    "page_url": page_url,
                    "creator_name": "Wikimedia Commons",
                    "creator_url": "https://commons.wikimedia.org",
                })
            except Exception:
                continue

        out.sort(key=lambda x: x["score"], reverse=True)
        return out
    except Exception as e:
        log("IMG", f"Wikimedia search failed for '{query}': {e}")
        return []


def search_source(source: str, query: str, page: int = 1) -> List[dict]:
    if source == "unsplash":
        return unsplash_search(query, page=page)
    if source == "pexels":
        return pexels_search(query, page=page)
    if source == "pixabay":
        return pixabay_search(query, page=page)
    if source == "wikimedia":
        return wikimedia_search(query, page=page)
    return []


def download_asset(asset: dict, out_path: Path) -> None:
    url = asset.get("download_url") or ""
    if not url:
        raise RuntimeError("download_url missing")

    if asset.get("source") == "unsplash":
        if "?" in url:
            url = url + "&fm=jpg&q=80&w=1800&fit=max"
        else:
            url = url + "?fm=jpg&q=80&w=1800&fit=max"

    r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)


def create_svg_visual(out_path: Path, title: str, subtitle: str, badge: str = "Workflow Visual") -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def esc(x: str) -> str:
        return html_escape(x)

    title = title[:72]
    subtitle = subtitle[:120]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-label="{esc(title)}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fbff"/>
      <stop offset="100%" stop-color="#eef4ff"/>
    </linearGradient>
  </defs>
  <rect width="1600" height="900" fill="url(#bg)"/>
  <rect x="90" y="90" width="1420" height="720" rx="34" fill="#ffffff" stroke="#dbe5f3"/>
  <rect x="140" y="140" width="260" height="44" rx="22" fill="#eaf2ff"/>
  <text x="170" y="168" font-family="Arial, Helvetica, sans-serif" font-size="20" fill="#2563eb" font-weight="700">{esc(badge)}</text>

  <text x="140" y="280" font-family="Arial, Helvetica, sans-serif" font-size="52" fill="#0f172a" font-weight="700">{esc(title)}</text>
  <text x="140" y="350" font-family="Arial, Helvetica, sans-serif" font-size="28" fill="#475569">{esc(subtitle)}</text>

  <rect x="140" y="430" width="350" height="170" rx="24" fill="#f8fafc" stroke="#e2e8f0"/>
  <rect x="560" y="430" width="350" height="170" rx="24" fill="#f8fafc" stroke="#e2e8f0"/>
  <rect x="980" y="430" width="350" height="170" rx="24" fill="#f8fafc" stroke="#e2e8f0"/>

  <text x="175" y="500" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="#0f172a" font-weight="700">Input</text>
  <text x="595" y="500" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="#0f172a" font-weight="700">Decision</text>
  <text x="1015" y="500" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="#0f172a" font-weight="700">Output</text>

  <line x1="490" y1="515" x2="560" y2="515" stroke="#94a3b8" stroke-width="6"/>
  <polygon points="560,515 540,503 540,527" fill="#94a3b8"/>
  <line x1="910" y1="515" x2="980" y2="515" stroke="#94a3b8" stroke-width="6"/>
  <polygon points="980,515 960,503 960,527" fill="#94a3b8"/>

  <text x="140" y="705" font-family="Arial, Helvetica, sans-serif" font-size="22" fill="#64748b">Generated by {esc(SITE_NAME)}</text>
</svg>"""
    out_path.write_text(svg, encoding="utf-8")


def find_best_asset_for_query(query: str, used_ids: set) -> Optional[dict]:
    clean_query = sanitize_query_for_image(query)
    candidates: List[dict] = []

    for source in IMAGE_SOURCE_PRIORITY:
        for page in [1, 2]:
            results = search_source(source, clean_query, page=page)
            if not results:
                continue

            for asset in results:
                if asset["id"] in used_ids:
                    continue
                candidates.append(asset)

            if candidates:
                break

        if candidates:
            break

    if not candidates:
        return None

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[0]


def build_image_asset_for_section(
    slug: str,
    idx: int,
    heading: str,
    image_query: str,
    visual_type: str,
    alt_hint: str,
    used_ids: set,
) -> Tuple[str, str, Optional[str], set]:
    folder = ASSETS_POSTS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    clean_query = " ".join([
        (image_query or "").strip(),
        (heading or "").strip(),
    ]).strip() or "modern office workspace laptop notes"
    alt_text = alt_hint or build_image_alt(heading, heading, clean_query)

    should_try_external = len(clean_query.split()) >= 1
    if should_try_external:
        asset = find_best_asset_for_query(clean_query, used_ids)

        if asset:
            used_ids.add(asset["id"])
            ext_path = folder / f"{idx}.jpg"
            try:
                download_asset(asset, ext_path)
                rel_path = f"assets/posts/{slug}/{idx}.jpg"

                creator_name = html_escape(asset.get("creator_name") or asset.get("source", "Image source"))
                creator_url = html_escape(asset.get("creator_url") or asset.get("page_url") or "#")
                page_url = html_escape(asset.get("page_url") or creator_url)
                source_label = html_escape(asset.get("source", "source").title())

                photo_credit_html = (
                    f'<li>Photo {idx}: '
                    f'<a href="{creator_url}" target="_blank" rel="noopener noreferrer">{creator_name}</a> '
                    f'via <a href="{page_url}" target="_blank" rel="noopener noreferrer">{source_label}</a></li>'
                )
                return rel_path, alt_text, photo_credit_html, used_ids
            except Exception as e:
                log("IMG", f"Download failed for '{clean_query}' from {asset.get('source')}: {e}")

    return "", alt_text, None, used_ids

def build_visual_assets(slug: str, sections: List[Dict[str, str]]) -> Tuple[List[str], List[str], List[str]]:
    used_raw = load_json(USED_IMAGES_JSON, {})
    used = ensure_used_schema(used_raw)
    used_ids = set(used.get("asset_ids") or [])

    image_paths: List[str] = []
    alt_texts: List[str] = []
    credits_li: List[str] = []

    for i, sec in enumerate(sections, start=1):
        path, alt, credit, used_ids = build_image_asset_for_section(
            slug=slug,
            idx=i,
            heading=sec.get("heading", f"Section {i}"),
            image_query=sec.get("image_query", sec.get("heading", "")),
            visual_type=sec.get("visual_type", "diagram"),
            alt_hint=sec.get("alt_text", sec.get("alt_hint", sec.get("heading", ""))),
            used_ids=used_ids,
        )
        image_paths.append(path)
        alt_texts.append(alt or sec.get("heading", f"Section {i}"))
        if credit:
            credits_li.append(credit)

    used["asset_ids"] = sorted(list(used_ids))
    save_json(USED_IMAGES_JSON, used)

    return image_paths, alt_texts, credits_li


# =========================================================
# Internal links
# =========================================================
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

        date_text = str(p.get("updated") or p.get("date") or "")
        if date_text:
            score += 2

        if p.get("keyword") and p.get("title"):
            score += int(semantic_overlap_score(category + " " + cluster, (p.get("category") or "") + " " + (p.get("cluster") or "")) * 10)

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


# =========================================================
# Slug and redirects
# =========================================================
def build_clean_slug(title: str, keyword: str = "") -> str:
    raw = slugify(title) or slugify(keyword) or f"post-{int(time.time())}"
    raw = raw[:72].strip("-")
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if len(raw) < 12:
        raw = f"{raw}-{int(time.time())}"
    return raw


def load_redirects() -> Dict[str, str]:
    raw = load_json(REDIRECTS_JSON, {})
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    return {}


def save_redirects(data: Dict[str, str]) -> None:
    save_json(REDIRECTS_JSON, data)


def normalize_existing_post(p: dict) -> dict:
    if not isinstance(p, dict):
        return p

    slug = (p.get("slug") or "").strip()
    title = (p.get("title") or "").strip()
    keyword = (p.get("keyword") or "").strip()
    cluster = (p.get("cluster") or "").strip()
    post_type = (p.get("post_type") or "normal").strip()

    if title:
        title = re.sub(r"\bin (2019|2020|2021|2022|2023|2024)\b", f"in {current_year_utc()}", title, flags=re.IGNORECASE)

    if slug:
        slug = slug.strip("-")[:72]
    elif title or keyword:
        slug = build_clean_slug(title or keyword, keyword)

    url = resolve_post_url_path(p)
    category = p.get("category") or pick_category(keyword=keyword or title, cluster_name=cluster, post_type=post_type)

    if category not in ALLOWED_CATEGORIES:
        category = pick_category(keyword=keyword or title, cluster_name=cluster, post_type=post_type)

    p["title"] = title
    p["slug"] = slug
    p["url"] = url if url else f"posts/{slug}.html"
    p["category"] = category

    if not p.get("description"):
        p["description"] = short_desc(title)

    if p["url"].endswith(".md"):
        p["url"] = p["url"][:-3] + ".html"

    if "updated" not in p and p.get("date"):
        p["updated"] = p["date"]

    return p


# =========================================================
# HTML rendering helpers
# =========================================================
def paragraphs_to_html(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n+", text)

    out = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue

        if all(re.match(r"^\d+\.\s+", ln) for ln in lines):
            items = []
            for ln in lines:
                m = re.match(r"^\d+\.\s+(.*)$", ln)
                if m:
                    items.append(f"<li>{html_escape(m.group(1).strip())}</li>")
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        if all(re.match(r"^[-*]\s+", ln) for ln in lines):
            items = []
            for ln in lines:
                m = re.match(r"^[-*]\s+(.*)$", ln)
                if m:
                    items.append(f"<li>{html_escape(m.group(1).strip())}</li>")
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        para = " ".join(lines)
        out.append(f"<p>{html_escape(para)}</p>")

    return "\n".join(out)


def build_json_ld(
    *,
    title: str,
    description: str,
    canonical: str,
    og_image: str,
    updated_iso: str,
    faq: List[Dict[str, str]],
    category: str,
) -> str:
    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "mainEntityOfPage": canonical,
        "image": [og_image] if og_image else [],
        "datePublished": updated_iso,
        "dateModified": updated_iso,
        "author": {
            "@type": "Organization",
            "name": AUTHOR_NAME,
            "url": AUTHOR_URL,
        },
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_URL,
        },
        "articleSection": category,
    }

    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{SITE_URL}/index.html"},
            {"@type": "ListItem", "position": 2, "name": category, "item": f"{SITE_URL}/category.html?cat={category.replace(' ', '%20')}"},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
        ],
    }

    blocks = [
        f'<script type="application/ld+json">{json.dumps(article, ensure_ascii=False)}</script>',
        f'<script type="application/ld+json">{json.dumps(breadcrumb, ensure_ascii=False)}</script>',
    ]

    if faq:
        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["q"],
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": item["a"],
                    },
                }
                for item in faq
            ],
        }
        blocks.append(f'<script type="application/ld+json">{json.dumps(faq_schema, ensure_ascii=False)}</script>')

    return "\n".join(blocks)


def render_post_html(
    *,
    title: str,
    description: str,
    category: str,
    updated_iso: str,
    slug: str,
    image_paths: List[str],
    alt_texts: List[str],
    sections: List[Dict[str, str]],
    tldr: str,
    faq: List[Dict[str, str]],
    photo_credits_li: List[str],
    related_posts: List[dict],
    post_type: str,
    editorial_note: str,
) -> str:
    canonical = f"{SITE_URL}/posts/{slug}.html"
    og_image = f"{SITE_URL}/{image_paths[0]}" if image_paths else ""

    blocks = []
    blocks.append("<h2>TL;DR</h2>")
    blocks.append(paragraphs_to_html(tldr))

    for i, sec in enumerate(sections):
        img_path = image_paths[i] if i < len(image_paths) else ""
        alt = html_escape(alt_texts[i] if i < len(alt_texts) else sec.get("heading", title))

        blocks.append(f"<h2>{html_escape(sec['heading'])}</h2>")

        section_body_html = paragraphs_to_html(sec["body"])

        if img_path:
            img_rel = f"../{img_path}"
            blocks.append(
                f'''
    <div class="section-media-block">
      <figure class="section-float">
        <img src="{img_rel}" alt="{alt}" loading="lazy">
        <figcaption>{alt}</figcaption>
      </figure>
      {section_body_html}
    </div>
    '''.strip()
            )
        else:
            blocks.append(section_body_html)

    if faq:
        blocks.append("<h2>FAQ</h2>")
        for item in faq:
            blocks.append(f"<p><strong>{html_escape(item['q'])}</strong><br>{html_escape(item['a'])}</p>")

    related_html = render_related_guides_html(related_posts)
    if related_html:
        blocks.append(related_html)

    blocks.append("""
<div class="post-search-block">
  <h2 class="post-search-title">Search more articles</h2>
  <p class="post-search-sub">Find related tools, workflows, and guides.</p>
  <form class="site-search-form js-inline-search-form" autocomplete="off">
    <div class="site-search-bar">
      <span class="site-search-icon">🔍</span>
      <input
        type="search"
        class="site-search-input js-inline-search-input"
        placeholder="Search guides, workflows, templates"
        aria-label="Search guides, workflows, templates"
      />
      <button type="submit" class="site-search-submit">Search</button>
    </div>
  </form>
  <div class="site-search-inline-results js-inline-search-results"></div>
</div>
""".strip())

    if photo_credits_li:
        blocks.append("<h2>Photo credits</h2>")
        blocks.append("<ul>" + "\n".join(photo_credits_li) + "</ul>")

    article_html = "\n".join([b for b in blocks if b])

    adsense_tag = ""
    if ADSENSE_CLIENT:
        adsense_tag = f"""
  <script async
  src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={html_escape(ADSENSE_CLIENT)}"
  crossorigin="anonymous"></script>
""".rstrip()

    guide_badge = ""
    if post_type == "pillar":
        guide_badge = '<span class="post-type-badge">Featured Guide</span>'

    json_ld = build_json_ld(
        title=title,
        description=description,
        canonical=canonical,
        og_image=og_image,
        updated_iso=updated_iso,
        faq=faq,
        category=category,
    )

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

  <meta name="author" content="{html_escape(AUTHOR_NAME)}">
  <meta name="article:section" content="{html_escape(category)}">
  <meta name="robots" content="index,follow,max-image-preview:large">

  <link rel="stylesheet" href="../style.css?v=10">
{adsense_tag}
{json_ld}
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
        <p class="post-dek">{html_escape(description)}</p>
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
        <h3>About this site</h3>
        <p>{html_escape(SITE_TAGLINE)}</p>
        <p>Written and reviewed by {html_escape(AUTHOR_NAME)}.</p>
      </div>

      <div class="sidecard">
        <h3>Categories</h3>
        <div class="catlist">
          <a class="catitem" href="../category.html?cat=AI%20Tools"><span class="caticon">🤖</span><span class="cattext"><span class="catname">AI Tools</span><span class="catsub">Automation and systems</span></span></a>
          <a class="catitem" href="../category.html?cat=Freelance%20Systems"><span class="caticon">📋</span><span class="cattext"><span class="catname">Freelance Systems</span><span class="catsub">Client ops and admin</span></span></a>
          <a class="catitem" href="../category.html?cat=Creator%20Income"><span class="caticon">💰</span><span class="cattext"><span class="catname">Creator Income</span><span class="catsub">Templates and monetization</span></span></a>
          <a class="catitem" href="../category.html?cat=Productivity"><span class="caticon">⚡</span><span class="cattext"><span class="catname">Productivity</span><span class="catsub">Focus and workflow</span></span></a>
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

<script src="../search.js?v={SEARCH_JS_VERSION}"></script>

</body>
</html>
""".strip()


# =========================================================
# Post index
# =========================================================
def load_posts_index() -> List[dict]:
    data = load_json(POSTS_JSON, [])
    posts = data if isinstance(data, list) else []
    normalized = [normalize_existing_post(p) for p in posts if isinstance(p, dict)]
    return normalized


def save_posts_index(posts: List[dict]) -> None:
    clean = [normalize_existing_post(p) for p in posts if isinstance(p, dict)]
    save_json(POSTS_JSON, clean)


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
    planning: Dict[str, Any],
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
        "keyword": keyword,
        "cluster": cluster,
        "post_type": post_type,
        "pillar_slug": (pillar_slug or slug) if post_type == "pillar" else pillar_slug,
        "audience": planning.get("audience", ""),
        "problem": planning.get("problem", ""),
        "outcome": planning.get("outcome", ""),
        "angle": planning.get("angle", ""),
    })


# =========================================================
# Main
# =========================================================
def main() -> int:
    base_keywords = load_keywords()
    posts = load_posts_index()
    redirects = load_redirects()

    existing_slugs = set(p.get("slug") for p in posts if isinstance(p, dict))
    existing_titles = [p.get("title", "") for p in posts if isinstance(p, dict) and p.get("title")]

    keyword_pool, cluster_name, post_type, current_pillar_slug = build_keyword_pool(base_keywords, existing_titles, posts)
    if not keyword_pool:
        log("MAIN", "No keyword pool available")
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
            log("MAIN", "Keyword pool exhausted for this run")
            break

        keyword = random.choice(remaining_keywords).strip()
        tried_keywords.add(normalize_keyword(keyword))
        if not keyword:
            continue

        created_iso = now_utc_iso()
        log("MAIN", f"Selected keyword='{keyword}' cluster='{cluster_name}' post_type='{post_type}'")

        data = None
        planning = {}
        corrective_note = ""

        for attempt in range(1, MAX_GENERATE_ATTEMPTS + 1):
            try:
                log("PLAN", f"Attempt {attempt} generating planning")
                cand, cand_planning = generate_deep_post(
                    keyword=keyword,
                    cluster_name=cluster_name,
                    post_type=post_type,
                    avoid_titles=existing_titles,
                    corrective_note=corrective_note,
                )

                if post_semantically_too_close(keyword, cand_planning, posts):
                    log("DUP", f"Semantic overlap detected on attempt {attempt} for keyword='{keyword}'")
                    corrective_note = """
                    Retry correction:
                    - Choose a meaningfully different audience or operating problem
                    - Narrow the angle
                    - Avoid overlap with existing onboarding, planning, admin, proposal, invoicing, and follow-up workflows
                    """
                    continue

                cand_title = cand["title"]

                if title_too_similar(cand_title, existing_titles, TITLE_SIM_THRESHOLD):
                    log("DUP", f"Title too similar on attempt {attempt}: '{cand_title}'")
                    corrective_note = """
                    Retry correction:
                    - Create a more distinct title
                    - Keep the title natural and human
                    - Do not resemble existing titles
                    """
                    continue

                ok, reason = quality_check_post(cand, keyword=keyword)
                if not ok:
                    log("QUALITY", f"Quality check failed on attempt {attempt}: reason='{reason}'")
                    corrective_note = build_retry_corrections(reason, cand_planning)
                    continue

                fp = make_fingerprint(cand_title, cand["sections"], cand["tldr"], cand["faq"])
                if fp in used_fps:
                    log("DUP", f"Fingerprint duplicate on attempt {attempt}")
                    corrective_note = """
                    Retry correction:
                    - Keep the same intent
                    - Change framing, examples, and reusable checklist
                    - Make the article materially different
                    """
                    continue

                data = cand
                planning = cand_planning
                used_fps.add(fp)
                break

            except Exception as e:
                import traceback
                log("GEN", f"Attempt {attempt} crashed for keyword='{keyword}': {e}")
                traceback.print_exc()
                corrective_note = "Retry correction: follow the required structure more strictly and keep the article less generic."
                continue
    
Retry correction:
- Choose a meaningfully different audience or operating problem
- Narrow the angle
- Avoid overlap with existing onboarding, planning, admin, proposal, invoicing, and follow-up workflows
"""
                continue

            cand_title = cand["title"]

            if title_too_similar(cand_title, existing_titles, TITLE_SIM_THRESHOLD):
                log("DUP", f"Title too similar on attempt {attempt}: '{cand_title}'")
                corrective_note = """
                    Retry correction:
                    - Create a more distinct title
                    - Keep the title natural and human
                    - Do not resemble existing titles
                    """
                continue

            ok, reason = quality_check_post(cand, keyword=keyword)
            if not ok:
                log("QUALITY", f"Quality check failed on attempt {attempt}: reason='{reason}'")
                corrective_note = build_retry_corrections(reason, cand_planning)
                continue

            fp = make_fingerprint(cand_title, cand["sections"], cand["tldr"], cand["faq"])
            if fp in used_fps:
                log("DUP", f"Fingerprint duplicate on attempt {attempt}")
                corrective_note = """
Retry correction:
- Keep the same intent
- Change framing, examples, and reusable checklist
- Make the article materially different
"""
                continue

            data = cand
            planning = cand_planning
            used_fps.add(fp)
            break

        if not data:
            log("MAIN", f"Failed to generate a unique post for keyword='{keyword}'")
            continue

        title = data["title"]
        description = data["description"] or planning.get("description") or short_desc(title)
        category = data["category"] or planning.get("category") or pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)
        sections = data["sections"]
        tldr = data["tldr"]
        faq = data["faq"]
        editorial_note = data.get("editorial_note", "")

        if category not in ALLOWED_CATEGORIES:
            category = pick_category(keyword=keyword, cluster_name=cluster_name, post_type=post_type)

        slug = build_clean_slug(title, keyword)
        if slug in existing_slugs:
            slug = f"{slug}-{int(time.time())}"

        old_slug = ""
        for p in posts[:100]:
            if isinstance(p, dict) and normalize_keyword(p.get("title", "")) == normalize_keyword(title):
                old_slug = (p.get("slug") or "").strip()
                break

        if old_slug and old_slug != slug:
            redirects[f"/posts/{old_slug}.html"] = f"/posts/{slug}.html"

        pillar_slug = current_pillar_slug
        if post_type == "pillar":
            pillar_slug = slug

        image_paths, alt_texts, credits_li = build_visual_assets(slug, sections)
       
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
            alt_texts=alt_texts,
            sections=sections,
            tldr=tldr,
            faq=faq,
            photo_credits_li=credits_li,
            related_posts=related_posts,
            post_type=post_type,
            editorial_note=editorial_note,
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
            planning=planning,
        )
        existing_slugs.add(slug)
        existing_titles.insert(0, title)

        used_texts["fingerprints"] = sorted(list(used_fps))
        save_json(USED_TEXTS_JSON, used_texts)
        save_redirects(redirects)

        log("DONE", f"Generated HTML: posts/{slug}.html")
        log("DONE", f"Source keyword: {keyword}")
        log("DONE", f"Topic cluster: {cluster_name}")
        log("DONE", f"Post type: {post_type}")
        log("DONE", f"Audience: {planning.get('audience', '')}")
        log("DONE", f"Problem: {planning.get('problem', '')}")
        log("DONE", f"Angle: {planning.get('angle', '')}")
        made += 1

    if made == 0:
        log("MAIN", "No posts generated this run. Exiting 0 so workflow stays green.")
        return 0

    save_posts_index(posts)
    log("MAIN", f"Finished build_id={BUILD_ID} made={made}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        import traceback
        print("[FATAL] Unhandled exception:")
        traceback.print_exc()
        raise

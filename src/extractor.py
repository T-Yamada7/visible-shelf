"""Step 2: Extract structured fields from raw AI responses (rule-based + LLM)."""
import json
import logging
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MALL_DOMAINS = {"rakuten.co.jp", "amazon.co.jp", "yahoo.co.jp", "qoo10.jp", "mercari.com"}

_LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"\d+[.．、\)）\s]|"
    r"[①-⑨]|"
    r"第\d+[位番]|"
    r"[・●▶▸◆■□▪]\s*|"
    r"[-—]\s+"
    r")",
    re.MULTILINE,
)

_RECOMMEND_RE = re.compile(
    r"(おすすめ|お勧め|ぜひ|オススメ|イチオシ|人気|評判|定番|名品|銘酒|紹介|ご紹介)"
)


# ── normalization ──────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[\s　]+", "", text)
    text = re.sub(r"(株式会社|合同会社|有限会社|（株）|\(株\))", "", text)
    return text


def _collect_target_names(target: dict) -> list[str]:
    names = [target["brand_name"]] + target.get("aliases", [])
    for product in target.get("products", []):
        names.append(product["name"])
        names.extend(product.get("aliases", []))
    return [n for n in names if n]


# ── list item parsing ──────────────────────────────────────────────────────────

def _find_list_items(text: str) -> list[tuple[int, str]]:
    """Return [(1-based rank, item text), ...] for each detected list item."""
    items = []
    idx = 0
    for line in text.splitlines():
        m = _LIST_ITEM_RE.match(line)
        if m:
            idx += 1
            items.append((idx, line[m.end():].strip()))
    return items


# ── appearance ─────────────────────────────────────────────────────────────────

def _detect_appearance(
    text: str,
    norm_text: str,
    norm_names: list[str],
    list_items: list[tuple[int, str]],
) -> str:
    if not any(n in norm_text for n in norm_names):
        return "miss"

    # In a list item → definite recommendation
    for _, item in list_items:
        if any(n in _normalize(item) for n in norm_names):
            return "hit"

    # Recommendation signal in same line
    for line in text.splitlines():
        if any(n in _normalize(line) for n in norm_names):
            if _RECOMMEND_RE.search(line):
                return "hit"

    return "mention"


# ── rank ───────────────────────────────────────────────────────────────────────

def _detect_rank(norm_names: list[str], list_items: list[tuple[int, str]]) -> int | None:
    for rank, item in list_items:
        if any(n in _normalize(item) for n in norm_names):
            return rank
    return None


# ── competitors (rule-based: other list items) ────────────────────────────────

def _extract_competitors_basic(
    list_items: list[tuple[int, str]], norm_names: list[str]
) -> list[str]:
    result = []
    for _, item in list_items:
        if not any(n in _normalize(item) for n in norm_names):
            result.append(item)
    return result[:10]


# ── LLM secondary judgment ─────────────────────────────────────────────────────

_LLM_SYSTEM = (
    "あなたは日本酒の推薦テキストを分析するアシスタントです。"
    "必ずJSON形式のみで返答してください。説明文は不要です。"
)


def _get_anthropic_client():
    import anthropic
    return anthropic.Anthropic()


def _relevant_snippet(text: str, norm_names: list[str], window: int = 3) -> str:
    """Return lines containing the target name with ±window lines of context."""
    lines = text.splitlines()
    hit_indices = {
        i for i, line in enumerate(lines)
        if any(n in _normalize(line) for n in norm_names)
    }
    collected = set()
    for i in hit_indices:
        for j in range(max(0, i - window), min(len(lines), i + window + 1)):
            collected.add(j)
    return "\n".join(lines[i] for i in sorted(collected))


def _llm_classify_appearance(text: str, target_names: list[str], norm_names: list[str]) -> str:
    """Ask Claude whether the target is a recommendation (hit) or mere mention."""
    snippet = _relevant_snippet(text, norm_names)
    if not snippet:
        return "mention"

    prompt = (
        f"以下のテキストにおいて「{'・'.join(target_names[:3])}」は"
        "「推薦（hit）」として登場していますか、それとも「単なる言及（mention）」ですか？\n\n"
        f"テキスト:\n{snippet}\n\n"
        '{"classification": "hit" または "mention", "reason": "理由"} の形式で返してください。'
    )

    try:
        client = _get_anthropic_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            system=[{"type": "text", "text": _LLM_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        result = data.get("classification", "mention")
        return result if result in ("hit", "mention") else "mention"
    except Exception as exc:
        logger.warning("LLM appearance classification failed: %s", exc)
        return "mention"


def _llm_extract_competitors(text: str, norm_names: list[str]) -> list[str]:
    """Ask Claude to extract all sake brand/brewery names from the response."""
    prompt = (
        "以下のテキストに登場する日本酒の銘柄名・蔵名をすべて抽出してください。\n"
        "重複なしで最大10件、JSON配列（文字列のみ）で返してください。\n\n"
        f"テキスト:\n{text[:2000]}\n\n"
        '例: ["獺祭", "久保田", "朝日酒造"]'
    )

    try:
        client = _get_anthropic_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=[{"type": "text", "text": _LLM_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        names = json.loads(raw)
        if not isinstance(names, list):
            return []
        # 自社名を除外
        return [n for n in names if not any(nn in _normalize(str(n)) for nn in norm_names)][:10]
    except Exception as exc:
        logger.warning("LLM competitor extraction failed: %s", exc)
        return []


# ── citations ──────────────────────────────────────────────────────────────────

def _self_domain(target: dict) -> str:
    try:
        return urlparse(target.get("website", "")).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _classify_url(url: str, self_dom: str) -> str:
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return "other"
    if self_dom and (domain == self_dom or domain.endswith("." + self_dom)):
        return "self"
    if any(m in domain for m in MALL_DOMAINS):
        return "mall"
    if any(kw in domain for kw in ("sake", "sakenomy", "nomooo", "nihonshu")):
        return "media"
    return "other"


# ── main entry point ───────────────────────────────────────────────────────────

def extract(text: str, citations: list[str], target: dict, use_llm: bool = False) -> dict:
    """Extract structured fields from one AI response.

    Args:
        use_llm: If True, refine appearance classification and competitor extraction via Claude.

    Returns:
        appearance: "hit" | "mention" | "miss"
        rank: int | None
        competitors: list of brand/brewery names
        self_cited: bool
        citation_domains: list of unique domains
        classified_citations: list of {url, type}
    """
    target_names = _collect_target_names(target)
    norm_names = [_normalize(n) for n in target_names]
    norm_text = _normalize(text)
    list_items = _find_list_items(text)

    appearance = _detect_appearance(text, norm_text, norm_names, list_items)
    rank = _detect_rank(norm_names, list_items) if appearance != "miss" else None

    if use_llm:
        # 二次判定: hit/mention が曖昧なケースをLLMで確定
        if appearance in ("hit", "mention"):
            appearance = _llm_classify_appearance(text, target_names, norm_names)
        # 競合抽出: LLMで全文から銘柄名を抽出
        competitors = _llm_extract_competitors(text, norm_names)
    else:
        competitors = _extract_competitors_basic(list_items, norm_names)

    self_dom = _self_domain(target)
    classified = [{"url": u, "type": _classify_url(u, self_dom)} for u in citations]
    self_cited = any(c["type"] == "self" for c in classified)
    domains = list({urlparse(c["url"]).netloc.lstrip("www.") for c in classified})

    return {
        "appearance": appearance,
        "rank": rank,
        "competitors": competitors,
        "self_cited": self_cited,
        "citation_domains": domains,
        "classified_citations": classified,
    }


# ── raw file loader (for --skip-api) ──────────────────────────────────────────

def _parse_engine_response(engine: str, response: dict) -> tuple[str, list[str]]:
    """Extract (text, citations) from a saved raw API response."""
    if engine == "perplexity":
        text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        citations = response.get("citations", [])
        return text, citations
    if engine == "chatgpt":
        text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        # web search citations are in annotations
        annotations = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("annotations", [])
        )
        citations = [
            a.get("url_citation", {}).get("url", "")
            for a in annotations
            if a.get("type") == "url_citation"
        ]
        return text, [u for u in citations if u]
    if engine == "gemini":
        parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        chunks = (
            response.get("candidates", [{}])[0]
            .get("groundingMetadata", {})
            .get("groundingChunks", [])
        )
        citations = [
            c.get("web", {}).get("uri", "")
            for c in chunks
            if c.get("web", {}).get("uri")
        ]
        return text, citations
    return "", []


def load_from_raw(raw_dir: Path, queries_path: Path) -> list[dict]:
    """Load all raw/*.json files and return a results list ready for extraction."""
    import yaml

    with open(queries_path, encoding="utf-8") as f:
        queries_cfg = yaml.safe_load(f)
    tier_map = {q["id"]: q["tier"] for q in queries_cfg["queries"]}

    results = []
    for raw_file in sorted(raw_dir.glob("*.json")):
        payload = json.loads(raw_file.read_text(encoding="utf-8"))
        engine = payload.get("engine", "")
        query_id = payload.get("query_id", "")
        response = payload.get("response", {})

        text, citations = _parse_engine_response(engine, response)
        results.append({
            "engine": engine,
            "query_id": query_id,
            "tier": tier_map.get(query_id, 0),
            "query_text": payload.get("query_text", ""),
            "text": text,
            "citations": citations,
            "raw_file": str(raw_file),
        })
    return results

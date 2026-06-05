"""Step 1: Call AI engines for each query and save raw responses."""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

MANUAL_CHECK_QUERY_IDS = {"q07", "q08", "q16"}


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_query_text(text: str, target: dict) -> str:
    brand = target.get("brand_name", "")
    prefecture = target.get("prefecture", "")
    product = target["products"][0]["name"] if target.get("products") else ""
    return text.replace("{brand}", brand).replace("{prefecture}", prefecture).replace("{product}", product)


def _get_engine_caller(engine_id: str):
    if engine_id == "perplexity":
        from src.engines.perplexity import ask
        return ask
    if engine_id == "chatgpt":
        from src.engines.chatgpt import ask
        return ask
    if engine_id == "gemini":
        from src.engines.gemini import ask
        return ask
    raise ValueError(f"Unknown engine: {engine_id}")


def _call_with_retry(ask_fn, prompt: str, model: str, max_retries: int = 3) -> dict:
    delay = 2.0
    for attempt in range(max_retries):
        try:
            return ask_fn(prompt, model)
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            logger.warning("Attempt %d failed (%s). Retrying in %.1fs...", attempt + 1, exc, delay)
            time.sleep(delay)
            delay *= 2


def run(
    target_path: Path,
    queries_path: Path,
    engines_path: Path,
    raw_dir: Path,
    out_dir: Path,
    engine_filter: list[str] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    target = _load_yaml(target_path)
    queries_cfg = _load_yaml(queries_path)
    engines_cfg = _load_yaml(engines_path)

    queries = queries_cfg["queries"]
    engines = [e for e in engines_cfg["engines"] if e.get("enabled", True)]
    if engine_filter:
        engines = [e for e in engines if e["id"] in engine_filter]

    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    manual_prompts: list[str] = []
    results: list[dict] = []

    if dry_run:
        print("--- dry-run: query list ---")
        for q in queries:
            text = _resolve_query_text(q["text"], target)
            for eng in engines:
                print(f"  [{eng['id']}] {q['id']}: {text[:60]}...")
        return results

    for eng in engines:
        engine_id = eng["id"]
        model = eng["model"]

        try:
            ask_fn = _get_engine_caller(engine_id)
        except (ImportError, ValueError) as exc:
            logger.warning("Skipping engine %s: %s", engine_id, exc)
            continue

        for q in queries:
            query_id = q["id"]
            resolved_text = _resolve_query_text(q["text"], target)

            if query_id in MANUAL_CHECK_QUERY_IDS:
                manual_prompts.append(
                    f"=== {engine_id} / {query_id} ===\n{resolved_text}\n"
                )

            timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            raw_file = raw_dir / f"{engine_id}_{query_id}_{timestamp}.json"

            logger.info("Calling %s / %s ...", engine_id, query_id)
            try:
                result = _call_with_retry(ask_fn, resolved_text, model)
            except Exception as exc:
                logger.error("Failed %s / %s: %s", engine_id, query_id, exc)
                result = {"text": "", "citations": [], "model": model, "raw": {"error": str(exc)}}

            raw_payload = {
                "engine": engine_id,
                "query_id": query_id,
                "query_text": resolved_text,
                "model": result["model"],
                "response": result["raw"],
            }
            raw_file.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Saved raw response: %s", raw_file.name)

            results.append({
                "engine": engine_id,
                "query_id": query_id,
                "tier": q["tier"],
                "query_text": resolved_text,
                "text": result["text"],
                "citations": result["citations"],
                "raw_file": str(raw_file),
            })

    if manual_prompts:
        manual_file = out_dir / "manual_check.txt"
        manual_file.write_text(
            "# API乖離確認用プロンプト（q07/q08/q16）\n"
            "# 以下のプロンプトをWeb版ChatGPT/Geminiに入力し、API結果と比較してください。\n\n"
            + "\n".join(manual_prompts),
            encoding="utf-8",
        )
        logger.info("Written manual check prompts: %s", manual_file)

    return results

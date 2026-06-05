import os
import requests
from typing import Any

SYSTEM_PROMPT = (
    "あなたは日本酒に詳しいショッピングアシスタントです。"
    "ユーザーの相談に対し、具体的な銘柄・蔵名を3〜5件、理由とともに挙げてください。"
    "可能なら購入できるサイトのURLも示してください。"
)

API_URL = "https://api.perplexity.ai/chat/completions"


def ask(prompt: str, model: str = "sonar") -> dict[str, Any]:
    """Call Perplexity API and return normalized response dict."""
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise EnvironmentError("PERPLEXITY_API_KEY is not set")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(API_URL, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    raw = response.json()

    text = raw["choices"][0]["message"]["content"]
    citations = raw.get("citations", [])

    return {
        "text": text,
        "citations": citations,
        "model": raw.get("model", model),
        "raw": raw,
    }

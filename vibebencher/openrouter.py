"""OpenRouter API client using urllib."""

import json
import os
import re
import time
import urllib.request
import urllib.error

BASE_URL = "https://openrouter.ai/api/v1"

_models_cache = None


def _get_api_key():
    """Get API key from config or environment."""
    from vibebencher import db

    key = db.get_config("openrouter_api_key")
    if key:
        return key
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    raise ConnectionError(
        "No OpenRouter API key found. Set it with: vb config openrouter-key <KEY>"
    )


def list_models():
    """Fetch all models from OpenRouter. Returns list of dicts with 'id' and 'name'."""
    global _models_cache
    if _models_cache is not None:
        return _models_cache

    url = f"{BASE_URL}/models"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise ConnectionError(f"Cannot connect to OpenRouter: {e}") from e

    _models_cache = [
        {"id": m["id"], "name": m.get("name", m["id"])} for m in data.get("data", [])
    ]
    return _models_cache


def search_models(query):
    """Search models by substring match on id and name. Returns list of dicts."""
    models = list_models()
    q = query.lower()
    return [m for m in models if q in m["id"].lower() or q in m["name"].lower()]


def generate(model, prompt):
    """Generate a response using OpenRouter chat completions.
    Returns dict with keys: response, duration_ms, eval_count, prompt_eval_count.
    """
    api_key = _get_api_key()
    url = f"{BASE_URL}/chat/completions"

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise ConnectionError(f"OpenRouter generate failed for {model}: {e}") from e

    elapsed_ms = int((time.monotonic() - start) * 1000)

    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    usage = data.get("usage", {})

    response_text = message.get("content", "")
    # OpenRouter may return reasoning in a separate field for thinking models.
    thinking = message.get("reasoning", "")
    # Some models embed thinking in <think>...</think> tags within the content.
    inline_think_match = re.search(r"<think>(.*?)</think>", response_text, re.DOTALL)
    if inline_think_match:
        if not thinking:
            thinking = inline_think_match.group(1).strip()
        response_text = re.sub(
            r"<think>.*?</think>", "", response_text, flags=re.DOTALL
        ).strip()

    return {
        "response": response_text,
        "thinking": thinking,
        "duration_ms": elapsed_ms,
        "eval_count": usage.get("completion_tokens", 0),
        "prompt_eval_count": usage.get("prompt_tokens", 0),
    }

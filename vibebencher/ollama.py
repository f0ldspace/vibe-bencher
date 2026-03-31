"""Ollama API client using urllib."""

import json
import re
import time
import urllib.request
import urllib.error

DEFAULT_BASE_URL = "http://localhost:11434"


def list_models(base_url=DEFAULT_BASE_URL):
    """Fetch available models from Ollama. Returns list of model name strings."""
    url = f"{base_url}/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return [m["name"] for m in data.get("models", [])]
    except urllib.error.URLError as e:
        raise ConnectionError(f"Cannot connect to Ollama at {base_url}: {e}") from e


def show_model(model, base_url=DEFAULT_BASE_URL):
    """Get model details from Ollama. Returns dict with parameter_size, quantization_level, family, etc.
    Returns None if the model is not found or Ollama is unavailable.
    """
    url = f"{base_url}/api/show"
    payload = json.dumps({"model": model}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        details = data.get("details", {})
        return {
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
            "family": details.get("family"),
            "families": details.get("families"),
        }
    except (urllib.error.URLError, urllib.error.HTTPError):
        return None


def generate(model, prompt, base_url=DEFAULT_BASE_URL):
    """Generate a response from a model. Returns dict with keys:
    response, duration_ms, eval_count, prompt_eval_count.
    """
    url = f"{base_url}/api/generate"
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
    ).encode()

    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    start = time.monotonic()

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama generate failed for {model}: {e}") from e

    elapsed_ms = int((time.monotonic() - start) * 1000)

    response_text = data.get("response", "")
    # Some models (e.g. DeepSeek-R1, QwQ) embed thinking in <think>...</think> tags.
    # Ollama may also return a separate "thinking" field. Capture both, strip from response.
    thinking = data.get("thinking", "")
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
        "duration_ms": data.get("total_duration", elapsed_ms * 1_000_000) // 1_000_000,
        "eval_count": data.get("eval_count", 0),
        "prompt_eval_count": data.get("prompt_eval_count", 0),
    }


def unload_model(model, base_url=DEFAULT_BASE_URL):
    """Unload a model from Ollama memory."""
    url = f"{base_url}/api/generate"
    payload = json.dumps(
        {
            "model": model,
            "prompt": "",
            "keep_alive": 0,
        }
    ).encode()

    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama unload failed for {model}: {e}") from e

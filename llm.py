"""
Layer 1 support — pluggable LLM interface.

Single entry point, `call_llm()`, used by both signal_extractor.py (headline
-> structured signal) and briefing_generator.py (optimizer output -> exec
note). Every caller is written to work with or without a real API key:
if ANTHROPIC_API_KEY isn't set (or the `anthropic` package isn't
installed), `call_llm()` returns None and the caller falls back to a
deterministic, clearly-labeled rule-based/template path instead of
crashing or silently pretending to be the LLM.

This is deliberate, not a stopgap: the plan's own Day 4 guidance is "cache
every demo path... solver slow live", the same logic that justified
pre-cached headlines over a live news feed. An LLM call is one more thing
that can be slow, rate-limited, or unavailable on conference Wi-Fi — a
solid deterministic fallback is a feature, not a placeholder.

To go live: set the ANTHROPIC_API_KEY environment variable in the same
Python environment that runs `streamlit run app.py`, and `pip install
anthropic`. Nothing else changes.
"""
import json
import os

LLM_MODEL = "claude-sonnet-5"  # update if your account uses a different model id

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

_client = None


def llm_configured() -> bool:
    """True only if both the SDK is importable AND a key is actually set —
    checked lazily (not at import time) so app.py can show a live status
    indicator without needing a restart if the user sets the key mid-session."""
    return _ANTHROPIC_AVAILABLE and bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client():
    global _client
    if _client is None and llm_configured():
        _client = anthropic.Anthropic()
    return _client


def call_llm(prompt: str, system: str | None = None, max_tokens: int = 1024) -> str | None:
    """Returns the model's text response, or None if no key is configured
    or the call fails for any reason (network, rate limit, bad key —
    callers should treat None as "use the deterministic fallback", not as
    an error to surface to the user mid-demo)."""
    client = _get_client()
    if client is None:
        return None
    try:
        kwargs = {"model": LLM_MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        return "".join(block.text for block in response.content if hasattr(block, "text"))
    except Exception:
        return None


def call_llm_json(prompt: str, system: str | None = None, max_tokens: int = 512) -> dict | None:
    """Same as call_llm, but parses the response as JSON. Returns None on
    any failure (no key, call error, or malformed JSON) — always check for
    None and fall back, never assume this succeeded."""
    text = call_llm(prompt, system=system, max_tokens=max_tokens)
    if text is None:
        return None
    try:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None

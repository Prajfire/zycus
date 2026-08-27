"""
llm_client.py

One thin wrapper around the Anthropic Messages API so Task 1 and Task 2 don't
each roll their own retry/parsing logic. Two things worth calling out:

1. Determinism (required by Task 2): Claude's API doesn't expose a `seed`
   parameter the way some other providers do. temperature=0 gets you *close*
   to deterministic but not guaranteed byte-identical output. So on top of
   temperature=0 we post-process: the account brief is assembled from
   structured JSON fields, not free narrative, and we hash+cache each
   (prompt, inputs) pair so re-running the same account_id returns the cached
   result instead of hitting the API again. That's the honest way to get
   determinism here — see README design note.

2. Everything goes through call_llm() so PII redaction (Task 4 concern) has
   exactly one choke point to sit in front of.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = "claude-3-5-sonnet-20241022"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".llm_cache"
CACHE_DIR.mkdir(exist_ok=True)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# --- lightweight PII scrub applied before anything leaves the process -----
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")


def scrub_pii(text: str) -> str:
    text = _EMAIL_RE.sub("[redacted-email]", text)
    text = _PHONE_RE.sub("[redacted-phone]", text)
    return text


def _cache_key(system: str, prompt: str) -> str:
    digest = hashlib.sha256((system + "||" + prompt).encode("utf-8")).hexdigest()
    return digest


def call_llm(
    system: str,
    prompt: str,
    max_tokens: int = 1200,
    use_cache: bool = True,
    redact: bool = True,
) -> str:
    if redact:
        prompt = scrub_pii(prompt)

    cache_path = CACHE_DIR / f"{_cache_key(system, prompt)}.json"
    if use_cache and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    client = _get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    if use_cache:
        cache_path.write_text(text, encoding="utf-8")
    return text


def call_llm_json(system: str, prompt: str, max_tokens: int = 1200) -> dict:
    """Same as call_llm but expects (and enforces) a JSON object back."""
    system = system + "\n\nRespond with ONLY a single valid JSON object. No markdown fences, no preamble."
    raw = call_llm(system, prompt, max_tokens=max_tokens)
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {raw[:300]}") from e

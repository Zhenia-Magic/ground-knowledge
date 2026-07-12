"""Optional embedding backend for SEMANTIC entity-resolution suggestions.

Lazy and key-gated: `embedder()` returns a `label -> vector` function using the first
OpenAI-compatible provider whose key is set (same rows as `ingest/llm.py`), or **None** when no key
is configured — in which case `engine/curate.suggest_duplicates` silently falls back to its
deterministic lexical suggestions. This lives in the ingestion layer on purpose: the engine stays
pure/stdlib/deterministic, embeddings are advisory, and nothing here merges anything.

    from ingest.embed import embedder
    e = embedder()                       # None if no API key
    suggest_duplicates(kb, embed=e)      # semantic candidates surfaced for a curator to confirm
"""
import json
import os
import urllib.error
import urllib.request

from ingest import llm

# Per-provider default embedding model (all speak the OpenAI /embeddings shape). Override with
# EPISTEMIC_EMBED_MODEL. Unknown providers fall back to the OpenAI name.
_EMBED_MODEL = {
    "openai": "text-embedding-3-small",
    "mistral": "mistral-embed",
    "nvidia": "nvidia/nv-embedqa-e5-v5",
    "gemini": "text-embedding-004",
    "openrouter": "openai/text-embedding-3-small",
}
_DEFAULT_EMBED_MODEL = "text-embedding-3-small"
_HTTP_TIMEOUT = int(os.environ.get("EPISTEMIC_HTTP_TIMEOUT", "60"))


def _embed_model(pid):
    return os.environ.get("EPISTEMIC_EMBED_MODEL") or _EMBED_MODEL.get(pid, _DEFAULT_EMBED_MODEL)


def embedder(model=None):
    """A `label -> list[float]` function (memoized per process), or None if no provider key is set.
    A failed call returns None for that label so callers degrade gracefully rather than raising."""
    row = llm._active_compat()
    if not row:
        return None
    env_key, base_url = row[0], row[1]
    key = os.environ.get(env_key)
    if not key:
        return None
    mdl = model or _embed_model(llm._compat_id(row))
    cache = {}

    def embed(text):
        text = (text or "").strip()
        if not text:
            return None
        if text in cache:
            return cache[text]
        body = json.dumps({"model": mdl, "input": text}).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/embeddings", data=body, method="POST",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
                vec = json.loads(r.read())["data"][0]["embedding"]
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TypeError):
            vec = None
        cache[text] = vec
        return vec

    return embed

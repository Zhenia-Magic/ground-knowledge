"""Model-agnostic LLM access via the stdlib (no SDK dependency).

Two phases pick their provider INDEPENDENTLY (see _search_provider / _label_provider):
  * SEARCH / discovery -> Anthropic first (its server-side web_search tool + deep research), any
    OpenAI-compatible key as a model-knowledge-only fallback.
  * LABELLING (reads text we already fetched) -> the first OpenAI-compatible key first; NVIDIA's
    build.nvidia.com leads that list and is free (rate-limited, ~40 req/min), so it labels by
    default even when an Anthropic key is present. Anthropic is the fallback when it's the only key.
So with BOTH an ANTHROPIC_API_KEY and a NVIDIA_API_KEY set, Claude searches and NVIDIA labels — the
expensive model only does the part that actually needs it. OpenAI, DeepSeek, Mistral, Groq, Gemini,
OpenRouter, and NVIDIA all speak the OpenAI chat-completions protocol, so one code path
(_openai_compat) serves them all. With no key set, callers should use --dry-run.

Overrides (all optional, all also settable live from the local console's Models panel):
  * EPISTEMIC_SEARCH_PROVIDER / EPISTEMIC_LABEL_PROVIDER pin a phase to one provider by id
    ("anthropic", "nvidia", "openai", "deepseek", "mistral", "groq", "gemini", "openrouter").
    A pin whose key isn't set is ignored (auto-fallback beats a hard failure on a stale pin).
  * EPISTEMIC_SEARCH_MODEL / EPISTEMIC_LABEL_MODEL pin each phase's model independently;
    EPISTEMIC_MODEL is a legacy global default applied to both phases only when they share a
    provider. Otherwise each phase uses a sensible per-provider default.
"""
import json
import os
import time
import urllib.error
import urllib.request

RETRY_CODES = {429, 500, 502, 503, 529}  # transient — Anthropic 529 = Overloaded
# Sonnet by default: faster/cheaper and far less prone to 529 "Overloaded" than Opus.
# Override with EPISTEMIC_SEARCH_MODEL / EPISTEMIC_LABEL_MODEL / EPISTEMIC_MODEL (see module docstring).
_DEFAULT_ANTHROPIC = "claude-sonnet-5"

# OpenAI-compatible providers, checked in this order after Anthropic. Each speaks the standard
# /chat/completions protocol, so adding one is just a row here.
# (env var, base URL, default model, human label)
_OPENAI_COMPAT = [
    # NVIDIA first: free (build.nvidia.com, ~40 req/min rate limit), so it wins by default over
    # any other compat key set alongside it. Default is z-ai/glm-5.2 — a strong general-purpose
    # text model, a better labeller than the smaller flash default it replaced. Other options:
    # deepseek-ai/deepseek-v4-pro, deepseek-ai/deepseek-v4-flash, minimaxai/minimax-m3,
    # nvidia/nemotron-3-ultra-550b-a55b.
    ("NVIDIA_API_KEY",     "https://integrate.api.nvidia.com/v1",                     "z-ai/glm-5.2",            "NVIDIA"),
    ("OPENAI_API_KEY",     "https://api.openai.com/v1",                               "gpt-4o",                  "OpenAI"),
    ("DEEPSEEK_API_KEY",   "https://api.deepseek.com/v1",                             "deepseek-chat",           "DeepSeek"),
    ("MISTRAL_API_KEY",    "https://api.mistral.ai/v1",                               "mistral-large-latest",    "Mistral"),
    ("GROQ_API_KEY",       "https://api.groq.com/openai/v1",                          "llama-3.3-70b-versatile", "Groq"),
    ("GEMINI_API_KEY",     "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash",        "Google Gemini"),
    ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",                            "deepseek/deepseek-chat",  "OpenRouter"),
]


# Rough USD per 1M tokens (input, output), matched by model-name substring. Prices drift, so this
# is an ESTIMATE for budgeting only; override a row or _PRICE_DEFAULT if yours differs.
_PRICE = {
    "claude-opus": (15.0, 75.0), "claude-sonnet": (3.0, 15.0), "claude-haiku": (0.80, 4.0),
    "claude-fable": (3.0, 15.0),
    "gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.0), "gpt-4": (10.0, 30.0),
    "deepseek": (0.27, 1.10), "mistral": (2.0, 6.0), "llama": (0.59, 0.79),
    "gemini-2.0-flash": (0.10, 0.40), "gemini": (1.25, 5.0),
    # build.nvidia.com is free (rate-limited) -- these full model ids are longer/more specific
    # than the generic "deepseek" row above, so they win the longest-match lookup and correctly
    # report $0 instead of inheriting DeepSeek's own direct-API pricing.
    "z-ai/glm-5.2": (0.0, 0.0), "minimaxai/minimax-m3": (0.0, 0.0),
    "nvidia/nemotron-3-ultra-550b-a55b": (0.0, 0.0),
    "deepseek-ai/deepseek-v4-pro": (0.0, 0.0), "deepseek-ai/deepseek-v4-flash": (0.0, 0.0),
}
_PRICE_DEFAULT = (3.0, 15.0)
_USAGE = {"calls": 0, "input": 0, "output": 0, "usd": 0.0}   # running spend this process


def reset_usage():
    _USAGE.update(calls=0, input=0, output=0, usd=0.0)


def usage():
    return dict(_USAGE)


def _price_for(model):
    """Longest matching key wins (most specific), independent of _PRICE's insertion order — so
    e.g. "gemini-2.0-flash" can't get shadowed by a future, more general "gemini" row added
    above it, or vice versa."""
    m = (model or "").lower()
    matches = [(key, val) for key, val in _PRICE.items() if key in m]
    if matches:
        return max(matches, key=lambda kv: len(kv[0]))[1]
    return _PRICE_DEFAULT


def _record_usage(model, resp):
    """Accumulate token usage + estimated USD from an API response (Anthropic or OpenAI shape)."""
    u = (resp or {}).get("usage") or {}
    inp = u.get("input_tokens", u.get("prompt_tokens", 0)) or 0
    out = u.get("output_tokens", u.get("completion_tokens", 0)) or 0
    pi, po = _price_for(model)
    _USAGE["calls"] += 1
    _USAGE["input"] += inp
    _USAGE["output"] += out
    _USAGE["usd"] += (inp * pi + out * po) / 1_000_000.0


def _active_compat():
    """The first OpenAI-compatible provider whose key is set, or None."""
    for row in _OPENAI_COMPAT:
        if os.environ.get(row[0]):
            return row
    return None


def _compat_id(row):
    """Stable provider id for a compat row, derived from its env var: NVIDIA_API_KEY -> 'nvidia'."""
    return row[0].split("_")[0].lower()


def _compat_by_id(pid):
    for row in _OPENAI_COMPAT:
        if _compat_id(row) == pid:
            return row
    return None


def _anthropic_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def has_key():
    return _anthropic_key() or _active_compat() is not None


# --- phase-aware provider + model selection ----------------------------------------------------
# Each selection returns ("anthropic", None) or ("compat", <_OPENAI_COMPAT row>) or None.
_PIN_ENV = {"search": "EPISTEMIC_SEARCH_PROVIDER", "label": "EPISTEMIC_LABEL_PROVIDER"}


def _pinned_provider(phase):
    """The user's explicit provider pin for a phase, resolved to a selection — or None when the
    pin is unset, 'auto', or names a provider whose key isn't set (a stale pin falls back to the
    automatic choice rather than hard-failing every call)."""
    pid = (os.environ.get(_PIN_ENV[phase]) or "").strip().lower()
    if not pid or pid == "auto":
        return None
    if pid == "anthropic":
        return ("anthropic", None) if _anthropic_key() else None
    row = _compat_by_id(pid)
    return ("compat", row) if row and os.environ.get(row[0]) else None


def _search_provider():
    """SEARCH / discovery: an explicit pin wins; else Anthropic first (server-side web search +
    deep research), then the first compat key (searches from model knowledge only — no live web)."""
    pin = _pinned_provider("search")
    if pin:
        return pin
    if _anthropic_key():
        return ("anthropic", None)
    c = _active_compat()
    return ("compat", c) if c else None


def _label_provider():
    """LABELLING: an explicit pin wins; else the first compat key — NVIDIA leads _OPENAI_COMPAT and
    is free, so it labels by default even alongside an Anthropic key kept for search — then
    Anthropic as a fallback."""
    pin = _pinned_provider("label")
    if pin:
        return pin
    c = _active_compat()
    if c:
        return ("compat", c)
    if _anthropic_key():
        return ("anthropic", None)
    return None


def _provider_id(sel):
    """Stable id of a selection: 'anthropic' or the compat id ('nvidia', 'openai', …) — the same
    ids EPISTEMIC_*_PROVIDER pins and the console's Models panel use."""
    if not sel:
        return None
    kind, c = sel
    return "anthropic" if kind == "anthropic" else _compat_id(c)


def _single_provider():
    """True when search and label land on the same provider — the historical single-key setup,
    where the legacy global EPISTEMIC_MODEL is safe to apply to both phases."""
    return _provider_id(_search_provider()) == _provider_id(_label_provider())


def _phase_model(phase, provider_default):
    """Resolve a phase's model at call time. Precedence: the phase-specific override
    (EPISTEMIC_SEARCH_MODEL / EPISTEMIC_LABEL_MODEL); then the legacy global EPISTEMIC_MODEL, but
    ONLY when both phases share a provider (applying e.g. a Claude id to a split NVIDIA-label setup
    would just error the NVIDIA call); then the provider's own default."""
    override = os.environ.get(
        "EPISTEMIC_SEARCH_MODEL" if phase == "search" else "EPISTEMIC_LABEL_MODEL")
    if override:
        return override
    if _single_provider():
        legacy = os.environ.get("EPISTEMIC_MODEL")
        if legacy:
            return legacy
    return provider_default


def _select(phase):
    """(kind, compat_row_or_None, resolved_model, human_label) for a phase, or None if no key."""
    sel = _search_provider() if phase == "search" else _label_provider()
    if sel is None:
        return None
    kind, c = sel
    if kind == "anthropic":
        return ("anthropic", None, _phase_model(phase, _DEFAULT_ANTHROPIC), "Anthropic")
    return ("compat", c, _phase_model(phase, c[2]), c[3])

# optional hook the server sets so retry/backoff notices show up in the progress log
LOG = None


def _say(msg):
    if LOG:
        try:
            LOG(msg)
        except Exception:
            pass
    print(msg, flush=True)


def active_model(phase="label"):
    """Human-readable 'Provider / model' the given phase ('search' or 'label') will use."""
    sel = _select(phase)
    if sel is None:
        return "manual (no API key)"
    return sel[3] + " / " + sel[2]


def active_models():
    """Both phases for status display — collapses to one line when they resolve to the same model."""
    s, l = active_model("search"), active_model("label")
    return s if s == l else "search: {} · label: {}".format(s, l)


# Suggested model ids per provider, for UI dropdowns. Free-typed ids are always allowed on top of
# these; a wrong id simply errors the API call with the provider's own message.
SUGGESTED_MODELS = {
    "anthropic": ["claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5"],
    "nvidia": ["z-ai/glm-5.2", "deepseek-ai/deepseek-v4-pro", "deepseek-ai/deepseek-v4-flash",
               "minimaxai/minimax-m3", "nvidia/nemotron-3-ultra-550b-a55b"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "mistral": ["mistral-large-latest"],
    "groq": ["llama-3.3-70b-versatile"],
    "gemini": ["gemini-2.0-flash"],
    "openrouter": ["deepseek/deepseek-chat"],
}


def provider_status():
    """Introspection for UIs (the local console's Models panel): every known provider with its key
    state and suggested models, plus how each phase currently resolves — including whether a pin is
    set and whether it is 'broken' (points at a keyless provider, so auto-fallback is in effect)."""
    providers = [{"id": "anthropic", "label": "Anthropic (Claude)", "hasKey": _anthropic_key(),
                  "free": False, "webSearch": True, "defaultModel": _DEFAULT_ANTHROPIC,
                  "models": SUGGESTED_MODELS["anthropic"]}]
    for row in _OPENAI_COMPAT:
        pid = _compat_id(row)
        providers.append({"id": pid, "label": row[3], "hasKey": bool(os.environ.get(row[0])),
                          "free": pid == "nvidia", "webSearch": False, "defaultModel": row[2],
                          "models": SUGGESTED_MODELS.get(pid, [row[2]])})
    phases = {}
    for phase in ("search", "label"):
        sel = _select(phase)
        pin = (os.environ.get(_PIN_ENV[phase]) or "").strip().lower() or None
        eff = _provider_id(_search_provider() if phase == "search" else _label_provider())
        phases[phase] = {
            "provider": eff, "providerLabel": sel[3] if sel else None,
            "model": sel[2] if sel else None,
            "pinnedProvider": pin,
            "pinnedModel": os.environ.get(
                "EPISTEMIC_SEARCH_MODEL" if phase == "search" else "EPISTEMIC_LABEL_MODEL") or None,
            "pinBroken": bool(pin and pin != "auto" and pin != eff),
        }
    return {"providers": providers, "search": phases["search"], "label": phases["label"],
            "hasKey": has_key(), "summary": active_models()}


def _post(url, headers, body, tries=4):
    """POST with retry+backoff on transient errors (429/5xx/529), so a single 'Overloaded'
    doesn't waste the whole run. Surfaces the API's own error message on permanent failures."""
    data = json.dumps(body).encode("utf-8")
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES and attempt < tries - 1:
                wait = 2 ** attempt * 2  # 2s, 4s, 8s
                _say("  LLM API {} — retrying in {}s ({}/{})".format(e.code, wait, attempt + 1, tries - 1))
                time.sleep(wait)
                continue
            raw = ""
            try:
                raw = e.read().decode("utf-8", "ignore")
                msg = json.loads(raw).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            raise SystemExit("LLM API error {}: {}".format(e.code, msg or raw[:500] or e.reason))
        except urllib.error.URLError as e:
            if attempt < tries - 1:
                _say("  network error ({}) — retrying…".format(e.reason))
                time.sleep(2 ** attempt * 2)
                continue
            raise SystemExit("network error reaching the LLM API: {}".format(e.reason))


def _anthropic(prompt, system, web, deep, model):
    # deep mode: allow far more searches and a longer answer so the model can cover every angle
    body = {"model": model, "max_tokens": 16000 if deep else 8192,
            "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    if web:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search",
                          "max_uses": 18 if deep else 6}]
    headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
               "anthropic-version": "2023-06-01", "content-type": "application/json"}
    resp = _post("https://api.anthropic.com/v1/messages", headers, body)
    _record_usage(model, resp)
    return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")


def _openai_compat(prompt, system, env, base, model):
    """One code path for every OpenAI-compatible backend (NVIDIA, OpenAI, DeepSeek, Mistral, Groq,
    Gemini's compat endpoint, OpenRouter). Server-side web search isn't part of this protocol,
    so `discover()` falls back to model-knowledge sources for these providers."""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    headers = {"Authorization": "Bearer " + os.environ[env], "content-type": "application/json"}
    resp = _post(base.rstrip("/") + "/chat/completions", headers,
                 {"model": model, "messages": msgs})
    _record_usage(model, resp)
    return resp["choices"][0]["message"]["content"]


_NO_KEY_MSG = (
    "No LLM API key set (ANTHROPIC_API_KEY, NVIDIA_API_KEY [free, build.nvidia.com], "
    "OPENAI_API_KEY, DEEPSEEK_API_KEY, MISTRAL_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, "
    "or OPENROUTER_API_KEY).\n"
    "Use --dry-run to print the prompt, paste it into any LLM / deep-research tool,\n"
    "then save the JSON it returns and run:  python cli.py add <kb.json> <delta.json>")


def complete(prompt, system=None, web=False, deep=False, phase=None):
    """Run one completion. `phase` ('search'|'label') decides the provider; it defaults from `web`
    (a web-grounded call is inherently search, everything else is labelling), but discover()'s
    no-web fallback passes phase='search' explicitly so it stays on the search provider."""
    if phase is None:
        phase = "search" if web else "label"
    sel = _select(phase)
    if sel is None:
        raise SystemExit(_NO_KEY_MSG)
    kind, c, model, _label = sel
    if kind == "anthropic":
        return _anthropic(prompt, system, web, deep, model)
    return _openai_compat(prompt, system, c[0], c[1], model)


def discover(prompt, deep=False):
    """Find real sources. Try web search first; if the backend rejects it (e.g. web search not
    enabled for this key/org), fall back to the model's own knowledge. The grounded fetch step
    then verifies every URL and skips any that don't resolve, so a bad link can't sneak in.
    deep=True runs a far more thorough, multi-search web pass (see _anthropic)."""
    sysmsg = ("You find real, citable sources for a research dispute. "
              "Prefer primary sources and use web search when available.")
    if deep:
        sysmsg += (" Work like a deep-research agent: run many separate searches, dig past the "
                   "first page, and be exhaustive across every position before answering.")
    try:
        return complete(prompt, system=sysmsg, web=True, deep=deep, phase="search")
    except SystemExit as web_err:
        try:
            # still the SEARCH phase, just without the web tool — stay on the search provider
            # (phase='search'), don't fall through to the labelling provider.
            return complete(prompt, system=sysmsg + " Web search is NOT available — list only "
                            "sources you are highly confident exist, with their correct URLs.",
                            web=False, phase="search")
        except SystemExit:
            raise web_err  # both failed: surface the original (web-search) error

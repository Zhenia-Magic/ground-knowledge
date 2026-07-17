"""The hosted portal API (deployment layer, Phase 2).

A thin, store-backed aggregator. It holds the canonical knowledge bases, lets people browse and
search questions, accepts pushed KBs from local CLIs (`cli.py push`), and offers bounded keyless
OpenAlex discovery/fetch for the public contribution flow. It deliberately does **no LLM work and
holds no model API key** — labelling happens in the contributor's browser/chatbot or local CLI.
Merging is pure stdlib, so the server stays cheap and key-free.

Endpoints (JSON):
  GET  /api/questions?search=&limit=     -> [{id, question, counts, ...}]
  POST /api/questions  {question}        -> {id, ...}                     (create)
  GET  /api/questions/{id}               -> {id, question, version, kb}   (pull)
  PUT  /api/questions/{id}  {kb, expected_version, contributor} -> {version}   (push)
  GET  /api/questions/{id}/log           -> [contributions]
  GET  /healthz                          -> ok

Run locally:  python -m app.portal --port 8800     (sqlite store, no key, no deps)
Production:   gunicorn-style not needed; ThreadingHTTPServer behind Railway is fine for this load.
"""
import hmac
import ipaddress
import json
import os
import threading
from http.server import BaseHTTPRequestHandler

from app import store, web
from app.http_utils import BoundedThreadingHTTPServer, SlidingWindowLimiter

MAX_BODY_BYTES = int(os.environ.get("EPISTEMIC_MAX_BODY_BYTES", str(4 * 1024 * 1024)))
MAX_FETCH_URLS = int(os.environ.get("EPISTEMIC_MAX_FETCH_URLS", "10"))
MAX_DELTA_BATCH = int(os.environ.get("EPISTEMIC_MAX_DELTA_BATCH", "50"))
_RATE_LIMITER = SlidingWindowLimiter(int(os.environ.get("EPISTEMIC_RATE_WINDOW_SECONDS", "60")))
_EXPENSIVE_SLOTS = threading.BoundedSemaphore(
    max(1, int(os.environ.get("EPISTEMIC_MAX_EXPENSIVE_REQUESTS", "2"))))


def _configure_from_env():
    global MAX_BODY_BYTES, MAX_FETCH_URLS, MAX_DELTA_BATCH, _RATE_LIMITER, _EXPENSIVE_SLOTS
    MAX_BODY_BYTES = int(os.environ.get("EPISTEMIC_MAX_BODY_BYTES", str(4 * 1024 * 1024)))
    MAX_FETCH_URLS = int(os.environ.get("EPISTEMIC_MAX_FETCH_URLS", "10"))
    MAX_DELTA_BATCH = int(os.environ.get("EPISTEMIC_MAX_DELTA_BATCH", "50"))
    _RATE_LIMITER = SlidingWindowLimiter(
        int(os.environ.get("EPISTEMIC_RATE_WINDOW_SECONDS", "60")))
    _EXPENSIVE_SLOTS = threading.BoundedSemaphore(
        max(1, int(os.environ.get("EPISTEMIC_MAX_EXPENSIVE_REQUESTS", "2"))))


def _audit(action, summary, contributor="portal-admin"):
    return {"action": action, "summary": summary, "contributor": contributor}


def _actor(value, default="anonymous"):
    return value.strip()[:100] if isinstance(value, str) and value.strip() else default


def _admin_delete_source(qid, sid):
    """Remove one source from a question's KB (admin moderation), prune its factor provenance,
    bump the version, and log it. Metrics recompute from the KB on the next render."""
    from engine import curate
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    try:
        report = curate.remove_source(kb, sid, reason="removed by portal administrator",
                                      by="portal-admin")
    except ValueError as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"],
                          _audit("remove-source", report.get("summary", sid)))
    except store.Conflict:
        return {"error": "changed concurrently — reload and retry"}
    return {"ok": True, "version": v}


def _admin_confirm_dataset(qid, dataset_ref, confirmed=True, by="portal-admin", source=None,
                           note=None, allow_similar=False):
    """Curator confirms (or un-confirms) a dataset as a real evidence base — a confirmed root counts
    at full strength; an unconfirmed/paste-back root remains visible but contributes zero headline
    nEff until confirmed (engine/roots). Admin moderation."""
    from engine import curate
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    try:
        res = curate.confirm_dataset(kb, dataset_ref, confirmed, by=_actor(by, "portal-admin"),
                                     source=source, note=note, allow_similar=allow_similar)
    except (ValueError, KeyError) as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"],
                          _audit("confirm-dataset", res.get("summary", "")))
    except store.Conflict:
        return {"error": "changed concurrently — reload and retry"}
    return {"ok": True, "version": v, "summary": res.get("summary")}


def _admin_merge_dataset(qid, src_ref, dst_ref):
    """Curator folds one dataset into another (same evidence base under two names): restsOn edges are
    repointed, the folded name is learned as an alias, and the surviving root keeps/gains confirmation
    (engine/curate.merge_datasets). This is what restores an honest independence reading when one
    cohort was split under two spellings. Admin moderation."""
    from engine import curate
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    try:
        res = curate.merge_datasets(kb, src_ref, dst_ref)
    except (ValueError, KeyError) as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"],
                          _audit("merge-dataset", res.get("summary", "")))
    except store.Conflict:
        return {"error": "changed concurrently — reload and retry"}
    return {"ok": True, "version": v, "summary": res.get("summary")}


def _admin_suggest_duplicates(qid):
    """Advisory list of dataset pairs whose labels look like the same evidence base, so a curator can
    merge without hunting. Suggestions only — never auto-merged (engine/curate.suggest_duplicates)."""
    from engine import curate
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    return {"dataset": curate.suggest_duplicates(q["kb"]).get("dataset", [])}


def _admin_dataset_status(qid):
    """Per-dataset admission status for the manage UI, mirroring what the report actually counts so
    the two views agree: 'curator' (a curator confirmed it), 'verified' (auto-admitted because a
    fetched source's exact quote names it), or 'proposed' (contributes zero to the headline). A base
    admitted by quote is grounded even without a curator record, so it must not read as proposed."""
    from engine import roots as _roots
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    cb = _roots.resolve(q["kb"]).get("confirmed_by", {})
    out = {}
    for d in q["kb"].get("datasets", []):
        rec = cb.get("ds:" + d["id"])
        out[d["id"]] = ("proposed" if not rec
                        else "verified" if str(rec.get("method", "")).startswith("verified-edge")
                        else "curator")
    return {"status": out}


def _admin_unadmitted_edges(qid):
    """The support links the REPORT flags but the datasets panel can't act on: a source claims an
    evidence base whose identity is confirmed, yet this particular source→base link is neither
    quote-verified nor curator-admitted, so it stays visible and contributes zero. Mirrors exactly
    what assess() warns about (engine/roots.resolve unadmitted_source_roots), so the manage page and
    the report agree. Returns one row per unadmitted edge: {source, sourceTitle, position, ref, label}."""
    from engine import roots as _roots
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    uar = _roots.resolve(kb).get("unadmitted_source_roots", {})
    src = {s["id"]: s for s in kb.get("sources", [])}
    ds_label = {d["id"]: d.get("label", d["id"]) for d in kb.get("datasets", [])}
    pos_label = {p["id"]: p.get("label") for p in kb.get("positions", [])}
    out = []
    for sid, root_keys in uar.items():
        source = src.get(sid)
        if not source or not root_keys:
            continue
        for rk in root_keys:
            if rk.startswith("ds:"):                       # root key ds:<id> -> restsOn ref <id>
                ref, label = rk[3:], ds_label.get(rk[3:], rk[3:])
            elif rk.startswith("src:"):                    # a source-citation edge keeps its prefix
                ref, label = rk, "source cited: " + rk[4:]
            else:
                ref, label = rk, rk
            out.append({"source": sid, "sourceTitle": source.get("title", ""),
                        "position": pos_label.get(source.get("position"), source.get("position")),
                        "ref": ref, "label": label})
    return {"edges": out}


def _admin_confirm_edge(qid, source_ref, edge_ref, confirmed=True, by="portal-admin", note=None):
    """Curator admits (or un-admits) one source→base/citation support edge — the human fallback when
    no fetched dependency quote verified it (engine/curate.confirm_edge). An admitted edge on a
    confirmed base starts counting toward coverage. Admin moderation; the auditable counterpart of the
    datasets panel's confirm, for the *link* layer rather than the *identity* layer."""
    from engine import curate
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    try:
        res = curate.confirm_edge(kb, source_ref, edge_ref, confirmed,
                                  by=_actor(by, "portal-admin"), note=note)
    except (ValueError, KeyError) as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"], _audit("confirm-edge", res.get("summary", "")))
    except store.Conflict:
        return {"error": "changed concurrently — reload and retry"}
    return {"ok": True, "version": v, "summary": res.get("summary")}


def _admin_set_dataset_kind(qid, dataset_ref, kind):
    """Curator sets an evidence base's kind (dataset | document | argument | model). Display + the
    empirical non-human discount only; never changes admission. Admin moderation."""
    from engine import curate
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    try:
        res = curate.set_kind(kb, dataset_ref, kind)
    except (ValueError, KeyError) as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"],
                          _audit("set-dataset-kind", res.get("summary", "")))
    except store.Conflict:
        return {"error": "changed concurrently — reload and retry"}
    return {"ok": True, "version": v, "summary": res.get("summary")}


def _admin_set_curated(qid, curated=True, by="portal-admin", note=None):
    """Admin marks (or unmarks) a whole question as officially curated & maintained — a trusted
    stewardship label shown to readers next to the computed confirmed-coverage percentage, never as a
    substitute for it (engine/curate.set_curated). Admin moderation; meta is unreachable by the public
    contribute path, so this is the only way the flag can be set on the portal (besides an admin push)."""
    from engine import curate
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    try:
        res = curate.set_curated(kb, curated=curated, by=_actor(by, "portal-admin"), note=note)
    except (ValueError, KeyError) as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"], _audit("set-curated", res.get("summary", "")))
    except store.Conflict:
        return {"error": "changed concurrently — reload and retry"}
    return {"ok": True, "version": v, "summary": res.get("summary")}


def _admin_review_resolve(qid, item_id, kind, action, position=None):
    """Resolve one ensemble disagreement ON THE PORTAL (admin moderation): a queued item
    (kind='pending') gets merged with the admin's chosen position or dropped; an already-merged
    flagged source (kind='flagged') gets its position re-decided in place, kept, or dropped.
    Pushed KBs carry both, so an admin can fix contested labels on the spot instead of
    round-tripping through the console. Same engine logic as everywhere else (engine/review.py)."""
    from engine import review
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    try:
        if kind == "flagged":
            rep = review.resolve_flagged_source(kb, item_id, action, position)
        else:
            rep = review.resolve_review(kb, item_id, action, position)
    except ValueError as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"],
                          _audit("resolve-review", "resolved review item " + str(item_id)))
    except store.Conflict:
        return {"error": "changed concurrently — reload and retry"}
    return {"ok": True, "version": v, "report": rep,
            "pending": len(kb.get("pendingReview", []))}


def _read_question(qid):
    q = store.get_question(qid, with_kb=True)
    if not q:
        return None
    return {"id": q["id"], "question": q["question"], "version": q["version"], "kb": q["kb"]}


def _strip_unverifiable_trust_fields(delta):
    """textDepth and provenance[field].verifiedQuote/factorWeights[].verifiedQuote are only
    honest when engine.verify computed them against text the server itself fetched
    (ingest/pipeline.py's _carry_meta, the CLI/automated paths). This keyless paste-back
    endpoint never fetches anything server-side, so a client could otherwise self-declare
    "textDepth": "full", "verifiedQuote": "exact" on a fabricated quote with nothing to check
    it against. Strip rather than trust."""
    from engine.verify import strip_untrusted_verification
    return strip_untrusted_verification(delta)


def _norm_delta(it):
    """Accept either a full delta {source, factorWeights} or a bare source object."""
    if not isinstance(it, dict):
        return None
    if "source" in it:
        return _strip_unverifiable_trust_fields(it)
    if it.get("title") and it.get("position"):
        return _strip_unverifiable_trust_fields(
            {"source": it, "factorWeights": it.get("factorWeights", [])})
    return None


def _delta_validation_error(delta):
    from engine.validate import delta_validation_errors
    errors = delta_validation_errors(delta)
    return errors[0] if errors else None


def _apply_delta(qid, q, delta, contributor):
    """Queue one or many public paste-back deltas for human review, version-checked.

    This endpoint has no trusted fetch context or authenticated curator identity. It therefore must
    not mutate positions, roots, or headline metrics directly. Admin review can admit/drop the
    source; support edges still require their own quote/curator admission in ``engine.roots``.
    """
    from engine import review
    kb, base = q["kb"], q["version"]
    items = delta if isinstance(delta, list) else [delta]
    if len(items) > MAX_DELTA_BATCH:
        return {"error": "too many deltas in one request (max {})".format(MAX_DELTA_BATCH)}
    deltas = []
    for it in items:
        d = _norm_delta(it)
        if not d:
            return {"error": "delta must be a source object or {source, factorWeights}"}
        err = _delta_validation_error(d)
        if err:
            return {"error": err}
        deltas.append(d)
    queued = dups = 0
    for d in deltas:
        src = d["source"]
        position = str(src.get("position") or "").strip()
        pv = (src.get("provenance") or {}).get("position") or {}
        src["modelAgreement"] = {
            "models": 0, "flagged": True, "reviewReason": "public-unverified-contribution",
            "positionVote": {position: 1},
            "proposals": [{"position": position, "votes": 1,
                           "quote": pv.get("quote") or "", "confidence": None}],
        }
        if review.queue_for_review(kb, d) is None:
            dups += 1
        else:
            queued += 1
    if not queued:
        return {"queued": 0, "duplicates": dups, "version": base}
    try:
        summary = "{} queued for review, {} duplicate".format(queued, dups)
        version = store.save_kb(qid, kb, base,
                                _audit("queue-sources", summary, contributor or "anonymous"))
    except store.Conflict:
        return {"error": "someone else updated this question — reload and re-import"}
    return {"queued": queued, "duplicates": dups, "version": version}


class Handler(BaseHTTPRequestHandler):
    server_version = "epistemic-portal/0.1"

    # -- helpers --
    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
                         "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")  # browser clients
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code, html):
        body = (html or "<h1>Not found</h1>").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._body_error = (400, {"error": "invalid Content-Length"})
            return None
        if n < 0:
            self._body_error = (400, {"error": "invalid Content-Length"})
            return None
        if n > MAX_BODY_BYTES:
            self._body_error = (413, {"error": "request body too large",
                                      "limit": MAX_BODY_BYTES})
            return None
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self._body_error = (400, {"error": "invalid JSON body"})
            return None

    def _json_body(self):
        self._body_error = None
        body = self._body()
        if body is None:
            code, obj = self._body_error or (400, {"error": "invalid request body"})
            self._send(code, obj)
            return None
        if not isinstance(body, dict):
            self._send(400, {"error": "JSON body must be an object"})
            return None
        return body

    def _get_q(self, qid):
        return store.get_question(qid, with_kb=True)

    def _is_admin(self):
        """True only if ADMIN_TOKEN is configured AND the request carries the matching token."""
        tok = os.environ.get("ADMIN_TOKEN")
        sent = self.headers.get("X-Admin-Token", "")
        return bool(tok) and hmac.compare_digest(sent, tok)

    def _client_key(self):
        # A proxy appends the real client to any attacker-supplied XFF chain, so trust the final
        # syntactically valid address rather than the spoofable first value.
        forwarded = (self.headers.get("X-Forwarded-For") or "").rsplit(",", 1)[-1].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            return str(self.client_address[0])

    def _rate_ok(self, action, limit):
        if _RATE_LIMITER.allow((self._client_key(), action), limit):
            return True
        self._send(429, {"error": "too many requests; please retry shortly"})
        return False

    def _send_file(self, text, mime, filename):
        body = (text or "").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="{}"'.format(filename))
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parts(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        return [p for p in path.split("/") if p]

    def _query(self):
        if "?" not in self.path:
            return {}
        from urllib.parse import parse_qs
        return {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}

    def log_message(self, *a):  # quieter
        pass

    def do_OPTIONS(self):
        self._send(200, {})

    # -- routes --
    def do_GET(self):
        p = self._parts()
        if p == ["healthz"]:
            return self._send(200, {"ok": True})
        # --- browser pages ---
        if p == []:
            return self._send_html(200, web.home_html())
        if p == ["docs"]:
            return self._send_html(200, web.docs_html())
        if len(p) == 2 and p[0] == "q":
            return self._send_html(200, web.viewer_html(p[1], self._get_q) or "")
        if len(p) == 3 and p[0] == "q" and p[2] == "add":
            return self._send_html(200, web.contribute_html(p[1], self._get_q) or "")
        if len(p) == 3 and p[0] == "q" and p[2] == "manage":
            return self._send_html(200, web.manage_html(p[1], self._get_q) or "")
        # --- JSON API ---
        if p == ["api", "questions"]:
            q = self._query()
            try:
                limit = int(q.get("limit") or 100)
            except (TypeError, ValueError):
                return self._send(400, {"error": "limit must be an integer"})
            limit = max(1, min(limit, 100))
            return self._send(200, {"questions": store.list_questions(q.get("search"), limit)})
        if len(p) == 3 and p[:2] == ["api", "questions"]:
            data = _read_question(p[2])
            return self._send(200, data) if data else self._send(404, {"error": "no such question"})
        if len(p) == 4 and p[:2] == ["api", "questions"] and p[3] == "log":
            return self._send(200, {"log": store.contributions(p[2])})
        if len(p) == 4 and p[:2] == ["api", "questions"] and p[3] == "export":
            q = self._get_q(p[2])
            if not q:
                return self._send(404, {"error": "no such question"})
            fmt = self._query().get("format", "bibtex")
            name = q["kb"]["meta"].get("id", "question")
            if fmt in ("kb", "json", "knowledge"):    # the full knowledge base — the portable artifact
                return self._send_file(json.dumps(q["kb"], indent=2, ensure_ascii=False),
                                       "application/json", name + ".kb.json")
            from ingest import citations
            text, mime, ext = citations.export(q["kb"], fmt)
            return self._send_file(text, mime, "{}.{}".format(name, ext))
        # --- reader study (anonymous) ---
        if p == ["study"]:
            from app import study_web
            import uuid as _uuid
            if not self._rate_ok("study-assignment", 10):
                return
            assignment = store.new_study_assignment()
            return self._send_html(200, study_web.study_form_html(
                assignment["plan"], assignment["id"], _uuid.uuid4().hex[:6]))
        if len(p) == 3 and p[0] == "study" and p[1] == "report":
            from app import study_web
            html = study_web.study_report_html(p[2])
            return self._send_html(200 if html else 404, html or "<h1>Not found</h1>")
        if p == ["study", "results"]:
            if not self._is_admin():
                return self._send(403, {"error": "admin token required"})
            from app import study_web
            return self._send_html(200, study_web.study_results_html(store.list_study_responses()))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        p = self._parts()
        # --- admin moderation (gated by ADMIN_TOKEN) ---
        if len(p) == 2 and p[0] == "api" and p[1] == "admin-check":
            return self._send(200, {"admin": self._is_admin()})
        if len(p) == 3 and p[:2] == ["api", "admin"]:
            if not self._is_admin():
                return self._send(403, {"error": "admin token required or incorrect"})
            body = self._json_body()
            if body is None:
                return
            if p[2] == "delete-question":
                store.delete_question(body.get("id"))
                return self._send(200, {"ok": True})
            if p[2] == "delete-source":
                return self._send(200, _admin_delete_source(body.get("id"), body.get("sourceId")))
            if p[2] == "review-resolve":
                return self._send(200, _admin_review_resolve(
                    body.get("id"), body.get("itemId") or body.get("prId"),
                    body.get("kind", "pending"), body.get("action"), body.get("position")))
            if p[2] == "confirm-dataset":
                return self._send(200, _admin_confirm_dataset(
                    body.get("id"), body.get("dataset") or body.get("datasetId"),
                    body.get("confirmed", True), body.get("by") or "portal-admin",
                    body.get("source"), body.get("note"), body.get("allowSimilar", False)))
            if p[2] == "merge-dataset":
                return self._send(200, _admin_merge_dataset(
                    body.get("id"), body.get("src") or body.get("from"),
                    body.get("dst") or body.get("into")))
            if p[2] == "suggest-duplicates":
                return self._send(200, _admin_suggest_duplicates(body.get("id")))
            if p[2] == "dataset-status":
                return self._send(200, _admin_dataset_status(body.get("id")))
            if p[2] == "unadmitted-edges":
                return self._send(200, _admin_unadmitted_edges(body.get("id")))
            if p[2] == "confirm-edge":
                return self._send(200, _admin_confirm_edge(
                    body.get("id"), body.get("source"), body.get("edge") or body.get("ref"),
                    body.get("confirmed", True), body.get("by") or "portal-admin", body.get("note")))
            if p[2] == "set-dataset-kind":
                return self._send(200, _admin_set_dataset_kind(
                    body.get("id"), body.get("dataset") or body.get("datasetId"), body.get("kind")))
            if p[2] == "set-curated":
                return self._send(200, _admin_set_curated(
                    body.get("id"), body.get("curated", True),
                    body.get("by") or "portal-admin", body.get("note")))
            return self._send(404, {"error": "unknown admin action"})
        if p == ["api", "questions"]:
            if not self._rate_ok("create-question", 6):
                return
            body = self._json_body()
            if body is None:
                return
            if not isinstance(body.get("question"), str):
                return self._send(400, {"error": "question text required"})
            question = body["question"].strip()
            if not question:
                return self._send(400, {"error": "question text required"})
            if len(question) > 1000:
                return self._send(400, {"error": "question is too long (max 1000 chars)"})
            q = store.create_question(question, _actor(body.get("contributor")))
            return self._send(201, {"id": q["id"], "question": q["question"], "version": 0})
        # contribute flow: /api/questions/{id}/{discover|fetch|delta} — all keyless server-side
        if len(p) == 4 and p[:2] == ["api", "questions"]:
            qid, action = p[2], p[3]
            q = self._get_q(qid)
            if not q:
                return self._send(404, {"error": "no such question"})
            body = self._json_body()
            if body is None:
                return
            if action == "discover":
                if not self._rate_ok("discover", 10):
                    return
                try:
                    k = max(1, min(int(body.get("k") or 10), 50))
                except (TypeError, ValueError):
                    return self._send(400, {"error": "k must be an integer"})
                if not _EXPENSIVE_SLOTS.acquire(False):
                    return self._send(429, {"error": "server is busy; retry shortly"})
                from ingest.search import search_openalex
                try:
                    try:
                        cands = search_openalex(q["question"], k)
                    except Exception:
                        return self._send(502, {"error": "scholarly discovery is temporarily unavailable"})
                finally:
                    _EXPENSIVE_SLOTS.release()
                return self._send(200, {"candidates": cands})
            if action == "fetch":
                if not self._rate_ok("fetch", 4):
                    return
                from ingest.pipeline import fetch_docs, build_batch_extract_prompt
                raw_urls = body.get("urls") or []
                if not isinstance(raw_urls, list) or any(not isinstance(u, str) for u in raw_urls):
                    return self._send(400, {"error": "urls must be an array of strings"})
                urls = [u.strip() for u in raw_urls if u.strip()]
                if len(urls) > MAX_FETCH_URLS:
                    return self._send(400, {"error": "too many URLs in one fetch request",
                                            "limit": MAX_FETCH_URLS})
                if not _EXPENSIVE_SLOTS.acquire(False):
                    return self._send(429, {"error": "server is busy; retry shortly"})
                try:
                    docs, skipped = fetch_docs(urls, allow_local=False)
                finally:
                    _EXPENSIVE_SLOTS.release()
                # ONE bundle over all fetched sources -> one file to upload, one JSON array back.
                # Full per-source text (not the old multi-prompt batches' small per-source cap),
                # so labelling sees the whole paper, not just the first few thousand characters.
                bundle = build_batch_extract_prompt(q["kb"], docs) if docs else ""
                return self._send(200, {"bundle": bundle, "fetched": len(docs),
                                        "skipped": skipped})
            if action == "import-citations":
                if not self._rate_ok("import-citations", 20):
                    return
                from ingest import citations
                try:
                    cands = citations.parse(body.get("text", ""), filename=body.get("filename", ""))
                except Exception as e:
                    return self._send(400, {"error": "could not parse citations: {}".format(e)})
                return self._send(200, {"candidates": cands})
            if action == "delta":
                if not self._rate_ok("delta", 30):
                    return
                res = _apply_delta(qid, q, body.get("delta"), _actor(body.get("contributor")))
                return self._send(400 if res.get("error") else 200, res)
            return self._send(404, {"error": "unknown action"})
        # --- reader study: anonymous response collection + auto-scoring ---
        if p == ["api", "study"]:
            if not self._rate_ok("study-submit", 10):
                return
            body = self._json_body()
            if body is None:
                return
            if not isinstance(body.get("cases"), list) or not body["cases"]:
                return self._send(400, {"error": "no cases in submission"})
            from eval.reader_study import study
            assignment_id = body.get("assignment")
            assignment = store.get_study_assignment(assignment_id)
            if not assignment or assignment.get("consumed"):
                return self._send(400, {"error": "study assignment is invalid or already submitted"})
            try:
                response = study.normalize_response_for_plan(body, assignment["plan"])
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            scored = study.score_response(response)
            if not scored:
                return self._send(400, {"error": "no scorable cases in submission"})
            try:
                store.save_study_response(assignment_id, response.get("participant"), response, scored)
            except store.Conflict as e:
                return self._send(409, {"error": str(e)})
            correct = sum(o["score"]["nCorrect"] for o in scored)
            items = sum(o["score"]["nItems"] for o in scored)
            return self._send(200, {"ok": True, "correct": correct, "items": items})
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        p = self._parts()
        if len(p) == 3 and p[:2] == ["api", "questions"]:
            body = self._json_body()
            if body is None:
                return
            kb = body.get("kb")
            if not isinstance(kb, dict):
                return self._send(400, {"error": "kb (object) required"})
            admin = self._is_admin()
            existing = store.get_question(p[2], with_kb=True)
            if not existing:
                return self._send(404, {"error": "no such question — create it first via POST /api/questions"})
            if not admin:
                # A keyless push may SEED a new/empty question, but never replace populated work and
                # never carry trust: sanitize curator confirmations, edge admissions, verified quotes,
                # and the curated stewardship flag so a non-admin can't inflate coverage or forge the
                # badge. Replacing a question that already has sources still needs the admin token.
                if existing.get("kb", {}).get("sources"):
                    return self._send(403, {"error": "this question already has sources — replacing the "
                                            "whole KB needs the admin token; add sources via the review flow instead"})
                if not self._rate_ok("push-open", 6):
                    return
                from engine.verify import strip_untrusted_kb
                strip_untrusted_kb(kb)
            try:
                from engine.migrate import migrate_kb, validation_errors
                kb, _changes = migrate_kb(kb)
                errors = validation_errors(kb)
                if errors:
                    return self._send(400, {"error": "invalid KB", "details": errors[:50]})
                version = store.save_kb(
                    p[2], kb, int(body.get("expected_version", 0)),
                    _audit("push-kb" if admin else "push-kb-open", "replaced canonical KB",
                           body.get("contributor") or "anonymous"))
            except (ValueError, TypeError) as e:
                return self._send(400, {"error": "invalid KB", "detail": str(e)})
            except store.Conflict as e:
                return self._send(409, {"error": "version conflict", "detail": str(e)})
            return self._send(200, {"version": version})
        self._send(404, {"error": "not found"})


def _seed_if_empty():
    """On a fresh deploy the store is empty — load the bundled demo cases so the portal isn't
    blank. Idempotent: does nothing once questions exist."""
    try:
        if store.list_questions(limit=1):
            return
        from app.seed import seed_from_cases
        added = seed_from_cases()
        if added:
            print("Seeded {} demo question(s).".format(len(added)))
    except Exception as e:
        print("seed skipped:", e)


def run(port=8800):
    from app.env import load_dotenv
    load_dotenv()
    store.configure_from_env()
    _configure_from_env()
    store.init_db()
    _seed_if_empty()
    httpd = BoundedThreadingHTTPServer(
        ("0.0.0.0", port), Handler,
        max_workers=int(os.environ.get("EPISTEMIC_MAX_REQUEST_THREADS", "32")),
        socket_timeout=int(os.environ.get("EPISTEMIC_SOCKET_TIMEOUT", "30")))
    print("Portal on http://0.0.0.0:{}  (store: {})".format(
        port, "Postgres" if store._IS_PG else store._SQLITE_PATH))
    httpd.serve_forever()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8800)))
    run(ap.parse_args().port)

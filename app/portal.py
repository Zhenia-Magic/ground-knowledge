"""The hosted portal API (deployment layer, Phase 2).

A thin, store-backed aggregator. It holds the canonical knowledge bases, lets people browse and
search questions, and accepts pushed KBs from local CLIs (`cli.py push`). It deliberately does
**no LLM work and holds no API key** — the expensive discover/fetch/label happens locally in the
contributor's CLI with their own env key; the portal only stores and serves the deterministic
result. Merging is pure stdlib, so the server stays cheap and key-free.

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
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import store, web

MAX_BODY_BYTES = int(os.environ.get("EPISTEMIC_MAX_BODY_BYTES", str(4 * 1024 * 1024)))
MAX_FETCH_URLS = int(os.environ.get("EPISTEMIC_MAX_FETCH_URLS", "25"))


def _admin_delete_source(qid, sid):
    """Remove one source from a question's KB (admin moderation), prune its factor provenance,
    bump the version, and log it. Metrics recompute from the KB on the next render."""
    from engine.merge import now_iso
    q = store.get_question(qid, with_kb=True)
    if not q:
        return {"error": "no such question"}
    kb = q["kb"]
    before = len(kb.get("sources", []))
    kb["sources"] = [s for s in kb.get("sources", []) if s.get("id") != sid]
    if len(kb["sources"]) == before:
        return {"error": "source not found"}
    for f in kb.get("factors", []):
        f["provenance"] = [pv for pv in f.get("provenance", []) if pv.get("source") != sid]
    from engine.curate import repoint_confirmation_source
    repoint_confirmation_source(kb, sid, reason="supporting source removed by portal administrator")
    from engine.merge import recompute_factor_weights
    recompute_factor_weights(kb)                      # re-derive cells so the dropped weight is gone
    kb["meta"]["version"] = kb["meta"].get("version", 0) + 1
    kb.setdefault("log", []).append({"version": kb["meta"]["version"],
                                     "action": "admin-remove-source", "source": sid,
                                     "ts": now_iso()})
    try:
        v = store.save_kb(qid, kb, q["version"])
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
        res = curate.confirm_dataset(kb, dataset_ref, confirmed, by=by or "portal-admin",
                                     source=source, note=note, allow_similar=allow_similar)
    except (ValueError, KeyError) as e:
        return {"error": str(e)}
    try:
        v = store.save_kb(qid, kb, q["version"])
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
        v = store.save_kb(qid, kb, q["version"])
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
        v = store.save_kb(qid, kb, q["version"])
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
    src = delta.get("source")
    if not isinstance(src, dict):
        return "delta.source must be an object"
    if src.get("relevant") is False:
        return None
    for field in ("title", "position"):
        if not str(src.get(field) or "").strip():
            return "delta.source.{} is required".format(field)
    if len(str(src.get("title"))) > 500:
        return "delta.source.title is too long (max 500 chars)"
    # restsOn is the root-admission surface: bound it and type-check it so one public source can't
    # supply an unbounded or malformed root list. (Novel roots from this path are unverified ->
    # textDepth is stripped to 'unknown' -> they stay visible but count ZERO until an auditable
    # confirmation admits them; see engine/roots.)
    rests = src.get("restsOn")
    if rests is not None:
        if not isinstance(rests, list):
            return "delta.source.restsOn must be an array"
        if len(rests) > 40:
            return "delta.source.restsOn has too many entries (max 40)"
        for i, e in enumerate(rests):
            if isinstance(e, dict):                       # edge object {ref, provenance}
                ref = e.get("ref")
                if not isinstance(ref, (str, int, float)) or not str(ref).strip():
                    return "delta.source.restsOn[{}].ref is required".format(i)
                if len(str(ref)) > 300:
                    return "delta.source.restsOn[{}].ref is too long".format(i)
                ep = e.get("provenance")
                if ep is not None and not isinstance(ep, dict):
                    return "delta.source.restsOn[{}].provenance must be an object".format(i)
                if isinstance(ep, dict) and len(str(ep.get("quote") or "")) > 2000:
                    return "delta.source.restsOn[{}].provenance.quote is too long".format(i)
                continue
            if not isinstance(e, (str, int, float)):
                return "delta.source.restsOn[{}] must be a string or {{ref, provenance}} object".format(i)
            if len(str(e)) > 300:
                return "delta.source.restsOn[{}] is too long".format(i)
    factor_weights = delta.get("factorWeights", [])
    if not isinstance(factor_weights, list):
        return "delta.factorWeights must be an array"
    if len(factor_weights) > 40:
        return "delta.factorWeights has too many entries (max 40)"
    for i, fw in enumerate(factor_weights):
        if not isinstance(fw, dict):
            return "delta.factorWeights[{}] must be an object".format(i)
        if not str(fw.get("factorLabel") or fw.get("factor") or "").strip():
            return "delta.factorWeights[{}].factorLabel is required".format(i)
        if fw.get("weight") not in ("high", "med", "low", "n/a"):
            return "delta.factorWeights[{}].weight must be high, med, low, or n/a".format(i)
    return None


def _apply_delta(qid, q, delta, contributor):
    """Merge one or many deltas into the question's KB (deterministic, no key), version-checked.
    A batch is one optimistic transaction: it records ONE recompute diff (whole batch, before→after)
    on the LAST added source's log entry, so the Changes tab shows what the contribution moved."""
    from engine.merge import merge_delta
    from engine.assess import assess, diff_assessments
    kb, base = q["kb"], q["version"]
    items = delta if isinstance(delta, list) else [delta]
    deltas = []
    for it in items:
        d = _norm_delta(it)
        if not d:
            return {"error": "delta must be a source object or {source, factorWeights}"}
        err = _delta_validation_error(d)
        if err:
            return {"error": err}
        deltas.append(d)
    added = dups = off = 0
    # Assess the existing artifact once, then the completed batch once. The previous implementation
    # assessed before and after EVERY source (2M whole-KB traversals for an M-source import), turning
    # large contributions into avoidable quadratic work. A batch is one optimistic transaction and
    # now has one epistemic diff; its last add-source log entry owns that diff.
    before = assess(kb)
    last_added_log = None
    for d in deltas:
        rep = merge_delta(kb, d)
        if rep.get("offTopic"):
            off += 1
        elif rep.get("duplicate"):
            dups += 1
        elif rep.get("addedSource"):
            added += 1
            if kb.get("log"):
                last_added_log = kb["log"][-1]
    from engine.merge import resolve_pending_refs
    resolve_pending_refs(kb)                          # second pass: NEW-SRC forward refs in this batch
    if last_added_log is not None:                    # persist one complete transaction diff
        last_added_log["diff"] = diff_assessments(before, assess(kb))
        last_added_log["batchSize"] = added
    try:
        version = store.save_kb(qid, kb, base)
    except store.Conflict:
        return {"error": "someone else updated this question — reload and re-import"}
    store.log_contribution(qid, contributor or "anonymous", "add-sources",
                           "{} added, {} duplicate, {} off-topic".format(added, dups, off))
    return {"added": added, "duplicates": dups, "offTopic": off, "version": version}


class Handler(BaseHTTPRequestHandler):
    server_version = "epistemic-portal/0.1"

    # -- helpers --
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")  # browser clients
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code, html):
        body = (html or "<h1>Not found</h1>").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
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

    def _send_file(self, text, mime, filename):
        body = (text or "").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="{}"'.format(filename))
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
            limit = int(q.get("limit") or 100)
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
            idx = store.count_study_participants()
            return self._send_html(200, study_web.study_form_html(idx, _uuid.uuid4().hex[:6]))
        if len(p) == 3 and p[0] == "study" and p[1] == "report":
            from app import study_web
            html = study_web.study_report_html(p[2])
            return self._send_html(200 if html else 404, html or "<h1>Not found</h1>")
        if p == ["study", "results"]:
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
            return self._send(404, {"error": "unknown admin action"})
        if p == ["api", "questions"]:
            body = self._json_body()
            if body is None:
                return
            question = (body.get("question") or "").strip()
            if not question:
                return self._send(400, {"error": "question text required"})
            q = store.create_question(question, body.get("contributor") or "anonymous")
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
                from ingest.search import search_openalex
                cands = search_openalex(q["question"], int(body.get("k") or 10))
                return self._send(200, {"candidates": cands})
            if action == "fetch":
                from ingest.pipeline import fetch_docs, build_batch_extract_prompt
                urls = [u for u in (body.get("urls") or []) if u]
                if len(urls) > MAX_FETCH_URLS:
                    return self._send(400, {"error": "too many URLs in one fetch request",
                                            "limit": MAX_FETCH_URLS})
                docs, skipped = fetch_docs(urls, allow_local=False)
                # ONE bundle over all fetched sources -> one file to upload, one JSON array back.
                # Full per-source text (not the old multi-prompt batches' small per-source cap),
                # so labelling sees the whole paper, not just the first few thousand characters.
                bundle = build_batch_extract_prompt(q["kb"], docs) if docs else ""
                return self._send(200, {"bundle": bundle, "fetched": len(docs),
                                        "skipped": skipped})
            if action == "import-citations":
                from ingest import citations
                try:
                    cands = citations.parse(body.get("text", ""), filename=body.get("filename", ""))
                except Exception as e:
                    return self._send(400, {"error": "could not parse citations: {}".format(e)})
                return self._send(200, {"candidates": cands})
            if action == "delta":
                res = _apply_delta(qid, q, body.get("delta"), body.get("contributor"))
                return self._send(400 if res.get("error") else 200, res)
            return self._send(404, {"error": "unknown action"})
        # --- reader study: anonymous response collection + auto-scoring ---
        if p == ["api", "study"]:
            body = self._json_body()
            if body is None:
                return
            if not isinstance(body.get("cases"), list) or not body["cases"]:
                return self._send(400, {"error": "no cases in submission"})
            from eval.reader_study import study
            scored = study.score_response(body)
            if not scored:
                return self._send(400, {"error": "no scorable cases in submission"})
            store.save_study_response(body.get("participant"), body, scored)
            correct = sum(o["score"]["nCorrect"] for o in scored)
            items = sum(o["score"]["nItems"] for o in scored)
            return self._send(200, {"ok": True, "correct": correct, "items": items})
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        p = self._parts()
        if len(p) == 3 and p[:2] == ["api", "questions"]:
            if not self._is_admin():
                return self._send(403, {"error": "admin token required or incorrect"})
            body = self._json_body()
            if body is None:
                return
            kb = body.get("kb")
            if not isinstance(kb, dict):
                return self._send(400, {"error": "kb (object) required"})
            try:
                version = store.save_kb(p[2], kb, int(body.get("expected_version", 0)))
            except store.Conflict as e:
                return self._send(409, {"error": "version conflict", "detail": str(e)})
            store.log_contribution(p[2], body.get("contributor") or "anonymous",
                                   "push-kb", "version -> {}".format(version))
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
    store.init_db()
    _seed_if_empty()
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("Portal on http://0.0.0.0:{}  (store: {})".format(
        port, "Postgres" if store._IS_PG else store._SQLITE_PATH))
    httpd.serve_forever()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8800)))
    run(ap.parse_args().port)

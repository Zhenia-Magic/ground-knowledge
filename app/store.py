"""Persistence for the deployed app (Phase 1 of the deployment layer).

A question holds one KB (the portable JSON document — unchanged). Around it we add a small
amount of relational state the multi-user app needs: a list of questions to browse/search, a
record of long-running harvest jobs, and a contribution log (who added what — open access now,
ready for accounts later).

ONE code path, two backends:
  * local dev  -> stdlib sqlite3, a file under ./data (zero new dependency).
  * production -> Postgres, when DATABASE_URL is set (Railway). `pip install psycopg[binary]`.

The KB is stored as a JSON document (TEXT in sqlite, JSONB in Postgres) so it stays the single
portable artifact — `export` just hands back kb verbatim. SQL is written with `?` placeholders
and translated for Postgres, and kept to the common subset both speak.
"""
import json
import os
import time
import uuid

from engine.schema import empty_kb
from engine.merge import slug

DATABASE_URL = os.environ.get("DATABASE_URL")
_IS_PG = bool(DATABASE_URL)
_SQLITE_PATH = os.environ.get("EPISTEMIC_DB", os.path.join("data", "app.db"))


class Conflict(Exception):
    """Raised when a KB write loses an optimistic-concurrency check (someone else wrote first)."""


# ---- connection / dialect ------------------------------------------------------------------

def _connect():
    if _IS_PG:
        import psycopg  # production only
        from psycopg.rows import dict_row  # rows keyed by column name, like sqlite3.Row
        return psycopg.connect(DATABASE_URL, autocommit=False, row_factory=dict_row)
    import sqlite3
    os.makedirs(os.path.dirname(_SQLITE_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrency for the local file
    return conn


def _sql(s):
    """sqlite uses ? placeholders; Postgres uses %s. Author once with ?, translate for PG."""
    return s.replace("?", "%s") if _IS_PG else s


def _now():
    return int(time.time())


# JSONB vs TEXT: in Postgres we cast the column to jsonb; either way we send/parse JSON strings,
# so the Python side is identical.
_KB_COL = "JSONB" if _IS_PG else "TEXT"


def configure_from_env():
    """Refresh backend configuration after the entrypoint has loaded ``.env``."""
    global DATABASE_URL, _IS_PG, _SQLITE_PATH, _KB_COL
    DATABASE_URL = os.environ.get("DATABASE_URL")
    _IS_PG = bool(DATABASE_URL)
    _SQLITE_PATH = os.environ.get("EPISTEMIC_DB", os.path.join("data", "app.db"))
    _KB_COL = "JSONB" if _IS_PG else "TEXT"


def _columns(cur, table):
    if _IS_PG:
        cur.execute("SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = current_schema() AND table_name = %s",
                    (table,))
        return {row["column_name"] for row in cur.fetchall()}
    cur.execute("PRAGMA table_info({})".format(table))
    return {row["name"] for row in cur.fetchall()}


def _add_column(cur, table, name, sql_type):
    if name not in _columns(cur, table):
        cur.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, name, sql_type))


def init_db():
    """Create tables if absent. Safe to call on every boot."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql(
            "CREATE TABLE IF NOT EXISTS questions ("
            " id TEXT PRIMARY KEY,"
            " slug TEXT,"
            " question TEXT NOT NULL,"
            " kb {kb} NOT NULL,"
            " version INTEGER NOT NULL DEFAULT 0,"
            " source_count INTEGER NOT NULL DEFAULT 0,"
            " position_count INTEGER NOT NULL DEFAULT 0,"
            " dataset_count INTEGER NOT NULL DEFAULT 0,"
            " kb_version INTEGER NOT NULL DEFAULT 0,"
            " created_at INTEGER NOT NULL,"
            " updated_at INTEGER NOT NULL)".format(kb=_KB_COL)))
        cur.execute(_sql(
            "CREATE TABLE IF NOT EXISTS jobs ("
            " id TEXT PRIMARY KEY,"
            " question_id TEXT NOT NULL,"
            " kind TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'running',"
            " progress {kb} NOT NULL,"        # JSON array of log lines
            " result {kb},"                   # JSON summary when done
            " created_at INTEGER NOT NULL,"
            " updated_at INTEGER NOT NULL)".format(kb=_KB_COL)))
        cur.execute(_sql(
            "CREATE TABLE IF NOT EXISTS contributions ("
            " id TEXT PRIMARY KEY,"
            " question_id TEXT NOT NULL,"
            " contributor TEXT NOT NULL DEFAULT 'anonymous',"
            " action TEXT NOT NULL,"
            " summary TEXT,"
            " created_at INTEGER NOT NULL)"))
        cur.execute(_sql(
            "CREATE TABLE IF NOT EXISTS study_responses ("   # blinded reader study (eval/reader_study)
            " id TEXT PRIMARY KEY,"
            " participant TEXT,"                              # self-chosen token, NOT PII
            " response {kb} NOT NULL,"                        # raw answers (incl. free text)
            " scored {kb} NOT NULL,"                          # auto-scored objective observations
            " assignment_id TEXT,"
            " created_at INTEGER NOT NULL)".format(kb=_KB_COL)))
        cur.execute(_sql(
            "CREATE TABLE IF NOT EXISTS study_assignments ("
            " id TEXT PRIMARY KEY,"
            " plan {kb} NOT NULL,"
            " consumed INTEGER NOT NULL DEFAULT 0,"
            " created_at INTEGER NOT NULL,"
            " submitted_at INTEGER)".format(kb=_KB_COL)))

        # Additive migrations for databases created by earlier releases.
        for name in ("source_count", "position_count", "dataset_count", "kb_version"):
            _add_column(cur, "questions", name, "INTEGER")
        _add_column(cur, "study_responses", "assignment_id", "TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_updated ON questions(updated_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_contributions_question ON contributions(question_id, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_question ON jobs(question_id, created_at)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_study_response_assignment ON study_responses(assignment_id)")

        # Backfill compact question-card metadata once; list_questions never needs to parse KB blobs.
        cur.execute("SELECT id, kb FROM questions WHERE source_count IS NULL OR position_count IS NULL"
                    " OR dataset_count IS NULL OR kb_version IS NULL")
        for row in cur.fetchall():
            counts = _counts(_load(row["kb"]))
            cur.execute(_sql("UPDATE questions SET source_count = ?, position_count = ?,"
                             " dataset_count = ?, kb_version = ? WHERE id = ?"),
                        (counts["sources"], counts["positions"], counts["datasets"],
                         counts["version"], row["id"]))
        conn.commit()
    finally:
        conn.close()


# ---- helpers -------------------------------------------------------------------------------

def _dump(obj):
    # Postgres JSONB columns want an adapted JSON value; sqlite TEXT columns want a string.
    if _IS_PG:
        from psycopg.types.json import Jsonb
        return Jsonb(obj)
    return json.dumps(obj, ensure_ascii=False)


def _load(val):
    """A KB/progress column comes back as a dict (psycopg JSONB) or a str (sqlite TEXT)."""
    if val is None:
        return None
    from engine.migrate import load_migrated
    parsed = val if isinstance(val, (dict, list)) else json.loads(val)
    return load_migrated(parsed)


def _row_to_question(row, with_kb=True):
    d = {"id": row["id"], "slug": row["slug"], "question": row["question"],
         "version": row["version"], "created_at": row["created_at"],
         "updated_at": row["updated_at"]}
    if with_kb:
        d["kb"] = _load(row["kb"])
    return d


# ---- questions -----------------------------------------------------------------------------

def create_question(question_text, contributor="anonymous"):
    """Create a new question with an empty seeded KB. Returns the question dict (with kb)."""
    qid = uuid.uuid4().hex[:12]
    kb = empty_kb(qid, question_text)
    sg = slug(question_text)
    now = _now()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql(
            "INSERT INTO questions (id, slug, question, kb, version, source_count, position_count,"
            " dataset_count, kb_version, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"),
            (qid, sg, question_text, _dump(kb), 0, 0, 0, 0,
             kb.get("meta", {}).get("version", 0), now, now))
        _insert_contribution(cur, qid, contributor, "create-question", question_text, now)
        conn.commit()
    finally:
        conn.close()
    return {"id": qid, "slug": sg, "question": question_text, "version": 0,
            "created_at": now, "updated_at": now, "kb": kb}


def get_question(qid, with_kb=True):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql("SELECT * FROM questions WHERE id = ?"), (qid,))
        row = cur.fetchone()
        return _row_to_question(row, with_kb) if row else None
    finally:
        conn.close()


def list_questions(search=None, limit=100):
    """Browse/search questions (no KB body — just the cards). Search matches the question text."""
    conn = _connect()
    try:
        cur = conn.cursor()
        if search:
            like = "%" + search.lower() + "%"
            cur.execute(_sql("SELECT id, slug, question, version, created_at, updated_at,"
                             " source_count, position_count, dataset_count, kb_version"
                             " FROM questions WHERE LOWER(question) LIKE ?"
                             " ORDER BY updated_at DESC LIMIT ?"), (like, limit))
        else:
            cur.execute(_sql("SELECT id, slug, question, version, created_at, updated_at,"
                             " source_count, position_count, dataset_count, kb_version"
                             " FROM questions ORDER BY updated_at DESC LIMIT ?"), (limit,))
        out = []
        for row in cur.fetchall():
            q = _row_to_question(row, with_kb=False)
            q["counts"] = {"sources": row["source_count"] or 0,
                           "positions": row["position_count"] or 0,
                           "datasets": row["dataset_count"] or 0,
                           "version": row["kb_version"] or 0}
            out.append(q)
        return out
    finally:
        conn.close()


def _counts(kb):
    return {"sources": len(kb.get("sources", [])), "positions": len(kb.get("positions", [])),
            "datasets": len(kb.get("datasets", [])), "version": kb.get("meta", {}).get("version", 0)}


def save_kb(qid, kb, expected_version, audit=None):
    """Write a KB back, optimistic-locked on version: fails with Conflict if someone else wrote
    in between (so concurrent harvests serialize instead of clobbering). Returns the new version."""
    # This is a server revision, deliberately separate from kb.meta.version. Queueing a review item
    # or replacing a KB may have the same semantic KB version as the previous document; it must still
    # advance optimistic locking so a concurrent writer cannot silently win.
    new_version = int(expected_version) + 1
    counts = _counts(kb)
    now = _now()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql(
            "UPDATE questions SET kb = ?, version = ?, source_count = ?, position_count = ?,"
            " dataset_count = ?, kb_version = ?, updated_at = ?"
            " WHERE id = ? AND version = ?"),
            (_dump(kb), new_version, counts["sources"], counts["positions"], counts["datasets"],
             counts["version"], now, qid, expected_version))
        if cur.rowcount == 0:
            conn.rollback()
            raise Conflict("question {} changed since version {}".format(qid, expected_version))
        if audit:
            _insert_contribution(cur, qid, audit.get("contributor") or "anonymous",
                                 audit.get("action") or "update-kb", audit.get("summary") or "", now)
        conn.commit()
        return new_version
    finally:
        conn.close()


def delete_question(qid):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql("DELETE FROM contributions WHERE question_id = ?"), (qid,))
        cur.execute(_sql("DELETE FROM jobs WHERE question_id = ?"), (qid,))
        cur.execute(_sql("DELETE FROM questions WHERE id = ?"), (qid,))
        conn.commit()
    finally:
        conn.close()


# ---- jobs (background harvest progress) ----------------------------------------------------

def new_job(qid, kind):
    jid = uuid.uuid4().hex[:12]
    now = _now()
    conn = _connect()
    try:
        conn.cursor().execute(_sql(
            "INSERT INTO jobs (id, question_id, kind, status, progress, created_at, updated_at)"
            " VALUES (?, ?, ?, 'running', ?, ?, ?)"),
            (jid, qid, kind, _dump([]), now, now))
        conn.commit()
    finally:
        conn.close()
    return jid


def append_job_log(jid, line):
    """Append a progress line (read-modify-write; jobs are single-writer per harvest)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql("SELECT progress FROM jobs WHERE id = ?"), (jid,))
        row = cur.fetchone()
        if not row:
            return
        lines = _load(row["progress"]) or []
        lines.append("{}  {}".format(time.strftime("%H:%M:%S"), line))
        cur.execute(_sql("UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?"),
                    (_dump(lines), _now(), jid))
        conn.commit()
    finally:
        conn.close()


def finish_job(jid, status, result=None):
    conn = _connect()
    try:
        conn.cursor().execute(_sql("UPDATE jobs SET status = ?, result = ?, updated_at = ? WHERE id = ?"),
                              (status, _dump(result) if result is not None else None, _now(), jid))
        conn.commit()
    finally:
        conn.close()


def get_job(jid):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql("SELECT * FROM jobs WHERE id = ?"), (jid,))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row["id"], "question_id": row["question_id"], "kind": row["kind"],
                "status": row["status"], "progress": _load(row["progress"]) or [],
                "result": _load(row["result"]), "updated_at": row["updated_at"]}
    finally:
        conn.close()


# ---- contribution log ----------------------------------------------------------------------

def log_contribution(qid, contributor, action, summary=""):
    conn = _connect()
    try:
        _insert_contribution(conn.cursor(), qid, contributor, action, summary, _now())
        conn.commit()
    finally:
        conn.close()


def _insert_contribution(cur, qid, contributor, action, summary, created_at):
    contributor = contributor.strip()[:100] if isinstance(contributor, str) and contributor.strip() \
        else "anonymous"
    action = action.strip()[:100] if isinstance(action, str) and action.strip() else "update-kb"
    summary = summary[:2000] if isinstance(summary, str) else ""
    cur.execute(_sql(
        "INSERT INTO contributions (id, question_id, contributor, action, summary, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"),
        (uuid.uuid4().hex[:12], qid, contributor, action, summary, created_at))


def contributions(qid, limit=100):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql("SELECT * FROM contributions WHERE question_id = ?"
                         " ORDER BY created_at DESC LIMIT ?"), (qid, limit))
        return [{"contributor": r["contributor"], "action": r["action"],
                 "summary": r["summary"], "created_at": r["created_at"]} for r in cur.fetchall()]
    finally:
        conn.close()


# ---- reader study ---------------------------------------------------------------------------

def count_study_participants():
    """Number of submissions so far — drives balanced crossover assignment (study.assign)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM study_responses")
        row = cur.fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


def new_study_assignment():
    """Allocate a balanced, server-owned crossover plan under a database lock."""
    from eval.reader_study import study
    aid = uuid.uuid4().hex
    now = _now()
    conn = _connect()
    try:
        cur = conn.cursor()
        if _IS_PG:
            cur.execute("LOCK TABLE study_assignments IN EXCLUSIVE MODE")
        else:
            cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT COUNT(*) AS n FROM study_assignments")
        row = cur.fetchone()
        index = int(row["n"]) if row else 0
        plan = study.assign(index)
        cur.execute(_sql("INSERT INTO study_assignments (id, plan, consumed, created_at)"
                         " VALUES (?, ?, 0, ?)"), (aid, _dump(plan), now))
        conn.commit()
        return {"id": aid, "plan": plan}
    finally:
        conn.close()


def get_study_assignment(assignment_id):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql("SELECT * FROM study_assignments WHERE id = ?"), (assignment_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row["id"], "plan": _load(row["plan"]),
                "consumed": bool(row["consumed"]), "created_at": row["created_at"]}
    finally:
        conn.close()


def save_study_response(assignment_id, participant, response, scored):
    rid = uuid.uuid4().hex[:12]
    participant = participant.strip()[:64] if isinstance(participant, str) else ""
    conn = _connect()
    try:
        cur = conn.cursor()
        now = _now()
        cur.execute(_sql("UPDATE study_assignments SET consumed = 1, submitted_at = ?"
                         " WHERE id = ? AND consumed = 0"), (now, assignment_id))
        if cur.rowcount == 0:
            conn.rollback()
            raise Conflict("study assignment is missing or was already submitted")
        cur.execute(_sql(
            "INSERT INTO study_responses (id, participant, response, scored, assignment_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"),
            (rid, participant, _dump(response), _dump(scored), assignment_id, now))
        conn.commit()
    finally:
        conn.close()
    return rid


def list_study_responses(limit=2000):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql("SELECT * FROM study_responses ORDER BY created_at ASC LIMIT ?"), (limit,))
        return [{"id": r["id"], "participant": r["participant"], "response": _load(r["response"]),
                 "scored": _load(r["scored"]), "created_at": r["created_at"]}
                for r in cur.fetchall()]
    finally:
        conn.close()

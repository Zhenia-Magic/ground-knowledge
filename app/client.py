"""Tiny stdlib HTTP client the CLI uses to sync with a portal (`cli.py push` / `pull`).

Portal URL comes from --portal or the EPISTEMIC_PORTAL env var. No dependencies.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def portal_url(explicit=None):
    url = explicit or os.environ.get("EPISTEMIC_PORTAL")
    if not url:
        raise SystemExit("No portal URL. Pass --portal <url> or set EPISTEMIC_PORTAL.")
    return url.rstrip("/")


def _request(method, url, payload=None, headers=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": e.reason}
    except urllib.error.URLError as e:
        raise SystemExit("Could not reach portal {}: {}".format(url, e.reason))


def list_questions(base, search=None):
    q = "?search=" + urllib.parse.quote(search) if search else ""
    _, body = _request("GET", base + "/api/questions" + q)
    return body.get("questions", [])


def get_question(base, qid):
    code, body = _request("GET", base + "/api/questions/" + qid)
    if code == 404:
        raise SystemExit("No question {} on the portal.".format(qid))
    return body


def create_question(base, question, contributor="anonymous"):
    code, body = _request("POST", base + "/api/questions",
                          {"question": question, "contributor": contributor})
    if code not in (200, 201):
        raise SystemExit("Create failed: {}".format(body.get("error") or code))
    return body


def optional_admin_token(explicit=None):
    """The admin token if one is available, else None — a keyless push into a new/empty question is
    allowed without it (the server sanitizes trust records on that path)."""
    return explicit or os.environ.get("EPISTEMIC_ADMIN_TOKEN") or os.environ.get("ADMIN_TOKEN") or None


def admin_token(explicit=None):
    token = optional_admin_token(explicit)
    if not token:
        raise SystemExit("This action requires the portal admin token. Pass --token or set "
                         "EPISTEMIC_ADMIN_TOKEN.")
    return token


def put_kb(base, qid, kb, expected_version, contributor="anonymous", token=None):
    headers = {"X-Admin-Token": token} if token else {}
    code, body = _request("PUT", base + "/api/questions/" + qid,
                          {"kb": kb, "expected_version": expected_version, "contributor": contributor},
                          headers=headers)
    if code == 403:
        raise SystemExit("This question already has content, so replacing its whole KB needs the "
                         "portal admin token — pass --token or set EPISTEMIC_ADMIN_TOKEN. "
                         "(A new or empty question pushes with no token.)")
    if code == 409:
        raise SystemExit("Version conflict — someone pushed first. Run `pull` to get the latest, "
                         "re-apply your sources, then push again.")
    if code != 200:
        raise SystemExit("Push failed: {}".format(body.get("error") or code))
    return body

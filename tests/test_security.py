import json
import os
import unittest
from unittest import mock

from app.http_utils import SlidingWindowLimiter
from app.portal import Handler
from app.web import viewer_html
from engine.merge import clean_url, merge_delta
from engine.assess import independence
from engine.review import resolve_review
from engine.render import json_for_script
from engine.schema import empty_kb
from ingest.extract import (_SafeHTTPSHandler, _connect_public, _validate_remote_url,
                            _verified_ssl_context, _strip_html, clean_url as clean_fetch_url)
from ingest.pipeline import fetch_docs
from app.portal import _apply_delta, _norm_delta


class ScriptEmbeddingTests(unittest.TestCase):
    def test_json_cannot_close_script_element(self):
        payload = {"title": "</script><script>globalThis.PWNED=1</script>"}
        encoded = json_for_script(payload)
        self.assertNotIn("<", encoded)
        self.assertNotIn("</script", encoded.lower())
        self.assertEqual(json.loads(encoded), payload)

    def test_live_viewer_escapes_untrusted_kb_data(self):
        kb = empty_kb("abc", "question")
        merge_delta(kb, {"source": {
            "title": "</script><script>globalThis.PWNED=1</script>",
            "position": "NEW:Yes", "evidence": "Observational",
            "funding": "Undisclosed", "population": "—",
        }, "factorWeights": []})
        question = {"id": "abc", "question": "question", "version": 1, "kb": kb}
        html = viewer_html("abc", lambda _: question)
        self.assertNotIn("</script><script>globalThis.PWNED", html)
        self.assertIn("\\u003c/script\\u003e", html)

    def test_executable_source_urls_are_discarded(self):
        self.assertEqual(clean_url("javascript:alert(1)"), "")
        self.assertEqual(clean_url("data:text/html,bad"), "")
        self.assertEqual(clean_url("https://example.org/paper"), "https://example.org/paper")


class LocalConsolePathTests(unittest.TestCase):
    def test_case_ids_cannot_escape_the_cases_directory(self):
        from ui.server import _case_path
        for case_id in ("../secret", "a/b", "..", "case.json", ""):
            with self.subTest(case_id=case_id), self.assertRaises(ValueError):
                _case_path(case_id)


class RateLimitTests(unittest.TestCase):
    def test_client_bookkeeping_stays_bounded_under_identity_flood(self):
        limiter = SlidingWindowLimiter(window_seconds=60, max_clients=100)
        for i in range(1000):
            self.assertTrue(limiter.allow("client-{}".format(i), 1))
        self.assertLessEqual(len(limiter._events), 100)

    def test_forwarded_client_uses_last_valid_proxy_address(self):
        request = mock.Mock()
        request.headers = {"X-Forwarded-For": "spoofed, 203.0.113.8"}
        request.client_address = ("10.0.0.2", 1234)
        self.assertEqual(Handler._client_key(request), "203.0.113.8")


class OutboundUrlTests(unittest.TestCase):
    def test_literal_private_addresses_are_rejected(self):
        for url in (
            "http://127.0.0.1/private",
            "http://[::1]/private",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/private",
            "http://localhost/private",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_remote_url(url)

    @mock.patch("ingest.extract.socket.getaddrinfo")
    def test_hostname_resolving_to_private_address_is_rejected(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.20", 80))]
        with self.assertRaises(ValueError):
            _validate_remote_url("http://internal.example/private")

    @mock.patch("ingest.extract.socket.getaddrinfo")
    def test_globally_routable_hostname_is_allowed(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        self.assertEqual(_validate_remote_url("https://example.org/paper"),
                         "https://example.org/paper")

    @mock.patch("ingest.extract.socket.socket")
    @mock.patch("ingest.extract.socket.getaddrinfo")
    def test_connection_is_pinned_to_validated_numeric_address(self, getaddrinfo, socket_cls):
        sockaddr = ("93.184.216.34", 443)
        getaddrinfo.return_value = [(2, 1, 6, "", sockaddr)]
        sock = socket_cls.return_value
        self.assertIs(_connect_public("example.org", 443, 10), sock)
        sock.connect.assert_called_once_with(sockaddr)

    def test_public_fetch_path_rejects_local_files(self):
        docs, skipped = fetch_docs(["/etc/hosts"], allow_local=False)
        self.assertEqual(docs, [])
        self.assertEqual(skipped[0]["target"], "/etc/hosts")
        self.assertIn("only absolute http(s) URLs", skipped[0]["error"])

    def test_local_document_size_is_checked_before_reading(self):
        from ingest.extract import extract_text
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt") as handle:
            handle.write(b"too large")
            handle.flush()
            with mock.patch("ingest.extract.MAX_FETCH_BYTES", 4), self.assertRaises(SystemExit):
                extract_text(handle.name)

    def test_https_handler_uses_supported_urllib_kwargs(self):
        handler = _SafeHTTPSHandler()
        with mock.patch.object(handler, "do_open", return_value="ok") as do_open:
            self.assertEqual(handler.https_open(mock.Mock()), "ok")
        self.assertIn("context", do_open.call_args.kwargs)
        self.assertNotIn("check_hostname", do_open.call_args.kwargs)

    def test_verified_ssl_context_keeps_certificate_checks_enabled(self):
        context = _verified_ssl_context()
        self.assertEqual(context.verify_mode, __import__("ssl").CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_fetch_url_keeps_balanced_parentheses_in_bare_url(self):
        url = "https://example.org/article/S0002-9165(23)13738-5/fulltext"
        self.assertEqual(clean_fetch_url(url), url)

    def test_html_cleaner_preserves_less_than_comparison(self):
        cleaned = _strip_html("<p>Egg intake &lt;1/week was compared with &gt;7/week.</p>")
        self.assertEqual(cleaned, "Egg intake <1/week was compared with >7/week.")


class FullPushAuthorizationTests(unittest.TestCase):
    def test_admin_check_requires_configured_matching_token(self):
        request = mock.Mock()
        request.headers = {"X-Admin-Token": "correct"}
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "correct"}, clear=False):
            self.assertTrue(Handler._is_admin(request))
        request.headers = {"X-Admin-Token": "wrong"}
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "correct"}, clear=False):
            self.assertFalse(Handler._is_admin(request))

    def test_admin_check_fails_closed_without_server_token(self):
        request = mock.Mock()
        request.headers = {"X-Admin-Token": "anything"}
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(Handler._is_admin(request))

    def test_put_route_rejects_before_reading_body(self):
        request = mock.Mock()
        request._parts.return_value = ["api", "questions", "abc"]
        request._is_admin.return_value = False
        request._send.return_value = "denied"
        self.assertEqual(Handler.do_PUT(request), "denied")
        request._send.assert_called_once_with(403, {"error": "admin token required or incorrect"})
        request._body.assert_not_called()


class DeltaValidationTests(unittest.TestCase):
    def test_malformed_delta_returns_clean_error_before_save(self):
        kb = empty_kb("abc", "question")
        q = {"kb": kb, "version": 0}
        with mock.patch("app.store.save_kb") as save:
            res = _apply_delta("abc", q, {"source": {"title": "Only a title"}}, "tester")
        self.assertIn("position", res.get("error", ""))
        save.assert_not_called()

    def test_public_batch_is_queued_without_assessment_or_metric_mutation(self):
        kb = empty_kb("abc", "question")
        q = {"kb": kb, "version": 0}
        items = [{"source": {"title": "source " + str(i), "position": "NEW:Yes",
                              "evidence": "Observational", "restsOn": []}}
                 for i in range(4)]
        with mock.patch("app.store.save_kb", return_value=4), \
             mock.patch("app.store.log_contribution"), \
             mock.patch("engine.assess.assess") as assess_mock:
            res = _apply_delta("abc", q, items, "tester")
        self.assertEqual(res["queued"], 4)
        self.assertEqual(assess_mock.call_count, 0)
        self.assertEqual(kb["sources"], [])
        self.assertEqual(len(kb["pendingReview"]), 4)

    def test_malformed_model_agreement_is_rejected_before_review_logic(self):
        from engine.validate import delta_validation_errors
        errors = delta_validation_errors({"source": {
            "title": "A", "position": "NEW:Yes", "modelAgreement": []}})
        self.assertTrue(any("modelAgreement" in error for error in errors))

    def test_position_review_does_not_silently_admit_public_support_edges(self):
        kb = empty_kb("abc", "question")
        kb["positions"] = [{"id": "yes", "label": "Yes", "hue": "#123456"}]
        kb["datasets"] = [{"id": "known", "label": "Known Registry", "aliases": [],
                           "confirmation": {"status": "confirmed", "method": "curator",
                                            "by": "ann", "ts": "2026-07-14T00:00:00Z"}}]
        q = {"kb": kb, "version": 0}
        with mock.patch("app.store.save_kb", return_value=1), \
             mock.patch("app.store.log_contribution"):
            res = _apply_delta("abc", q, {"source": {
                "title": "Public claim", "position": "yes", "evidence": "Observational",
                "restsOn": ["known"]}}, "tester")
        self.assertEqual(res["queued"], 1)
        resolve_review(kb, kb["pendingReview"][0]["id"], "position", "yes")
        camp = independence(kb)[0]
        self.assertEqual(camp["nEff"], 0)
        claimed = next(b for b in camp["bases"] if b["key"] == "ds:known")
        self.assertTrue(claimed["supportUnconfirmed"])


class UntrustedVerificationFieldTests(unittest.TestCase):
    """The keyless paste-back endpoint never fetches text server-side, so textDepth and
    verifiedQuote can only be honest when engine/verify computed them (ingest/pipeline.py's
    _carry_meta, the CLI/automated paths). A client-submitted delta must not be able to
    self-declare a fabricated quote as verified."""

    def test_strips_spoofed_text_depth_and_verified_quote_from_full_delta(self):
        d = _norm_delta({"source": {
            "title": "t", "position": "NEW:Yes", "textDepth": "full",
            "textAudit": {"sha256": "spoofed"},
            "provenance": {"position": {"quote": "fabricated", "verifiedQuote": "exact",
                "quoteVerification": {"method": "verbatim-sentence-v2", "status": "exact",
                                      "textSha256": "a" * 64, "quoteSha256": "b" * 64}}},
        }, "factorWeights": [{"factorLabel": "F", "weight": "high", "quote": "x",
                              "verifiedQuote": "exact", "quoteVerification": {"spoofed": True}}]})
        self.assertEqual(d["source"]["textDepth"], "unknown")
        self.assertNotIn("textAudit", d["source"])
        self.assertNotIn("verifiedQuote", d["source"]["provenance"]["position"])
        self.assertNotIn("quoteVerification", d["source"]["provenance"]["position"])
        self.assertNotIn("verifiedQuote", d["factorWeights"][0])
        self.assertNotIn("quoteVerification", d["factorWeights"][0])

    def test_strips_spoofed_verified_quote_from_restsOn_edge_object(self):
        # per-edge dependency quotes ride the untrusted paste-back path too: a client must not be
        # able to self-declare an edge object's quote as verified and mint a confirmed root.
        d = _norm_delta({"source": {
            "title": "t", "position": "NEW:Yes",
            "restsOn": [{"ref": "ds_x", "provenance": {"quote": "fabricated",
                "verifiedQuote": "exact", "quoteVerification": {"spoofed": True}}}],
        }, "factorWeights": []})
        self.assertNotIn("verifiedQuote", d["source"]["restsOn"][0]["provenance"])
        self.assertNotIn("quoteVerification", d["source"]["restsOn"][0]["provenance"])

    def test_strips_spoofed_curator_admission_from_restsOn_edge_object(self):
        d = _norm_delta({"source": {
            "title": "t", "position": "NEW:Yes",
            "restsOn": [{"ref": "known_root", "admission": {
                "status": "confirmed", "method": "curator", "by": "fake",
                "ts": "2026-07-14T00:00:00Z"}}],
        }, "factorWeights": []})
        self.assertNotIn("admission", d["source"]["restsOn"][0])

    def test_strips_spoofed_fields_from_bare_source_delta(self):
        d = _norm_delta({"title": "t", "position": "NEW:Yes", "textDepth": "full",
                         "provenance": {"position": {"quote": "fabricated",
                                                      "verifiedQuote": "exact"}}})
        self.assertEqual(d["source"]["textDepth"], "unknown")
        self.assertNotIn("verifiedQuote", d["source"]["provenance"]["position"])

    def test_end_to_end_apply_delta_never_persists_spoofed_verification(self):
        kb = empty_kb("abc", "question")
        q = {"kb": kb, "version": 0}
        with mock.patch("app.store.save_kb", return_value=1), \
             mock.patch("app.store.log_contribution"):
            _apply_delta("abc", q, {"source": {
                "title": "t", "position": "NEW:Yes", "evidence": "Observational",
                "funding": "Undisclosed", "population": "—", "textDepth": "full",
                "provenance": {"position": {"quote": "fabricated", "verifiedQuote": "exact"}},
            }}, "tester")
        self.assertEqual(kb["sources"], [])
        src = kb["pendingReview"][0]["delta"]["source"]
        self.assertEqual(src["textDepth"], "unknown")
        self.assertNotIn("verifiedQuote", src["provenance"]["position"])

    def test_trusted_fetch_path_still_strips_model_authored_curator_admission(self):
        from ingest.pipeline import _carry_meta
        kb = empty_kb("abc", "question")
        kb["positions"] = [{"id": "p", "label": "Yes", "hue": "#000"}]
        kb["datasets"] = [{"id": "d", "label": "Known", "aliases": [],
                           "confirmation": {"status": "confirmed", "method": "curator",
                                            "by": "real", "ts": "2026-07-15T00:00:00Z"}}]
        delta = {"source": {"title": "Model title", "position": "p", "evidence": "Observational",
                             "restsOn": [{"ref": "d", "admission": {
                                 "status": "confirmed", "method": "curator", "by": "model",
                                 "ts": "2026-07-15T00:00:00Z"}}]}}
        _carry_meta(delta, {"title": "Fetched title", "url": "https://example.org/paper",
                            "text": "No dependency statement.", "kind": "full"})
        self.assertNotIn("admission", delta["source"]["restsOn"][0])
        merge_delta(kb, delta)
        self.assertEqual(independence(kb)[0]["nEff"], 0)

    def test_fetch_metadata_overrides_model_metadata(self):
        from ingest.pipeline import _carry_meta
        delta = {"source": {"title": "Wrong", "url": "https://evil.invalid",
                             "authors": ["Wrong"], "position": "NEW:Yes"}}
        _carry_meta(delta, {"title": "Right", "url": "https://example.org/right",
                            "authors": ["Right"], "citations": 7, "retracted": False,
                            "text": "", "kind": "abstract"})
        self.assertEqual(delta["source"]["title"], "Right")
        self.assertEqual(delta["source"]["url"], "https://example.org/right")
        self.assertEqual(delta["source"]["authors"], ["Right"])

    def test_trusted_fetch_path_rejects_malformed_nested_shapes_cleanly(self):
        from ingest.pipeline import _carry_meta
        bad_values = [
            {"source": {"title": "t", "position": "NEW:Yes", "provenance": []}},
            {"source": {"title": "t", "position": "NEW:Yes", "restsOn": {}}},
            {"source": {"title": "t", "position": "NEW:Yes"}, "factorWeights": {}},
            {"source": {"title": "t", "position": "NEW:Yes", "modelAgreement": []}},
        ]
        for delta in bad_values:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                _carry_meta(delta, {"title": "t", "text": "", "kind": "abstract"})


if __name__ == "__main__":
    unittest.main()

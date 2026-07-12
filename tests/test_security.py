import json
import os
import unittest
from unittest import mock

from app.portal import Handler
from app.web import viewer_html
from engine.merge import clean_url, merge_delta
from engine.render import json_for_script
from engine.schema import empty_kb
from ingest.extract import _SafeHTTPSHandler, _connect_public, _validate_remote_url
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

    def test_https_handler_uses_supported_urllib_kwargs(self):
        handler = _SafeHTTPSHandler()
        with mock.patch.object(handler, "do_open", return_value="ok") as do_open:
            self.assertEqual(handler.https_open(mock.Mock()), "ok")
        self.assertIn("context", do_open.call_args.kwargs)
        self.assertNotIn("check_hostname", do_open.call_args.kwargs)


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

    def test_batch_assesses_only_before_and_after_transaction(self):
        kb = empty_kb("abc", "question")
        q = {"kb": kb, "version": 0}
        items = [{"source": {"title": "source " + str(i), "position": "NEW:Yes",
                              "evidence": "Observational", "restsOn": []}}
                 for i in range(4)]
        with mock.patch("app.store.save_kb", return_value=4), \
             mock.patch("app.store.log_contribution"), \
             mock.patch("engine.assess.assess", wraps=__import__("engine.assess", fromlist=["assess"]).assess) as assess_mock:
            res = _apply_delta("abc", q, items, "tester")
        self.assertEqual(res["added"], 4)
        self.assertEqual(assess_mock.call_count, 2)
        add_logs = [entry for entry in kb["log"] if entry.get("action") == "add-source"]
        self.assertEqual(add_logs[-1]["batchSize"], 4)
        self.assertIn("diff", add_logs[-1])


class UntrustedVerificationFieldTests(unittest.TestCase):
    """The keyless paste-back endpoint never fetches text server-side, so textDepth and
    verifiedQuote can only be honest when engine/verify computed them (ingest/pipeline.py's
    _carry_meta, the CLI/automated paths). A client-submitted delta must not be able to
    self-declare a fabricated quote as verified."""

    def test_strips_spoofed_text_depth_and_verified_quote_from_full_delta(self):
        d = _norm_delta({"source": {
            "title": "t", "position": "NEW:Yes", "textDepth": "full",
            "provenance": {"position": {"quote": "fabricated", "verifiedQuote": "exact"}},
        }, "factorWeights": [{"factorLabel": "F", "weight": "high", "quote": "x",
                              "verifiedQuote": "exact"}]})
        self.assertNotIn("textDepth", d["source"])
        self.assertNotIn("verifiedQuote", d["source"]["provenance"]["position"])
        self.assertNotIn("verifiedQuote", d["factorWeights"][0])

    def test_strips_spoofed_verified_quote_from_restsOn_edge_object(self):
        # per-edge dependency quotes ride the untrusted paste-back path too: a client must not be
        # able to self-declare an edge object's quote as verified and mint a confirmed root.
        d = _norm_delta({"source": {
            "title": "t", "position": "NEW:Yes",
            "restsOn": [{"ref": "ds_x", "provenance": {"quote": "fabricated", "verifiedQuote": "exact"}}],
        }, "factorWeights": []})
        self.assertNotIn("verifiedQuote", d["source"]["restsOn"][0]["provenance"])

    def test_strips_spoofed_fields_from_bare_source_delta(self):
        d = _norm_delta({"title": "t", "position": "NEW:Yes", "textDepth": "full",
                         "provenance": {"position": {"quote": "fabricated",
                                                      "verifiedQuote": "exact"}}})
        self.assertNotIn("textDepth", d["source"])
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
        src = kb["sources"][0]
        self.assertEqual(src["textDepth"], "unknown")
        self.assertNotIn("verifiedQuote", src["provenance"]["position"])


if __name__ == "__main__":
    unittest.main()

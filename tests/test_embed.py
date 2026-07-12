import json
import os
import unittest
import urllib.error
from unittest import mock

from ingest import embed


_ROW = ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o", "OpenAI")


class EmbedderTests(unittest.TestCase):
    """The embedding backend is lazy and key-gated: no key -> None (curation falls back to lexical);
    with a key it calls the provider's /embeddings endpoint; a failed call degrades to None."""

    def test_no_provider_key_returns_none(self):
        with mock.patch("ingest.llm._active_compat", return_value=None):
            self.assertIsNone(embed.embedder())

    def test_returns_vectors_via_mocked_provider(self):
        payload = json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode("utf-8")
        with mock.patch("ingest.llm._active_compat", return_value=_ROW), \
             mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False), \
             mock.patch("ingest.embed.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = payload
            e = embed.embedder()
            self.assertIsNotNone(e)
            self.assertEqual(e("some label"), [0.1, 0.2, 0.3])
            self.assertIsNone(e(""))                 # empty text -> None, no call
            self.assertEqual(e("some label"), [0.1, 0.2, 0.3])   # cached (still one network call)
            self.assertEqual(urlopen.call_count, 1)

    def test_failed_call_returns_none_for_that_label(self):
        with mock.patch("ingest.llm._active_compat", return_value=_ROW), \
             mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False), \
             mock.patch("ingest.embed.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("boom")):
            e = embed.embedder()
            self.assertIsNone(e("some label"))       # degrades gracefully, does not raise


if __name__ == "__main__":
    unittest.main()

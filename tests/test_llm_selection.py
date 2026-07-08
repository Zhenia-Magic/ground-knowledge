"""Tests for the phase-aware provider/model selection in ingest/llm.py — the auto split
(Anthropic searches, first compat key labels), the explicit per-phase provider pins behind the
console's Models panel, stale-pin fallback, and the legacy EPISTEMIC_MODEL guard."""
import os
import unittest

from ingest import llm

_MANAGED = [
    "ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
    "EPISTEMIC_MODEL", "EPISTEMIC_SEARCH_MODEL", "EPISTEMIC_LABEL_MODEL",
    "EPISTEMIC_SEARCH_PROVIDER", "EPISTEMIC_LABEL_PROVIDER",
]


class EnvCase(unittest.TestCase):
    """Isolates every managed env var per test, restoring the real environment afterwards."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _MANAGED}
        for k in _MANAGED:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _phase(self, phase):
        sel = llm._select(phase)
        return (None, None) if sel is None else (
            llm._provider_id(llm._search_provider() if phase == "search"
                             else llm._label_provider()), sel[2])


class AutoResolutionTests(EnvCase):
    def test_no_key_means_no_selection(self):
        self.assertIsNone(llm._select("search"))
        self.assertIsNone(llm._select("label"))
        self.assertFalse(llm.has_key())

    def test_anthropic_only_serves_both_phases(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        self.assertEqual(self._phase("search")[0], "anthropic")
        self.assertEqual(self._phase("label")[0], "anthropic")

    def test_split_default_claude_searches_nvidia_labels(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["NVIDIA_API_KEY"] = "k"
        self.assertEqual(self._phase("search")[0], "anthropic")
        self.assertEqual(self._phase("label")[0], "nvidia")

    def test_compat_order_nvidia_beats_openai(self):
        os.environ["OPENAI_API_KEY"] = "k"
        os.environ["NVIDIA_API_KEY"] = "k"
        self.assertEqual(self._phase("label")[0], "nvidia")


class PinTests(EnvCase):
    def test_label_pin_overrides_the_free_default(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["NVIDIA_API_KEY"] = "k"
        os.environ["EPISTEMIC_LABEL_PROVIDER"] = "anthropic"
        self.assertEqual(self._phase("label")[0], "anthropic")
        self.assertEqual(self._phase("search")[0], "anthropic")   # search untouched

    def test_search_pin_overrides_anthropic_first(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["OPENAI_API_KEY"] = "k"
        os.environ["EPISTEMIC_SEARCH_PROVIDER"] = "openai"
        self.assertEqual(self._phase("search")[0], "openai")
        self.assertEqual(self._phase("label")[0], "openai")       # label auto = first compat

    def test_stale_pin_falls_back_to_auto(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["EPISTEMIC_LABEL_PROVIDER"] = "nvidia"          # no NVIDIA key set
        self.assertEqual(self._phase("label")[0], "anthropic")
        st = llm.provider_status()
        self.assertTrue(st["label"]["pinBroken"])
        self.assertEqual(st["label"]["provider"], "anthropic")

    def test_auto_and_empty_pins_are_no_ops(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["NVIDIA_API_KEY"] = "k"
        for v in ("auto", "", "  "):
            os.environ["EPISTEMIC_LABEL_PROVIDER"] = v
            self.assertEqual(self._phase("label")[0], "nvidia")


class ModelResolutionTests(EnvCase):
    def test_phase_model_pins_win(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["NVIDIA_API_KEY"] = "k"
        os.environ["EPISTEMIC_SEARCH_MODEL"] = "claude-opus-4-8"
        os.environ["EPISTEMIC_LABEL_MODEL"] = "z-ai/glm-5.2"
        self.assertEqual(self._phase("search")[1], "claude-opus-4-8")
        self.assertEqual(self._phase("label")[1], "z-ai/glm-5.2")

    def test_legacy_global_model_only_applies_to_a_single_provider_setup(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["EPISTEMIC_MODEL"] = "claude-opus-4-8"
        self.assertEqual(self._phase("search")[1], "claude-opus-4-8")
        self.assertEqual(self._phase("label")[1], "claude-opus-4-8")
        # split setup: the legacy global must NOT leak a Claude id onto the NVIDIA call
        os.environ["NVIDIA_API_KEY"] = "k"
        self.assertNotEqual(self._phase("label")[1], "claude-opus-4-8")

    def test_provider_defaults_apply_when_nothing_is_pinned(self):
        os.environ["NVIDIA_API_KEY"] = "k"
        self.assertEqual(self._phase("label")[1], "deepseek-ai/deepseek-v4-flash")


class ProviderStatusTests(EnvCase):
    def test_status_lists_every_provider_with_key_state(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        st = llm.provider_status()
        ids = [p["id"] for p in st["providers"]]
        self.assertEqual(ids[0], "anthropic")
        for pid in ("nvidia", "openai", "deepseek", "mistral", "groq", "gemini", "openrouter"):
            self.assertIn(pid, ids)
        by = {p["id"]: p for p in st["providers"]}
        self.assertTrue(by["anthropic"]["hasKey"])
        self.assertTrue(by["anthropic"]["webSearch"])
        self.assertFalse(by["nvidia"]["hasKey"])
        self.assertTrue(by["nvidia"]["free"])
        self.assertTrue(st["hasKey"])
        self.assertIn("claude", st["search"]["model"])

    def test_status_reports_pins(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        os.environ["NVIDIA_API_KEY"] = "k"
        os.environ["EPISTEMIC_LABEL_PROVIDER"] = "nvidia"
        os.environ["EPISTEMIC_LABEL_MODEL"] = "minimaxai/minimax-m3"
        st = llm.provider_status()
        self.assertEqual(st["label"]["pinnedProvider"], "nvidia")
        self.assertEqual(st["label"]["pinnedModel"], "minimaxai/minimax-m3")
        self.assertFalse(st["label"]["pinBroken"])
        self.assertEqual(st["label"]["model"], "minimaxai/minimax-m3")
        self.assertIsNone(st["search"]["pinnedProvider"])


if __name__ == "__main__":
    unittest.main()

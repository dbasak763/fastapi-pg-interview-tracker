import unittest

from llm_config import LLMSettings


class LLMSettingsTests(unittest.TestCase):
    def test_local_provider_is_opt_in(self):
        settings = LLMSettings.from_env({})

        self.assertEqual(settings.available_provider_names(), ())

    def test_builds_local_openai_compatible_provider(self):
        settings = LLMSettings.from_env(
            {
                "LOCAL_LLM_ENABLED": "true",
                "LOCAL_LLM_MODEL": "qwen3:8b",
            }
        )

        provider = settings.build_provider("local", "visualization")
        self.assertEqual(settings.available_provider_names(), ("local",))
        self.assertEqual(provider.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(provider.model, "qwen3:8b")
        self.assertEqual(provider.api_key, "ollama")

    def test_uses_different_groq_models_by_intent(self):
        settings = LLMSettings.from_env({"GROQ_API_KEY": "test-key"})

        lookup = settings.build_provider("groq", "lookup")
        analysis = settings.build_provider("groq", "analysis")
        visualization = settings.build_provider("groq", "visualization")

        self.assertEqual(lookup.model, "openai/gpt-oss-20b")
        self.assertEqual(analysis.model, "openai/gpt-oss-120b")
        self.assertEqual(visualization.model, "openai/gpt-oss-120b")

    def test_legacy_model_does_not_override_route_models(self):
        settings = LLMSettings.from_env(
            {
                "GROQ_API_KEY": "test-key",
                "GROQ_MODEL": "legacy-model",
            }
        )

        self.assertEqual(
            settings.build_provider("groq", "lookup").model,
            "openai/gpt-oss-20b",
        )

    def test_prefers_local_only_for_simple_lookups(self):
        settings = LLMSettings.from_env({})

        self.assertEqual(settings.provider_preferences["lookup"], "local")
        self.assertEqual(settings.provider_preferences["analysis"], "groq")
        self.assertEqual(
            settings.provider_preferences["visualization"],
            "groq",
        )

    def test_provider_order_places_route_first_and_has_no_duplicates(self):
        settings = LLMSettings.from_env(
            {
                "GROQ_API_KEY": "test-key",
                "LOCAL_LLM_ENABLED": "true",
            }
        )

        self.assertEqual(settings.provider_order("local"), ("local", "groq"))
        self.assertEqual(settings.provider_order("groq"), ("groq", "local"))


if __name__ == "__main__":
    unittest.main()

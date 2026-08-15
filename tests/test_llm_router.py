import unittest

from llm_router import classify_request, route_llm_request


class LLMRouterTests(unittest.TestCase):
    def test_classifies_simple_data_lookup(self):
        self.assertEqual(classify_request("What is my latest score?"), "lookup")

    def test_classifies_analysis_request(self):
        self.assertEqual(
            classify_request("Compare my weakest topic with my strongest"),
            "analysis",
        )

    def test_classifies_visualization_before_analysis(self):
        self.assertEqual(
            classify_request("Plot my progress as a chart"),
            "visualization",
        )

    def test_uses_intent_provider_preference(self):
        decision = route_llm_request(
            "Visualize my scores",
            available_providers=["groq", "local"],
            preferences={"visualization": "local"},
        )

        self.assertEqual(decision.intent, "visualization")
        self.assertEqual(decision.provider, "local")

    def test_uses_first_available_provider_when_preference_is_offline(self):
        decision = route_llm_request(
            "Why did my score change?",
            available_providers=["groq"],
            preferences={"analysis": "local"},
        )

        self.assertEqual(decision.provider, "groq")
        self.assertIn("unavailable", decision.reason)

    def test_routes_to_fallback_without_a_provider(self):
        decision = route_llm_request(
            "How many attempts do I have?",
            available_providers=[],
        )

        self.assertEqual(decision.provider, "fallback")


if __name__ == "__main__":
    unittest.main()

import unittest

from topic_taxonomy import canonical_topic


class TopicTaxonomyTests(unittest.TestCase):
    def test_groups_deep_learning_variants(self):
        examples = (
            ("Deep Learning", "Deep Learning"),
            (
                "Deep Learning Fundamentals (Backpropagation, Gradient Descent, "
                "Activation Functions)",
                "Deep Learning Fundamentals (Backpropagation, Gradient Descent, "
                "Activation Functions)",
            ),
            (
                "Forward propagation, backpropagation, activation functions",
                "Deep Learning Fundamentals",
            ),
        )

        self.assertEqual(
            {canonical_topic(topic, focus) for topic, focus in examples},
            {"Deep Learning"},
        )

    def test_uses_specific_search_category_before_machine_learning(self):
        self.assertEqual(
            canonical_topic(
                "Machine Learning & AI Background",
                "Marketplace Search Ranking and Learning-to-Rank System Design",
            ),
            "Recommendation & Search",
        )

    def test_groups_algorithm_focus_areas(self):
        self.assertEqual(
            canonical_topic(
                "Hard graph problem involving SCCs",
                "Strongly Connected Components and Condensation Graphs",
            ),
            "Algorithms & Data Structures",
        )

    def test_groups_lyft_focus_areas_by_interview_purpose(self):
        examples = {
            "Resource Utilization and Documentation": "Programming & Code Quality",
            "Platform Familiarity": "Programming & Code Quality",
            "Motivation and Fit for Lyft": "Behavioral & Communication",
            "Time and Space Complexity Analysis": "Algorithms & Data Structures",
        }

        for focus_topic, expected_topic in examples.items():
            with self.subTest(focus_topic=focus_topic):
                self.assertEqual(
                    canonical_topic(focus_topic, focus_topic),
                    expected_topic,
                )


if __name__ == "__main__":
    unittest.main()

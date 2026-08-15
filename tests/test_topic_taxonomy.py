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


if __name__ == "__main__":
    unittest.main()

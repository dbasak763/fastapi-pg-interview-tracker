import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")

from main import (
    AttemptCreate,
    AttemptResponse,
    ChatRequest,
    TopicPerformanceSummary,
    TopicScorePoint,
    TopicScoreProgressionResponse,
    _build_chat_visualization,
)


class AttemptSchemaTests(unittest.TestCase):
    def test_reads_legacy_challenge_without_round_metadata(self):
        attempt = AttemptResponse.model_validate(
            {
                "id": 1,
                "attemptedDate": "2026-01-01",
                "attemptSource": "challenge",
                "topic": "Legacy challenge",
                "score": 75,
                "status": "complete",
                "createdAt": datetime.now(timezone.utc),
            }
        )

        self.assertEqual(attempt.attempt_source, "challenge")
        self.assertIsNone(attempt.round_number)

    def test_requires_round_metadata_for_new_challenges(self):
        with self.assertRaisesRegex(
            ValueError,
            "Challenge attempts require",
        ):
            AttemptCreate.model_validate(
                {
                    "attemptedDate": "2026-01-01",
                    "attemptSource": "challenge",
                    "topic": "New challenge",
                    "score": 75,
                    "status": "complete",
                }
            )

    @patch("main.topic_score_progression")
    def test_builds_bar_chart_from_validated_progression(self, progression):
        progression.return_value = TopicScoreProgressionResponse(
            focus_topic="System Design",
            points=[
                TopicScorePoint(
                    attempt_id=1,
                    attempted_date="2026-01-01",
                    started_at=datetime.now(timezone.utc),
                    company="Example Co",
                    attempt_number=1,
                    score=72,
                )
            ],
        )

        visualization = _build_chat_visualization(
            ChatRequest(
                message="Draw a bar chart",
                focus_topic="System Design",
            ),
            "visualization",
            db=object(),
        )

        self.assertEqual(visualization.chart_type, "bar")
        self.assertEqual(visualization.points[0].value, 72)
        self.assertEqual(visualization.points[0].detail, "Example Co")

    @patch("main.topic_summaries")
    def test_builds_topic_comparison_for_plural_prompt(self, summaries):
        summaries.return_value = [
            TopicPerformanceSummary(
                focus_topic="SQL",
                attempt_count=3,
                average_score=68,
                lowest_score=60,
                highest_score=75,
                first_score=60,
                latest_score=75,
                score_change=15,
            )
        ]

        visualization = _build_chat_visualization(
            ChatRequest(
                message="Draw a bar chart comparing all topics",
                focus_topic="System Design",
            ),
            "visualization",
            db=object(),
        )

        self.assertEqual(visualization.title, "Topic average scores")
        self.assertEqual(visualization.points[0].label, "SQL")


if __name__ == "__main__":
    unittest.main()

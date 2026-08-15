import os
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
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
    _resolve_chat_query_scope,
)


class AttemptSchemaTests(unittest.TestCase):
    def test_last_week_uses_inclusive_seven_day_window_across_topics(self):
        scope = _resolve_chat_query_scope(
            ChatRequest(
                message="tell me progress in last week latest rounds",
                focus_topic="Spotify topic",
            ),
            today=date(2026, 8, 15),
        )

        self.assertEqual(scope.start_date, date(2026, 8, 8))
        self.assertEqual(scope.end_date, date(2026, 8, 15))
        self.assertIsNone(scope.focus_topic)

    def test_full_context_ignores_selected_topic(self):
        scope = _resolve_chat_query_scope(
            ChatRequest(
                message=(
                    "tell me progress in last week latest rounds "
                    "based on full context of topics"
                ),
                focus_topic="Spotify topic",
            ),
            today=date(2026, 8, 15),
        )

        self.assertEqual(scope.start_date, date(2026, 8, 8))
        self.assertIsNone(scope.focus_topic)

    @patch("main.list_attempts")
    def test_last_week_chart_uses_filtered_attempts_across_topics(self, attempts):
        attempts.return_value = [
            SimpleNamespace(
                attempted_date=date(2026, 8, 12),
                company="Airbnb",
                focus_topic="Optimization",
                score=56,
            ),
            SimpleNamespace(
                attempted_date=date(2026, 8, 9),
                company="Netflix",
                focus_topic="Evaluation",
                score=86,
            ),
        ]
        payload = ChatRequest(
            message="show me bar chart of latest tests last week",
            focus_topic="Unrelated selected topic",
        )
        scope = _resolve_chat_query_scope(payload, today=date(2026, 8, 15))

        visualization = _build_chat_visualization(
            payload,
            "visualization",
            db=object(),
            scope=scope,
        )

        self.assertEqual(visualization.chart_type, "bar")
        self.assertEqual(
            visualization.title,
            "Scores from 2026-08-08 through 2026-08-15",
        )
        self.assertEqual(len(visualization.points), 2)
        self.assertEqual(visualization.points[0].detail, "Netflix · Evaluation")
        call = attempts.call_args.kwargs
        self.assertEqual(call["start_date"], date(2026, 8, 8))
        self.assertEqual(call["end_date"], date(2026, 8, 15))
        self.assertEqual(call["attempt_status"], "complete")

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

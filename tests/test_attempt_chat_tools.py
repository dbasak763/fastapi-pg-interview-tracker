import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")

from chat_backend import build_tools_from_openapi, execute_approved_operation
from database import Base
from main import (
    APPROVED_CHAT_OPERATIONS,
    ChatQueryScope,
    ChatRequest,
    _resolve_precise_attempt_operation,
    app,
    dashboard_chat,
)
from models import InterviewAttempt


class OfflineSettings:
    provider_preferences = {
        "lookup": "local",
        "analysis": "local",
        "visualization": "local",
    }

    @staticmethod
    def available_provider_names():
        return ()

    @staticmethod
    def provider_order(selected_provider):
        return ()


class AttemptChatToolTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        for index in range(30):
            self.db.add(
                InterviewAttempt(
                    attempted_date=date(2026, 8, 1),
                    attempt_source="manual",
                    company=f"Company {index}",
                    topic="System Design",
                    score=60 + index % 20,
                    status="complete",
                    started_at=start + timedelta(minutes=index),
                    completed_at=start + timedelta(minutes=index + 1),
                )
            )
        self.db.add(
            InterviewAttempt(
                attempted_date=date(2026, 8, 20),
                attempt_source="manual",
                company="Latest Co",
                topic="Resume Review",
                score=91,
                status="complete",
                started_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
                completed_at=datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc),
            )
        )
        self.db.add(
            InterviewAttempt(
                attempted_date=date(2026, 8, 21),
                attempt_source="manual",
                company="Draft Co",
                topic="Draft",
                score=None,
                status="incomplete",
                started_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_openapi_exposes_exact_read_tools_only(self):
        tools = build_tools_from_openapi(
            app.openapi(),
            APPROVED_CHAT_OPERATIONS,
        )
        names = {tool["function"]["name"] for tool in tools}

        self.assertIn("count_attempts", names)
        self.assertIn("latest_attempt", names)
        self.assertNotIn("create_attempt", names)

    def test_count_tool_is_exact_beyond_list_page_size(self):
        result = execute_approved_operation(
            "count_attempts",
            {"status": "complete"},
            APPROVED_CHAT_OPERATIONS,
            self.db,
        )

        self.assertEqual(result, {"count": 31})

    def test_latest_tool_orders_by_attempt_date_then_timestamp(self):
        result = execute_approved_operation(
            "latest_attempt",
            {"status": "complete"},
            APPROVED_CHAT_OPERATIONS,
            self.db,
        )

        self.assertEqual(result["attemptedDate"], "2026-08-20")
        self.assertEqual(result["company"], "Latest Co")
        self.assertEqual(result["topic"], "Resume Review")
        self.assertEqual(result["score"], "91.00")

    def test_precise_count_and_latest_queries_are_server_resolved(self):
        scope = ChatQueryScope(current_date=date(2026, 8, 23), topic=None)

        count_operation = _resolve_precise_attempt_operation(
            "How many completed interview attempts do I have?",
            scope,
        )
        latest_operation = _resolve_precise_attempt_operation(
            "What was my latest finished interview attempt?",
            scope,
        )

        self.assertEqual(count_operation[0], "count_attempts")
        self.assertEqual(count_operation[1], {"status": "complete"})
        self.assertEqual(latest_operation[0], "latest_attempt")
        self.assertEqual(latest_operation[1], {"status": "complete"})

    @patch("main.LLMSettings.from_env", return_value=OfflineSettings())
    def test_database_fallback_keeps_count_exact(self, _settings):
        response = dashboard_chat(
            ChatRequest(
                message="How many completed interview attempts do I have?"
            ),
            db=self.db,
        )

        self.assertEqual(response.provider, "database")
        self.assertEqual(response.operations, ["count_attempts"])
        self.assertIn("31 complete interview attempts", response.reply)

    @patch("main.LLMSettings.from_env", return_value=OfflineSettings())
    def test_database_fallback_returns_all_latest_fields(self, _settings):
        response = dashboard_chat(
            ChatRequest(
                message=(
                    "What was my latest completed interview attempt? Give the "
                    "date, company, topic, and score."
                )
            ),
            db=self.db,
        )

        self.assertEqual(response.provider, "database")
        self.assertEqual(response.operations, ["latest_attempt"])
        self.assertIn("August 20, 2026", response.reply)
        self.assertIn("Latest Co", response.reply)
        self.assertIn("Resume Review", response.reply)
        self.assertIn("score 91", response.reply)


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite://")

from main import AttemptCreate, AttemptResponse


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


if __name__ == "__main__":
    unittest.main()

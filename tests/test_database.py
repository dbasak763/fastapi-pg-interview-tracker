import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite://")

from database import normalize_database_url


class DatabaseConfigTests(unittest.TestCase):
    def test_upgrades_psycopg2_url_to_psycopg(self):
        self.assertEqual(
            normalize_database_url(
                "postgresql+psycopg2://user:password@localhost/interviews"
            ),
            "postgresql+psycopg://user:password@localhost/interviews",
        )

    def test_leaves_non_postgres_url_unchanged(self):
        self.assertEqual(
            normalize_database_url("sqlite:///interviews.db"),
            "sqlite:///interviews.db",
        )


if __name__ == "__main__":
    unittest.main()

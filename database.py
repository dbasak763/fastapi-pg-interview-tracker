"""PostgreSQL connection and per-request SQLAlchemy session lifecycle.

Routes receive a session through ``Depends(get_db)``. The generator guarantees
that the session is closed after FastAPI finishes the request.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def normalize_database_url(database_url: str) -> str:
    """Use the psycopg v3 driver installed by this application."""

    for legacy_scheme in ("postgresql+psycopg2://", "postgresql://"):
        if database_url.startswith(legacy_scheme):
            return database_url.replace(
                legacy_scheme,
                "postgresql+psycopg://",
                1,
            )
    return database_url


# Load environment variables from the .env file
load_dotenv()

# Read database connection URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it to the .env file.")
DATABASE_URL = normalize_database_url(DATABASE_URL)

# Create the SQLAlchemy engine for the database
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base class for ORM models
Base = declarative_base()


def get_db():
    """Yield one database session for a FastAPI request, then close it."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

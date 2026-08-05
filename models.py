"""SQLAlchemy mapping for the PostgreSQL interview_attempts table.

Pydantic models in ``main.py`` describe API input/output JSON. This SQLAlchemy
model describes how the same data is stored and queried in PostgreSQL.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class InterviewAttempt(Base):
    """One recorded interview or practice attempt."""

    __tablename__ = "interview_attempts"
    __table_args__ = (
        CheckConstraint(
            "attempt_source IN ('manual', 'casual', 'challenge', 'question_bank')",
            name="valid_attempt_source",
        ),
        CheckConstraint(
            "status IN ('incomplete', 'complete', 'invalidated')",
            name="valid_attempt_status",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="valid_score",
        ),
        CheckConstraint(
            "attempt_number IS NULL OR attempt_number > 0",
            name="positive_attempt_number",
        ),
        CheckConstraint(
            "round_number IS NULL OR round_number > 0",
            name="positive_round_number",
        ),
    )

    # Primary key column
    id: Mapped[int] = mapped_column(primary_key=True)
    # Date of the interview attempt
    attempted_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Where the attempt came from in InterviewStack or from a manual import
    attempt_source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="manual",
    )
    # InterviewStack's own attempt identifier, when it is available
    external_attempt_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        unique=True,
    )
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    # UUID visible in an InterviewStack challenge URL
    challenge_id: Mapped[Optional[str]] = mapped_column(String(36))
    # Snapshot labels preserve history if InterviewStack later renames a challenge
    challenge_title: Mapped[Optional[str]] = mapped_column(String(300))
    round_number: Mapped[Optional[int]] = mapped_column(SmallInteger)
    round_name: Mapped[Optional[str]] = mapped_column(String(250))
    
    focus_topic: Mapped[Optional[str]] = mapped_column(String(250))
    question_bank_topic_slug: Mapped[Optional[str]] = mapped_column(String(200))
    # retake count within the same challenge round and focus topic
    attempt_number: Mapped[Optional[int]] = mapped_column(Integer)
    # Company name (optional)
    company: Mapped[Optional[str]] = mapped_column(String(150))
    # Role name (optional)
    role: Mapped[Optional[str]] = mapped_column(String(150))
    # Level of the interview / candidate (optional)
    level: Mapped[Optional[str]] = mapped_column(String(100))
    # Interview topic (required)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    # Incomplete and invalidated attempts may not have a numeric score
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="complete",
    )
    # Notes for the interview attempt (optional)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Exact timestamps distinguish multiple attempts made on the same date
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Timestamp when the attempt was created
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

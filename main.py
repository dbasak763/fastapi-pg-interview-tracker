"""Interview Tracker FastAPI application.

Suggested reading order:

1. Startup and shared configuration near the top of this file.
2. Pydantic API schemas, including the chat/tool argument schemas.
3. Regular CRUD and dashboard GET routes that query PostgreSQL.
4. ``_execute_*`` adapters that make selected GET routes callable as LLM tools.
5. ``APPROVED_CHAT_OPERATIONS``: the security allowlist.
6. ``dashboard_chat``: Groq/Llama orchestration with a local fallback.

``chat_backend.py`` owns generic LLM/tool mechanics. This file owns application
data, database queries, and the decision about which operations are approved.
"""

import logging
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Literal, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import InterviewAttempt
from chat_backend import (
    ApprovedOperation,
    ChatToolError,
    build_tools_from_openapi,
    run_provider_tool_chat,
)
from llm_config import LLMSettings
from llm_router import route_llm_request

logger = logging.getLogger(__name__)

# Ensure the SQLAlchemy model has a backing table before requests are served.
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # STARTUP FLOW:
    # 1. Ask FastAPI for its generated OpenAPI/Swagger document.
    # 2. Keep only GET operations in APPROVED_CHAT_OPERATIONS.
    # 3. Convert them into Groq/Llama function-tool definitions.
    # 4. Cache the definitions for reuse by every chat request.
    #
    # No request is sent to Groq during startup.
    application.state.chat_tools = build_tools_from_openapi(
        application.openapi(),
        APPROVED_CHAT_OPERATIONS,
    )
    yield


app = FastAPI(
    title="Interview Tracker API",
    version="1.0.0",
    lifespan=lifespan,
)
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(word.capitalize() for word in rest)


class AttemptBase(BaseModel):
    #defines and validates the common data for an interview attempt
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    attempted_date: date
    attempt_source: Literal[
        "manual",
        "casual",
        "challenge",
        "question_bank",
    ] = "manual"
    external_attempt_id: Optional[str] = Field(default=None, max_length=100)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    challenge_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    challenge_title: Optional[str] = Field(default=None, max_length=300)
    round_number: Optional[int] = Field(default=None, ge=1)
    round_name: Optional[str] = Field(default=None, max_length=250)
    focus_topic: Optional[str] = Field(default=None, max_length=250)
    question_bank_topic_slug: Optional[str] = Field(default=None, max_length=200)
    attempt_number: Optional[int] = Field(default=None, ge=1)
    company: Optional[str] = Field(default=None, max_length=150)
    role: Optional[str] = Field(default=None, max_length=150)
    level: Optional[str] = Field(default=None, max_length=100)
    topic: str = Field(min_length=1, max_length=200)
    score: Optional[Decimal] = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )
    status: Literal["incomplete", "complete", "invalidated"] = "complete"
    notes: Optional[str] = None
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    completed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_attempt_identity(self):
        if self.status == "complete" and self.score is None:
            raise ValueError("A completed attempt must have a score")

        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completedAt cannot be earlier than startedAt")
        return self


class AttemptCreate(AttemptBase):
    #Request body used when creating an interview attempt.
    @model_validator(mode="after")
    def validate_challenge_identity(self):
        if self.attempt_source != "challenge":
            return self

        required = {
            "roundNumber": self.round_number,
            "roundName": self.round_name,
            "focusTopic": self.focus_topic,
            "attemptNumber": self.attempt_number,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "Challenge attempts require: " + ", ".join(missing)
            )
        return self


class AttemptUpdate(BaseModel):
    #Request body used when updating an existing attempt.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    attempted_date: Optional[date] = None
    attempt_source: Optional[
        Literal["manual", "casual", "challenge", "question_bank"]
    ] = None
    external_attempt_id: Optional[str] = Field(default=None, max_length=100)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    challenge_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    challenge_title: Optional[str] = Field(default=None, max_length=300)
    round_number: Optional[int] = Field(default=None, ge=1)
    round_name: Optional[str] = Field(default=None, max_length=250)
    focus_topic: Optional[str] = Field(default=None, max_length=250)
    question_bank_topic_slug: Optional[str] = Field(default=None, max_length=200)
    attempt_number: Optional[int] = Field(default=None, ge=1)
    company: Optional[str] = Field(default=None, max_length=150)
    role: Optional[str] = Field(default=None, max_length=150)
    level: Optional[str] = Field(default=None, max_length=100)
    topic: Optional[str] = Field(default=None, min_length=1, max_length=200)
    score: Optional[Decimal] = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )
    status: Optional[Literal["incomplete", "complete", "invalidated"]] = None
    notes: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AttemptResponse(AttemptBase):
    #Response model returned to the frontend.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    id: int
    created_at: datetime


class ChallengeTopicSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    focus_topic: str
    attempt_count: int


class TopicPerformanceSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    focus_topic: str
    attempt_count: int
    average_score: float
    lowest_score: float
    highest_score: float
    first_score: float
    latest_score: float
    score_change: float


class TopicScorePoint(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    attempt_id: int
    attempted_date: date
    started_at: datetime
    completed_at: Optional[datetime] = None
    company: Optional[str] = None
    role: Optional[str] = None
    focus_topic: Optional[str] = None
    attempt_source: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None 
    source_url: Optional[str] = None
    external_attempt_id: Optional[str] = None
    question_bank_topic_slug: Optional[str] = None
    level: Optional[str] = None
    topic: Optional[str] = None
    challenge_id: Optional[str] = None
    challenge_title: Optional[str] = None
    round_number: Optional[int] = None
    round_name: Optional[str] = None
    attempt_number: int
    score: float


class TopicScoreProgressionResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    focus_topic: str
    points: List[TopicScorePoint]


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    message: str = Field(min_length=1, max_length=1000)
    focus_topic: Optional[str] = Field(default=None, max_length=250)
    history: List[ChatHistoryMessage] = Field(default_factory=list, max_length=12)


class ChatResponse(BaseModel):
    # ``operations`` is an audit/debug trace. The browser currently displays
    # the reply and provider/model but does not render this trace.
    reply: str
    provider: str = "local-fallback"
    model: Optional[str] = None
    route: Optional[str] = None
    operations: List[str] = Field(default_factory=list)


class ChatRouteConfig(BaseModel):
    provider: str
    model: Optional[str] = None


class ChatConfigResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    available_providers: List[str]
    routes: Dict[str, ChatRouteConfig]


# ---------------------------------------------------------------------------
# LLM TOOL ARGUMENT SCHEMAS
# These schemas are stricter than the public routes. They define exactly what
# Llama may supply when requesting each approved operation.
# ---------------------------------------------------------------------------

class EmptyToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListAttemptsToolArguments(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    company: Optional[str] = Field(default=None, max_length=150)
    role: Optional[str] = Field(default=None, max_length=150)
    level: Optional[str] = Field(default=None, max_length=100)
    topic: Optional[str] = Field(default=None, max_length=200)
    attempt_source: Optional[
        Literal["manual", "casual", "challenge", "question_bank"]
    ] = None
    challenge_id: Optional[str] = Field(default=None, max_length=36)
    round_number: Optional[int] = Field(default=None, ge=1)
    status: Optional[Literal["incomplete", "complete", "invalidated"]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class AttemptDetailToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: int = Field(ge=1)


class TopicProgressionToolArguments(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    focus_topic: str = Field(min_length=1, max_length=250)


@app.get("/")
def read_root():
    #Basic route that confirms that the API server is running.
    return {"message": "Interview Tracker API is running"}


@app.get("/dashboard", include_in_schema=False)
def read_dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/database-health")
def check_database_health(db: Session = Depends(get_db)):
    #Check whether the API can communicate with the database.
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "interview_tracker"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        ) from exc


@app.post(
    "/api/attempts",
    response_model=AttemptResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
def create_attempt(payload: AttemptCreate, db: Session = Depends(get_db)):
    #Create and save a new interview attempt to the database.
    attempt = InterviewAttempt(**payload.model_dump())
    db.add(attempt)
    try:
        db.commit()
        db.refresh(attempt)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save the interview attempt",
        ) from exc
    return attempt


@app.get(
    "/api/attempts",
    response_model=List[AttemptResponse],
    response_model_by_alias=True,
    operation_id="list_attempts",
)
def list_attempts(
    company: Optional[str] = None,
    role: Optional[str] = None,
    level: Optional[str] = None,
    topic: Optional[str] = None,
    attempt_source: Optional[str] = Query(default=None, alias="attemptSource"),
    challenge_id: Optional[str] = Query(default=None, alias="challengeId"),
    round_number: Optional[int] = Query(default=None, alias="roundNumber"),
    attempt_status: Optional[str] = Query(default=None, alias="status"),
    start_date: Optional[date] = Query(default=None, alias="startDate"),
    end_date: Optional[date] = Query(default=None, alias="endDate"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List attempts using optional company, role, topic, source, status, and date filters."""
    query = db.query(InterviewAttempt)
    if company:
        query = query.filter(InterviewAttempt.company == company)
    if role:
        query = query.filter(InterviewAttempt.role == role)
    if level:
        query = query.filter(InterviewAttempt.level == level)
    if topic:
        query = query.filter(InterviewAttempt.topic == topic)
    if attempt_source:
        query = query.filter(InterviewAttempt.attempt_source == attempt_source)
    if challenge_id:
        query = query.filter(InterviewAttempt.challenge_id == challenge_id)
    if round_number:
        query = query.filter(InterviewAttempt.round_number == round_number)
    if attempt_status:
        query = query.filter(InterviewAttempt.status == attempt_status)
    if start_date:
        query = query.filter(InterviewAttempt.attempted_date >= start_date)
    if end_date:
        query = query.filter(InterviewAttempt.attempted_date <= end_date)
    return (
        query.order_by(
            InterviewAttempt.started_at.desc(),
            InterviewAttempt.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_attempt_or_404(attempt_id: int, db: Session) -> InterviewAttempt:
    # Helper function that returns an attempt or raises 404 if not found.
    attempt = db.get(InterviewAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Interview attempt not found")
    return attempt


@app.get(
    "/api/attempts/{attempt_id}",
    response_model=AttemptResponse,
    response_model_by_alias=True,
    operation_id="get_attempt",
)
def get_attempt(attempt_id: int, db: Session = Depends(get_db)):
    """Retrieve the complete record for one attempt by its numeric ID."""
    return get_attempt_or_404(attempt_id, db)


@app.put(
    "/api/attempts/{attempt_id}",
    response_model=AttemptResponse,
    response_model_by_alias=True,
)
def update_attempt(
    attempt_id: int,
    payload: AttemptUpdate,
    db: Session = Depends(get_db),
): 
    # Update the fields of an existing interview attempt.
    attempt = get_attempt_or_404(attempt_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(attempt, field, value)
    try:
        AttemptCreate.model_validate(attempt)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        db.commit()
        db.refresh(attempt)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update the interview attempt",
        ) from exc
    return attempt


@app.delete("/api/attempts/{attempt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attempt(attempt_id: int, db: Session = Depends(get_db)):
    # Delete an interview attempt by ID and return no content.
    attempt = get_attempt_or_404(attempt_id, db)
    db.delete(attempt)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/dashboard/score-history",
    operation_id="score_history",
)
def score_history(db: Session = Depends(get_db)):
    """Return average scores grouped chronologically by attempt date."""
    rows = db.execute(
        text(
            """
            SELECT attempted_date, ROUND(AVG(score), 2) AS average_score
            FROM interview_attempts
            GROUP BY attempted_date
            ORDER BY attempted_date
            """
        )
    ).mappings()
    return [
        {
            "attemptedDate": row["attempted_date"],
            "averageScore": row["average_score"],
        }
        for row in rows
    ]


@app.get(
    "/api/dashboard/score-timeline",
    response_model=List[AttemptResponse],
    response_model_by_alias=True,
    operation_id="score_timeline",
)
def score_timeline(db: Session = Depends(get_db)):
    """Return every scored attempt chronologically, including same-day retakes."""
    return (
        db.query(InterviewAttempt)
        .filter(InterviewAttempt.score.is_not(None))
        .order_by(
            InterviewAttempt.started_at.asc(),
            InterviewAttempt.id.asc(),
        )
        .all()
    )


@app.get(
    "/api/dashboard/challenge-topics",
    response_model=List[ChallengeTopicSummary],
    response_model_by_alias=True,
    operation_id="challenge_topics",
)
def challenge_topics(db: Session = Depends(get_db)):
    """List every scored focus topic and its completed attempt count."""
    rows = (
        db.query(
            InterviewAttempt.focus_topic,
            func.count(InterviewAttempt.id).label("attempt_count"),
        )
        .filter(
            InterviewAttempt.status == "complete",
            InterviewAttempt.score.is_not(None),
            InterviewAttempt.focus_topic.is_not(None),
        )
        .group_by(InterviewAttempt.focus_topic)
        .order_by(InterviewAttempt.focus_topic.asc())
        .all()
    )
    return [
        ChallengeTopicSummary(
            focus_topic=row.focus_topic,
            attempt_count=row.attempt_count,
        )
        for row in rows
    ]


@app.get(
    "/api/dashboard/topic-summaries",
    response_model=List[TopicPerformanceSummary],
    response_model_by_alias=True,
    operation_id="topic_summaries",
)
def topic_summaries(db: Session = Depends(get_db)):
    """Compare all focus topics by count, average, range, latest score, and change."""
    attempts = (
        db.query(InterviewAttempt)
        .filter(
            InterviewAttempt.status == "complete",
            InterviewAttempt.score.is_not(None),
            InterviewAttempt.focus_topic.is_not(None),
        )
        .order_by(
            InterviewAttempt.focus_topic.asc(),
            InterviewAttempt.attempted_date.asc(),
            InterviewAttempt.started_at.asc(),
            InterviewAttempt.id.asc(),
        )
        .all()
    )
    grouped = {}
    for attempt in attempts:
        grouped.setdefault(attempt.focus_topic, []).append(float(attempt.score))

    summaries = [
        TopicPerformanceSummary(
            focus_topic=focus_topic,
            attempt_count=len(scores),
            average_score=sum(scores) / len(scores),
            lowest_score=min(scores),
            highest_score=max(scores),
            first_score=scores[0],
            latest_score=scores[-1],
            score_change=scores[-1] - scores[0],
        )
        for focus_topic, scores in grouped.items()
    ]
    return sorted(summaries, key=lambda item: item.average_score)


@app.get(
    "/api/dashboard/topic-score-progression",
    response_model=TopicScoreProgressionResponse,
    response_model_by_alias=True,
    operation_id="topic_score_progression",
)
def topic_score_progression(
    focus_topic: str = Query(
        min_length=1,
        max_length=250,
        alias="focusTopic",
    ),
    db: Session = Depends(get_db),
):
    """Return every completed score for one exact focus topic chronologically."""
    attempts = (
        db.query(InterviewAttempt)
        .filter(
            InterviewAttempt.status == "complete",
            InterviewAttempt.score.is_not(None),
            InterviewAttempt.focus_topic == focus_topic,
        )
        .order_by(
            InterviewAttempt.attempted_date.asc(),
            InterviewAttempt.started_at.asc(),
            InterviewAttempt.id.asc(),
        )
        .all()
    )
    if not attempts:
        raise HTTPException(
            status_code=404,
            detail=f"No completed scores found for topic: {focus_topic}",
        )

    return TopicScoreProgressionResponse(
        focus_topic=focus_topic,
        points=[
            TopicScorePoint(
                attempt_id=attempt.id,
                attempted_date=attempt.attempted_date,
                started_at=attempt.started_at,
                completed_at=attempt.completed_at,
                company=attempt.company,
                role=attempt.role,
                topic=attempt.topic,
                focus_topic=attempt.focus_topic,
                attempt_source=attempt.attempt_source,
                status=attempt.status,
                notes=attempt.notes,
                source_url=attempt.source_url,
                external_attempt_id=attempt.external_attempt_id,
                question_bank_topic_slug=attempt.question_bank_topic_slug,
                level=attempt.level,
                challenge_id=attempt.challenge_id,
                challenge_title=attempt.challenge_title,
                round_number=attempt.round_number,
                round_name=attempt.round_name,
                attempt_number=attempt.attempt_number or position,
                score=float(attempt.score),
            )
            for position, attempt in enumerate(attempts, start=1)
        ],
    )


def _serialize_attempt(attempt: InterviewAttempt) -> dict:
    """Turn an ORM row into the same camelCase JSON returned by the public API."""

    return AttemptResponse.model_validate(attempt).model_dump(
        by_alias=True,
        mode="json",
    )


# ---------------------------------------------------------------------------
# LLM TOOL EXECUTOR ADAPTERS
# These functions bridge validated LLM arguments to existing application query
# functions. They call Python functions directly; they do not make internal HTTP
# requests back to FastAPI.
# ---------------------------------------------------------------------------

def _execute_list_attempts(
    arguments: ListAttemptsToolArguments,
    db: Session,
) -> List[dict]:
    attempts = list_attempts(
        company=arguments.company,
        role=arguments.role,
        level=arguments.level,
        topic=arguments.topic,
        attempt_source=arguments.attempt_source,
        challenge_id=arguments.challenge_id,
        round_number=arguments.round_number,
        attempt_status=arguments.status,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        limit=arguments.limit,
        offset=arguments.offset,
        db=db,
    )
    return [_serialize_attempt(attempt) for attempt in attempts]


def _execute_get_attempt(
    arguments: AttemptDetailToolArguments,
    db: Session,
) -> dict:
    try:
        return _serialize_attempt(get_attempt(arguments.attempt_id, db))
    except HTTPException as exc:
        raise ChatToolError(str(exc.detail)) from exc


def _execute_score_history(
    arguments: EmptyToolArguments,
    db: Session,
) -> List[dict]:
    return jsonable_encoder(score_history(db))


def _execute_score_timeline(
    arguments: EmptyToolArguments,
    db: Session,
) -> List[dict]:
    return [_serialize_attempt(attempt) for attempt in score_timeline(db)]


def _execute_challenge_topics(
    arguments: EmptyToolArguments,
    db: Session,
) -> List[dict]:
    return [
        item.model_dump(by_alias=True, mode="json")
        for item in challenge_topics(db)
    ]


def _execute_topic_summaries(
    arguments: EmptyToolArguments,
    db: Session,
) -> List[dict]:
    return [
        item.model_dump(by_alias=True, mode="json")
        for item in topic_summaries(db)
    ]


def _execute_topic_progression(
    arguments: TopicProgressionToolArguments,
    db: Session,
) -> dict:
    try:
        return topic_score_progression(
            focus_topic=arguments.focus_topic,
            db=db,
        ).model_dump(by_alias=True, mode="json")
    except HTTPException as exc:
        raise ChatToolError(str(exc.detail)) from exc


# ---------------------------------------------------------------------------
# CHAT SECURITY ALLOWLIST
# Only operations registered here can become Swagger-derived LLM tools. The
# POST, PUT, and DELETE attempt routes are intentionally absent.
# ---------------------------------------------------------------------------

APPROVED_CHAT_OPERATIONS: Dict[str, ApprovedOperation] = {
    "list_attempts": ApprovedOperation(
        arguments_model=ListAttemptsToolArguments,
        executor=_execute_list_attempts,
    ),
    "get_attempt": ApprovedOperation(
        arguments_model=AttemptDetailToolArguments,
        executor=_execute_get_attempt,
    ),
    "score_history": ApprovedOperation(
        arguments_model=EmptyToolArguments,
        executor=_execute_score_history,
    ),
    "score_timeline": ApprovedOperation(
        arguments_model=EmptyToolArguments,
        executor=_execute_score_timeline,
    ),
    "challenge_topics": ApprovedOperation(
        arguments_model=EmptyToolArguments,
        executor=_execute_challenge_topics,
    ),
    "topic_summaries": ApprovedOperation(
        arguments_model=EmptyToolArguments,
        executor=_execute_topic_summaries,
    ),
    "topic_score_progression": ApprovedOperation(
        arguments_model=TopicProgressionToolArguments,
        executor=_execute_topic_progression,
    ),
}


@app.get(
    "/api/dashboard/chat/config",
    response_model=ChatConfigResponse,
    response_model_by_alias=True,
    include_in_schema=False,
)
def dashboard_chat_config():
    """Return the active routing plan without exposing provider credentials."""

    settings = LLMSettings.from_env()
    available = settings.available_provider_names()
    routes: Dict[str, ChatRouteConfig] = {}
    for intent in ("lookup", "analysis", "visualization"):
        provider_order = settings.provider_order(
            settings.provider_preferences[intent]
        )
        if not provider_order:
            routes[intent] = ChatRouteConfig(provider="fallback")
            continue
        provider = settings.build_provider(provider_order[0], intent)
        routes[intent] = ChatRouteConfig(
            provider=provider.name,
            model=provider.model,
        )

    return ChatConfigResponse(
        available_providers=list(available),
        routes=routes,
    )


@app.post("/api/dashboard/chat", response_model=ChatResponse)
def dashboard_chat(payload: ChatRequest, db: Session = Depends(get_db)):
    """Answer a dashboard question using approved read tools and PostgreSQL.

    Primary path:
      browser -> this route -> Llama selects tool -> server validates/executes
      -> PostgreSQL result -> Llama explains -> browser

    Fallback path:
      if the key is missing or Groq/tool execution fails, use deterministic
      local query rules below so basic dashboard questions still work.
    """
    settings = LLMSettings.from_env()
    decision = route_llm_request(
        payload.message,
        available_providers=settings.available_provider_names(),
        preferences=settings.provider_preferences,
    )
    for provider_name in settings.provider_order(decision.provider):
        provider = settings.build_provider(provider_name, decision.intent)
        try:
            # app.state.chat_tools was built once from OpenAPI during startup.
            result = run_provider_tool_chat(
                provider=provider,
                message=payload.message,
                focus_topic=payload.focus_topic,
                history=[
                    {"role": item.role, "content": item.content}
                    for item in payload.history
                ],
                tools=app.state.chat_tools,
                approved_operations=APPROVED_CHAT_OPERATIONS,
                db=db,
                request_intent=decision.intent,
            )
            return ChatResponse(
                reply=result.reply,
                provider=provider.name,
                model=provider.model,
                route=decision.intent,
                operations=result.operations,
            )
        except (
            httpx.HTTPError,
            ChatToolError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            # Try the other configured provider before deterministic fallback.
            logger.warning(
                "%s tool chat failed: %s",
                provider.name,
                type(exc).__name__,
            )

    # LOCAL FALLBACK
    # Everything below this point is deterministic Python/SQLAlchemy logic. It
    # does not call Groq and is intentionally limited to common simple queries.
    message = " ".join(payload.message.lower().split())
    message_words = set(re.findall(r"[a-z]+", message))

    asks_for_weakest_topic = "topic" in message and (
        "weak" in message
        or ("lowest" in message and "average" in message)
    )
    if asks_for_weakest_topic:
        summaries = topic_summaries(db)
        if summaries:
            weakest = min(summaries, key=lambda item: item.average_score)
            return ChatResponse(
                reply=(
                    f"Your lowest-scoring topic is {weakest.focus_topic}, "
                    f"averaging {weakest.average_score:.1f} across "
                    f"{weakest.attempt_count} "
                    f"{'attempt' if weakest.attempt_count == 1 else 'attempts'}."
                )
            )
        return ChatResponse(reply="You do not have any scored topics yet.")

    scored_query = db.query(InterviewAttempt).filter(
        InterviewAttempt.status == "complete",
        InterviewAttempt.score.is_not(None),
    )
    if payload.focus_topic:
        scored_query = scored_query.filter(
            InterviewAttempt.focus_topic == payload.focus_topic,
        )

    attempts = scored_query.order_by(
        InterviewAttempt.attempted_date.asc(),
        InterviewAttempt.started_at.asc(),
        InterviewAttempt.id.asc(),
    ).all()

    topic_label = (
        f" for {payload.focus_topic}" if payload.focus_topic else ""
    )
    if message_words.intersection({"hello", "hi", "hey"}):
        return ChatResponse(
            reply=(
                "Hello! I can summarize your latest score, progress, attempt "
                "count, or available topics."
            )
        )

    if "topic" in message and any(
        word in message for word in ("available", "list", "what", "which", "all")
    ):
        topics = (
            db.query(InterviewAttempt.focus_topic)
            .filter(
                InterviewAttempt.status == "complete",
                InterviewAttempt.score.is_not(None),
                InterviewAttempt.focus_topic.is_not(None),
            )
            .distinct()
            .order_by(InterviewAttempt.focus_topic.asc())
            .all()
        )
        names = [row.focus_topic for row in topics]
        return ChatResponse(
            reply=(
                f"Your scored topics are: {', '.join(names)}."
                if names
                else "You do not have any scored topics yet."
            )
        )

    if not attempts:
        return ChatResponse(
            reply=f"I could not find any completed scored attempts{topic_label}."
        )

    first = attempts[0]
    latest = attempts[-1]
    first_score = float(first.score)
    latest_score = float(latest.score)
    change = latest_score - first_score

    if any(word in message for word in ("latest", "current", "recent", "score")):
        return ChatResponse(
            reply=(
                f"Your latest score{topic_label} is {latest_score:.1f}, from "
                f"{latest.attempted_date:%B %d, %Y}."
            )
        )

    if any(word in message for word in ("progress", "improve", "change", "trend")):
        direction = "up" if change > 0 else "down" if change < 0 else "unchanged"
        return ChatResponse(
            reply=(
                f"Across {len(attempts)} completed attempts{topic_label}, your "
                f"score is {direction} {abs(change):.1f} points—from "
                f"{first_score:.1f} to {latest_score:.1f}."
            )
        )

    if any(word in message for word in ("attempt", "count", "many")):
        return ChatResponse(
            reply=(
                f"You have {len(attempts)} completed scored "
                f"{'attempt' if len(attempts) == 1 else 'attempts'}{topic_label}."
            )
        )

    return ChatResponse(
        reply=(
            f"I found {len(attempts)} completed attempts{topic_label}. Your "
            f"latest score is {latest_score:.1f}. Ask me about your latest "
            "score, progress, attempts, or topics."
        )
    )

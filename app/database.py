import json
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session, Column, String, JSON


class DateType(str, Enum):
    last_accessed = "last_accessed"
    last_modified = "last_modified"
    date_added = "date_added"
    last_watched = "last_watched"


class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    directory: str
    size_min_mb: Optional[float] = None
    size_max_mb: Optional[float] = None
    date_type: DateType = Field(default=DateType.last_modified)
    date_threshold_days: int = 90
    extensions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class StagedFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_id: int = Field(foreign_key="rule.id")
    filepath: str
    filename: str
    size_bytes: int
    matched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    delete_at: datetime
    notified: bool = False
    deleted: bool = False


class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    cron_expression: str = "0 3 * * *"
    notify_lead_hours: int = 48
    apprise_urls: str = ""
    first_run_complete: bool = False
    trash_path: str = "/moth/trash"
    trash_retention_days: int = 7
    # Tautulli integration
    tautulli_url: str = ""
    tautulli_api_key: str = ""
    tautulli_enabled: bool = False
    tautulli_path_mapping: str = ""  # JSON: {"plex_prefix": "moth_prefix", ...}
    # Season suggestions
    season_suggest_enabled: bool = False
    season_suggest_threshold_pct: int = 75
    season_suggest_users: str = ""  # Comma-separated usernames (empty = all)


class SeasonSuggestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    show_title: str
    show_rating_key: str = ""
    current_season: int
    next_season: int
    user: str
    progress_pct: float
    suggested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    dismissed: bool = False


class ScanLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    completed_at: Optional[datetime] = None
    files_matched: int = 0
    files_deleted: int = 0
    dry_run: bool = False
    notes: Optional[str] = None


DATABASE_URL = os.getenv("MOTH_DATABASE_URL", "sqlite:////data/moth.db")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db():
    """Create all tables and ensure default settings row exists."""
    # Enable WAL mode for concurrent read/write safety
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.commit()

    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        settings = session.get(Settings, 1)
        if not settings:
            settings = Settings(
                cron_expression=os.getenv("MOTH_CRON", "0 3 * * *"),
                notify_lead_hours=int(os.getenv("MOTH_NOTIFY_LEAD_HOURS", "48")),
                apprise_urls=os.getenv("MOTH_APPRISE_URLS", ""),
                trash_path=os.getenv("MOTH_TRASH_PATH", "/moth/trash"),
                tautulli_url=os.getenv("MOTH_TAUTULLI_URL", ""),
                tautulli_api_key=os.getenv("MOTH_TAUTULLI_API_KEY", ""),
                tautulli_enabled=os.getenv("MOTH_TAUTULLI_ENABLED", "").lower() in ("1", "true", "yes"),
            )
            session.add(settings)
            session.commit()


def get_session():
    with Session(engine) as session:
        yield session

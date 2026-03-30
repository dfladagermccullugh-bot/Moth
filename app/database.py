import json
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session, Column, String, JSON


class DateType(str, Enum):
    last_accessed = "last_accessed"
    last_modified = "last_modified"
    date_added = "date_added"


class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    directory: str
    size_min_mb: Optional[float] = None
    size_max_mb: Optional[float] = None
    date_type: DateType = Field(default=DateType.last_modified)
    date_threshold_days: int = 90
    extensions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StagedFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_id: int = Field(foreign_key="rule.id")
    filepath: str
    filename: str
    size_bytes: int
    matched_at: datetime = Field(default_factory=datetime.utcnow)
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


class ScanLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    files_matched: int = 0
    files_deleted: int = 0
    dry_run: bool = False
    notes: Optional[str] = None


DATABASE_URL = "sqlite:///data/moth.db"

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
            import os
            settings = Settings(
                cron_expression=os.getenv("MOTH_CRON", "0 3 * * *"),
                notify_lead_hours=int(os.getenv("MOTH_NOTIFY_LEAD_HOURS", "48")),
                apprise_urls=os.getenv("MOTH_APPRISE_URLS", ""),
                trash_path=os.getenv("MOTH_TRASH_PATH", "/moth/trash"),
            )
            session.add(settings)
            session.commit()


def get_session():
    with Session(engine) as session:
        yield session

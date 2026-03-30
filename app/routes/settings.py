import json
import logging

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session

from app.database import Settings, get_session
from app.extensions import VIDEO_EXTENSIONS
from app.notifier import send_test_notification
from app.scheduler import reschedule
from app.tautulli import TautulliClient, TautulliError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


class SettingsUpdate(BaseModel):
    cron_expression: str | None = None
    notify_lead_hours: int | None = None
    apprise_urls: str | None = None
    first_run_complete: bool | None = None
    trash_retention_days: int | None = None
    # Tautulli
    tautulli_url: str | None = None
    tautulli_api_key: str | None = None
    tautulli_enabled: bool | None = None
    tautulli_path_mapping: str | None = None
    # Season suggestions
    season_suggest_enabled: bool | None = None
    season_suggest_threshold_pct: int | None = None
    season_suggest_users: str | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                CronTrigger.from_crontab(v)
            except ValueError as e:
                raise ValueError(f"Invalid cron expression: {e}")
        return v

    @field_validator("tautulli_path_mapping")
    @classmethod
    def validate_path_mapping(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            try:
                parsed = json.loads(v)
                if not isinstance(parsed, dict):
                    raise ValueError("Path mapping must be a JSON object")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON for path mapping: {e}")
        return v


@router.get("/api/settings")
def get_settings(session: Session = Depends(get_session)):
    settings = session.get(Settings, 1)
    if not settings:
        raise HTTPException(status_code=500, detail="Settings not initialized")
    # Mask the Tautulli API key in responses
    data = {
        "id": settings.id,
        "cron_expression": settings.cron_expression,
        "notify_lead_hours": settings.notify_lead_hours,
        "apprise_urls": settings.apprise_urls,
        "first_run_complete": settings.first_run_complete,
        "trash_path": settings.trash_path,
        "trash_retention_days": settings.trash_retention_days,
        "tautulli_url": settings.tautulli_url,
        "tautulli_api_key_set": bool(settings.tautulli_api_key),
        "tautulli_enabled": settings.tautulli_enabled,
        "tautulli_path_mapping": settings.tautulli_path_mapping,
        "season_suggest_enabled": settings.season_suggest_enabled,
        "season_suggest_threshold_pct": settings.season_suggest_threshold_pct,
        "season_suggest_users": settings.season_suggest_users,
    }
    return data


@router.put("/api/settings")
def update_settings(
    data: SettingsUpdate, session: Session = Depends(get_session)
):
    settings = session.get(Settings, 1)
    if not settings:
        raise HTTPException(status_code=500, detail="Settings not initialized")

    update_data = data.model_dump(exclude_unset=True)

    # If tautulli_api_key is empty string, don't overwrite existing key
    # (frontend sends empty when the key is masked)
    if "tautulli_api_key" in update_data and update_data["tautulli_api_key"] == "":
        del update_data["tautulli_api_key"]

    old_cron = settings.cron_expression
    for key, value in update_data.items():
        setattr(settings, key, value)
    session.add(settings)
    session.commit()
    session.refresh(settings)

    if "cron_expression" in update_data and settings.cron_expression != old_cron:
        reschedule(settings.cron_expression)

    return get_settings(session)


@router.get("/api/extensions")
def get_extensions():
    return VIDEO_EXTENSIONS


@router.post("/api/notify/test")
def test_notification(session: Session = Depends(get_session)):
    success = send_test_notification(session)
    if success:
        return {"ok": True, "message": "Test notification sent"}
    return {"ok": False, "message": "No notification URLs configured or send failed"}


@router.post("/api/tautulli/test")
def test_tautulli(session: Session = Depends(get_session)):
    settings = session.get(Settings, 1)
    if not settings or not settings.tautulli_url or not settings.tautulli_api_key:
        return {"ok": False, "message": "Tautulli URL and API key are required"}

    client = TautulliClient(settings.tautulli_url, settings.tautulli_api_key)
    try:
        info = client.test_connection()
        version = info.get("tautulli_version", "unknown")
        return {"ok": True, "message": f"Connected to Tautulli v{version}"}
    except TautulliError as e:
        logger.warning("Tautulli connection test failed: %s", e)
        return {"ok": False, "message": str(e)}

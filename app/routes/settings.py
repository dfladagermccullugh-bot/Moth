from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session

from app.database import Settings, get_session
from app.extensions import VIDEO_EXTENSIONS
from app.notifier import send_test_notification
from app.scheduler import reschedule

router = APIRouter(tags=["settings"])


class SettingsUpdate(BaseModel):
    cron_expression: str | None = None
    notify_lead_hours: int | None = None
    apprise_urls: str | None = None
    first_run_complete: bool | None = None
    trash_retention_days: int | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                CronTrigger.from_crontab(v)
            except ValueError as e:
                raise ValueError(f"Invalid cron expression: {e}")
        return v


@router.get("/api/settings")
def get_settings(session: Session = Depends(get_session)):
    settings = session.get(Settings, 1)
    if not settings:
        raise HTTPException(status_code=500, detail="Settings not initialized")
    return settings


@router.put("/api/settings")
def update_settings(
    data: SettingsUpdate, session: Session = Depends(get_session)
):
    settings = session.get(Settings, 1)
    if not settings:
        raise HTTPException(status_code=500, detail="Settings not initialized")

    update_data = data.model_dump(exclude_unset=True)
    old_cron = settings.cron_expression
    for key, value in update_data.items():
        setattr(settings, key, value)
    session.add(settings)
    session.commit()
    session.refresh(settings)

    if "cron_expression" in update_data and settings.cron_expression != old_cron:
        reschedule(settings.cron_expression)

    return settings


@router.get("/api/extensions")
def get_extensions():
    return VIDEO_EXTENSIONS


@router.post("/api/notify/test")
def test_notification(session: Session = Depends(get_session)):
    success = send_test_notification(session)
    if success:
        return {"ok": True, "message": "Test notification sent"}
    return {"ok": False, "message": "No notification URLs configured or send failed"}

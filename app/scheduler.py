from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from app.database import engine, Settings
from app.scanner import run_scan, cleanup_trash

scheduler = BackgroundScheduler()


def _scheduled_scan():
    """Run a scan cycle within its own session."""
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        if not settings or not settings.first_run_complete:
            return
        run_scan(session)


def _scheduled_trash_cleanup():
    """Clean up expired files from the trash staging folder."""
    with Session(engine) as session:
        cleanup_trash(session)


def start_scheduler():
    """Initialize and start the scheduler with current settings."""
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        cron_expr = settings.cron_expression if settings else "0 3 * * *"

    _apply_cron(cron_expr)

    # Trash cleanup runs daily at 4am
    scheduler.add_job(
        _scheduled_trash_cleanup,
        CronTrigger.from_crontab("0 4 * * *"),
        id="trash_cleanup",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()


def reschedule(cron_expression: str):
    """Update the scan schedule with a new cron expression."""
    _apply_cron(cron_expression)


def _apply_cron(cron_expression: str):
    """Add or replace the scan job with the given cron expression."""
    trigger = CronTrigger.from_crontab(cron_expression)
    scheduler.add_job(
        _scheduled_scan,
        trigger,
        id="moth_scan",
        replace_existing=True,
        misfire_grace_time=3600,
    )

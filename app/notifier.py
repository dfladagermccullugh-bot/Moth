import apprise
from sqlmodel import Session

from app.database import Settings


def _get_apprise(session: Session) -> apprise.Apprise | None:
    settings = session.get(Settings, 1)
    if not settings or not settings.apprise_urls.strip():
        return None
    ap = apprise.Apprise()
    for url in settings.apprise_urls.split(","):
        url = url.strip()
        if url:
            ap.add(url)
    return ap


def send_notification(session: Session, title: str, body: str) -> bool:
    ap = _get_apprise(session)
    if not ap:
        return False
    return ap.notify(title=title, body=body)


def notify_pre_deletion(session: Session, filenames: list[str], hours_remaining: int):
    count = len(filenames)
    file_list = ", ".join(filenames[:10])
    if count > 10:
        file_list += f" ... and {count - 10} more"
    send_notification(
        session,
        title=f"Moth: {count} file(s) will be deleted in {hours_remaining}h",
        body=file_list,
    )


def notify_deletion_confirmed(session: Session, filenames: list[str]):
    count = len(filenames)
    file_list = ", ".join(filenames[:10])
    if count > 10:
        file_list += f" ... and {count - 10} more"
    send_notification(
        session,
        title=f"Moth: {count} file(s) were deleted",
        body=file_list,
    )


def notify_scan_error(session: Session, error_message: str):
    send_notification(
        session,
        title="Moth: Scan error",
        body=f"{error_message}. Check logs.",
    )


def send_test_notification(session: Session) -> bool:
    return send_notification(
        session,
        title="Moth: Test Notification",
        body="If you see this, notifications are working!",
    )

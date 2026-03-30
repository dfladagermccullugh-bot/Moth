import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.database import Rule, StagedFile, ScanLog, Settings, DateType
from app.notifier import notify_pre_deletion, notify_deletion_confirmed, notify_scan_error
from app.tautulli import get_client_from_settings, build_watch_date_cache, TautulliError

logger = logging.getLogger(__name__)


def _get_file_date(filepath: str, date_type: DateType, watch_cache: dict[str, datetime] | None = None) -> datetime:
    if date_type == DateType.last_watched:
        if watch_cache and filepath in watch_cache:
            return watch_cache[filepath]
        # No watch history — treat as never watched (very old date triggers deletion)
        return datetime.min
    stat = os.stat(filepath)
    if date_type == DateType.last_accessed:
        return datetime.fromtimestamp(stat.st_atime)
    elif date_type == DateType.last_modified:
        return datetime.fromtimestamp(stat.st_mtime)
    else:  # date_added
        return datetime.fromtimestamp(stat.st_ctime)


def _file_matches_rule(filepath: str, rule: Rule, watch_cache: dict[str, datetime] | None = None) -> bool:
    ext = Path(filepath).suffix.lstrip(".").lower()
    if rule.extensions and ext not in [e.lower() for e in rule.extensions]:
        return False

    try:
        size_bytes = os.stat(filepath).st_size
    except OSError:
        return False

    size_mb = size_bytes / (1024 * 1024)
    if rule.size_min_mb is not None and size_mb < rule.size_min_mb:
        return False
    if rule.size_max_mb is not None and size_mb > rule.size_max_mb:
        return False

    try:
        file_date = _get_file_date(filepath, rule.date_type, watch_cache)
    except OSError:
        return False

    threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=rule.date_threshold_days)
    if file_date > threshold:
        return False

    return True


def _walk_directory(directory: str, extensions: list[str]):
    """Walk directory and yield file paths matching any of the given extensions."""
    ext_set = {e.lower() for e in extensions} if extensions else None
    try:
        for root, _dirs, files in os.walk(directory):
            for fname in files:
                if ext_set:
                    ext = Path(fname).suffix.lstrip(".").lower()
                    if ext not in ext_set:
                        continue
                yield os.path.join(root, fname)
    except PermissionError as e:
        logger.warning("Permission denied accessing directory %s: %s", directory, e)


def _build_watch_cache_if_needed(rules: list[Rule], settings: Settings) -> dict[str, datetime] | None:
    """Build the Tautulli watch date cache if any rule uses last_watched."""
    needs_tautulli = any(r.date_type == DateType.last_watched for r in rules)
    if not needs_tautulli:
        return None

    client = get_client_from_settings(settings)
    if not client:
        logger.warning("Rules use last_watched but Tautulli is not configured/enabled — those rules will be skipped")
        return None

    path_mapping = None
    if settings.tautulli_path_mapping:
        try:
            path_mapping = json.loads(settings.tautulli_path_mapping)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid tautulli_path_mapping JSON, ignoring")

    try:
        return build_watch_date_cache(client, path_mapping)
    except TautulliError as e:
        logger.error("Failed to build Tautulli watch cache: %s", e)
        return None


def run_scan(session: Session, dry_run: bool = False) -> ScanLog:
    """Execute a full scan cycle. Returns the ScanLog entry."""
    log = ScanLog(started_at=datetime.now(timezone.utc).replace(tzinfo=None), dry_run=dry_run)
    session.add(log)
    session.commit()
    session.refresh(log)

    settings = session.get(Settings, 1)
    files_matched = 0
    files_deleted = 0
    notes_parts: list[str] = []

    try:
        rules = session.exec(select(Rule).where(Rule.enabled == True)).all()

        # Build Tautulli watch cache if needed
        watch_cache = _build_watch_cache_if_needed(rules, settings)

        # Track which filepaths are matched this scan (for un-staging)
        matched_filepaths: set[str] = set()

        for rule in rules:
            # Skip last_watched rules when Tautulli cache is unavailable
            if rule.date_type == DateType.last_watched and watch_cache is None:
                notes_parts.append(f"Skipped rule {rule.id} (last_watched): Tautulli unavailable")
                continue

            if not os.path.isdir(rule.directory):
                notes_parts.append(f"Directory not found: {rule.directory}")
                continue

            for filepath in _walk_directory(rule.directory, rule.extensions):
                try:
                    if not _file_matches_rule(filepath, rule, watch_cache):
                        continue
                except Exception as e:
                    notes_parts.append(f"Error checking {filepath}: {e}")
                    continue

                matched_filepaths.add(filepath)
                files_matched += 1

                if dry_run:
                    continue

                # Check if already staged
                existing = session.exec(
                    select(StagedFile).where(
                        StagedFile.filepath == filepath,
                        StagedFile.deleted == False,
                    )
                ).first()

                if not existing:
                    delete_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
                        hours=settings.notify_lead_hours + 24
                    )
                    staged = StagedFile(
                        rule_id=rule.id,
                        filepath=filepath,
                        filename=os.path.basename(filepath),
                        size_bytes=os.stat(filepath).st_size,
                        delete_at=delete_at,
                    )
                    session.add(staged)

        if not dry_run:
            session.commit()

            # Un-stage files that no longer match any rule
            all_staged = session.exec(
                select(StagedFile).where(StagedFile.deleted == False)
            ).all()
            for staged in all_staged:
                if staged.filepath not in matched_filepaths:
                    session.delete(staged)
            session.commit()

            # Send notifications for files approaching deletion
            notify_threshold = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
                hours=settings.notify_lead_hours
            )
            pending_notify = session.exec(
                select(StagedFile).where(
                    StagedFile.deleted == False,
                    StagedFile.notified == False,
                    StagedFile.delete_at <= notify_threshold,
                )
            ).all()
            if pending_notify:
                filenames = [sf.filename for sf in pending_notify]
                notify_pre_deletion(session, filenames, settings.notify_lead_hours)
                for sf in pending_notify:
                    sf.notified = True
                session.commit()

            # Delete files past their delete_at time
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            ready_to_delete = session.exec(
                select(StagedFile).where(
                    StagedFile.deleted == False,
                    StagedFile.delete_at <= now,
                )
            ).all()

            deleted_filenames: list[str] = []
            for sf in ready_to_delete:
                try:
                    # Use basename to prevent path traversal attacks
                    safe_name = os.path.basename(sf.filename)
                    # Add UUID prefix to prevent filename collisions
                    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
                    trash_dest = os.path.join(settings.trash_path, unique_name)
                    os.makedirs(settings.trash_path, exist_ok=True)
                    shutil.move(sf.filepath, trash_dest)
                    # Mark deleted AFTER successful move
                    sf.deleted = True
                    files_deleted += 1
                    deleted_filenames.append(sf.filename)
                except Exception as e:
                    notes_parts.append(f"Failed to delete {sf.filepath}: {e}")
                    logger.error("Failed to move %s to trash: %s", sf.filepath, e)

            session.commit()

            if deleted_filenames:
                notify_deletion_confirmed(session, deleted_filenames)

    except Exception as e:
        notes_parts.append(f"Scan error: {e}")
        notify_scan_error(session, str(e))

    log.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    log.files_matched = files_matched
    log.files_deleted = files_deleted
    log.notes = "; ".join(notes_parts) if notes_parts else None
    session.add(log)
    session.commit()
    session.refresh(log)

    return log


def cleanup_trash(session: Session):
    """Permanently delete files from trash that have exceeded retention."""
    settings = session.get(Settings, 1)
    if not settings or not os.path.isdir(settings.trash_path):
        return

    retention = timedelta(days=settings.trash_retention_days)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for fname in os.listdir(settings.trash_path):
        fpath = os.path.join(settings.trash_path, fname)
        try:
            mtime = datetime.fromtimestamp(os.stat(fpath).st_mtime)
            if now - mtime > retention:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                elif os.path.isdir(fpath):
                    shutil.rmtree(fpath)
        except OSError:
            pass

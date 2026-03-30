import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.database import Settings, SeasonSuggestion
from app.notifier import send_notification
from app.tautulli import TautulliClient, TautulliError, get_client_from_settings

logger = logging.getLogger(__name__)


def check_season_pickups(session: Session) -> list[SeasonSuggestion]:
    """
    Check Tautulli for users nearing the end of a TV season
    and suggest picking up the next season if it's missing.

    Returns list of newly created SeasonSuggestion records.
    """
    settings = session.get(Settings, 1)
    if not settings or not settings.season_suggest_enabled:
        return []

    client = get_client_from_settings(settings)
    if not client:
        logger.warning("Season suggestions enabled but Tautulli is not configured")
        return []

    threshold_pct = settings.season_suggest_threshold_pct
    tracked_users = _parse_tracked_users(settings.season_suggest_users)

    try:
        return _analyze_season_progress(session, client, threshold_pct, tracked_users)
    except TautulliError as e:
        logger.error("Failed to check season pickups: %s", e)
        return []


def _parse_tracked_users(users_str: str) -> set[str] | None:
    """Parse comma-separated usernames. Returns None if empty (track all)."""
    if not users_str or not users_str.strip():
        return None
    return {u.strip().lower() for u in users_str.split(",") if u.strip()}


def _analyze_season_progress(
    session: Session,
    client: TautulliClient,
    threshold_pct: int,
    tracked_users: set[str] | None,
) -> list[SeasonSuggestion]:
    """Core logic: analyze watch history and generate suggestions."""
    # Get recent TV watch history (last 30 days, generous window)
    history = client.get_history(length=5000, media_type="episode")

    # Group watches by user -> show -> season -> set of episode indexes
    # Structure: {username: {grandparent_rating_key: {season_num: set(episode_indexes)}}}
    user_progress: dict[str, dict[str, dict[int, set[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    # Track show titles for display
    show_titles: dict[str, str] = {}

    for entry in history:
        username = (entry.get("user") or entry.get("friendly_name") or "").lower()
        if tracked_users is not None and username not in tracked_users:
            continue

        media_type = entry.get("media_type", "")
        if media_type != "episode":
            continue

        grandparent_key = str(entry.get("grandparent_rating_key", ""))
        if not grandparent_key:
            continue

        show_title = entry.get("grandparent_title", "Unknown Show")
        show_titles[grandparent_key] = show_title

        try:
            season_num = int(entry.get("parent_media_index", 0))
            episode_index = int(entry.get("media_index", 0))
        except (ValueError, TypeError):
            continue

        if season_num > 0 and episode_index > 0:
            user_progress[username][grandparent_key][season_num].add(episode_index)

    new_suggestions: list[SeasonSuggestion] = []

    for username, shows in user_progress.items():
        for show_key, seasons in shows.items():
            show_title = show_titles.get(show_key, "Unknown Show")

            for season_num, watched_episodes in seasons.items():
                # Get total episodes in this season from Tautulli metadata
                total_episodes = _get_season_episode_count(client, show_key, season_num)
                if total_episodes <= 0:
                    continue

                progress = (len(watched_episodes) / total_episodes) * 100

                if progress < threshold_pct:
                    continue

                next_season = season_num + 1

                # Check if next season exists in Plex
                if _season_exists_in_library(client, show_key, next_season):
                    continue

                # Check if we already suggested this
                existing = session.exec(
                    select(SeasonSuggestion).where(
                        SeasonSuggestion.show_rating_key == show_key,
                        SeasonSuggestion.current_season == season_num,
                        SeasonSuggestion.next_season == next_season,
                        SeasonSuggestion.user == username,
                        SeasonSuggestion.dismissed == False,
                    )
                ).first()

                if existing:
                    # Update progress if it changed
                    if existing.progress_pct != round(progress, 1):
                        existing.progress_pct = round(progress, 1)
                        session.add(existing)
                    continue

                suggestion = SeasonSuggestion(
                    show_title=show_title,
                    show_rating_key=show_key,
                    current_season=season_num,
                    next_season=next_season,
                    user=username,
                    progress_pct=round(progress, 1),
                )
                session.add(suggestion)
                new_suggestions.append(suggestion)

    session.commit()

    # Send notifications for new suggestions
    if new_suggestions:
        _notify_suggestions(session, new_suggestions)

    return new_suggestions


# Cache for season episode counts within a single run
_episode_count_cache: dict[str, int] = {}


def _get_season_episode_count(client: TautulliClient, show_rating_key: str, season_num: int) -> int:
    """Get total episode count for a specific season of a show."""
    cache_key = f"{show_rating_key}_s{season_num}"
    if cache_key in _episode_count_cache:
        return _episode_count_cache[cache_key]

    try:
        metadata = client.get_metadata(show_rating_key)
        for child in metadata.get("children", []):
            if child.get("media_index") == season_num or str(child.get("media_index")) == str(season_num):
                count = int(child.get("leaf_count", 0))
                _episode_count_cache[cache_key] = count
                return count
        # If children aren't in the show metadata, the show metadata itself
        # might have season info at a different level — fall back to 0
    except (TautulliError, KeyError, TypeError) as e:
        logger.debug("Could not get episode count for %s S%d: %s", show_rating_key, season_num, e)

    _episode_count_cache[cache_key] = 0
    return 0


def _season_exists_in_library(client: TautulliClient, show_rating_key: str, season_num: int) -> bool:
    """Check if a specific season number exists for a show in the Plex library."""
    try:
        metadata = client.get_metadata(show_rating_key)
        for child in metadata.get("children", []):
            if child.get("media_index") == season_num or str(child.get("media_index")) == str(season_num):
                return True
    except (TautulliError, KeyError, TypeError):
        pass
    return False


def _notify_suggestions(session: Session, suggestions: list[SeasonSuggestion]):
    """Send Apprise notification for new season suggestions."""
    lines = []
    for s in suggestions:
        lines.append(
            f"- {s.show_title}: {s.user} is {s.progress_pct}% through S{s.current_season:02d}. "
            f"Season {s.next_season} is not in your library."
        )

    body = "\n".join(lines)
    send_notification(
        session,
        title=f"Moth: {len(suggestions)} season pickup suggestion(s)",
        body=body,
    )

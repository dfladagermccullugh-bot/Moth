# Tautulli Integration Plan for Moth

## Context

Moth is a standalone media lifecycle manager that decides what to delete based on filesystem timestamps. Tautulli is a Plex monitoring tool with rich watch history, user stats, and activity data — but no formal plugin system.

The goal: make Tautulli a **data source** for Moth, not rewrite Moth as a Tautulli plugin. This gives Moth real watch intelligence instead of unreliable filesystem dates, and opens the door to a new "season pickup" suggestion feature.

---

## Phase 1: Tautulli Connection & Settings

**Goal**: Let users configure their Tautulli instance in Moth's settings.

### Database Changes (`app/database.py`)

Add fields to the `Settings` model:

```python
# Tautulli connection
tautulli_url: str = ""           # e.g. "http://192.168.1.50:8181"
tautulli_api_key: str = ""       # Tautulli API key
tautulli_enabled: bool = False   # Master toggle
```

### Settings API (`app/routes/settings.py`)

- Add `tautulli_url`, `tautulli_api_key`, `tautulli_enabled` to `SettingsUpdate`
- Add a `POST /api/tautulli/test` endpoint that calls Tautulli's `get_server_info` (`cmd=get_tautulli_info`) to verify connectivity
- Mask the API key in GET responses (return `"****"` if set, `""` if not)

### Settings UI (`app/templates/settings.html`)

- New "Tautulli" section with URL, API key, and enable/disable toggle
- "Test Connection" button (HTMX POST to `/api/tautulli/test`)

### New Module: `app/tautulli.py`

Thin client wrapping Tautulli's REST API using the existing `httpx` dependency:

```python
class TautulliClient:
    def __init__(self, url: str, api_key: str):
        self.base = url.rstrip("/")
        self.api_key = api_key

    def _get(self, cmd: str, **params) -> dict:
        """Call Tautulli API: GET /api/v2?apikey=...&cmd=..."""

    def get_server_info(self) -> dict: ...
    def get_history(self, rating_key: str = None, length: int = 1000) -> list[dict]: ...
    def get_library_media_info(self, section_id: str, length: int = ...) -> list[dict]: ...
    def get_metadata(self, rating_key: str) -> dict: ...
    def get_home_stats(self, ...) -> dict: ...
```

**Estimated effort**: Small. ~200 lines across 4 files.

---

## Phase 2: `last_watched` Date Type

**Goal**: Let rules use Plex watch history instead of filesystem timestamps to determine staleness.

This is the highest-value change. Filesystem `atime` is unreliable — Plex, Sonarr, and scrapers constantly touch files, making "last accessed" meaningless. Tautulli knows when a human actually watched something.

### How It Works

1. Add `last_watched` to the `DateType` enum in `database.py`
2. When a rule uses `date_type = "last_watched"`, the scanner calls Tautulli instead of `os.stat()`
3. Tautulli's `get_history` API returns play history with timestamps per media item

### Key Design Decision: Mapping Files to Tautulli Rating Keys

Tautulli identifies media by Plex `rating_key`, not filesystem path. We need to map between them.

**Approach: Library media info lookup + path matching**

1. On scan, call `get_library_media_info` for each Plex library section to get a mapping of `rating_key -> file_path`
2. Cache this mapping in memory (or SQLite) for the duration of the scan
3. For each file Moth finds on disk, look up its `rating_key` from the cached map
4. Query `get_history(rating_key=...)` to find the last play timestamp
5. If no play history exists, treat the file as "never watched" (use `date_added` from Tautulli metadata as fallback, or the file's filesystem date)

**Alternative considered**: Tautulli's `get_metadata` returns `file` paths directly, but requires one API call per item. The library-level bulk fetch is more efficient.

### Scanner Changes (`app/scanner.py`)

```python
def _get_file_date(filepath: str, date_type: DateType, tautulli_cache: dict = None) -> datetime:
    if date_type == DateType.last_watched:
        if tautulli_cache and filepath in tautulli_cache:
            return tautulli_cache[filepath]
        # Fallback: treat as very old (will match the rule)
        return datetime.min
    # ... existing filesystem logic
```

In `run_scan()`, build the Tautulli cache once before iterating rules:

```python
if any(r.date_type == DateType.last_watched for r in rules):
    tautulli_cache = build_watch_date_cache(tautulli_client)
```

### New: `app/tautulli.py` additions

```python
def build_watch_date_cache(client: TautulliClient) -> dict[str, datetime]:
    """
    Returns {filepath: last_watched_datetime} for all media in all libraries.
    Files with no watch history are omitted (caller handles fallback).
    """
```

**Estimated effort**: Medium. ~300 lines. The path-matching logic is the tricky part — Plex paths may differ from Moth's mounted paths (e.g., `/media/TV` in Moth vs `/data/TV Shows` in Plex). We'll need a configurable path prefix mapping in settings:

```python
# In Settings model
tautulli_path_mapping: str = ""  # JSON: {"/media": "/data/TV Shows"}
```

---

## Phase 3: Season Pickup Suggestions

**Goal**: Detect when users are finishing a season and notify you to acquire the next one.

This is the feature your friend specifically asked for: "suggest when I need to pick up my next season for subscribers."

### How It Works

1. **Periodic check** (new scheduled job, e.g., daily alongside the scan)
2. Query Tautulli's `get_history` for recent watch activity
3. For each TV series with recent activity:
   - Get the show's metadata to find total seasons/episodes
   - Calculate watch progress: what % of the current season has user X watched?
   - If progress >= configurable threshold (e.g., 75%), check if the next season exists on disk
   - If next season is **missing**, fire an Apprise notification:
     > "User 'alice' is 80% through Season 3 of Breaking Bad. Season 4 is not in your library."

### Database Changes

```python
# New model
class SeasonSuggestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    show_title: str
    current_season: int
    next_season: int
    user: str
    progress_pct: float
    suggested_at: datetime
    dismissed: bool = False

# Settings additions
season_suggest_enabled: bool = False
season_suggest_threshold_pct: int = 75  # Notify when user has watched this % of a season
season_suggest_users: str = ""          # Comma-separated Tautulli usernames to track (empty = all)
```

### New Module: `app/suggestions.py`

```python
def check_season_pickups(session: Session, client: TautulliClient) -> list[SeasonSuggestion]:
    """
    For each tracked user:
    1. Get recent TV watch history
    2. Group by show + season
    3. Calculate progress per season
    4. Check if next season exists in library
    5. Return new suggestions (deduplicated against existing)
    """
```

### API Endpoints (`app/routes/suggestions.py`)

- `GET /api/suggestions` — List active suggestions
- `POST /api/suggestions/{id}/dismiss` — Dismiss a suggestion
- `GET /suggestions` — Web UI page showing active suggestions with dismiss buttons

### Scheduler Addition

- New job: `check_season_pickups`, runs daily (configurable)
- Fires Apprise notifications for new suggestions

### Optional: Sonarr Integration

If the user also runs Sonarr, we could go further:

- Check Sonarr's API to see if the next season is monitored/available for download
- Offer a "Monitor in Sonarr" action button

This is out of scope for initial implementation but worth noting as a future enhancement.

**Estimated effort**: Large. ~500 lines across 4-5 files. This is a genuinely new feature, not just a data source swap.

---

## Phase 4: Web UI Enhancements

### Tautulli Stats on Staged Files

When Tautulli is connected, enrich the `/staged` page with watch data:

- Last watched date and by whom
- Total play count
- Show a warning icon if something staged for deletion was recently watched

### Suggestions Dashboard

New `/suggestions` page:

- Table of active season pickup suggestions
- Show: title, user, current season progress, next season needed
- "Dismiss" button per suggestion
- Filter by user

### Rule Editor Enhancement

- When Tautulli is connected, show `last_watched` as a date type option in the rule editor
- Show a tooltip explaining the difference from filesystem dates

**Estimated effort**: Medium. ~300 lines of templates + CSS.

---

## Implementation Order

| Priority | Phase | Value | Effort | Notes |
|----------|-------|-------|--------|-------|
| 1 | Phase 1: Connection & Settings | Foundation | Small | Required by everything else |
| 2 | Phase 2: `last_watched` | Very High | Medium | Core value prop — smart deletions |
| 3 | Phase 3: Season Suggestions | High | Large | Your friend's key ask |
| 4 | Phase 4: UI Enhancements | Medium | Medium | Polish, can be incremental |

---

## Technical Considerations

### Path Mapping

Plex and Moth see different filesystem paths (Plex might mount media at `/data/TV Shows`, Moth at `/media/tv`). The path mapping config is critical — without it, Moth can't correlate Tautulli's metadata with files on disk. This should be a simple prefix substitution, configurable in settings.

### API Rate Limiting

Tautulli's API has no documented rate limits, but we should:
- Cache library media info per scan (don't re-fetch per file)
- Use bulk endpoints (`get_library_media_info`) over per-item endpoints (`get_metadata`)
- Add a configurable timeout (default 30s) for Tautulli API calls

### Tautulli Unavailability

If Tautulli is unreachable during a scan:
- Rules using `last_watched` should **skip** (not fall back to filesystem dates)
- Log a warning and send an Apprise notification
- Other rules (filesystem-based) continue normally

### No New Dependencies

`httpx` is already in `requirements.txt`. The Tautulli client needs nothing else.

### Docker Considerations

No container changes needed. Moth already runs on a Docker network — users just need Tautulli reachable from the Moth container (same Docker network or host networking).

---

## Environment Variables (New)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MOTH_TAUTULLI_URL` | *(empty)* | Tautulli base URL |
| `MOTH_TAUTULLI_API_KEY` | *(empty)* | Tautulli API key |
| `MOTH_TAUTULLI_ENABLED` | `false` | Enable Tautulli integration |

These seed the database on first run, same pattern as existing env vars.

---

## Summary

The integration turns Moth from a filesystem-level cleanup tool into a **watch-aware media manager**. Phase 2 (`last_watched`) is the single highest-impact change — it solves the fundamental problem that filesystem timestamps don't reflect actual viewing. Phase 3 (season suggestions) adds a new acquisition-oriented workflow that complements the existing deletion-oriented core.

Total estimated new code: ~1,300 lines across ~8 files, zero new dependencies.

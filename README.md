# Moth

Autonomous Media Lifecycle Manager

Moth monitors media directories, detects stale files based on configurable rules, and automatically cleans them up. Optionally connects to Tautulli for watch-aware cleanup and season pickup suggestions. Self-hosted via Docker.

## Quick Start

1. Copy and edit the environment file:
   ```bash
   cp .env.example .env
   ```

2. Set your media directory in `docker-compose.yml`:
   ```yaml
   volumes:
     - /path/to/your/media:/media
   ```

3. Start the container:
   ```bash
   docker compose up -d
   ```

4. Open `http://localhost:6969`, configure rules, and acknowledge the first-run dry run before any live deletions occur.

## Features

- **Rule-based scanning** — per-directory rules with size, date, and extension filters
- **Safe deletion** — files move to trash with a configurable grace period before permanent removal
- **Notifications** — pre-deletion warnings via Apprise (Telegram, Discord, email, ntfy, 80+ services)
- **Tautulli integration** — use Plex watch history instead of filesystem timestamps for smarter cleanup
- **Season pickup suggestions** — get notified when users are finishing a season and the next one isn't in your library
- **Web GUI** — HTMX-powered interface for rules, staged files, suggestions, and settings
- **CLI** — thin client backed by the same API
- **Scheduled scans** — configurable cron schedule
- **First-run dry run** — mandatory review before any live deletions
- **API key auth** — optional authentication for all endpoints

## Configuration

All configuration is done via environment variables in `.env`:

| Variable | Default | Description |
|---|---|---|
| `MOTH_PORT` | `6969` | Host port mapping |
| `MOTH_TRASH_PATH` | `/path/to/trash` | Host path for staged deletions |
| `MOTH_CRON` | `0 3 * * *` | Scan schedule (cron syntax) |
| `MOTH_NOTIFY_LEAD_HOURS` | `48` | Hours before deletion to send notification |
| `MOTH_APPRISE_URLS` | *(empty)* | Comma-separated [Apprise URLs](https://github.com/caronc/apprise/wiki) |
| `MOTH_API_KEY` | *(empty)* | API key for authentication (disabled when empty) |
| `MOTH_DATABASE_URL` | `sqlite:////data/moth.db` | Database connection string |
| `MOTH_LOG_LEVEL` | `INFO` | Logging level |
| `MOTH_TAUTULLI_URL` | *(empty)* | Tautulli base URL (e.g. `http://192.168.1.50:8181`) |
| `MOTH_TAUTULLI_API_KEY` | *(empty)* | Tautulli API key |
| `MOTH_TAUTULLI_ENABLED` | `false` | Enable Tautulli integration |

All settings can also be changed at runtime via the web UI under Settings.

## Tautulli Integration

When connected to Tautulli, Moth gains two capabilities:

**Watch-aware cleanup** — Create rules using the "Last Watched" date type. Instead of relying on filesystem timestamps (which Plex, Sonarr, and scrapers constantly touch), Moth checks when media was actually watched in Plex. "Delete media nobody has watched in 90 days" becomes meaningful.

**Season pickup suggestions** — Moth monitors per-user watch progress. When someone is 75%+ through a season and the next season isn't in your library, you get an Apprise notification to pick it up. Enable this in Settings > Season Pickup Suggestions.

**Path mapping** — If Plex and Moth see different mount paths for the same files (e.g. Plex uses `/data/TV Shows`, Moth uses `/media/tv`), configure a JSON path mapping in Settings:
```json
{"/data/TV Shows": "/media/tv", "/data/Movies": "/media/movies"}
```

## CLI Usage

```bash
moth rules list
moth rules add -d /media/movies -t 90 -e mkv,mp4
moth rules delete 1
moth scan dry-run
moth scan run
moth scan staged
moth scan rescue 5
moth settings get
moth settings set cron_expression "0 2 * * *"
moth notify test
```

Set `MOTH_HOST` to point the CLI at your instance (default: `http://localhost:6969`).

## Tech Stack

Python 3.12 / FastAPI / SQLite (SQLModel) / APScheduler / Apprise / HTMX + Jinja2 / Click / Docker

## License

AGPL-3.0

# Moth

Autonomous Media Lifecycle Manager

Moth is a self-hosted, Docker-deployed tool that monitors media directories, detects stale files based on configurable rules, and automatically cleans them up. Inspired by the reverse hanger method — if you haven't touched it in a while, it goes.

## Quick Start

1. Copy and edit the environment file:
   ```bash
   cp .env.example .env
   # Edit .env with your paths and preferences
   ```

2. Set your media directory in `docker-compose.yml`:
   ```yaml
   volumes:
     - /path/to/your/media:/media   # <-- change this to your media directory
   ```

3. Start the container:
   ```bash
   docker compose up -d
   ```

4. Open `http://localhost:6969`, configure rules, and acknowledge the first-run dry run before any live deletions occur.

## Features

- **Rule-based scanning** — per-directory rules with size, date, and extension filters
- **Safe deletion** — files are moved to a trash folder with a configurable grace period before permanent removal
- **Notifications** — pre-deletion warnings via Apprise (Telegram, Discord, email, ntfy, and 80+ other services)
- **First-run dry run** — mandatory review before any live deletions
- **Web GUI** — HTMX-powered interface for rule management and monitoring
- **CLI** — Click-based CLI backed by the same API
- **Scheduled scans** — configurable cron schedule via APScheduler
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
| `MOTH_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## CLI Usage

The CLI is a thin client that talks to the Moth API.

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

If API key auth is enabled, the CLI does not currently pass the key automatically — use `--host` or configure your requests accordingly.

## Tech Stack

Python 3.12 / FastAPI / SQLite (SQLModel) / APScheduler / Apprise / HTMX + Jinja2 / Click / Docker

## License

AGPL-3.0

# Moth
Autonomous Media Lifecycle Manager

Moth is a self-hosted, Docker-deployed tool that monitors media directories, detects stale files, and automatically cleans them up — inspired by the reverse hanger method.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your paths and preferences
docker compose up -d
```

Open `http://localhost:6969` to configure rules and acknowledge the first-run dry run.

## Features

- **Rule-based scanning** — per-directory rules with size, date, and extension filters
- **Safe deletion** — staging trash folder with configurable grace period
- **Notifications** — pre-deletion warnings via Apprise (Telegram, Discord, email, ntfy, 80+ services)
- **First-run dry run** — mandatory review before any live deletions
- **Web GUI** — HTMX-powered interface for rule management and monitoring
- **CLI** — full-featured Click-based CLI backed by the same API
- **Scheduled scans** — configurable cron via APScheduler

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MOTH_PORT` | `6969` | Host port mapping |
| `MOTH_TRASH_PATH` | `/path/to/trash` | Host path for staged deletions |
| `MOTH_CRON` | `0 3 * * *` | Scan schedule (cron) |
| `MOTH_NOTIFY_LEAD_HOURS` | `48` | Hours before deletion to notify |
| `MOTH_APPRISE_URLS` | *(empty)* | Comma-separated Apprise URLs |

## CLI Usage

```bash
moth rules list
moth rules add -d /media/movies -t 90 -e mkv,mp4
moth scan dry-run
moth scan run
moth settings get
moth notify test
```

Set `MOTH_HOST` to point the CLI at your Moth instance (default: `http://localhost:6969`).

## Tech Stack

Python 3.12 / FastAPI / SQLite (SQLModel) / APScheduler / Apprise / HTMX + Jinja2 / Click / Docker

## License

AGPL-3.0

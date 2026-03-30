#!/usr/bin/env python3
"""Moth CLI — thin client that calls the Moth API."""

import os
import sys
import json

import click
import httpx

BASE_URL = os.getenv("MOTH_HOST", "http://localhost:6969")


def api(method: str, path: str, **kwargs):
    """Make an API call and return the response."""
    url = f"{BASE_URL}{path}"
    try:
        resp = httpx.request(method, url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = str(e)
        click.echo(f"Error: {detail}", err=True)
        sys.exit(1)
    except httpx.ConnectError:
        click.echo(f"Error: Could not connect to Moth at {BASE_URL}", err=True)
        sys.exit(1)


@click.group()
@click.option("--host", envvar="MOTH_HOST", default="http://localhost:6969", help="Moth API base URL")
def cli(host):
    """Moth — Autonomous Media Lifecycle Manager"""
    global BASE_URL
    BASE_URL = host


# --- Rules ---

@cli.group()
def rules():
    """Manage monitored directory rules."""
    pass


@rules.command("list")
def rules_list():
    """List all rules."""
    data = api("GET", "/api/rules")
    if not data:
        click.echo("No rules configured.")
        return
    for r in data:
        status = "ON" if r["enabled"] else "OFF"
        exts = ", ".join(r.get("extensions", []))
        click.echo(
            f"[{r['id']}] {status}  {r['directory']}  "
            f"{r['date_type']}>{r['date_threshold_days']}d  "
            f"exts=[{exts}]"
        )


@rules.command("add")
@click.option("--directory", "-d", prompt="Directory path", help="Absolute path to monitor")
@click.option("--date-type", type=click.Choice(["last_accessed", "last_modified", "date_added", "last_watched"]), default="last_modified")
@click.option("--threshold", "-t", type=int, default=90, help="Days threshold")
@click.option("--extensions", "-e", default="mkv,mp4,avi", help="Comma-separated extensions")
@click.option("--size-min", type=float, default=None, help="Min file size in MB")
@click.option("--size-max", type=float, default=None, help="Max file size in MB")
def rules_add(directory, date_type, threshold, extensions, size_min, size_max):
    """Add a new rule."""
    payload = {
        "directory": directory,
        "date_type": date_type,
        "date_threshold_days": threshold,
        "extensions": [e.strip() for e in extensions.split(",") if e.strip()],
        "size_min_mb": size_min,
        "size_max_mb": size_max,
    }
    result = api("POST", "/api/rules", json=payload)
    click.echo(f"Rule created: ID {result['id']}")


@rules.command("delete")
@click.argument("rule_id", type=int)
def rules_delete(rule_id):
    """Delete a rule by ID."""
    api("DELETE", f"/api/rules/{rule_id}")
    click.echo(f"Rule {rule_id} deleted.")


@rules.command("toggle")
@click.argument("rule_id", type=int)
def rules_toggle(rule_id):
    """Toggle a rule on/off."""
    result = api("PATCH", f"/api/rules/{rule_id}/toggle")
    status = "enabled" if result["enabled"] else "disabled"
    click.echo(f"Rule {rule_id} {status}.")


# --- Scan ---

@cli.group()
def scan():
    """Scan operations."""
    pass


@scan.command("run")
def scan_run():
    """Trigger a live scan now."""
    result = api("POST", "/api/scan/run")
    click.echo(
        f"Scan complete: {result['files_matched']} matched, "
        f"{result['files_deleted']} deleted."
    )


@scan.command("dry-run")
def scan_dryrun():
    """Run a dry run and print results."""
    result = api("POST", "/api/scan/dry-run")
    click.echo(f"Dry run: {result['files_matched']} file(s) would be matched.")


@scan.command("staged")
def scan_staged():
    """List files currently staged for deletion."""
    data = api("GET", "/api/scan/staged")
    if not data:
        click.echo("No files staged.")
        return
    for sf in data:
        size_mb = sf["size_bytes"] / 1048576
        click.echo(
            f"[{sf['id']}] {sf['filename']}  "
            f"{size_mb:.1f}MB  delete_at={sf['delete_at']}"
        )


@scan.command("rescue")
@click.argument("staged_id", type=int)
def scan_rescue(staged_id):
    """Un-stage a file by ID."""
    result = api("DELETE", f"/api/scan/staged/{staged_id}")
    click.echo(f"Rescued: {result['rescued']}")


# --- Settings ---

@cli.group()
def settings():
    """Global settings."""
    pass


@settings.command("get")
def settings_get():
    """Print current settings."""
    data = api("GET", "/api/settings")
    for key in ["cron_expression", "notify_lead_hours", "apprise_urls",
                "first_run_complete", "trash_path", "trash_retention_days",
                "tautulli_url", "tautulli_enabled", "tautulli_api_key_set",
                "season_suggest_enabled", "season_suggest_threshold_pct",
                "season_suggest_users"]:
        click.echo(f"{key}: {data.get(key)}")


@settings.command("set")
@click.argument("key")
@click.argument("value")
def settings_set(key, value):
    """Update a settings value."""
    # Attempt to parse as int/bool
    if value.lower() in ("true", "false"):
        value = value.lower() == "true"
    else:
        try:
            value = int(value)
        except ValueError:
            pass
    api("PUT", "/api/settings", json={key: value})
    click.echo(f"Updated {key}.")


# --- Notify ---

@cli.group()
def notify():
    """Notification operations."""
    pass


@notify.command("test")
def notify_test():
    """Send a test notification."""
    result = api("POST", "/api/notify/test")
    click.echo(result["message"])


if __name__ == "__main__":
    cli()

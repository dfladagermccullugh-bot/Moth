import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class TautulliError(Exception):
    """Raised when a Tautulli API call fails."""


class TautulliClient:
    """Thin wrapper around Tautulli's REST API."""

    def __init__(self, url: str, api_key: str, timeout: float = DEFAULT_TIMEOUT):
        self.base = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, cmd: str, **params) -> dict:
        params["apikey"] = self.api_key
        params["cmd"] = cmd
        try:
            resp = httpx.get(
                f"{self.base}/api/v2",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise TautulliError(f"Tautulli API request failed: {e}") from e

        data = resp.json()
        response = data.get("response", {})
        if response.get("result") != "success":
            msg = response.get("message", "Unknown error")
            raise TautulliError(f"Tautulli API error: {msg}")
        return response.get("data", {})

    def test_connection(self) -> dict:
        return self._get("get_tautulli_info")

    def get_library_sections(self) -> list[dict]:
        return self._get("get_libraries")

    def get_library_media_info(self, section_id: str, length: int = 10000) -> list[dict]:
        data = self._get("get_library_media_info", section_id=section_id, length=str(length))
        return data.get("data", [])

    def get_history(
        self,
        rating_key: str | None = None,
        length: int = 1000,
        user: str | None = None,
        media_type: str | None = None,
    ) -> list[dict]:
        params: dict = {"length": str(length)}
        if rating_key:
            params["rating_key"] = rating_key
        if user:
            params["user"] = user
        if media_type:
            params["media_type"] = media_type
        data = self._get("get_history", **params)
        return data.get("data", [])

    def get_metadata(self, rating_key: str) -> dict:
        return self._get("get_metadata", rating_key=rating_key)

    def get_recently_added(self, count: int = 50, media_type: str | None = None) -> list[dict]:
        params: dict = {"count": str(count)}
        if media_type:
            params["media_type"] = media_type
        data = self._get("get_recently_added", **params)
        return data.get("recently_added", [])

    def get_users(self) -> list[dict]:
        return self._get("get_users")


def get_client_from_settings(settings) -> TautulliClient | None:
    """Create a TautulliClient from Settings model if Tautulli is enabled and configured."""
    if not settings or not settings.tautulli_enabled:
        return None
    if not settings.tautulli_url or not settings.tautulli_api_key:
        return None
    return TautulliClient(settings.tautulli_url, settings.tautulli_api_key)


def build_watch_date_cache(client: TautulliClient, path_mapping: dict[str, str] | None = None) -> dict[str, datetime]:
    """
    Build a mapping of {filepath: last_watched_datetime} across all libraries.

    path_mapping: optional dict mapping Plex path prefixes to Moth path prefixes,
                  e.g. {"/data/TV Shows": "/media/tv"}
    """
    cache: dict[str, datetime] = {}

    try:
        libraries = client.get_library_sections()
    except TautulliError as e:
        logger.error("Failed to fetch Tautulli libraries: %s", e)
        return cache

    for lib in libraries:
        section_id = str(lib.get("section_id", ""))
        if not section_id:
            continue

        try:
            media_items = client.get_library_media_info(section_id)
        except TautulliError as e:
            logger.warning("Failed to fetch library %s media info: %s", section_id, e)
            continue

        for item in media_items:
            rating_key = item.get("rating_key", "")
            if not rating_key:
                continue

            last_played = item.get("last_played")
            if not last_played:
                continue

            try:
                watched_dt = datetime.fromtimestamp(int(last_played))
            except (ValueError, TypeError, OSError):
                continue

            file_paths = _extract_file_paths(item)
            for fpath in file_paths:
                mapped = _apply_path_mapping(fpath, path_mapping)
                # Keep the most recent watch date per file
                if mapped not in cache or cache[mapped] < watched_dt:
                    cache[mapped] = watched_dt

    logger.info("Built Tautulli watch cache: %d files with watch history", len(cache))
    return cache


def _extract_file_paths(item: dict) -> list[str]:
    """Extract file paths from a Tautulli media info item."""
    paths = []
    # Direct file path
    if item.get("file"):
        paths.append(item["file"])
    # Some items have media_info with parts
    for media in item.get("media_info", []):
        for part in media.get("parts", []):
            if part.get("file"):
                paths.append(part["file"])
    return paths


def _apply_path_mapping(filepath: str, mapping: dict[str, str] | None) -> str:
    """Apply path prefix substitution. First matching prefix wins."""
    if not mapping:
        return filepath
    for plex_prefix, moth_prefix in mapping.items():
        if filepath.startswith(plex_prefix):
            return moth_prefix + filepath[len(plex_prefix):]
    return filepath

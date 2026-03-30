import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import init_db, get_session, Settings, Rule, StagedFile, ScanLog, SeasonSuggestion
from app.routes import rules, scan, settings, suggestions
from app.scheduler import start_scheduler
from app.tautulli import get_client_from_settings, build_watch_date_cache, TautulliError

# Configure structured logging
logging.basicConfig(
    level=os.getenv("MOTH_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("MOTH_API_KEY", "")


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Optional API key authentication. Skipped when MOTH_API_KEY is not set."""

    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)
        # Allow static assets without auth
        if request.url.path.startswith("/static"):
            return await call_next(request)
        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("/data", exist_ok=True)
    os.makedirs(os.getenv("MOTH_TRASH_PATH", "/moth/trash"), exist_ok=True)
    init_db()
    start_scheduler()
    logger.info("Moth started")
    yield
    logger.info("Moth shutting down")


app = FastAPI(title="Moth", version="1.0.0", lifespan=lifespan)
app.add_middleware(ApiKeyMiddleware)

app.include_router(rules.router)
app.include_router(scan.router)
app.include_router(settings.router)
app.include_router(suggestions.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def _check_first_run(session: Session) -> bool:
    s = session.get(Settings, 1)
    return s and s.first_run_complete


@app.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    if not _check_first_run(session):
        return RedirectResponse(url="/dryrun", status_code=302)
    rules_list = session.exec(select(Rule)).all()
    return templates.TemplateResponse(
        "rules.html", {"request": request, "rules": rules_list}
    )


@app.get("/dryrun")
def dryrun_page(request: Request, session: Session = Depends(get_session)):
    s = session.get(Settings, 1)
    return templates.TemplateResponse(
        "dryrun.html",
        {"request": request, "first_run_complete": s.first_run_complete if s else False},
    )


@app.post("/dryrun/acknowledge")
def acknowledge_dryrun(session: Session = Depends(get_session)):
    s = session.get(Settings, 1)
    if s:
        s.first_run_complete = True
        session.add(s)
        session.commit()
    return RedirectResponse(url="/", status_code=302)


@app.get("/staged")
def staged_page(request: Request, session: Session = Depends(get_session)):
    if not _check_first_run(session):
        return RedirectResponse(url="/dryrun", status_code=302)
    staged = session.exec(
        select(StagedFile).where(StagedFile.deleted == False)
    ).all()
    # Fetch watch dates from Tautulli if available
    s = session.get(Settings, 1)
    watch_info = {}
    if s and s.tautulli_enabled:
        client = get_client_from_settings(s)
        if client:
            path_mapping = None
            if s.tautulli_path_mapping:
                try:
                    path_mapping = json.loads(s.tautulli_path_mapping)
                except (json.JSONDecodeError, TypeError):
                    pass
            try:
                watch_info = build_watch_date_cache(client, path_mapping)
            except TautulliError:
                pass
    return templates.TemplateResponse(
        "staged.html", {"request": request, "staged_files": staged, "watch_info": watch_info}
    )


@app.get("/log")
def log_page(request: Request, session: Session = Depends(get_session)):
    if not _check_first_run(session):
        return RedirectResponse(url="/dryrun", status_code=302)
    logs = session.exec(
        select(ScanLog).order_by(ScanLog.started_at.desc()).limit(100)
    ).all()
    return templates.TemplateResponse(
        "log.html", {"request": request, "logs": logs}
    )


@app.get("/suggestions")
def suggestions_page(request: Request, session: Session = Depends(get_session)):
    if not _check_first_run(session):
        return RedirectResponse(url="/dryrun", status_code=302)
    s = session.get(Settings, 1)
    active_suggestions = session.exec(
        select(SeasonSuggestion).where(SeasonSuggestion.dismissed == False).order_by(SeasonSuggestion.suggested_at.desc())
    ).all()
    return templates.TemplateResponse(
        "suggestions.html",
        {"request": request, "suggestions": active_suggestions, "settings": s},
    )


@app.get("/settings")
def settings_page(request: Request, session: Session = Depends(get_session)):
    if not _check_first_run(session):
        return RedirectResponse(url="/dryrun", status_code=302)
    s = session.get(Settings, 1)
    return templates.TemplateResponse(
        "settings.html", {"request": request, "settings": s}
    )

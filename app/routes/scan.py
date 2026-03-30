from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.database import StagedFile, ScanLog, Settings, get_session
from app.scanner import run_scan

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.post("/dry-run")
def dry_run(session: Session = Depends(get_session)):
    log = run_scan(session, dry_run=True)
    return {
        "log": log,
        "note": "Dry run complete — no files were moved or deleted.",
        "files_matched": log.files_matched,
    }


@router.post("/run")
def manual_scan(session: Session = Depends(get_session)):
    settings = session.get(Settings, 1)
    if not settings or not settings.first_run_complete:
        raise HTTPException(
            status_code=403,
            detail="First-run dry run has not been acknowledged. Complete a dry run first.",
        )
    log = run_scan(session, dry_run=False)
    return log


@router.get("/staged")
def list_staged(session: Session = Depends(get_session)):
    return session.exec(
        select(StagedFile).where(StagedFile.deleted == False)
    ).all()


@router.delete("/staged/{staged_id}")
def rescue_file(staged_id: int, session: Session = Depends(get_session)):
    sf = session.get(StagedFile, staged_id)
    if not sf or sf.deleted:
        raise HTTPException(status_code=404, detail="Staged file not found")
    session.delete(sf)
    session.commit()
    return {"ok": True, "rescued": sf.filename}


@router.get("/log")
def scan_log(
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return session.exec(
        select(ScanLog).order_by(ScanLog.started_at.desc()).offset(offset).limit(limit)
    ).all()

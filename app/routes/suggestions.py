from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import SeasonSuggestion, get_session
from app.suggestions import check_season_pickups

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


@router.get("")
def list_suggestions(
    include_dismissed: bool = False,
    session: Session = Depends(get_session),
):
    query = select(SeasonSuggestion).order_by(SeasonSuggestion.suggested_at.desc())
    if not include_dismissed:
        query = query.where(SeasonSuggestion.dismissed == False)
    return session.exec(query).all()


@router.post("/{suggestion_id}/dismiss")
def dismiss_suggestion(suggestion_id: int, session: Session = Depends(get_session)):
    suggestion = session.get(SeasonSuggestion, suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    suggestion.dismissed = True
    session.add(suggestion)
    session.commit()
    return {"ok": True}


@router.post("/check")
def manual_check(session: Session = Depends(get_session)):
    new_suggestions = check_season_pickups(session)
    return {
        "new_suggestions": len(new_suggestions),
        "suggestions": new_suggestions,
    }

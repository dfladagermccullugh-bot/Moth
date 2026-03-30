from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel

from app.database import Rule, DateType, get_session

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleCreate(BaseModel):
    directory: str
    size_min_mb: float | None = None
    size_max_mb: float | None = None
    date_type: DateType = DateType.last_modified
    date_threshold_days: int = 90
    extensions: list[str] = []
    enabled: bool = True


class RuleUpdate(BaseModel):
    directory: str | None = None
    size_min_mb: float | None = None
    size_max_mb: float | None = None
    date_type: DateType | None = None
    date_threshold_days: int | None = None
    extensions: list[str] | None = None
    enabled: bool | None = None


@router.get("")
def list_rules(session: Session = Depends(get_session)):
    return session.exec(select(Rule)).all()


@router.post("", status_code=201)
def create_rule(rule: RuleCreate, session: Session = Depends(get_session)):
    db_rule = Rule(**rule.model_dump())
    session.add(db_rule)
    session.commit()
    session.refresh(db_rule)
    return db_rule


@router.put("/{rule_id}")
def update_rule(
    rule_id: int, rule: RuleUpdate, session: Session = Depends(get_session)
):
    db_rule = session.get(Rule, rule_id)
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    update_data = rule.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_rule, key, value)
    session.add(db_rule)
    session.commit()
    session.refresh(db_rule)
    return db_rule


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    db_rule = session.get(Rule, rule_id)
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    session.delete(db_rule)
    session.commit()
    return {"ok": True}


@router.patch("/{rule_id}/toggle")
def toggle_rule(rule_id: int, session: Session = Depends(get_session)):
    db_rule = session.get(Rule, rule_id)
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db_rule.enabled = not db_rule.enabled
    session.add(db_rule)
    session.commit()
    session.refresh(db_rule)
    return db_rule

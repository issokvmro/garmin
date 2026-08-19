from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.daily_score import DailyScore
from app.models.user import User
from app.services.score_pipeline import compute_and_store_score, recompute_range

router = APIRouter(prefix="/scores", tags=["Scores"])


def _serialize(score: DailyScore) -> dict:
    return {c.name: getattr(score, c.name) for c in score.__table__.columns}


@router.get("/today")
def get_today_score(db: Session = Depends(get_db)):
    return get_score_for_date(date.today().isoformat(), db)


@router.get("/{date_str}")
def get_score_for_date(date_str: str, db: Session = Depends(get_db)):
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")

    score = db.query(DailyScore).filter(DailyScore.date == target_date).first()
    if not score:
        # Compute on-demand if we have raw data for that day
        score = compute_and_store_score(db, target_date)
    if not score:
        raise HTTPException(404, f"No data available to score {date_str}")
    return _serialize(score)


@router.get("")
def get_score_range(
    start: str = Query(...),
    end: str = Query(...),
    db: Session = Depends(get_db),
):
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "start/end must be YYYY-MM-DD")

    scores = (
        db.query(DailyScore)
        .filter(DailyScore.date >= start_date, DailyScore.date <= end_date)
        .order_by(DailyScore.date.asc())
        .all()
    )
    return [_serialize(s) for s in scores]


@router.post("/recompute")
def recompute(
    days: int = Query(90, ge=1, le=365, description="How many days back to recompute"),
    db: Session = Depends(get_db),
):
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    count = recompute_range(db, start_date, end_date)
    return {"recomputed": count, "start": start_date.isoformat(), "end": end_date.isoformat()}


@router.get("/whoop-age/history")
def whoop_age_history(days: int = Query(180, ge=7, le=730), db: Session = Depends(get_db)):
    start_date = date.today() - timedelta(days=days)
    scores = (
        db.query(DailyScore)
        .filter(DailyScore.date >= start_date)
        .filter(DailyScore.whoop_age_years.isnot(None))
        .order_by(DailyScore.date.asc())
        .all()
    )
    if not scores:
        raise HTTPException(
            404,
            "No Whoop Age data yet — set your birth_date (and ideally sex/vo2_max) "
            "in your profile, then POST /api/scores/recompute.",
        )
    return [
        {
            "date": s.date.isoformat(),
            "whoop_age_years": s.whoop_age_years,
            "delta": s.whoop_age_delta,
            "inputs": s.whoop_age_inputs,
        }
        for s in scores
    ]

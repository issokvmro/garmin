from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.daily_summary import DailySummary
from app.models.daily_score import DailyScore

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("")
def get_dashboard_summary(date_str: str = None, db: Session = Depends(get_db)):
    from datetime import date
    query = db.query(DailySummary)
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
            summary = query.filter(DailySummary.date == target_date).first()
        except ValueError:
            summary = query.order_by(DailySummary.date.desc()).first()
    else:
        summary = query.order_by(DailySummary.date.desc()).first()

    if summary:
        result = {c.name: getattr(summary, c.name) for c in summary.__table__.columns}

        # Use the computed DailyScore if available — this is the single source of truth
        score = db.query(DailyScore).filter(
            DailyScore.date == summary.date,
            DailyScore.user_id == summary.user_id
        ).first()

        if score:
            result["recovery_score"] = score.recovery_score
            result["recovery_band"] = score.recovery_band
            result["strain_score"] = score.strain_score
            result["strain_band"] = score.strain_band
            result["strain_target_low"] = score.strain_target_low
            result["strain_target_high"] = score.strain_target_high
            result["sleep_performance"] = score.sleep_performance
            result["sleep_need_minutes"] = score.sleep_need_minutes
            result["sleep_debt_minutes"] = score.sleep_debt_minutes
            result["stress_score"] = score.stress_score
            result["stress_band"] = score.stress_band
            result["whoop_age_years"] = score.whoop_age_years
            result["whoop_age_delta"] = score.whoop_age_delta
            result["illness_risk_level"] = score.illness_risk_level
            result["illness_risk_flags"] = score.illness_risk_flags
            result["explanations"] = score.explanations
        else:
            # Fallback: compute on-the-fly if no stored score exists yet
            from app.services.score_pipeline import compute_and_store_score
            computed = compute_and_store_score(db, summary.date)
            if computed:
                result["recovery_score"] = computed.recovery_score
                result["strain_score"] = computed.strain_score
                result["sleep_performance"] = computed.sleep_performance
                result["stress_score"] = computed.stress_score
                result["whoop_age_years"] = computed.whoop_age_years
                result["explanations"] = computed.explanations

        return result
    return {"message": "No data available. Please sync with Garmin MCP."}

@router.get("/history")
def get_dashboard_history(limit: int = 30, date_str: str = None, include_details: bool = False, db: Session = Depends(get_db)):
    from datetime import date
    from app.models.daily_score import DailyScore

    target_date = date.today()
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            pass

    summaries = db.query(DailySummary).filter(
        DailySummary.date <= target_date
    ).order_by(DailySummary.date.desc()).limit(limit).all()

    if not summaries:
        return []

    # Fetch scores for the same dates in a single query
    dates = [s.date for s in summaries]
    scores = db.query(DailyScore).filter(
        DailyScore.date.in_(dates)
    ).all()
    score_map = {s.date: s for s in scores}

    results = []
    for s in summaries:
        s_dict = {c.name: getattr(s, c.name) for c in s.__table__.columns if include_details or c.name != 'details'}

        # Merge in computed scores from the single source of truth
        score = score_map.get(s.date)
        if score:
            s_dict['recovery_score'] = score.recovery_score
            s_dict['recovery_band'] = score.recovery_band
            s_dict['strain_score'] = score.strain_score
            s_dict['strain_band'] = score.strain_band
            s_dict['sleep_performance'] = score.sleep_performance
            s_dict['stress_score'] = score.stress_score
            s_dict['whoop_age_years'] = score.whoop_age_years
            s_dict['explanations'] = score.explanations

        results.append(s_dict)

    results.reverse()
    return results

@router.get("/sync")
async def force_sync(db: Session = Depends(get_db)):
    from app.services.sync_service import run_sync
    await run_sync()
    return {"status": "success", "message": "Live sync completed"}

@router.get("/hr")
async def get_hr_data(date_str: str = None):
    from datetime import date
    from app.config import settings
    
    target_date = date.today()
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            pass

    if settings.GARMIN_PROVIDER == "mcp":
        from app.services.garmin_mcp import MCPGarminProvider
        provider = MCPGarminProvider()
        try:
            await provider.connect()
            data = await provider.get_heart_rates(target_date)
            return data
        except Exception:
            return {}
        finally:
            await provider.disconnect()
    return {}

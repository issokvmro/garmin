from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.daily_summary import DailySummary

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
        import math
        
        # Calculate Recovery
        recovery = summary.recovery_score
        if recovery is None:
            recovery = summary.body_battery_highest or 0
            
        # Calculate Strain
        cals = summary.calories_burned
        if not cals:
            # Sum up calories from activities for this day
            from app.models.activity import Activity
            acts = db.query(Activity).filter(
                Activity.user_id == summary.user_id,
                Activity.start_time >= (date.fromisoformat(date_str) if date_str else date.today()),
            ).all()
            day_acts = [a for a in acts if a.start_time and a.start_time.date() == summary.date]
        else:
            day_acts = []
        bb_current = summary.body_battery_current
        bb_highest = summary.body_battery_highest
        recovery = bb_current if bb_current is not None else (bb_highest if bb_highest is not None else (summary.sleep_score or 0))
        
        cals = summary.calories_burned or 0
        active_cals = max(0, cals - 1800)
        strain_from_activities = 0.0
        if active_cals > 0:
            strain_from_activities = min(21.0, 4.0 + (math.log(active_cals + 1) * 2.2))
            
        avg_stress = 0
        if summary.details and 'stress' in summary.details and isinstance(summary.details['stress'], dict):
            avg_stress = summary.details['stress'].get('avgStressLevel', 0)
        
        strain_from_stress = min(21.0, (avg_stress / 100.0) * 16.0)
        
        strain = 21.0 * (1.0 - (1.0 - strain_from_stress / 21.0) * (1.0 - strain_from_activities / 21.0))
        
        result = {c.name: getattr(summary, c.name) for c in summary.__table__.columns}
        
        # Estimate Fitness Age
        base_age = 22.0
        rhr = summary.resting_heart_rate or 60
        rhr_factor = (rhr - 60) * 0.5
        strain_factor = strain * 0.2
        recovery_factor = (100 - (recovery or 50)) * 0.05
        sleep_factor = (100 - (summary.sleep_score or 50)) * 0.05
        fitness_age = base_age + rhr_factor - strain_factor + recovery_factor + sleep_factor
        fitness_age = max(18.0, min(float(fitness_age), 80.0))
        
        result["strain_score"] = round(strain, 1)
        result["recovery_score"] = int(recovery)
        result["calories_burned"] = cals
        result["fitness_age"] = int(round(fitness_age))
        return result
    return {"message": "No data available. Please sync with Garmin MCP."}

@router.get("/history")
def get_dashboard_history(limit: int = 30, date_str: str = None, include_details: bool = False, db: Session = Depends(get_db)):
    from datetime import date
    import math
    from app.models.activity import Activity
    
    target_date = date.today()
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            pass
            
    summaries = db.query(DailySummary).filter(
        DailySummary.date <= target_date
    ).order_by(DailySummary.date.desc()).limit(limit).all()
    
    if summaries:
        min_date = summaries[-1].date
        acts = db.query(Activity).filter(
            Activity.user_id == summaries[0].user_id,
        ).all()
    else:
        acts = []
    
    results = []
    for s in summaries:
        s_dict = {c.name: getattr(s, c.name) for c in s.__table__.columns if include_details or c.name != 'details'}
        
        # Recovery
        bb_current = s_dict.get('body_battery_current')
        bb_highest = s_dict.get('body_battery_highest')
        recovery = bb_current if bb_current is not None else (bb_highest if bb_highest is not None else s_dict.get('sleep_score', 0))
        s_dict['recovery_score'] = recovery
        
        # Strain
        cals = s_dict.get('calories_burned') or 0
        active_cals = max(0, cals - 1800)
        strain_from_activities = 0.0
        if active_cals > 0:
            strain_from_activities = min(21.0, 4.0 + (math.log(active_cals + 1) * 2.2))
            
        avg_stress = 0
        details = s_dict.get('details')
        if details and isinstance(details, dict) and 'stress' in details and isinstance(details['stress'], dict):
            avg_stress = details['stress'].get('avgStressLevel', 0)
            
        strain_from_stress = min(21.0, (avg_stress / 100.0) * 16.0)
        strain = 21.0 * (1.0 - (1.0 - strain_from_stress / 21.0) * (1.0 - strain_from_activities / 21.0))
        
        s_dict['strain_score'] = round(strain, 1)
        
        # Estimate Fitness Age
        base_age = 22.0
        rhr = s_dict.get('resting_heart_rate') or 60
        rhr_factor = (rhr - 60) * 0.5
        strain_factor = strain * 0.2
        recovery_factor = (100 - (s_dict.get('recovery_score') or 50)) * 0.05
        sleep_factor = (100 - (s_dict.get('sleep_score') or 50)) * 0.05
        fitness_age = base_age + rhr_factor - strain_factor + recovery_factor + sleep_factor
        s_dict['fitness_age'] = int(round(max(18.0, min(float(fitness_age), 80.0))))
            
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

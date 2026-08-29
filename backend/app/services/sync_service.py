import asyncio
import logging
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.daily_summary import DailySummary
from app.models.activity import Activity
from app.models.user import User
from app.config import settings

logger = logging.getLogger(__name__)

async def run_sync():
    """
    Background job to sync Garmin data via the configured provider.
    """
    logger.info("Starting Garmin sync job")

    from app.api.activities_api import get_garmin_client
    client = get_garmin_client()

    try:
        db: Session = SessionLocal()
        
        # Ensure a default user exists for personal dashboard
        user = db.query(User).first()
        if not user:
            user = User(name="Local User", garmin_id="local")
            db.add(user)
            db.commit()
            db.refresh(user)
            
        # 1. Sync Daily Summary for today and yesterday
        dates_to_sync = [date.today(), date.today() - timedelta(days=1)]
        for sync_date in dates_to_sync:
            try:
                date_str = sync_date.isoformat()
                
                # Fetch detailed payload just like the historical sync
                bb = client.get_body_battery(date_str)
                hr = client.get_heart_rates(date_str)
                sleep = client.get_sleep_data(date_str)
                stress = client.get_stress_data(date_str)
                try:
                    hrv = client.get_hrv_data(date_str)
                except Exception:
                    hrv = None
                
                details = {
                    "body_battery": bb,
                    "heart_rate": hr,
                    "sleep": sleep,
                    "stress": stress,
                    "hrv": hrv
                }
                
                existing = db.query(DailySummary).filter(
                    DailySummary.user_id == user.id,
                    DailySummary.date == sync_date
                ).first()
                
                if not existing:
                    existing = DailySummary(user_id=user.id, date=sync_date)
                    db.add(existing)
                    
                existing.details = details
                
                if hr and isinstance(hr, dict):
                    existing.resting_heart_rate = hr.get("restingHeartRate")
                
                if sleep and isinstance(sleep, dict):
                    dailySleep = sleep.get("dailySleepDTO", {})
                    score = dailySleep.get("sleepScores", {}).get("overall", {}).get("value")
                    if score is not None:
                        existing.sleep_score = score
                    existing.sleep_duration = dailySleep.get("sleepTimeSeconds")
                    existing.deep_sleep = dailySleep.get("deepSleepSeconds")
                    existing.rem_sleep = dailySleep.get("remSleepSeconds")
                    existing.light_sleep = dailySleep.get("lightSleepSeconds")
                    existing.awake_time = dailySleep.get("awakeSleepSeconds")
                
                if bb and isinstance(bb, list) and len(bb) > 0:
                    values = bb[0].get("bodyBatteryValuesArray", [])
                    bb_values = [v[1] for v in values if isinstance(v, list) and len(v) == 2 and v[1] is not None]
                    if bb_values:
                        existing.body_battery_highest = max(bb_values)
                        existing.body_battery_lowest = min(bb_values)
                        existing.body_battery_current = bb_values[-1]
                        
                if hrv and isinstance(hrv, dict):
                    # Garmin's get_hrv_data returns hrvSummary -> lastNightAvg
                    hrv_summary = hrv.get("hrvSummary", {})
                    last_night = hrv_summary.get("lastNightAvg")
                    if last_night is not None:
                        existing.current_hrv = last_night
                        
                db.commit()
            except Exception as e:
                logger.error(f"Failed daily summary sync for {sync_date}: {e}")

                
        # 2. Sync Activities for the last 7 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        try:
            activities_data = client.get_activities(0, 10) # last 10 activities
            
            for act_data in activities_data:
                garmin_id = str(act_data.get('activityId'))
                existing_act = db.query(Activity).filter(Activity.garmin_activity_id == garmin_id).first()
                if not existing_act:
                    new_act = Activity(
                        user_id=user.id,
                        garmin_activity_id=garmin_id,
                        name=act_data.get('activityName'),
                        activity_type=act_data.get('activityType', {}).get('typeKey'),
                        start_time=datetime.fromisoformat(act_data.get('startTimeLocal')) if act_data.get('startTimeLocal') else None,
                        distance=act_data.get('distance'),
                        duration=act_data.get('duration'),
                        calories=act_data.get('calories'),
                        average_heart_rate=act_data.get('averageHR'),
                        max_heart_rate=act_data.get('maxHR'),
                        details=act_data
                    )
                    db.add(new_act)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to sync activities: {e}")

        # 3. Recompute Whoop-style scores (Recovery/Strain/Sleep/Stress/Whoop Age)
        # now that fresh raw data has landed for today/yesterday.
        try:
            from app.services.score_pipeline import compute_and_store_score
            for sync_date in dates_to_sync:
                compute_and_store_score(db, sync_date)
        except Exception as e:
            logger.error(f"Failed to compute scores after sync: {e}")

        db.close()
        
        logger.info("Garmin sync job completed successfully")
    except Exception as e:
        logger.error(f"Error during Garmin sync: {e}")


async def run_historical_sync(start_date: date, end_date: date):
    """
    Background job to sync Garmin data historically.
    """
    logger.info(f"Starting Garmin historical sync from {start_date} to {end_date}")
    if settings.GARMIN_PROVIDER == "mcp":
        from .garmin_mcp import MCPGarminProvider
        provider = MCPGarminProvider()
    else:
        logger.error(f"Unknown provider: {settings.GARMIN_PROVIDER}")
        return

    try:
        await provider.connect()
        db: Session = SessionLocal()
        user = db.query(User).first()
        if not user:
            user = User(name="Local User", garmin_id="local")
            db.add(user)
            db.commit()
            db.refresh(user)
            
        current_date = start_date
        while current_date <= end_date:
            logger.info(f"Syncing daily summary for {current_date}")
            summary_data = await provider.get_daily_summary(current_date)
            if summary_data:
                existing = db.query(DailySummary).filter(
                    DailySummary.user_id == user.id,
                    DailySummary.date == current_date
                ).first()
                if not existing:
                    existing = DailySummary(user_id=user.id, date=current_date)
                    db.add(existing)
                
                existing.recovery_score = summary_data.get('recovery_score', existing.recovery_score)
                existing.sleep_score = summary_data.get('sleep_score', existing.sleep_score)
                existing.body_battery_highest = summary_data.get('body_battery_highest', existing.body_battery_highest)
                existing.resting_heart_rate = summary_data.get('resting_heart_rate', existing.resting_heart_rate)
                existing.current_hrv = summary_data.get('current_hrv', existing.current_hrv)
                existing.calories_burned = summary_data.get('calories_burned', existing.calories_burned)
                db.commit()
            current_date += timedelta(days=1)
            
        logger.info(f"Syncing activities from {start_date} to {end_date}")
        activities_data = await provider.get_activities(
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time())
        )
        for act_data in activities_data:
            garmin_id = str(act_data.get('id'))
            existing_act = db.query(Activity).filter(Activity.garmin_activity_id == garmin_id).first()
            if not existing_act:
                new_act = Activity(
                    user_id=user.id,
                    garmin_activity_id=garmin_id,
                    name=act_data.get('name'),
                    activity_type=act_data.get('type'),
                    start_time=datetime.fromisoformat(act_data.get('start_time')) if act_data.get('start_time') else None,
                    distance=act_data.get('distance_meters'),
                    duration=act_data.get('duration_seconds'),
                    calories=act_data.get('calories'),
                    average_heart_rate=act_data.get('avg_hr_bpm'),
                    max_heart_rate=act_data.get('max_hr_bpm'),
                    details=act_data
                )
                db.add(new_act)
        db.commit()

        # Backfill scores across the whole synced range now that raw data exists.
        try:
            from app.services.score_pipeline import recompute_range
            recompute_range(db, start_date, end_date)
        except Exception as e:
            logger.error(f"Failed to backfill scores after historical sync: {e}")

        db.close()
        logger.info("Garmin historical sync job completed successfully")
    except Exception as e:
        logger.error(f"Error during Garmin historical sync: {e}")
    finally:
        await provider.disconnect()

def start_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    # Run sync every hour
    scheduler.add_job(run_sync, 'interval', hours=1, next_run_time=datetime.now())
    scheduler.start()
    return scheduler

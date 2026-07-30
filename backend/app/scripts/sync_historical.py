import asyncio
import sys
import logging
import os
from datetime import date, timedelta
from sqlalchemy.orm import Session

sys.path.append("/Users/dharanedharran/Documents/garmin app/backend")

from app.database import SessionLocal
from app.models.daily_summary import DailySummary
from app.models.user import User
from app.api.activities import get_garmin_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill():
    client = get_garmin_client()
    db: Session = SessionLocal()
    
    user = db.query(User).first()
    if not user:
        user = User(name="Local User", garmin_id="local")
        db.add(user)
        db.commit()
        db.refresh(user)
        
    start_date = date(2026, 2, 1)
    end_date = date.today()
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.isoformat()
        logger.info(f"Syncing detailed data for {date_str}...")
        
        try:
            bb = client.get_body_battery(date_str)
            hr = client.get_heart_rates(date_str)
            sleep = client.get_sleep_data(date_str)
            stress = client.get_stress_data(date_str)
            
            details = {
                "body_battery": bb,
                "heart_rate": hr,
                "sleep": sleep,
                "stress": stress
            }
            
            existing = db.query(DailySummary).filter(
                DailySummary.user_id == user.id,
                DailySummary.date == current_date
            ).first()
            
            if not existing:
                existing = DailySummary(user_id=user.id, date=current_date)
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
            
            db.commit()
            
        except Exception as e:
            logger.error(f"Failed to sync {date_str}: {e}")
            
        current_date += timedelta(days=1)
        
    db.close()
    logger.info("Done!")

if __name__ == "__main__":
    asyncio.run(backfill())

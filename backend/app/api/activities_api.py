from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.activity import Activity
from app.config import settings
import os
import logging
import json
import base64
import zipfile
import io
from garminconnect import Garmin

router = APIRouter(prefix="/activities", tags=["Activities"])

# Global cache to prevent re-login on every request if using garminconnect directly
garmin_client = None

def get_garmin_client():
    global garmin_client
    if garmin_client is None:
        token_dir = os.path.expanduser("~/.garminconnect")
        
        if settings.GARMIN_TOKENS_BASE64 and not os.path.exists(token_dir):
            try:
                os.makedirs(token_dir, exist_ok=True)
                zip_data = base64.b64decode(settings.GARMIN_TOKENS_BASE64)
                with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
                    # Extract to token_dir. The zip should contain just the files, or a folder.
                    # Usually it's just the files.
                    zip_ref.extractall(token_dir)
                logging.info("Restored Garmin tokens from base64 environment variable.")
            except Exception as e:
                logging.error(f"Failed to restore Garmin tokens from base64: {e}")
                
        # Always instantiate with credentials so it can perform an initial login
        # if the token cache is empty or expired.
        garmin_client = Garmin(settings.GARMIN_EMAIL, settings.GARMIN_PASSWORD)
        
        try:
            os.makedirs(token_dir, exist_ok=True)
            garmin_client.login(tokenstore=token_dir)
        except Exception as e:
            logging.error(f"Failed to login to garminconnect: {e}")
            raise HTTPException(status_code=500, detail="Failed to authenticate with Garmin")
            
    return garmin_client

@router.get("")
def list_activities(limit: int = 10, date_str: str = None, db: Session = Depends(get_db)):
    from datetime import date, datetime
    target_date = date.today()
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            pass
            
    end_time = datetime.combine(target_date, datetime.max.time())
    activities = db.query(Activity).filter(Activity.start_time <= end_time).order_by(Activity.start_time.desc()).limit(limit).all()
    return activities

@router.get("/{activity_id}/comprehensive")
def get_comprehensive_activity(activity_id: str, db: Session = Depends(get_db)):
    """
    Fetches raw, detailed information bypassing the database to get
    the absolute maximum amount of data Garmin provides for a single activity.
    """
    client = get_garmin_client()
    
    try:
        # 1. Get the base activity summary
        summary = client.get_activity(activity_id)
        
        # 2. Get the time-series details (Charts and Polylines)
        details = client.get_activity_details(activity_id)
        
        # 3. Get splits (Laps)
        splits = client.get_activity_splits(activity_id)
        
        # 4. Get heart rate time zones
        hr_zones = client.get_activity_hr_in_timezones(activity_id)
        
        # 5. Get power zones
        try:
            power_zones = client.get_activity_power_in_timezones(activity_id)
        except Exception:
            power_zones = None
            
        # 6. Get gear
        try:
            gear = client.get_activity_gear(activity_id)
        except Exception:
            gear = None
        
        return {
            "summary": summary,
            "details": details,
            "splits": splits,
            "hr_zones": hr_zones,
            "power_zones": power_zones,
            "gear": gear
        }
    except Exception as e:
        logging.error(f"Failed to fetch comprehensive activity {activity_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch comprehensive details: {str(e)}")

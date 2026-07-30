import asyncio
from app.services.sync_service import get_garmin_client
import datetime
import json

async def main():
    client = await get_garmin_client()
    today = datetime.date.today()
    hrv = await asyncio.to_thread(client.get_hrv_data, today.isoformat())
    print("HRV Keys:", list(hrv.keys()))
    if 'hrvSummary' in hrv:
        print("HRV Summary:", hrv['hrvSummary'])
    
    summary = await asyncio.to_thread(client.get_daily_summary, today.isoformat())
    print("Keys in daily summary:", list(summary.keys()))
    if 'lastSevenDaysHrvBaseline' in summary:
        print("lastSevenDaysHrvBaseline:", summary['lastSevenDaysHrvBaseline'])
    
if __name__ == "__main__":
    asyncio.run(main())

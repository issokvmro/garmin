import asyncio
import sys
from datetime import date, timedelta
sys.path.append("/Users/dharanedharran/Documents/garmin app/backend")

async def main():
    from app.api.activities import get_garmin_client
    client = get_garmin_client()
    target = (date.today() - timedelta(days=1)).isoformat()
    summary = await asyncio.to_thread(client.get_daily_summary, target)
    print("Keys in daily summary:", list(summary.keys()))
    print("Stress-related keys:")
    for k, v in summary.items():
        if 'stress' in k.lower():
            print(f"  {k}: {v}")

if __name__ == "__main__":
    asyncio.run(main())

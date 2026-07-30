import asyncio
import sys
from datetime import date, timedelta
sys.path.append("/Users/dharanedharran/Documents/garmin app/backend")

async def main():
    from app.api.activities import get_garmin_client
    client = get_garmin_client()
    target = (date.today() - timedelta(days=1)).isoformat()
    sleep = await asyncio.to_thread(client.get_sleep_data, target)
    if 'sleepLevels' in sleep and sleep['sleepLevels']:
        print("First sleepLevel:", sleep['sleepLevels'][0])

if __name__ == "__main__":
    asyncio.run(main())

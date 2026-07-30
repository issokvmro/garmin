import asyncio
from app.services.sync_service import get_garmin_client
import datetime
import json

async def main():
    client = await get_garmin_client()
    today = datetime.date.today() - datetime.timedelta(days=1)
    sleep = await asyncio.to_thread(client.get_sleep_data, today.isoformat())
    print("Keys in sleep data:", list(sleep.keys()))
    if 'dailySleepDTO' in sleep:
        print("Keys in dailySleepDTO:", list(sleep['dailySleepDTO'].keys()))
        if 'sleepLevels' in sleep['dailySleepDTO']:
            print("sleepLevels inside dailySleepDTO")
    if 'sleepLevels' in sleep:
        print("sleepLevels at root")
    
if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import sys
from datetime import date, timedelta
sys.path.append("/Users/dharanedharran/Documents/garmin app/backend")

async def main():
    try:
        from app.api.activities import get_garmin_client
        client = get_garmin_client()
        
        target = (date.today() - timedelta(days=1)).isoformat()
        sleep = await asyncio.to_thread(client.get_sleep_data, target)
        
        print("SLEEP type:", type(sleep))
        if isinstance(sleep, dict):
            print("SLEEP keys:", sleep.keys())
            if 'dailySleepDTO' in sleep:
                print("dailySleepDTO keys:", sleep['dailySleepDTO'].keys())
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())

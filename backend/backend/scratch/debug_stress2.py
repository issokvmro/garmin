import asyncio
import sys
from datetime import date, timedelta
sys.path.append("/Users/dharanedharran/Documents/garmin app/backend")

async def main():
    from app.api.activities import get_garmin_client
    client = get_garmin_client()
    target = (date.today() - timedelta(days=1)).isoformat()
    stress = await asyncio.to_thread(client.get_stress_data, target)
    print("avgStressLevel:", stress.get('avgStressLevel'))

if __name__ == "__main__":
    asyncio.run(main())

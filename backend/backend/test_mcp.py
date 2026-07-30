import asyncio
import os
import sys
from datetime import date, datetime, timedelta

# Mock settings just for this test
class Settings:
    MCP_TRANSPORT = "stdio"
    MCP_COMMAND = "uvx"
    MCP_ARGS = "--python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp"
    GARMIN_EMAIL = None
    GARMIN_PASSWORD = None

import app.config
app.config.settings = Settings()

from app.services.garmin_mcp import MCPGarminProvider

async def main():
    print("Initializing Garmin MCP Provider...")
    provider = MCPGarminProvider()
    
    try:
        await provider.connect()
        print("Connected!")
        
        print(f"\n--- Testing get_daily_summary for {date.today()} ---")
        summary = await provider.get_daily_summary(date.today())
        print(f"Summary result: {summary}")
        
        print("\n--- Testing get_activities for last 7 days ---")
        end = datetime.now()
        start = end - timedelta(days=7)
        activities = await provider.get_activities(start, end)
        print(f"Activities found: {len(activities)}")
        if activities:
            print(f"First activity: {activities[0].get('activityName')}")
            
    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        await provider.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
import sys

# Override config for local testing
import app.config
app.config.settings.DATABASE_URL = "postgresql://postgres:password@localhost:5432/garmin_db"
app.config.settings.MCP_COMMAND = "uvx"
app.config.settings.MCP_ARGS = "--python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp"
app.config.settings.GARMIN_PROVIDER = "mcp"

# Important: We need to use the token path explicitly for local test if different
# Actually, uvx garmin-mcp will use ~/.garminconnect automatically!

from app.services.sync_service import run_sync
import logging

logging.basicConfig(level=logging.INFO)

async def test():
    print("Testing run_sync locally against localhost postgres...")
    try:
        await run_sync()
        print("Test completed.")
    except Exception as e:
        print(f"Exception during run_sync: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())

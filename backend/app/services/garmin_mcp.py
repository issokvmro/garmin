import os
import asyncio
from typing import List, Dict, Any, Optional
from datetime import date, datetime

# Using the official MCP SDK
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

from .garmin_provider import GarminDataProvider
from app.config import settings

class MCPGarminProvider(GarminDataProvider):
    def __init__(self):
        self.transport_type = settings.MCP_TRANSPORT # 'stdio' or 'sse'
        self.session: Optional[ClientSession] = None
        self._exit_stack = None

    async def connect(self):
        from contextlib import AsyncExitStack
        self._exit_stack = AsyncExitStack()
        
        if self.transport_type == "stdio":
            env = os.environ.copy()
            if settings.GARMIN_EMAIL:
                env["GARMIN_EMAIL"] = settings.GARMIN_EMAIL
            if settings.GARMIN_PASSWORD:
                env["GARMIN_PASSWORD"] = settings.GARMIN_PASSWORD
                
            server_params = StdioServerParameters(
                command=settings.MCP_COMMAND,
                args=settings.MCP_ARGS.split(),
                env=env
            )
            read_stream, write_stream = await self._exit_stack.enter_async_context(stdio_client(server_params))
        elif self.transport_type == "sse":
            # Assuming MCP_ARGS contains the URL for SSE
            url = settings.MCP_ARGS if settings.MCP_ARGS.startswith("http") else "http://localhost:8000/sse"
            read_stream, write_stream = await self._exit_stack.enter_async_context(sse_client(url))
        else:
            raise ValueError(f"Unknown MCP transport: {self.transport_type}")

        self.session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()

    async def disconnect(self):
        if self._exit_stack:
            await self._exit_stack.aclose()
            self.session = None

    async def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
            
        import json
        summary = {}
        
        # 1. Get daily stats
        stats_result = await self.session.call_tool("get_stats", {"date": target_date.isoformat()})
        if not stats_result.isError and stats_result.content:
            try:
                stats = json.loads(stats_result.content[0].text)
                summary['body_battery_highest'] = stats.get('body_battery_highest', 0)
                summary['body_battery_lowest'] = stats.get('body_battery_lowest', 0)
                summary['body_battery_current'] = stats.get('body_battery_current', 0)
                summary['resting_heart_rate'] = stats.get('resting_heart_rate_bpm', 0)
                summary['calories_burned'] = stats.get('total_calories', 0)
            except Exception:
                pass
            
        # 2. Get sleep data
        sleep_result = await self.session.call_tool("get_sleep_data", {"date": target_date.isoformat()})
        if not sleep_result.isError and sleep_result.content:
            try:
                sleep = json.loads(sleep_result.content[0].text)
                dto = sleep.get('dailySleepDTO', {})
                summary['sleep_score'] = dto.get('sleepScores', {}).get('overall', {}).get('value', 0)
                summary['sleep_duration'] = dto.get('sleepTimeSeconds', 0)
                summary['deep_sleep'] = dto.get('deepSleepSeconds', 0)
                summary['rem_sleep'] = dto.get('remSleepSeconds', 0)
                summary['light_sleep'] = dto.get('lightSleepSeconds', 0)
                summary['awake_time'] = dto.get('awakeSleepSeconds', 0)
            except Exception:
                pass
            
        # 3. Get HRV
        hrv_result = await self.session.call_tool("get_hrv_data", {"date": target_date.isoformat()})
        if not hrv_result.isError and hrv_result.content:
            try:
                hrv = json.loads(hrv_result.content[0].text)
                summary['current_hrv'] = hrv.get('last_night_avg_hrv_ms', 0)
            except Exception:
                pass
            
        # 4. Get Training Readiness (mapped to recovery score roughly)
        readiness_result = await self.session.call_tool("get_training_readiness", {"date": target_date.isoformat()})
        if not readiness_result.isError and readiness_result.content:
            try:
                readiness = json.loads(readiness_result.content[0].text)
                if isinstance(readiness, list) and len(readiness) > 0:
                    summary['recovery_score'] = readiness[0].get('score', 0)
                elif isinstance(readiness, dict):
                    summary['recovery_score'] = readiness.get('score', 0)
            except Exception:
                pass

        return summary if summary else None

    async def get_activities(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
            
        result = await self.session.call_tool("get_activities", {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        })
        if result.isError:
            return []
            
        import json
        if result.content and len(result.content) > 0:
            try:
                data = json.loads(result.content[0].text)
                return data.get('activities', []) if isinstance(data, dict) else []
            except Exception:
                return []
        return []

    async def get_heart_rates(self, target_date: date) -> Dict[str, Any]:
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
            
        result = await self.session.call_tool("get_heart_rates", {"date": target_date.isoformat()})
        if result.isError:
            return {}
            
        import json
        if result.content and len(result.content) > 0:
            try:
                return json.loads(result.content[0].text)
            except Exception:
                return {}
        return {}

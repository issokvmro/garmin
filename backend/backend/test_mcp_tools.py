import asyncio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
import os

async def main():
    env = os.environ.copy()
    server_params = StdioServerParameters(
        command="uvx",
        args="--python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp".split(),
        env=env
    )
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")

asyncio.run(main())

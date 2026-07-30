from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:password@db:5432/garmin_db"
    GARMIN_PROVIDER: str = "mcp"
    MCP_TRANSPORT: str = "stdio"
    MCP_COMMAND: str = "uvx"
    MCP_ARGS: str = "--python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp"
    
    GARMIN_EMAIL: Optional[str] = None
    GARMIN_PASSWORD: Optional[str] = None
    GARMIN_TOKENS_BASE64: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"

settings = Settings()

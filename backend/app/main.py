from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.api import dashboard_router, activities_router, chat_router, scores_router, profile_router
from app.database import engine, Base
from app.models import *
from app.auth import verify_api_key
from fastapi import Depends
from app.services.sync_service import start_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables and start the background scheduler
    Base.metadata.create_all(bind=engine)
    scheduler = start_scheduler()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(title="Garmin Dashboard API", lifespan=lifespan)

# Configure CORS — restrict to known origins in production
allowed_origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()] if hasattr(settings, 'ALLOWED_ORIGINS') and settings.ALLOWED_ORIGINS else []

if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Fallback for local dev — restrict to localhost origins only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(dashboard_router, prefix="/api", dependencies=[Depends(verify_api_key)])
app.include_router(activities_router, prefix="/api", dependencies=[Depends(verify_api_key)])
app.include_router(chat_router, prefix="/api", dependencies=[Depends(verify_api_key)])
app.include_router(scores_router, prefix="/api", dependencies=[Depends(verify_api_key)])
app.include_router(profile_router, prefix="/api", dependencies=[Depends(verify_api_key)])

@app.get("/")
def read_root():
    return {"message": "Garmin Dashboard API is running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

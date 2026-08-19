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

# Create tables
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the background scheduler
    scheduler = start_scheduler()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(title="Garmin Dashboard API", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to frontend URL
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

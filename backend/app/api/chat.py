from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.ai_service import ai_service
from app.models.user import User

router = APIRouter(prefix="/chat", tags=["AI Chat"])

@router.get("/insight")
async def get_insight(focus: str = None, date_str: str = None, db: Session = Depends(get_db)):
    # Fetch local user
    user = db.query(User).first()
    if not user:
        return {"insight": "Please wait for your first Garmin sync."}
        
    insight = await ai_service.generate_insight(db, user.id, focus, date_str)
    return {"insight": insight}

from pydantic import BaseModel
from typing import Optional
class ChatMessage(BaseModel):
    message: str
    focus: Optional[str] = None

@router.post("")
async def chat_with_ai(chat_req: ChatMessage, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        return {"reply": "Please wait for your first Garmin sync."}
        
    reply = await ai_service.chat(db, user.id, chat_req.message, chat_req.focus)
    return {"reply": reply}

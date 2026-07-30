from typing import List, Dict, Any
import logging
import time
from sqlalchemy.orm import Session
from app.models.daily_summary import DailySummary
from app.models.activity import Activity
from app.config import settings

logger = logging.getLogger(__name__)

_insight_cache = {}

class AIService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_MODEL
        self.enabled = bool(self.api_key)
        
        if self.enabled:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    async def generate_insight(self, db: Session, user_id: int, focus: str = None, date_str: str = None) -> str:
        if not self.enabled:
            return "AI Insights are disabled. Please configure GEMINI_API_KEY."
            
        cache_key = f"{user_id}_{focus}_{date_str or 'today'}"
        cached = _insight_cache.get(cache_key)
        # Cache for 1 hour to prevent burning requests on page refreshes
        if cached and (time.time() - cached['timestamp'] < 3600):
            return cached['text']
            
        # RAG: Retrieve context
        from datetime import date, timedelta
        target_date = date.today()
        if date_str:
            try:
                target_date = date.fromisoformat(date_str)
            except ValueError:
                pass
                
        # Get 7 days ending on target_date
        recent_summaries = db.query(DailySummary).filter(
            DailySummary.user_id == user_id,
            DailySummary.date <= target_date
        ).order_by(DailySummary.date.desc()).limit(7).all()
        
        # Get activities leading up to target_date
        from datetime import datetime
        end_time = datetime.combine(target_date, datetime.max.time())
        recent_activities = db.query(Activity).filter(
            Activity.user_id == user_id,
            Activity.start_time <= end_time
        ).order_by(Activity.start_time.desc()).limit(5).all()
        
        if not recent_summaries:
            return "Not enough data to generate insights yet."
            
        import math
        def calc_strain(cals):
            ac = max(0, (cals or 1800) - 1800)
            return min(21.0, 4.0 + (math.log(ac + 1) * 2.2)) if ac > 0 else 0.0

        context_data = "\n".join([
            f"Date: {s.date}, Recovery: {s.recovery_score}%, Sleep: {s.sleep_score}%, Strain: {calc_strain(s.calories_burned):.1f}/21, Stress: {s.average_stress_level}, Body Battery: {s.body_battery_highest}"
            for s in recent_summaries
        ])
        
        if focus == "sleep":
            prompt = f"Analyze the following recent health data and provide a single, short (1-2 sentence) insightful observation specifically about the user's SLEEP and RECOVERY. Act like an elite WHOOP performance coach. Provide a specific, highly actionable insight.\n\nData:\n{context_data}"
        elif focus == "training" or focus == "activities":
            activity_data = "\n".join([f"- {a.start_time.date() if a.start_time else 'Unknown'}: {a.name} ({a.distance}m, {a.duration}s, {a.calories} kcal)" for a in recent_activities])
            prompt = f"Analyze the following recent training and health data and provide a single, short (1-2 sentence) insightful observation specifically about the user's STRAIN and FITNESS. Act like an elite WHOOP athletic coach. Provide a specific, highly actionable insight.\n\nData:\n{context_data}\n\nActivities:\n{activity_data}"
        else:
            prompt = f"Analyze the following recent health data for the user and provide a single, short (1-2 sentence) insightful observation. Act like an elite WHOOP performance coach analyzing the Trinity (Strain, Recovery, Sleep). Provide a specific, highly actionable insight.\n\nData:\n{context_data}"
        
        try:
            # Note: google-genai client.models.generate_content is currently synchronous,
            # but we can wrap it in asyncio.to_thread to avoid blocking if needed,
            # or just call it directly for now.
            import asyncio
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=f"System: You are an elite Garmin health and performance analyst.\nUser: {prompt}"
            )
            _insight_cache[cache_key] = {'text': response.text, 'timestamp': time.time()}
            return response.text
        except Exception as e:
            logger.error(f"Error generating AI insight: {e}")
            return "Could not generate insight at this time."

    async def chat(self, db: Session, user_id: int, message: str, focus: str = None) -> str:
        if not self.enabled:
            return "AI Chat is disabled. Please configure GEMINI_API_KEY."
            
        # RAG: Retrieve context (simplified for now to last 7 days)
        recent_summaries = db.query(DailySummary).filter(DailySummary.user_id == user_id).order_by(DailySummary.date.desc()).limit(7).all()
        recent_activities = db.query(Activity).filter(Activity.user_id == user_id).order_by(Activity.start_time.desc()).limit(15).all()
        
        import math
        def calc_strain(cals):
            ac = max(0, (cals or 1800) - 1800)
            return min(21.0, 4.0 + (math.log(ac + 1) * 2.2)) if ac > 0 else 0.0

        context_data = "Recent Daily Summaries:\n" + "\n".join([
            f"- {s.date}: Recovery {s.recovery_score}%, Sleep {s.sleep_score}%, Strain {calc_strain(s.calories_burned):.1f}/21, Stress {s.average_stress_level}, BB {s.body_battery_highest}"
            for s in recent_summaries
        ]) + "\n\nRecent Activities:\n" + "\n".join([
            f"- {a.start_time.date() if a.start_time else 'Unknown'}: {a.name} ({a.distance}m, {a.duration}s, {a.calories} kcal)"
            for a in recent_activities
        ])
        
        try:
            import asyncio
            
            system_prompt = """You are an elite, highly knowledgeable AI sports scientist, performance analyst, and health coach, styled exactly like a WHOOP behavioral coach.
You are deeply familiar with the WHOOP 'Trinity': Strain (0-21 scale), Recovery (0-100%), and Sleep (0-100%).
When analyzing the user's data, you should:
1. Speak in terms of the interplay between Strain, Recovery, and Sleep.
2. Provide deep, specific correlations (e.g., 'Your massive 18.2 Strain yesterday clearly crushed your Recovery today down to 34%').
3. Offer highly actionable, physiological advice based on their current Recovery level.
4. Keep insights concise, punchy, and highly analytical.
Answer the user's questions clearly based on the provided context."""

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=f"System: {system_prompt}\n\nContext Data:\n{context_data}\n\nUser: {message}"
            )
            return response.text
        except Exception as e:
            logger.error(f"Error in AI chat: {e}")
            return "Sorry, I am having trouble connecting to my AI brain."

ai_service = AIService()

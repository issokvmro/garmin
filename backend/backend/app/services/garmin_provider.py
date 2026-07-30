from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import date, datetime

class GarminDataProvider(ABC):
    """
    Abstract interface for fetching Garmin data.
    This allows swapping out the MCP provider for a direct API implementation later.
    """
    
    @abstractmethod
    async def connect(self):
        """Establish connection to the provider."""
        pass
        
    @abstractmethod
    async def disconnect(self):
        """Close connection to the provider."""
        pass
        
    @abstractmethod
    async def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        """Fetch daily summary metrics for a specific date."""
        pass
        
    @abstractmethod
    async def get_activities(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch activities between two dates."""
        pass
        
    @abstractmethod
    async def get_heart_rates(self, target_date: date) -> Dict[str, Any]:
        """Fetch heart rate data for a specific date."""
        pass

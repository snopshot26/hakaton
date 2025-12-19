"""
Booster purchase manager
"""
from typing import Optional, List
from core.api import APIClient
from core.state import BoosterState
from core.logger import GameLogger
from utils.time import get_current_time

logger = GameLogger()


class BoosterManager:
    """Manages booster purchases"""
    
    def __init__(self, api_client: APIClient, cooldown_seconds: int = 30):
        self.api_client = api_client
        self.cooldown_seconds = cooldown_seconds
        self.last_attempt_time = 0.0
        self.last_attempt_failed = False
    
    def fetch_boosters(self) -> Optional[BoosterState]:
        """Fetch available boosters from API"""
        response = self.api_client.get_booster()
        if response:
            return BoosterState.from_dict(response)
        return None
    
    def _get_booster_priority(self) -> List[str]:
        """Get booster priority list"""
        return ["speed", "bomb_range", "bomb_count", "vision"]
    
    def _find_booster_index(self, booster_name: str, available: List[dict]) -> Optional[int]:
        """Find index of booster in available list (available is list of {type: str, cost: int})"""
        for idx, booster in enumerate(available):
            if isinstance(booster, dict) and booster.get("type") == booster_name:
                return idx
        return None
    
    def should_attempt_purchase(self) -> bool:
        """Check if we should attempt a purchase"""
        current_time = get_current_time()
        
        # Don't attempt if previous attempt failed recently
        if self.last_attempt_failed:
            time_since_failure = current_time - self.last_attempt_time
            if time_since_failure < self.cooldown_seconds:
                return False
        
        # Don't attempt if we tried recently
        time_since_attempt = current_time - self.last_attempt_time
        if time_since_attempt < self.cooldown_seconds:
            return False
        
        return True
    
    def try_purchase_booster(self, booster_state: BoosterState) -> bool:
        """
        Attempt to purchase a booster
        
        Returns:
            True if purchase was attempted (success or failure), False if skipped
        """
        if not self.should_attempt_purchase():
            return False
        
        # Don't attempt if no points
        if booster_state.points == 0:
            return False
        
        # Don't attempt if no boosters available
        if not booster_state.available:
            return False
        
        # Try to purchase in priority order
        priority = self._get_booster_priority()
        
        for booster_name in priority:
            booster_index = self._find_booster_index(booster_name, booster_state.available)
            if booster_index is not None:
                # Attempt purchase
                self.last_attempt_time = get_current_time()
                response = self.api_client.post_booster(booster_index)
                
                if response:
                    logger.booster(f"Purchased {booster_name} (index {booster_index})")
                    self.last_attempt_failed = False
                    return True
                else:
                    logger.booster(f"Failed to purchase {booster_name} (index {booster_index})")
                    self.last_attempt_failed = True
                    return True  # Attempt was made, even if failed
        
        # No booster found in priority list
        return False


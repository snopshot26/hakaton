"""
Booster purchase logic
"""
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BoosterManager:
    """Manages booster purchases"""
    
    def __init__(self):
        self.last_purchase_tick = 0
        self.last_points = 0
        self.purchased_boosters: Dict[str, int] = {}  # booster_type -> count
        self.consecutive_failures = 0
        self.max_failures = 3  # Disable after 3 consecutive failures
        self.disabled = False  # ENABLED - boosters are critical for high k!
    
    def get_priority(self) -> List[str]:
        """
        Priority order (optimized for max points):
        1. bomb_range - CRITICAL for k>=3-4 (10x points vs k=1!)
        2. bomb_delay - faster bomb cycle = more bombs
        3. bomb_count - more bombs simultaneously
        4. speed - faster movement
        5. acrobatics - survivability
        6. armor - last resort
        """
        return [
            "bomb_range",  # FIRST! range=2 allows k>=3-4
            "bomb_delay",  # fuse reduction
            "bomb_count",  # pockets
            "speed",
            "acrobatics",
            "armor"
        ]
    
    def should_purchase(self, current_points: int, current_tick: int) -> bool:
        """Check if should attempt purchase"""
        # Disabled if too many failures
        if self.disabled:
            return False
        
        # Only if points increased (new skill point available)
        if current_points <= self.last_points:
            return False
        
        # Rate limit: don't check every tick
        if current_tick - self.last_purchase_tick < 10:
            return False
        
        return True
    
    def record_failure(self):
        """Record a purchase failure"""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures:
            self.disabled = True
            logger.warning(f"Booster purchases disabled after {self.consecutive_failures} consecutive failures")
    
    def record_success(self):
        """Record a successful purchase"""
        self.consecutive_failures = 0
    
    def select_booster(self, available: List[Dict[str, Any]], 
                      state: Dict[str, Any], current_points: int) -> Optional[int]:
        """
        Select booster to purchase based on priority.
        Returns index in available list, or None.
        """
        priority = self.get_priority()
        points = state.get("points", 0)
        
        for booster_type in priority:
            # Find booster in available list
            for idx, booster in enumerate(available):
                if booster.get("type") == booster_type:
                    cost = booster.get("cost", 1)
                    
                    # Check if can afford
                    if points < cost:
                        continue
                    
                    # Check limits
                    if booster_type == "bomb_delay":
                        if self.purchased_boosters.get(booster_type, 0) >= 2:
                            continue
                    elif booster_type == "bomb_range":
                        if self.purchased_boosters.get(booster_type, 0) >= 2:
                            continue
                    elif booster_type == "speed":
                        if self.purchased_boosters.get(booster_type, 0) >= 2:
                            continue
                    elif booster_type == "acrobatics":
                        if self.purchased_boosters.get(booster_type, 0) >= 1:
                            continue
                    
                    # Special: armor only if needed (simplified - skip for now)
                    if booster_type == "armor":
                        continue  # Skip armor for now
                    
                    return idx
        
        return None
    
    def record_purchase(self, booster_type: str, current_tick: int):
        """Record that a booster was purchased"""
        self.purchased_boosters[booster_type] = self.purchased_boosters.get(booster_type, 0) + 1
        self.last_purchase_tick = current_tick
        logger.info(f"Purchased booster: {booster_type}")


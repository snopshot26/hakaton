"""
Upgrade manager: purchase decisions for skill points

Priority (from spec):
1) Fuse reduction: -2s per level, max 3, cost 1
2) Range: +1 radius, cost 1
3) Pockets: +1 bomb capacity, cost 1
4) Speed: +1 speed, max 3, cost 1
5) Acrobatics: pass obstacles, cost 2
6) Armor: +1 armor, cost 1 (only if deaths frequent)
"""
from typing import Optional, Dict, List, Tuple, Any
import logging

from bot.config import (
    UPGRADE_FUSE, UPGRADE_RANGE, UPGRADE_POCKETS,
    UPGRADE_SPEED, UPGRADE_ACROBATICS, UPGRADE_ARMOR
)

logger = logging.getLogger(__name__)


class UpgradeManager:
    """
    Manages upgrade purchases based on priority and available points.
    
    Skill points gained every 1.5 minutes (from spec).
    Max 10 skill points per round.
    """
    
    def __init__(self):
        self.purchased: Dict[str, int] = {}  # upgrade_type -> count
        self.last_purchase_tick: int = 0
        self.cooldown_ticks: int = 5  # Don't spam purchases
        self.death_count: int = 0  # Track deaths for armor decision
    
    def should_purchase(self, current_tick: int, points: int) -> bool:
        """Check if should attempt purchase"""
        if points <= 0:
            return False
        
        if current_tick - self.last_purchase_tick < self.cooldown_ticks:
            return False
        
        return True
    
    def select_upgrade(
        self,
        available_boosters: List[Dict[str, Any]],
        current_points: int,
        current_state: Dict[str, Any]
    ) -> Optional[int]:
        """
        Select upgrade to purchase based on priority.
        
        Args:
            available_boosters: List from GET /api/booster
            current_points: Available skill points
            current_state: Current booster state (from API)
        
        Returns:
            Index in available_boosters array, or None
        """
        if not available_boosters:
            return None
        
        # Build priority list
        priorities = self._get_priorities(current_state)
        
        # Find first affordable upgrade in priority order
        for upgrade_type, max_level in priorities:
            for idx, booster in enumerate(available_boosters):
                booster_type = booster.get("type", "").lower()
                cost = booster.get("cost", 999)
                
                # Check if matches priority and affordable
                if booster_type == upgrade_type and cost <= current_points:
                    # Check if haven't exceeded max level
                    current_level = self.purchased.get(upgrade_type, 0)
                    if current_level < max_level:
                        logger.info(f"Purchasing {upgrade_type} (level {current_level + 1}, cost {cost})")
                        return idx
        
        return None
    
    def _get_priorities(self, current_state: Dict[str, Any]) -> List[Tuple[str, int]]:
        """
        Get upgrade priorities based on current state.
        
        Returns:
            List of (upgrade_type, max_level) tuples
        """
        priorities = []
        
        # 1) Fuse reduction (max 3)
        priorities.append((UPGRADE_FUSE, 3))
        
        # 2) Range (unlimited, but prioritize early)
        priorities.append((UPGRADE_RANGE, 10))  # Reasonable limit
        
        # 3) Pockets (unlimited, but prioritize early)
        priorities.append((UPGRADE_POCKETS, 10))  # Reasonable limit
        
        # 4) Speed (max 3)
        priorities.append((UPGRADE_SPEED, 3))
        
        # 5) Acrobatics (expensive, but useful)
        priorities.append((UPGRADE_ACROBATICS, 3))
        
        # 6) Armor (only if deaths are frequent)
        if self.death_count > 2:
            priorities.append((UPGRADE_ARMOR, 5))  # Reasonable limit
        
        return priorities
    
    def record_purchase(self, upgrade_type: str, tick: int):
        """Record successful purchase"""
        self.purchased[upgrade_type] = self.purchased.get(upgrade_type, 0) + 1
        self.last_purchase_tick = tick
        logger.info(f"Purchased {upgrade_type}, total: {self.purchased[upgrade_type]}")
    
    def record_death(self):
        """Record unit death (for armor decision)"""
        self.death_count += 1


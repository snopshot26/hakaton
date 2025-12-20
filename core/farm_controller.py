"""
Global farm controller - manages all farming activity
"""
from typing import Dict, Tuple, List, Set
from core.state import Bomber, GameState
from core.tactical_state import FarmMemory
from core.roles import BomberRole, RoleManager
from core.logger import SystemLogger

logger = SystemLogger()


class FarmController:
    """Global controller for all farming operations"""
    
    def __init__(self, max_active_farmers: int = 2, max_active_bombs: int = 3):
        self.max_active_farmers = max_active_farmers
        self.max_active_bombs = max_active_bombs
        self.active_farmers: Set[str] = set()  # Bombers currently farming
        self.active_bombs: Dict[Tuple[int, int], int] = {}  # (x, y) -> tick planted
        self.farm_scores: Dict[str, float] = {}  # bomber_id -> last calculated score
        self.hard_threshold = 50.0  # Minimum score to allow farming
        self.base_threshold = 50.0  # Base threshold
        self.min_threshold = 15.0  # Minimum safe threshold
        self.last_bomb_tick = 0  # Track when last bomb was placed
        self.last_points = 0  # Track points for adaptive threshold
        self.ticks_without_bomb = 0  # Count ticks without bombs
    
    def can_start_farming(self, bomber_id: str, role: BomberRole, 
                         alive_farmers: int = 0) -> bool:
        """Check if bomber can start farming"""
        # Only farmers can farm
        if role != BomberRole.FARMER:
            return False
        
        # BOOTSTRAP RULE: If no active farmers and at least one farmer alive, allow one
        if len(self.active_farmers) == 0 and alive_farmers > 0:
            return True  # Override limits to bootstrap farming
        
        # Check active farmer limit
        if len(self.active_farmers) >= self.max_active_farmers:
            return False
        
        # Check active bomb limit
        active_bomb_count = len([b for b in self.active_bombs.values() if b > 0])
        if active_bomb_count >= self.max_active_bombs:
            return False
        
        return True
    
    def start_farming(self, bomber_id: str, bomb_pos: Tuple[int, int], current_tick: int):
        """Register that a bomber started farming"""
        self.active_farmers.add(bomber_id)
        self.active_bombs[bomb_pos] = current_tick
        logger.info(f"FarmController: {bomber_id[:8]} started farming at {bomb_pos}, "
                   f"active_farmers={len(self.active_farmers)}, active_bombs={len(self.active_bombs)}")
    
    def finish_farming(self, bomber_id: str, bomb_pos: Tuple[int, int], current_tick: int):
        """Register that farming is complete (bomb exploded)"""
        if bomber_id in self.active_farmers:
            self.active_farmers.remove(bomber_id)
        if bomb_pos in self.active_bombs:
            del self.active_bombs[bomb_pos]
        logger.info(f"FarmController: {bomber_id[:8]} finished farming, "
                   f"active_farmers={len(self.active_farmers)}, active_bombs={len(self.active_bombs)}")
    
    def cleanup_old_bombs(self, current_tick: int, bomb_lifetime: int = 100):
        """Remove old bomb entries"""
        to_remove = []
        for pos, tick in self.active_bombs.items():
            if current_tick - tick > bomb_lifetime:
                to_remove.append(pos)
        for pos in to_remove:
            del self.active_bombs[pos]
    
    def get_farm_score(self, bomber_id: str) -> float:
        """Get last calculated farm score for bomber"""
        return self.farm_scores.get(bomber_id, 0.0)
    
    def set_farm_score(self, bomber_id: str, score: float):
        """Set farm score for bomber"""
        self.farm_scores[bomber_id] = score
    
    def meets_threshold(self, score: float, bootstrap: bool = False) -> bool:
        """Check if score meets hard threshold"""
        # Bootstrap mode: lower threshold if no active farmers
        if bootstrap and len(self.active_farmers) == 0:
            return score >= self.min_threshold  # Lower threshold for bootstrap
        return score >= self.hard_threshold
    
    def update_adaptive_threshold(self, current_tick: int, current_points: int):
        """Adaptively lower threshold if no progress"""
        # Count ticks without bombs
        if current_tick - self.last_bomb_tick > 20:
            self.ticks_without_bomb += 1
        else:
            self.ticks_without_bomb = 0
        
        # Lower threshold if no bombs for too long
        if self.ticks_without_bomb > 30:
            self.hard_threshold = max(self.min_threshold, self.hard_threshold * 0.8)
            logger.info(f"FarmController: Lowered threshold to {self.hard_threshold:.1f} (no bombs for {self.ticks_without_bomb} ticks)")
            self.ticks_without_bomb = 0  # Reset counter
        
        # Lower threshold if points not increasing
        if current_points <= self.last_points and self.ticks_without_bomb > 10:
            self.hard_threshold = max(self.min_threshold, self.hard_threshold * 0.9)
            logger.info(f"FarmController: Lowered threshold to {self.hard_threshold:.1f} (points stagnant)")
        
        # Reset threshold if progress is good
        if current_points > self.last_points:
            self.hard_threshold = min(self.base_threshold, self.hard_threshold * 1.1)
        
        self.last_points = current_points
    
    def record_bomb_placed(self, current_tick: int):
        """Record that a bomb was placed"""
        self.last_bomb_tick = current_tick
        self.ticks_without_bomb = 0


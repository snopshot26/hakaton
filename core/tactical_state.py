"""
Tactical state machine for bombers
"""
from enum import Enum
from typing import Dict, Tuple, Optional
from core.state import Bomber, GameState


class TacticalState(Enum):
    """High-level tactical states for bombers"""
    DANGER = "DANGER"      # In danger, must escape
    WAIT = "WAIT"          # Waiting for bomb/cooldown
    FARM = "FARM"          # Farming obstacles
    POST_FARM = "POST_FARM"  # Just farmed, must move away
    RELOCATE = "RELOCATE"  # Moving to new area
    IDLE = "IDLE"          # No clear action


class FarmMemory:
    """Tracks which tiles were farmed and when"""
    
    def __init__(self, cooldown_ticks: int = 30):
        self.farmed_tiles: Dict[Tuple[int, int], int] = {}  # (x, y) -> last_farmed_tick
        self.cooldown_ticks = cooldown_ticks
    
    def was_farmed_recently(self, pos: Tuple[int, int], current_tick: int) -> bool:
        """Check if tile was farmed recently"""
        if pos not in self.farmed_tiles:
            return False
        return (current_tick - self.farmed_tiles[pos]) < self.cooldown_ticks
    
    def mark_farmed(self, pos: Tuple[int, int], current_tick: int):
        """Mark a tile as farmed"""
        self.farmed_tiles[pos] = current_tick
    
    def cleanup_old(self, current_tick: int, max_age: int = 100):
        """Remove old entries to prevent memory bloat"""
        to_remove = []
        for pos, tick in self.farmed_tiles.items():
            if current_tick - tick > max_age:
                to_remove.append(pos)
        for pos in to_remove:
            del self.farmed_tiles[pos]


class BomberTacticalState:
    """Tracks tactical state for a single bomber"""
    
    def __init__(self, bomber_id: str, min_action_interval: int = 2, farm_cooldown: int = 30):
        self.bomber_id = bomber_id
        self.state = TacticalState.IDLE
        self.last_action_tick = 0
        self.last_farm_tick = 0
        self.last_farm_pos: Optional[Tuple[int, int]] = None
        self.post_farm_start_tick = 0
        self.min_action_interval = min_action_interval
        self.farm_cooldown = farm_cooldown
        self.min_farm_distance = 3  # Must move this far after farming
    
    def can_act(self, current_tick: int) -> bool:
        """Check if bomber can perform an action (rate limiting)"""
        return (current_tick - self.last_action_tick) >= self.min_action_interval
    
    def should_skip_action(self, current_tick: int, role=None) -> bool:
        """Check if action should be skipped based on state"""
        if self.state == TacticalState.WAIT:
            return True
        if self.state == TacticalState.POST_FARM:
            # In post-farm, must move away, but check cooldown
            if (current_tick - self.post_farm_start_tick) < self.farm_cooldown:
                return False  # Can act to move away
            return True  # Cooldown active, skip
        if self.state == TacticalState.IDLE:
            # FARMERS should never be in IDLE (should have been caught)
            if role and role.value == "FARMER":
                return False  # Force action for farmers
            # Only act if enough time has passed
            return not self.can_act(current_tick)
        return False
    
    def can_farm_again(self, current_tick: int) -> bool:
        """Check if bomber can farm again (cooldown expired)"""
        if self.last_farm_tick == 0:
            return True
        return (current_tick - self.last_farm_tick) >= self.farm_cooldown
    
    def update_state(self, new_state: TacticalState, current_tick: int, logger=None):
        """Update tactical state"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            if new_state == TacticalState.FARM:
                self.last_farm_tick = current_tick
            if new_state == TacticalState.POST_FARM:
                self.post_farm_start_tick = current_tick
            if logger:
                logger.info(f"Bomber {self.bomber_id[:8]}: {old_state.value} -> {new_state.value}")
    
    def record_action(self, current_tick: int):
        """Record that an action was taken"""
        self.last_action_tick = current_tick


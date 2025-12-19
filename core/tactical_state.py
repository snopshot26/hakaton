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
    
    def __init__(self, bomber_id: str):
        self.bomber_id = bomber_id
        self.state = TacticalState.IDLE
        self.last_action_tick = 0
        self.last_farm_tick = 0
        self.last_farm_pos: Optional[Tuple[int, int]] = None
        self.min_action_interval = 2  # Minimum ticks between actions
    
    def can_act(self, current_tick: int) -> bool:
        """Check if bomber can perform an action (rate limiting)"""
        return (current_tick - self.last_action_tick) >= self.min_action_interval
    
    def should_skip_action(self, current_tick: int) -> bool:
        """Check if action should be skipped based on state"""
        if self.state == TacticalState.WAIT:
            return True
        if self.state == TacticalState.IDLE:
            # Only act if enough time has passed
            return not self.can_act(current_tick)
        return False
    
    def update_state(self, new_state: TacticalState, current_tick: int):
        """Update tactical state"""
        if self.state != new_state:
            self.state = new_state
            if new_state == TacticalState.FARM:
                self.last_farm_tick = current_tick
    
    def record_action(self, current_tick: int):
        """Record that an action was taken"""
        self.last_action_tick = current_tick


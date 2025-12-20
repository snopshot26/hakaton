"""
Coordinator: multi-unit assignment and conflict resolution

Selects conflict-free set of actions using greedy matching:
- Sort actions by score
- Pick best actions that don't conflict in:
  - Target cell
  - Retreat corridor
  - Bomb crossfire
  - Cell reservation window
"""
from typing import List, Set, Dict, Tuple, Optional
from dataclasses import dataclass
import logging

from bot.strategy.planner import CandidateAction
from bot.models import Position, ArenaState

logger = logging.getLogger(__name__)


@dataclass
class AssignedAction:
    """Final assigned action for a unit"""
    unit_id: str
    path: List[Position]
    bomb_pos: Optional[Position] = None


class Coordinator:
    """
    Coordinates actions across all units to avoid conflicts.
    
    Maintains cell reservations to prevent units from:
    - Targeting same cell
    - Blocking each other's retreat paths
    - Getting caught in crossfire
    """
    
    def __init__(self):
        self.reserved_cells: Dict[Tuple[int, int], str] = {}  # cell -> unit_id
        self.reservation_ttl: Dict[Tuple[int, int], int] = {}  # cell -> tick
        self.current_tick: int = 0
    
    def select_actions(
        self,
        all_candidates: Dict[str, List[CandidateAction]],
        state: ArenaState,
        tick: int
    ) -> List[AssignedAction]:
        """
        Select conflict-free set of actions.
        
        Args:
            all_candidates: Dict[unit_id, List[CandidateAction]]
            state: Current arena state
            tick: Current tick
        
        Returns:
            List of assigned actions
        """
        self.current_tick = tick
        self._cleanup_reservations(tick)
        
        # Flatten and sort all candidates by score
        all_actions: List[CandidateAction] = []
        for unit_id, candidates in all_candidates.items():
            for action in candidates:
                all_actions.append(action)
        
        # Sort by score (descending)
        all_actions.sort(key=lambda a: a.score, reverse=True)
        
        # Greedy selection: pick best non-conflicting actions
        selected: List[AssignedAction] = []
        used_units: Set[str] = set()
        reserved: Set[Tuple[int, int]] = set()
        
        for action in all_actions:
            # Skip if unit already has action
            if action.unit_id in used_units:
                continue
            
            # Check for conflicts
            if self._has_conflict(action, reserved, state):
                continue
            
            # Assign action
            assigned = AssignedAction(
                unit_id=action.unit_id,
                path=action.path,
                bomb_pos=action.bomb_pos
            )
            selected.append(assigned)
            used_units.add(action.unit_id)
            
            # Reserve cells
            self._reserve_action(action, reserved, tick)
        
        logger.info(f"Selected {len(selected)} actions for {len(used_units)} units")
        return selected
    
    def _has_conflict(
        self,
        action: CandidateAction,
        reserved: Set[Tuple[int, int]],
        state: ArenaState
    ) -> bool:
        """Check if action conflicts with reserved cells"""
        # Check path cells
        for pos in action.path:
            if pos.to_tuple() in reserved:
                return True
        
        # Check bomb position
        if action.bomb_pos and action.bomb_pos.to_tuple() in reserved:
            return True
        
        # Check retreat position
        if action.retreat_pos and action.retreat_pos.to_tuple() in reserved:
            return True
        
        # Check for crossfire (bomb blast zones overlapping)
        if action.bomb_pos:
            # Simple check: if another unit is planting nearby, might conflict
            for cell_tuple, unit_id in self.reserved_cells.items():
                if unit_id == action.unit_id:
                    continue
                # Check if cells are close (within bomb range)
                cell_pos = Position(cell_tuple[0], cell_tuple[1])
                dist = action.bomb_pos.manhattan_distance(cell_pos)
                if dist <= 3:  # Within potential blast range
                    return True
        
        return False
    
    def _reserve_action(
        self,
        action: CandidateAction,
        reserved: Set[Tuple[int, int]],
        tick: int
    ):
        """Reserve cells for action"""
        ttl = 3  # Ticks to reserve
        
        # Reserve path cells
        for pos in action.path:
            cell_tuple = pos.to_tuple()
            reserved.add(cell_tuple)
            self.reserved_cells[cell_tuple] = action.unit_id
            self.reservation_ttl[cell_tuple] = tick + ttl
        
        # Reserve bomb position
        if action.bomb_pos:
            cell_tuple = action.bomb_pos.to_tuple()
            reserved.add(cell_tuple)
            self.reserved_cells[cell_tuple] = action.unit_id
            self.reservation_ttl[cell_tuple] = tick + ttl
        
        # Reserve retreat position
        if action.retreat_pos:
            cell_tuple = action.retreat_pos.to_tuple()
            reserved.add(cell_tuple)
            self.reserved_cells[cell_tuple] = action.unit_id
            self.reservation_ttl[cell_tuple] = tick + ttl
    
    def _cleanup_reservations(self, tick: int):
        """Remove expired reservations"""
        expired = [
            cell for cell, expire_tick in self.reservation_ttl.items()
            if tick >= expire_tick
        ]
        
        for cell in expired:
            if cell in self.reserved_cells:
                del self.reserved_cells[cell]
            if cell in self.reservation_ttl:
                del self.reservation_ttl[cell]
    
    def get_reserved_cells(self) -> Set[Tuple[int, int]]:
        """Get set of currently reserved cells"""
        return set(self.reserved_cells.keys())


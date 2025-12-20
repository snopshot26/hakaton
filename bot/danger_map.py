"""
Danger map: blast prediction and mob avoidance

Computes:
- Safe cells at each time step
- Blast zones from active bombs (including chain reactions)
- Mob danger zones (predicted positions)
"""
from typing import Dict, Set, Tuple, List
from dataclasses import dataclass
import logging

from bot.models import Position, ArenaState, Bomb, Mob
from bot.config import DEFAULT_BOMB_FUSE, MOB_GHOST, MOB_PATROL

logger = logging.getLogger(__name__)


@dataclass
class BlastZone:
    """Blast zone from a bomb"""
    center: Position
    range: int
    explode_time: float  # Seconds until explosion
    affected_cells: Set[Tuple[int, int]]  # All cells in blast


class DangerMap:
    """
    Computes danger zones from bombs and mobs.
    
    Bomb explosions:
    - Cross pattern (N/E/S/W) with length = range
    - Each ray stops at first obstacle/bomb
    - Chain reactions: bomb can trigger other bombs early
    
    Mob danger:
    - Ghost: passes obstacles, vision 10, speed 1
    - Patrol: normal movement, speed 1
    - Contact kills: unit dies if on same cell as awake mob
    """
    
    def __init__(self):
        self.blast_zones: List[BlastZone] = []
        self.unsafe_cells: Set[Tuple[int, int]] = set()
        self.mob_danger: Dict[Tuple[int, int], float] = {}  # pos -> danger level
    
    def update(self, state: ArenaState, current_time: float = 0.0):
        """
        Update danger map from current state.
        
        Args:
            state: Current arena state
            current_time: Current game time (seconds)
        """
        self.blast_zones = []
        self.unsafe_cells = set()
        self.mob_danger = {}
        
        # Compute blast zones for all bombs
        processed_bombs: Set[Tuple[int, int]] = set()
        
        for bomb in state.bombs:
            if bomb.pos.to_tuple() in processed_bombs:
                continue
            
            # Compute blast zone (including chain reactions)
            blast_cells = self._compute_blast_zone(
                bomb, state, processed_bombs, current_time
            )
            
            explode_time = bomb.timer
            self.blast_zones.append(BlastZone(
                center=bomb.pos,
                range=bomb.range,
                explode_time=explode_time,
                affected_cells=blast_cells
            ))
            
            # Mark cells as unsafe if explosion is soon
            if explode_time <= 8.0:  # Within fuse time
                self.unsafe_cells.update(blast_cells)
        
        # Compute mob danger
        self._compute_mob_danger(state)
    
    def _compute_blast_zone(
        self,
        bomb: Bomb,
        state: ArenaState,
        processed_bombs: Set[Tuple[int, int]],
        current_time: float
    ) -> Set[Tuple[int, int]]:
        """
        Compute blast zone including chain reactions.
        
        Returns set of all cells that will be affected.
        """
        affected = {bomb.pos.to_tuple()}
        processed_bombs.add(bomb.pos.to_tuple())
        
        # Directions: N, E, S, W
        directions = [(0, -1), (1, 0), (0, 1), (-1, 0)]
        
        for dx, dy in directions:
            for dist in range(1, bomb.range + 1):
                x = bomb.pos.x + dx * dist
                y = bomb.pos.y + dy * dist
                
                # Bounds check
                if (x < 0 or x >= state.map_size[0] or
                    y < 0 or y >= state.map_size[1]):
                    break
                
                cell = (x, y)
                affected.add(cell)
                
                # Check if ray stops (obstacle or bomb)
                # Check for obstacles (ray stops at first obstacle)
                if any(o.x == x and o.y == y for o in state.obstacles):
                    break  # Ray stops at obstacle
                
                # Check for walls (ray stops at wall)
                if any(w.x == x and w.y == y for w in state.walls):
                    break  # Ray stops at wall
                
                # Check for other bombs (chain reaction)
                for other_bomb in state.bombs:
                    if other_bomb.pos.x == x and other_bomb.pos.y == y:
                        if other_bomb.pos.to_tuple() not in processed_bombs:
                            # Chain reaction: this bomb will explode early
                            # Recursively compute its blast zone
                            chain_cells = self._compute_blast_zone(
                                other_bomb, state, processed_bombs, current_time
                            )
                            affected.update(chain_cells)
                        break  # Ray stops at bomb
                else:
                    # No obstacle/wall/bomb, ray continues
                    continue
                
                # Ray stopped
                break
        
        return affected
    
    def _compute_mob_danger(self, state: ArenaState):
        """
        Compute mob danger zones.
        
        For awake mobs, predict their movement and mark nearby cells as dangerous.
        Ghost: can pass obstacles, larger vision
        Patrol: normal movement
        """
        for mob in state.mobs:
            if mob.safe_time > 0:
                continue  # Sleeping, not dangerous
            
            pos = mob.pos
            danger_radius = 2  # Cells within 2 steps are dangerous
            
            # Mark nearby cells as dangerous
            for dx in range(-danger_radius, danger_radius + 1):
                for dy in range(-danger_radius, danger_radius + 1):
                    if abs(dx) + abs(dy) > danger_radius:
                        continue
                    
                    x = pos.x + dx
                    y = pos.y + dy
                    
                    # Bounds check
                    if (x < 0 or x >= state.map_size[0] or
                        y < 0 or y >= state.map_size[1]):
                        continue
                    
                    cell = (x, y)
                    # Higher danger if closer to mob
                    distance = abs(dx) + abs(dy)
                    danger = 1.0 / (distance + 1)
                    
                    if cell not in self.mob_danger:
                        self.mob_danger[cell] = 0.0
                    self.mob_danger[cell] = max(self.mob_danger[cell], danger)
    
    def is_safe(self, pos: Position, time_horizon: float = 8.0) -> bool:
        """
        Check if position is safe within time horizon.
        
        Args:
            pos: Position to check
            time_horizon: Time horizon in seconds (default: bomb fuse time)
        """
        pos_tuple = pos.to_tuple()
        
        # Check blast zones
        for blast in self.blast_zones:
            if pos_tuple in blast.affected_cells:
                if blast.explode_time <= time_horizon:
                    return False
        
        # Check mob danger (high danger = unsafe)
        if pos_tuple in self.mob_danger:
            if self.mob_danger[pos_tuple] > 0.5:  # Threshold
                return False
        
        return True
    
    def get_safe_retreat_position(
        self,
        bomb_pos: Position,
        bomb_range: int,
        start_pos: Position,
        state: ArenaState,
        max_steps: int = 8
    ) -> Optional[Position]:
        """
        Find a safe retreat position from a bomb.
        
        Args:
            bomb_pos: Position where bomb will be placed
            bomb_range: Bomb explosion range
            start_pos: Starting position (where unit will be after planting)
            state: Current arena state
            max_steps: Maximum steps to search
        
        Returns:
            Safe position or None
        """
        # Compute blast cells
        blast_cells = set()
        blast_cells.add(bomb_pos.to_tuple())
        
        directions = [(0, -1), (1, 0), (0, 1), (-1, 0)]
        for dx, dy in directions:
            for dist in range(1, bomb_range + 1):
                x = bomb_pos.x + dx * dist
                y = bomb_pos.y + dy * dist
                
                if (x < 0 or x >= state.map_size[0] or
                    y < 0 or y >= state.map_size[1]):
                    break
                
                blast_cells.add((x, y))
        
        # BFS from start_pos to find safe cell outside blast
        from collections import deque
        queue = deque([(start_pos, 0)])
        visited = {start_pos.to_tuple()}
        
        while queue:
            current, steps = queue.popleft()
            
            if steps >= max_steps:
                continue
            
            # Check if safe (not in blast, not in danger)
            if current.to_tuple() not in blast_cells:
                if self.is_safe(current):
                    return current
            
            # Explore neighbors
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                neighbor = Position(current.x + dx, current.y + dy)
                neighbor_tuple = neighbor.to_tuple()
                
                if (neighbor.x < 0 or neighbor.x >= state.map_size[0] or
                    neighbor.y < 0 or neighbor.y >= state.map_size[1]):
                    continue
                
                if neighbor_tuple in visited:
                    continue
                
                visited.add(neighbor_tuple)
                queue.append((neighbor, steps + 1))
        
        return None


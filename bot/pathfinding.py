"""
Pathfinding: BFS for shortest paths

Handles:
- Walls and obstacles as blocked
- Bombs as blocked (unless can_pass_bombs)
- Mobs as blocked if awake (contact kills)
- Max path length (30 from spec)
"""
from typing import List, Optional, Set, Tuple
from collections import deque
import logging

from bot.models import Position, ArenaState, Bomb, Mob
from bot.world_model import WorldModel
from bot.config import MAX_PATH_LENGTH, MOB_SLEEP_TIME_MS

logger = logging.getLogger(__name__)


def bfs_path(
    start: Position,
    goal: Position,
    state: ArenaState,
    world: WorldModel,
    max_length: int = MAX_PATH_LENGTH,
    can_pass_bombs: bool = False,
    can_pass_obstacles: bool = False,
    can_pass_walls: bool = False
) -> Optional[List[Position]]:
    """
    Find shortest path using BFS.
    
    Args:
        start: Starting position
        goal: Goal position
        state: Current arena state
        world: World model
        max_length: Maximum path length
        can_pass_bombs: Can pass through bombs (acrobatics upgrade)
        can_pass_obstacles: Can pass through obstacles (acrobatics upgrade)
        can_pass_walls: Can pass through walls (acrobatics upgrade)
    
    Returns:
        List of positions from start to goal, or None if no path
    """
    if start.x == goal.x and start.y == goal.y:
        return [start]
    
    queue = deque([(start, [start])])
    visited: Set[Tuple[int, int]] = {start.to_tuple()}
    
    while queue:
        current, path = queue.popleft()
        
        # Check path length limit
        if len(path) > max_length:
            continue
        
        # Check if reached goal
        if current.x == goal.x and current.y == goal.y:
            return path
        
        # Explore neighbors
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            neighbor = Position(current.x + dx, current.y + dy)
            neighbor_tuple = neighbor.to_tuple()
            
            # Bounds check
            if (neighbor.x < 0 or neighbor.x >= state.map_size[0] or
                neighbor.y < 0 or neighbor.y >= state.map_size[1]):
                continue
            
            # Skip if already visited
            if neighbor_tuple in visited:
                continue
            
            # Check if blocked
            if world.is_wall(neighbor) and not can_pass_walls:
                continue
            
            if world.is_obstacle(neighbor) and not can_pass_obstacles:
                # Can pass if it's the goal and we're bombing it
                if neighbor.x != goal.x or neighbor.y != goal.y:
                    continue
            
            # Check for bombs
            if not can_pass_bombs:
                if any(b.pos.x == neighbor.x and b.pos.y == neighbor.y for b in state.bombs):
                    continue
            
            # Check for awake mobs (contact kills)
            for mob in state.mobs:
                if mob.safe_time <= 0:  # Awake
                    if mob.pos.x == neighbor.x and mob.pos.y == neighbor.y:
                        # Skip if mob is at neighbor (contact kill)
                        break
            else:
                # No mob blocking, add to queue
                visited.add(neighbor_tuple)
                queue.append((neighbor, path + [neighbor]))
    
    return None


def manhattan_path(start: Position, goal: Position) -> List[Position]:
    """
    Simple Manhattan path (for fallback when BFS fails).
    Does not check for obstacles.
    """
    path = [start]
    current = start
    
    while current.x != goal.x or current.y != goal.y:
        if current.x < goal.x:
            current = Position(current.x + 1, current.y)
        elif current.x > goal.x:
            current = Position(current.x - 1, current.y)
        elif current.y < goal.y:
            current = Position(current.y, current.y + 1)
        elif current.y > goal.y:
            current = Position(current.x, current.y - 1)
        
        path.append(current)
        
        if len(path) > MAX_PATH_LENGTH:
            break
    
    return path


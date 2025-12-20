"""
Global map memory - union of all observed tiles
"""
from typing import Set, Dict, Tuple, Optional
from dataclasses import dataclass
from src.models import Position, ArenaState


@dataclass
class TileInfo:
    """Information about a map tile"""
    is_wall: bool = False
    is_obstacle: bool = False
    is_observed: bool = False
    last_obstacle_tick: Optional[int] = None  # When obstacle was last seen


class WorldMemory:
    """Global map memory tracking observed tiles"""
    
    def __init__(self):
        self.tiles: Dict[Tuple[int, int], TileInfo] = {}
        self.obstacle_memory: Dict[Tuple[int, int], int] = {}  # Track when obstacles were destroyed
        self.current_tick = 0
    
    def update(self, state: ArenaState, tick: int):
        """Update world memory from current arena state"""
        self.current_tick = tick
        
        # Mark all visible tiles as observed
        vision_radius = 5  # Default vision radius
        
        for bomber in state.bombers:
            if bomber.alive:
                self._mark_visible(bomber.pos, vision_radius, state)
        
        # Update obstacles - if not in current state, mark as destroyed
        current_obstacles = {obs.to_tuple() for obs in state.obstacles}
        for pos_tuple, tile_info in self.tiles.items():
            if tile_info.is_obstacle and pos_tuple not in current_obstacles:
                # Obstacle was destroyed
                self.obstacle_memory[pos_tuple] = tick
                tile_info.is_obstacle = False
    
    def _mark_visible(self, center: Position, radius: int, state: ArenaState):
        """Mark tiles in vision radius as observed"""
        cx, cy = center.x, center.y
        
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                # Check if within vision radius (Manhattan distance)
                if abs(dx) + abs(dy) > radius:
                    continue
                
                x, y = cx + dx, cy + dy
                if x < 0 or x >= state.map_size[0] or y < 0 or y >= state.map_size[1]:
                    continue
                
                pos_tuple = (x, y)
                if pos_tuple not in self.tiles:
                    self.tiles[pos_tuple] = TileInfo(is_observed=False)
                
                tile = self.tiles[pos_tuple]
                tile.is_observed = True
                
                # Update obstacle status
                pos_obj = Position(x, y)
                if pos_obj in state.obstacles:
                    tile.is_obstacle = True
                    tile.last_obstacle_tick = self.current_tick
                elif pos_obj in state.walls:
                    tile.is_wall = True
    
    def is_blocked(self, pos: Position) -> bool:
        """Check if position is blocked. Unknown is considered free to allow exploration."""
        pos_tuple = pos.to_tuple()
        
        if pos_tuple not in self.tiles:
            return False  # Unknown -> explore
        
        tile = self.tiles[pos_tuple]
        # Block walls and known obstacles; allow empty/unknown for exploration
        return tile.is_wall or tile.is_obstacle
    
    def is_obstacle(self, pos: Position) -> bool:
        """Check if position has an obstacle"""
        pos_tuple = pos.to_tuple()
        if pos_tuple not in self.tiles:
            return False
        return self.tiles[pos_tuple].is_obstacle
    
    def was_obstacle_destroyed(self, pos: Position, since_tick: int) -> bool:
        """Check if obstacle was destroyed since given tick"""
        pos_tuple = pos.to_tuple()
        if pos_tuple not in self.obstacle_memory:
            return False
        return self.obstacle_memory[pos_tuple] > since_tick
    
    def get_observed_area(self) -> Set[Tuple[int, int]]:
        """Get set of all observed tile positions"""
        return {pos for pos, tile in self.tiles.items() if tile.is_observed}


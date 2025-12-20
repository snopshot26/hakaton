"""
World model: persistent map memory with fog-of-war

Tracks:
- Known tiles (walls, obstacles, empty)
- Last seen timestamp
- Vision updates from each unit
- Obstacle destruction tracking
"""
from typing import Dict, Tuple, Optional, Set
from dataclasses import dataclass
from enum import Enum
import logging

from bot.models import Position, ArenaState
from bot.config import VISION_RADIUS

logger = logging.getLogger(__name__)


class TileType(Enum):
    """Tile type"""
    UNKNOWN = "unknown"
    EMPTY = "empty"
    WALL = "wall"
    OBSTACLE = "obstacle"


@dataclass
class TileInfo:
    """Information about a tile"""
    tile_type: TileType
    last_seen: int  # Tick when last observed
    is_observed: bool  # Currently in vision of any unit


class WorldModel:
    """
    Persistent world model with fog-of-war.
    
    Each unit has vision radius 5 (r^2 = x^2 + y^2).
    Updates map from each unit's vision every tick.
    """
    
    def __init__(self):
        self.tiles: Dict[Tuple[int, int], TileInfo] = {}
        self.map_size: Tuple[int, int] = (0, 0)
        self.current_tick: int = 0
        # Track destroyed obstacles (for farm memory)
        self.destroyed_obstacles: Dict[Tuple[int, int], int] = {}  # pos -> tick destroyed
        self.farm_cooldown_ticks: int = 30  # Don't re-farm same spot for N ticks
    
    def update(self, state: ArenaState, tick: int):
        """
        Update world model from current arena state.
        
        Args:
            state: Current arena state
            tick: Current tick number
        """
        self.current_tick = tick
        self.map_size = state.map_size
        
        # Mark all tiles as not currently observed
        for tile_info in self.tiles.values():
            tile_info.is_observed = False
        
        # Update from each bomber's vision
        for bomber in state.bombers:
            if not bomber.alive:
                continue
            self._update_vision(bomber.pos, state, tick)
        
        # Update known walls and obstacles from arena data
        for wall in state.walls:
            pos_tuple = wall.to_tuple()
            if pos_tuple not in self.tiles:
                self.tiles[pos_tuple] = TileInfo(TileType.WALL, tick, True)
            else:
                self.tiles[pos_tuple].tile_type = TileType.WALL
                self.tiles[pos_tuple].last_seen = tick
                self.tiles[pos_tuple].is_observed = True
        
        for obstacle in state.obstacles:
            pos_tuple = obstacle.to_tuple()
            if pos_tuple not in self.tiles:
                self.tiles[pos_tuple] = TileInfo(TileType.OBSTACLE, tick, True)
            else:
                # If was obstacle before but now empty in state, it was destroyed
                if self.tiles[pos_tuple].tile_type == TileType.OBSTACLE:
                    # Check if still in obstacles list
                    if obstacle not in state.obstacles:
                        self.destroyed_obstacles[pos_tuple] = tick
                        self.tiles[pos_tuple].tile_type = TileType.EMPTY
                else:
                    self.tiles[pos_tuple].tile_type = TileType.OBSTACLE
                self.tiles[pos_tuple].last_seen = tick
                self.tiles[pos_tuple].is_observed = True
    
    def _update_vision(self, center: Position, state: ArenaState, tick: int):
        """
        Update tiles visible from center position.
        
        Vision: r^2 = x^2 + y^2, radius = 5
        """
        vision_radius_sq = VISION_RADIUS * VISION_RADIUS
        
        # Check all tiles in vision range
        for dx in range(-VISION_RADIUS, VISION_RADIUS + 1):
            for dy in range(-VISION_RADIUS, VISION_RADIUS + 1):
                if dx * dx + dy * dy > vision_radius_sq:
                    continue
                
                x = center.x + dx
                y = center.y + dy
                
                # Bounds check
                if x < 0 or x >= self.map_size[0] or y < 0 or y >= self.map_size[1]:
                    continue
                
                pos_tuple = (x, y)
                
                # Determine tile type
                tile_type = TileType.EMPTY
                if any(w.x == x and w.y == y for w in state.walls):
                    tile_type = TileType.WALL
                elif any(o.x == x and o.y == y for o in state.obstacles):
                    tile_type = TileType.OBSTACLE
                
                # Update tile info
                if pos_tuple not in self.tiles:
                    self.tiles[pos_tuple] = TileInfo(tile_type, tick, True)
                else:
                    self.tiles[pos_tuple].tile_type = tile_type
                    self.tiles[pos_tuple].last_seen = tick
                    self.tiles[pos_tuple].is_observed = True
    
    def is_blocked(self, pos: Position) -> bool:
        """
        Check if position is blocked (wall or obstacle).
        Unknown tiles are treated as blocked for safety.
        """
        pos_tuple = pos.to_tuple()
        if pos_tuple not in self.tiles:
            return True  # Unknown = blocked
        
        tile_info = self.tiles[pos_tuple]
        return tile_info.tile_type in [TileType.WALL, TileType.OBSTACLE]
    
    def is_wall(self, pos: Position) -> bool:
        """Check if position is a wall."""
        pos_tuple = pos.to_tuple()
        if pos_tuple not in self.tiles:
            return False
        return self.tiles[pos_tuple].tile_type == TileType.WALL
    
    def is_obstacle(self, pos: Position) -> bool:
        """Check if position is a destructible obstacle."""
        pos_tuple = pos.to_tuple()
        if pos_tuple not in self.tiles:
            return False
        return self.tiles[pos_tuple].tile_type == TileType.OBSTACLE
    
    def was_farmed_recently(self, pos: Position) -> bool:
        """
        Check if obstacle at position was recently farmed.
        Used to avoid re-farming same spot.
        """
        pos_tuple = pos.to_tuple()
        if pos_tuple not in self.destroyed_obstacles:
            return False
        
        destroyed_tick = self.destroyed_obstacles[pos_tuple]
        return (self.current_tick - destroyed_tick) < self.farm_cooldown_ticks
    
    def get_frontier_tiles(self, known_tiles: Set[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        """
        Get frontier tiles (unknown tiles adjacent to known tiles).
        Used for exploration/scouting.
        """
        frontier = set()
        
        for x, y in known_tiles:
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                neighbor = (x + dx, y + dy)
                
                # Bounds check
                if (neighbor[0] < 0 or neighbor[0] >= self.map_size[0] or
                    neighbor[1] < 0 or neighbor[1] >= self.map_size[1]):
                    continue
                
                # If unknown, it's a frontier tile
                if neighbor not in self.tiles:
                    frontier.add(neighbor)
        
        return frontier


"""
State models for game entities
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class Bomber:
    """Represents a single bomber"""
    id: str
    position: Tuple[int, int]
    alive: bool
    moving: bool
    target: Optional[Tuple[int, int]]
    bombs_available: int
    last_action_time: float
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], current_time: float) -> 'Bomber':
        """Create Bomber from API response (view.Bomber schema)"""
        pos_data = data.get("pos", [0, 0])
        pos = tuple(pos_data) if isinstance(pos_data, list) else (0, 0)
        
        return cls(
            id=str(data.get("id", "")),
            position=pos,
            alive=bool(data.get("alive", True)),
            moving=not bool(data.get("can_move", True)),  # can_move=False means moving
            target=None,  # Not provided in API response
            bombs_available=int(data.get("bombs_available", 1)),
            last_action_time=current_time
        )


@dataclass
class BoosterState:
    """Represents available boosters"""
    available: List[Dict[str, Any]]  # List of {type: str, cost: int}
    points: int
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BoosterState':
        """Create BoosterState from API response (view.AvailableBoosterResponse schema)"""
        state = data.get("state", {})
        return cls(
            available=list(data.get("available", [])),  # List of booster objects
            points=int(state.get("points", 0))
        )


@dataclass
class GameState:
    """Represents the complete game state"""
    round_id: str
    tick: int
    points: int
    bombers: List[Bomber]
    map_size: Tuple[int, int]
    obstacles: List[Tuple[int, int]]
    explosions: List[Tuple[int, int]]
    enemies: List[Tuple[int, int]]  # Enemy bomber positions
    mobs: List[Tuple[int, int]]  # Mob positions
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], current_time: float) -> 'GameState':
        """Create GameState from API response (view.PlayerResponse schema)"""
        bombers = [
            Bomber.from_dict(bomber_data, current_time)
            for bomber_data in data.get("bombers", [])
        ]
        
        map_size_data = data.get("map_size", [100, 100])
        map_size = tuple(map_size_data) if isinstance(map_size_data, list) else (100, 100)
        
        arena = data.get("arena", {})
        obstacles = [
            tuple(obs) for obs in arena.get("obstacles", [])
        ]
        
        # Calculate explosion positions from active bombs (cross pattern)
        bombs = arena.get("bombs", [])
        walls = [tuple(w) for w in arena.get("walls", [])]
        explosions = []
        for bomb in bombs:
            bomb_pos_data = bomb.get("pos", [0, 0])
            bomb_pos = tuple(bomb_pos_data) if isinstance(bomb_pos_data, list) else (0, 0)
            bomb_range = bomb.get("range", 1)
            
            # Add bomb position
            explosions.append(bomb_pos)
            
            # Add explosion positions in cross pattern
            x, y = bomb_pos
            directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]
            for dx, dy in directions:
                for r in range(1, bomb_range + 1):
                    exp_pos = (x + dx * r, y + dy * r)
                    # Stop if hit wall
                    if exp_pos in walls:
                        break
                    explosions.append(exp_pos)
        
        enemies = [
            tuple(enemy.get("pos", [0, 0])) for enemy in data.get("enemies", [])
        ]
        
        mobs = [
            tuple(mob.get("pos", [0, 0])) for mob in data.get("mobs", [])
        ]
        
        return cls(
            round_id=str(data.get("round", "")),
            tick=0,  # Not provided in API response
            points=int(data.get("raw_score", 0)),
            bombers=bombers,
            map_size=map_size,
            obstacles=obstacles,
            explosions=explosions,
            enemies=enemies,
            mobs=mobs
        )


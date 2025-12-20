"""
Data models for DatsJingleBang API

Schemas extracted from OpenAPI spec:
- view.PlayerResponse: GET /api/arena response
- command.Player: POST /api/move request
- command.Booster: POST /api/booster request
- view.AvailableBoosterResponse: GET /api/booster response
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field


@dataclass
class Position:
    """2D position on map"""
    x: int
    y: int
    
    def to_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)
    
    @classmethod
    def from_list(cls, data: List[int]) -> 'Position':
        return cls(x=data[0], y=data[1])
    
    def distance_sq(self, other: 'Position') -> int:
        """Squared distance (for vision radius check: r^2 = x^2 + y^2)"""
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy
    
    def manhattan_distance(self, other: 'Position') -> int:
        """Manhattan distance"""
        return abs(self.x - other.x) + abs(self.y - other.y)


@dataclass
class Bomb:
    """Active bomb on arena"""
    pos: Position
    range: int  # Explosion radius
    timer: float  # Seconds until explosion


@dataclass
class Bomber:
    """Player's bomber unit"""
    id: str
    pos: Position
    alive: bool
    can_move: bool  # False if already moving
    bombs_available: int  # Number of bombs can place
    armor: int  # Armor level
    safe_time: int  # Milliseconds of invulnerability remaining


@dataclass
class EnemyBomber:
    """Enemy bomber (in vision)"""
    id: str
    pos: Position
    safe_time: int  # Invulnerability remaining


@dataclass
class Mob:
    """Mob (ghost, patrol, etc.)"""
    id: str
    pos: Position
    type: str  # "ghost", "patrol", etc.
    safe_time: int  # Sleep time remaining (ms), 0 if awake


@dataclass
class ArenaState:
    """Complete arena state from GET /api/arena"""
    bombers: List[Bomber]
    enemies: List[EnemyBomber]
    mobs: List[Mob]
    obstacles: List[Position]  # Destructible obstacles
    walls: List[Position]  # Indestructible walls
    bombs: List[Bomb]
    map_size: Tuple[int, int]  # (width, height)
    round_name: str
    raw_score: int
    player_name: str


class BoosterResponse(BaseModel):
    """Response from GET /api/booster"""
    available: List[Dict[str, Any]] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)
    
    @property
    def points(self) -> int:
        """Available skill points"""
        return self.state.get("points", 0)
    
    @property
    def available_boosters(self) -> List[Dict[str, Any]]:
        """List of available boosters with type and cost"""
        return self.available


def parse_arena_response(data: Dict[str, Any]) -> ArenaState:
    """
    Parse GET /api/arena response into ArenaState.
    
    Response structure (from spec):
    {
        "bombers": [...],
        "enemies": [...],
        "mobs": [...],
        "arena": {
            "walls": [[x, y], ...],
            "obstacles": [[x, y], ...],
            "bombs": [...]
        },
        "map_size": [width, height],
        "round": "round-name",
        "raw_score": 123,
        "player": "player-name"
    }
    """
    bombers = [
        Bomber(
            id=b["id"],
            pos=Position.from_list(b["pos"]),
            alive=b.get("alive", True),
            can_move=b.get("can_move", True),
            bombs_available=b.get("bombs_available", 1),
            armor=b.get("armor", 0),
            safe_time=b.get("safe_time", 0)
        )
        for b in data.get("bombers", [])
    ]
    
    enemies = [
        EnemyBomber(
            id=e["id"],
            pos=Position.from_list(e["pos"]),
            safe_time=e.get("safe_time", 0)
        )
        for e in data.get("enemies", [])
    ]
    
    mobs = [
        Mob(
            id=m["id"],
            pos=Position.from_list(m["pos"]),
            type=m.get("type", "unknown"),
            safe_time=m.get("safe_time", 0)
        )
        for m in data.get("mobs", [])
    ]
    
    arena = data.get("arena", {})
    obstacles = [Position.from_list(obs) for obs in arena.get("obstacles", [])]
    walls = [Position.from_list(w) for w in arena.get("walls", [])]
    
    bombs = [
        Bomb(
            pos=Position.from_list(b["pos"]),
            range=b.get("range", 1),
            timer=b.get("timer", 0.0)
        )
        for b in arena.get("bombs", [])
    ]
    
    map_size_data = data.get("map_size", [100, 100])
    map_size = (map_size_data[0], map_size_data[1])
    
    return ArenaState(
        bombers=bombers,
        enemies=enemies,
        mobs=mobs,
        obstacles=obstacles,
        walls=walls,
        bombs=bombs,
        map_size=map_size,
        round_name=data.get("round", ""),
        raw_score=data.get("raw_score", 0),
        player_name=data.get("player", "")
    )


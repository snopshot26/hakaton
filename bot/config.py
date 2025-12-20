"""
Configuration for DatsJingleBang bot

Extracted from API spec:
- Base URLs: https://games-test.datsteam.dev (test), https://games.datsteam.dev (production)
- Auth: Authorization: Bearer <token> or X-Auth-Token header
- Rate limit: 3 requests per second (global team limit)
- Endpoints:
  - GET /api/arena - Game state
  - POST /api/move - Send commands (path max 30 steps, bombs on path)
  - GET /api/booster - Available upgrades
  - POST /api/booster - Purchase upgrade ({"booster": <integer_index>})
  - GET /api/rounds - Round schedule
- Vision: radius 5 (r^2 = x^2 + y^2)
- Bomb: cross pattern, default radius=1, fuse=8s
- Scoring: obstacles 1+2+3+4 (max 10), kills +10, full wipe -10%
"""
import os
from typing import Optional

# API Configuration
BASE_URL: str = os.getenv("BASE_URL", "https://games-test.datsteam.dev")
API_KEY: Optional[str] = os.getenv("API_KEY", os.getenv("API_TOKEN"))
USE_BEARER: bool = os.getenv("USE_BEARER", "true").lower() == "true"

# Rate Limiting
RATE_LIMIT_PER_SECOND: float = 3.0
RATE_LIMIT_CAPACITY: float = 3.0

# Game Constants (from spec)
VISION_RADIUS: int = 5  # r^2 = x^2 + y^2
DEFAULT_BOMB_RADIUS: int = 1
DEFAULT_BOMB_FUSE: float = 8.0  # seconds
MAX_PATH_LENGTH: int = 30
TICK_INTERVAL_MS: int = 50  # ~50ms per tick (from spec: "about 50ms")
MOB_SLEEP_TIME_MS: int = 10000  # 10 seconds sleep for new mobs
INVULNERABILITY_MS: int = 5000  # 5 seconds after respawn

# Strategy Constants
ANCHOR_COUNT: int = 1
FARMER_COUNT: int = 4
SCOUT_COUNT: int = 1
TOTAL_UNITS: int = 6

# Scoring (from spec)
OBSTACLE_SCORES: list[int] = [1, 2, 3, 4]  # k=1->1pt, k=2->3pt, k=3->6pt, k=4->10pt
KILL_SCORE: int = 10
MOB_KILL_SCORE: int = 10
FULL_WIPE_PENALTY_PCT: float = 0.10  # -10% of current score

# Upgrade Priorities (from spec)
UPGRADE_FUSE: str = "fuse"  # -2s per level, max 3, cost 1
UPGRADE_RANGE: str = "range"  # +1 radius, cost 1
UPGRADE_POCKETS: str = "pockets"  # +1 bomb capacity, cost 1
UPGRADE_SPEED: str = "speed"  # +1 speed, max 3, cost 1
UPGRADE_ACROBATICS: str = "acrobatics"  # pass through obstacles, cost 2
UPGRADE_ARMOR: str = "armor"  # +1 armor, cost 1

# Mob Types (from spec)
MOB_GHOST: str = "ghost"  # Passes obstacles, vision 10, speed 1
MOB_PATROL: str = "patrol"  # Normal movement, speed 1


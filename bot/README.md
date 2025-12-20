# DatsJingleBang Bot

Production-ready Python bot for the DatsJingleBang tournament.

## Strategy

**Goal**: Maximize score while avoiding catastrophic full-team wipe penalty (-10% score).

### Unit Roles

- **4 Farmers**: High-value obstacle bombing (k=2-4 obstacles per bomb)
- **1 Scout**: Explore frontiers, reveal map, opportunistic kills
- **1 Anchor**: Low-risk farming, survival priority (prevents full wipe)

### Bomb Strategy

- **Target Selection**: Prefer k=4 (10 points), then k=3 (6 points), then k=2 (3 points)
- **Safety**: Never plant without guaranteed safe retreat path
- **Scoring**: Obstacles give 1+2+3+4 points (max 10) for k=4 hits

### Scoring Model

- **Obstacles**: k obstacles destroyed = 1+2+...+k points (max 10 for k=4)
- **Kills**: Enemy/mob kill = +10 points
- **Full Wipe**: -10% current score penalty on respawn

### Upgrade Priority

1. Fuse reduction (-2s per level, max 3, cost 1)
2. Range (+1 radius, cost 1)
3. Pockets (+1 bomb capacity, cost 1)
4. Speed (+1 speed, max 3, cost 1)
5. Acrobatics (pass obstacles, cost 2)
6. Armor (+1 armor, cost 1, only if deaths frequent)

## Setup

### Requirements

- Python 3.11+
- pip

### Installation

```bash
pip install -r requirements.txt
```

### Environment Variables

```bash
export BASE_URL="https://games-test.datsteam.dev"  # or https://games.datsteam.dev for production
export API_KEY="your-api-key-here"  # or API_TOKEN
export USE_BEARER="true"  # Use Authorization: Bearer (default), set to "false" for X-Auth-Token
```

### Running

```bash
python -m bot
```

## Project Structure

```
bot/
├── __init__.py
├── config.py              # Configuration and constants
├── api_client.py          # HTTP client for API endpoints
├── models.py              # Data models (Pydantic/dataclasses)
├── rate_limiter.py        # Global rate limiter (3 req/sec)
├── world_model.py         # Persistent map memory with fog-of-war
├── pathfinding.py         # BFS pathfinding
├── danger_map.py          # Blast prediction and mob avoidance
├── main.py                # Main entry point
└── strategy/
    ├── __init__.py
    ├── planner.py          # Candidate action generation
    ├── coordinator.py     # Multi-unit assignment, conflict resolution
    └── upgrades.py        # Upgrade purchase decisions

tests/
├── test_bomb_eval.py      # Bomb evaluation tests
├── test_safety.py         # Safety check tests
└── test_rate_limiter.py   # Rate limiter tests
```

## API Details

Extracted from OpenAPI spec:

- **Base URLs**: 
  - Test: `https://games-test.datsteam.dev`
  - Production: `https://games.datsteam.dev`

- **Endpoints**:
  - `GET /api/arena` - Game state (bombers, enemies, mobs, arena layout)
  - `POST /api/move` - Send commands (path max 30 steps, bombs on path)
  - `GET /api/booster` - Available upgrades and current state
  - `POST /api/booster` - Purchase upgrade (`{"booster": <integer_index>}`)
  - `GET /api/rounds` - Round schedule

- **Authentication**: `Authorization: Bearer <token>` or `X-Auth-Token` header

- **Rate Limit**: 3 requests per second (global team limit)

## Game Mechanics

- **Vision**: Radius 5 (r² = x² + y²)
- **Bombs**: Cross pattern (N/E/S/W), default radius=1, fuse=8s
- **Mobs**: 
  - Ghost: Passes obstacles, vision 10, speed 1
  - Patrol: Normal movement, speed 1
  - Contact kills: Unit dies if on same cell as awake mob
- **Tick Rate**: ~50ms per tick

## Features

- ✅ Global rate limiting (3 req/sec, token bucket)
- ✅ Persistent world model with fog-of-war
- ✅ BFS pathfinding with obstacle/bomb/mob avoidance
- ✅ Danger map with blast prediction and chain reactions
- ✅ Multi-unit coordination with conflict resolution
- ✅ Role-based strategy (Anchor/Farmer/Scout)
- ✅ Upgrade management with priority system
- ✅ Safe retreat path validation
- ✅ Full wipe protection (Anchor survival)

## Testing

```bash
pytest tests/ -v
```

## Logging

The bot logs:
- Unit roles and assignments
- Chosen actions (FARM/SCOUT/EVADE)
- Target bomb cells and retreat positions
- Expected points (k value and score)
- Risk checks and rejections
- Upgrade purchases

## Error Handling

- Exponential backoff on API errors
- Respects `Retry-After` header on 429
- Never crashes: errors are logged and bot continues
- Defensive parsing for missing API fields

## License

MIT


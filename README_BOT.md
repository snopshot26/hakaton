# DatsJingleBang Bot - Complete Implementation

This is a complete, production-ready bot implementation for the DatsJingleBang tournament.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BASE_URL="https://games-test.datsteam.dev"
export API_KEY="your-api-key-here"

# Run bot
python -m bot
```

## Project Structure

The bot is organized in the `bot/` directory:

- **Core Modules**:
  - `api_client.py` - HTTP client with rate limiting
  - `models.py` - Data models (Pydantic/dataclasses)
  - `rate_limiter.py` - Global rate limiter (3 req/sec)
  - `world_model.py` - Persistent map memory
  - `pathfinding.py` - BFS pathfinding
  - `danger_map.py` - Blast prediction and mob avoidance

- **Strategy Modules** (`bot/strategy/`):
  - `planner.py` - Candidate action generation per unit
  - `coordinator.py` - Multi-unit assignment and conflict resolution
  - `upgrades.py` - Upgrade purchase decisions

- **Entry Point**:
  - `main.py` - Main bot orchestrator

## Key Features

1. **Global Rate Limiting**: Token bucket algorithm, 3 req/sec limit
2. **World Model**: Persistent map memory with fog-of-war
3. **Pathfinding**: BFS with obstacle/bomb/mob avoidance
4. **Danger Map**: Blast prediction including chain reactions
5. **Multi-Unit Coordination**: Conflict-free action selection
6. **Role-Based Strategy**: Anchor (survival), Farmers (score), Scout (explore)
7. **Upgrade Management**: Priority-based purchase system
8. **Safety First**: Always validates safe retreat paths

## Strategy Details

### Unit Roles

- **4 Farmers**: Target k=2-4 obstacle bombs (3-10 points)
- **1 Scout**: Explore frontiers, reveal map
- **1 Anchor**: Low-risk farming, prevents full wipe

### Bomb Selection

- Prefer k=4 (10 points), then k=3 (6 points), then k=2 (3 points)
- Always validate safe retreat path before planting
- Avoid re-farming recently destroyed obstacles

### Scoring

- Obstacles: k obstacles = 1+2+...+k points (max 10)
- Kills: +10 points
- Full wipe: -10% score penalty

## Testing

```bash
pytest tests/ -v
```

## API Compliance

All endpoints and schemas are extracted from the OpenAPI spec:
- `GET /api/arena` - Game state
- `POST /api/move` - Send commands
- `GET /api/booster` - Available upgrades
- `POST /api/booster` - Purchase upgrade
- `GET /api/rounds` - Round schedule

Rate limit: 3 requests per second (enforced globally).

## Error Handling

- Exponential backoff on API errors
- Respects `Retry-After` header on 429
- Defensive parsing for missing fields
- Never crashes: errors are logged and bot continues

## Logging

The bot logs:
- Unit roles and actions
- Target cells and expected points
- Risk checks and rejections
- Upgrade purchases
- API errors and retries

## Requirements

- Python 3.11+
- `requests` library
- `pydantic` for data validation
- `pytest` for testing


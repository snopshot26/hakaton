# DatsJingleBang Bot

Production-ready tactical bot for the DatsJingleBang tournament.

## Strategy

- **Win condition**: Maximize placement points through consistent high round ranks
- **Approach**: Low-variance strategy focusing on high score per bomb + survival

### Roles

- **1 Anchor bomber**: Prioritizes survival, avoids mobs/bombs, only low-risk 2+ obstacle bombs
- **3 Farmers**: Main score engine, hunt 2-4 obstacle bombs with safe exits
- **2 Scouts**: Map reveal + opportunistic traps/kills when safe

### Bomb Tile Selection

- Explosion is a cross pattern; each ray stops at first obstacle/bomb
- Evaluate tile by counting obstacle "first hits" in 4 directions => k in [0..4]
- Default: only bomb if k >= 2. Prefer k=3 or k=4
- Safety constraint: ensure post-bomb escape tile outside blast lines

### Scoring

- Obstacle score per bomb capped at 10 total via 1+2+3+4 (max 4 obstacle hits)
- Enemy kill +10, mob kill +10, own death -10, full wipe causes -10% current score
- Tie-breakers: more enemies killed, fewer bombs used, shorter distance traveled

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
python main.py
```

## Project Structure

```
datsjinglebang-bot/
├── src/
│   ├── __init__.py
│   ├── client.py      # HTTP client with rate limiting
│   ├── models.py      # Data models for API responses
│   ├── world.py       # Global map memory
│   ├── planner.py     # Role assignment, target selection, pathing
│   ├── boosters.py    # Booster purchase logic
│   └── bot.py         # Main loop orchestration
├── tests/
│   └── test_planner.py  # Unit tests
├── main.py            # Entry point
├── requirements.txt   # Dependencies
└── README.md         # This file
```

## API Endpoints

- `GET /api/rounds` - Get round schedule
- `GET /api/arena` - Get current arena state
- `POST /api/move` - Send move commands
- `GET /api/booster` - Get available boosters
- `POST /api/booster` - Purchase booster

## Rate Limiting

- Maximum 3 requests per second
- Token bucket rate limiter
- Exponential backoff on 429 responses

## Features

- **World Memory**: Tracks observed tiles, treats unknown as blocked for safety
- **BFS Pathing**: Shortest path finding with max length 30
- **Bomb Scoring**: Evaluates tiles by obstacle "first hits" in cross pattern
- **Role-Based Strategy**: Anchor, Farmers, Scouts with distinct behaviors
- **Booster Management**: Priority-based purchase system
- **Mob Handling**: Avoids contact, respects sleep mechanics

## Testing

```bash
python -m pytest tests/
```

## License

MIT


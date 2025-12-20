# Fix: Bot Not Gaining Points

## Problem Analysis

From the logs, the bot was:
- ✅ Successfully placing bombs: "💣 Bomb placed at (147,27), (144,29), etc."
- ❌ But points remained at 0: "⭐ POINTS: 0"
- ❌ Obstacles were not being destroyed despite bombs exploding

## Root Cause

**Bombs were being placed ON obstacles instead of ADJACENT to them!**

Looking at the code in `src/planner.py`:
- `find_best_target()` was iterating over obstacles
- It called `score_bomb_tile(obstacle, ...)` - placing bomb AT obstacle position
- But **bombs cannot be placed on obstacles** - they must be on empty tiles!

From the game rules:
- Bombs are placed on empty tiles
- Explosion is cross pattern (N/E/S/W)
- Explosion hits obstacles in the blast radius
- You cannot place a bomb on an obstacle cell

## Solution

Changed `find_best_target()` to:
1. **Find empty tiles adjacent to obstacles** (not the obstacles themselves)
2. **Score those empty tiles** based on how many obstacles they can hit
3. **Place bombs on the empty tiles**, not on obstacles

### Code Changes

**Before:**
```python
for obstacle in state.obstacles:
    # Score obstacle position as bomb placement
    target = self.score_bomb_tile(obstacle, state, world, ...)
```

**After:**
```python
# Find adjacent empty tiles where we can place a bomb to hit obstacles
bomb_candidates: Dict[Tuple[int, int], List[Position]] = {}

for obstacle in state.obstacles:
    # For each direction, find empty tile adjacent to obstacle
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        bomb_pos = Position(obstacle.x - dx, obstacle.y - dy)
        
        # Bomb must be on empty tile (not obstacle, not wall, not bomb)
        if world.is_blocked(bomb_pos) or bomb_pos in state.obstacles:
            continue
        
        # Add to candidates
        bomb_candidates[bomb_pos.to_tuple()].append(obstacle)

# Score each bomb position
for bomb_pos_tuple, hit_obstacles in bomb_candidates.items():
    bomb_pos = Position(bomb_pos_tuple[0], bomb_pos_tuple[1])
    target = self.score_bomb_tile(bomb_pos, state, world, ...)  # Score empty tile!
```

## Expected Result

After this fix:
- ✅ Bombs will be placed on empty tiles adjacent to obstacles
- ✅ Explosions will hit obstacles correctly
- ✅ Points will be gained when obstacles are destroyed
- ✅ k-value calculation will be correct (obstacles in blast radius)

## Testing

Run the bot and verify:
1. Logs show bombs placed on empty tiles (not obstacle positions)
2. Points increase when obstacles are destroyed
3. Obstacle count decreases after explosions
4. No more "pointsΔ=+0" when bombs explode

## Additional Notes

- Default `bomb_range` is 1 (from spec: start radius R=1)
- Bomb explosion is cross pattern: N, E, S, W directions
- Each ray stops at first obstacle/bomb/wall
- Scoring: k obstacles = 1+2+...+k points (max 10 for k=4)


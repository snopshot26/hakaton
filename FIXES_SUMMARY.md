# Fixes Summary: Stuck Loop & Rate Limit Issues

## What Changed

### 1. Fixed Escape Path Logic (`src/planner.py`)

**Problem**: Escape path BFS was too strict, rejecting valid escapes when:
- There were 0 bombs (should always find escape)
- Start position was blocked by the bomb being placed
- Allied units were treated as hard walls

**Fix**:
- Added `start_pos` parameter to `_find_escape_position()` to handle bomber's current position
- Escape BFS now allows passing through reserved tiles (allied units), only blocks walls/obstacles/bombs
- When no bombs exist, escape path should always be found
- Improved logging to show why escape paths fail

**Key Changes**:
- Lines 174-260: Enhanced `_find_escape_position()` with proper start_pos handling
- Lines 118-152: Updated `score_bomb_tile()` to pass bomber position to escape path finder

### 2. Enhanced Reservation System (`src/planner.py`)

**Problem**: Multiple units could pick the same destination, causing stacking

**Fix**:
- Added reservation checks before selecting targets
- Reserve both destination AND first step to prevent collisions
- Check reservations in escape path BFS
- Log all reservation decisions

**Key Changes**:
- Lines 42-44: Added `last_steps` tracking to avoid reversing
- Lines 539-548: `reserve_destination()` and `reset_reservations()` methods
- Lines 580-600: Reservation checks before path selection
- Lines 567-568: Escape path respects reservations

### 3. Improved Fallback Logic (`src/planner.py`)

**Problem**: Fallback could cause ping-pong (reversing last step) and congestion

**Fix**:
- `_find_safe_step()` now avoids reversing last step
- Penalizes moves to crowded areas (nearby allies)
- Checks reservations before selecting fallback steps
- Deterministic tie-breaking by position coordinates

**Key Changes**:
- Lines 489-600: Enhanced `_find_safe_step()` with reverse avoidance and crowding penalty
- Lines 587-588: Penalty for reversing
- Lines 590-595: Penalty for moving near allies

### 4. Rate Limit Handling (`src/bot.py`, `src/client.py`)

**Problem**: API spam causing 429 errors, no backoff, planning continued during rate limits

**Fix**:
- Skip planning entirely when rate limited
- Cache arena state per tick (only fetch once)
- Only plan for READY units (skip MOVING units)
- Exponential backoff with proper logging
- Skip command sending when rate limited

**Key Changes**:
- `src/bot.py` lines 50-71: Enhanced arena fetch with rate limit tracking
- `src/bot.py` lines 89-95: Skip MOVING units, log skipped count
- `src/bot.py` lines 130-150: Rate limit check before sending commands
- `src/client.py` lines 121-126: Better 429 handling with attempt tracking

### 5. Enhanced Logging

**Added Logs**:
- `📍 Reserved destination` - when a tile is reserved
- `⏸️ Skipping planning (MOVING state)` - when unit is moving
- `📊 Planning summary` - ready/moving/command counts
- `⚠️ Rate limited, skipping` - when rate limit detected
- `✅ Successfully sent commands` - confirmation of sends
- `⏸️ Target already reserved` - reservation conflicts

### 6. Adaptive Thresholds (Already Implemented)

**Current Behavior**:
- `stuck_count > 20`: Allows k>=0, relaxes escape requirements
- `stuck_count > 10`: Allows k>=0, still requires escape
- `stuck_count <= 10`: Normal (k>=2, then k>=1)

## How to Verify

### 1. Run the Bot and Check Logs

```bash
python main.py
```

**Look for**:
- ✅ No repeated "rejected: no escape path" when there are 0 bombs
- ✅ "Reserved destination" messages showing deconfliction
- ✅ "Skipping planning (MOVING state)" for moving units
- ✅ No repeated "Rate limited (429)" spam
- ✅ Units taking different paths (not clustering)

### 2. Run Tests

```bash
pytest tests/test_reservations.py -v
```

**Tests verify**:
- Two adjacent units don't pick same next tile
- Escape path works with 0 bombs
- Rate limit handling prevents planning

### 3. Manual Verification Scenarios

**Scenario A: No Escape Path Loop**
- Start bot with 0 bombs on map
- Verify units find targets and plant bombs
- Check logs: should see "Selected target" not endless "rejected: no escape path"

**Scenario B: Deconfliction**
- Watch logs for multiple units at same position
- Verify "Reserved destination" messages show different tiles
- Check that units don't stack on same tile

**Scenario C: Rate Limit**
- If 429 occurs, verify:
  - "Rate limited, skipping arena fetch" message
  - Bot waits and retries
  - No command spam during backoff

## Files Modified

1. `src/planner.py` - Escape path, reservations, fallback logic
2. `src/bot.py` - Rate limit handling, MOVING unit skipping, caching
3. `src/client.py` - Better 429 error handling
4. `tests/test_reservations.py` - New test file

## Key Improvements

✅ **Escape paths work correctly** - No false "no escape path" when 0 bombs  
✅ **No unit stacking** - Reservations prevent collisions  
✅ **No API spam** - Only READY units planned, rate limit skips planning  
✅ **Smart fallback** - Avoids reversing, avoids crowded areas  
✅ **Better logging** - Can verify all fixes work  

## Notes

- All changes are minimal and maintain existing interfaces
- Deterministic behavior (tie-breaking by position coordinates)
- Backward compatible (only adds new features, doesn't break existing)
- Test coverage for critical paths (reservations, escape paths, rate limits)


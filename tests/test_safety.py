"""
Tests for safety checks and danger map
"""
import pytest
from bot.models import Position, ArenaState, Bomb
from bot.danger_map import DangerMap


def test_blast_zone_calculation():
    """Test blast zone calculation for bomb"""
    danger = DangerMap()
    
    # Create simple state
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[],
        walls=[],
        bombs=[Bomb(pos=Position(5, 5), range=2, timer=5.0)],
        map_size=(20, 20),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    danger.update(state, current_time=0.0)
    
    # Check that bomb center is in blast zone
    assert (5, 5) in danger.unsafe_cells
    
    # Check that cells in range are unsafe
    # North: (5, 4), (5, 3)
    # East: (6, 5), (7, 5)
    # South: (5, 6), (5, 7)
    # West: (4, 5), (3, 5)
    assert (5, 4) in danger.unsafe_cells or (5, 3) in danger.unsafe_cells


def test_safe_retreat_position():
    """Test finding safe retreat position"""
    danger = DangerMap()
    
    # Create state with bomb
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[],
        walls=[],
        bombs=[Bomb(pos=Position(5, 5), range=2, timer=5.0)],
        map_size=(20, 20),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    danger.update(state, current_time=0.0)
    
    # Find safe retreat from bomb position
    bomb_pos = Position(5, 5)
    start_pos = Position(5, 5)
    retreat = danger.get_safe_retreat_position(
        bomb_pos, bomb_range=2, start_pos=start_pos, state=state, max_steps=8
    )
    
    # Should find a safe position (not in blast zone)
    if retreat:
        assert retreat.to_tuple() not in danger.unsafe_cells


def test_mob_danger():
    """Test mob danger calculation"""
    danger = DangerMap()
    
    # Create state with awake mob
    from bot.models import Mob
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[Mob(id="mob1", pos=Position(10, 10), type="patrol", safe_time=0)],
        obstacles=[],
        walls=[],
        bombs=[],
        map_size=(20, 20),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    danger.update(state, current_time=0.0)
    
    # Mob position should have danger
    assert (10, 10) in danger.mob_danger
    assert danger.mob_danger[(10, 10)] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


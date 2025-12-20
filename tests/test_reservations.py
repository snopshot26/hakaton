"""
Tests for reservation system and deconfliction
"""
import pytest
from src.planner import Planner
from src.models import Bomber, ArenaState, Position
from src.world import WorldMemory


def test_reservation_prevents_clustering():
    """Test that two units starting adjacent do not pick the same next tile"""
    planner = Planner()
    world = WorldMemory()
    
    # Create two bombers at adjacent positions
    bomber1 = Bomber(
        id="bomber1",
        pos=Position(10, 10),
        alive=True,
        can_move=True,
        bombs_available=1,
        armor=0,
        safe_time=0
    )
    bomber2 = Bomber(
        id="bomber2",
        pos=Position(11, 10),  # Adjacent
        alive=True,
        can_move=True,
        bombs_available=1,
        armor=0,
        safe_time=0
    )
    
    # Create minimal state
    state = ArenaState(
        bombers=[bomber1, bomber2],
        enemies=[],
        mobs=[],
        obstacles=[Position(12, 10)],  # One obstacle nearby
        walls=[],
        bombs=[],
        map_size=(50, 50),
        round_name="test",
        player_name="test",
        raw_score=0
    )
    
    world.update(state, 1)
    planner.assign_roles(state.bombers)
    
    # Plan moves for both
    path1, _ = planner.plan_move(bomber1, state, world, 1)
    path2, _ = planner.plan_move(bomber2, state, world, 1)
    
    # If both have paths, they should not have the same first step
    if path1 and path2:
        first_step1 = path1[0].to_tuple()
        first_step2 = path2[0].to_tuple()
        assert first_step1 != first_step2, f"Both units chose same first step: {first_step1}"


def test_escape_path_with_no_bombs():
    """Test that escape path works when there are 0 bombs (should always find escape)"""
    planner = Planner()
    world = WorldMemory()
    
    bomber = Bomber(
        id="bomber1",
        pos=Position(10, 10),
        alive=True,
        can_move=True,
        bombs_available=1,
        armor=0,
        safe_time=0
    )
    
    # State with no bombs
    state = ArenaState(
        bombers=[bomber],
        enemies=[],
        mobs=[],
        obstacles=[Position(12, 10)],
        walls=[],
        bombs=[],  # No bombs
        map_size=(50, 50),
        round_name="test",
        player_name="test",
        raw_score=0
    )
    
    world.update(state, 1)
    
    # Try to score a bomb tile - should find escape since no bombs exist
    target = planner.score_bomb_tile(
        Position(12, 10), state, world, bomber.id, min_k=1, bomber=bomber
    )
    
    # Should find a target with escape path (even if k=1)
    # The escape path should exist since there are no bombs
    if target:
        assert target.escape_pos is not None, "Escape path should exist when no bombs present"


def test_rate_limit_handling():
    """Test that rate limit tracking works correctly"""
    from src.bot import Bot
    from src.client import APIClient
    from unittest.mock import Mock, patch
    
    # Create a mock client that returns None (simulating rate limit)
    mock_client = Mock(spec=APIClient)
    mock_client.get_arena.return_value = None
    
    bot = Bot(mock_client)
    bot.rate_limited = False
    
    # First tick - should mark as rate limited
    bot.tick()
    assert bot.rate_limited == True, "Should mark as rate limited when get_arena returns None"
    
    # Second tick - should skip planning
    initial_tick = bot.tick_count
    bot.tick()
    assert bot.tick_count == initial_tick, "Should not increment tick when rate limited"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


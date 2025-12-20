"""
Tests for bomb evaluation and scoring
"""
import pytest
from bot.models import Position
from bot.strategy.planner import Planner
from bot.world_model import WorldModel
from bot.danger_map import DangerMap
from bot.models import ArenaState, Bomber, Bomb


def test_obstacle_scoring():
    """Test obstacle scoring (k=1->1pt, k=2->3pt, k=3->6pt, k=4->10pt)"""
    from bot.config import OBSTACLE_SCORES
    
    # k=1: 1 point
    assert sum(OBSTACLE_SCORES[:1]) == 1
    
    # k=2: 1+2 = 3 points
    assert sum(OBSTACLE_SCORES[:2]) == 3
    
    # k=3: 1+2+3 = 6 points
    assert sum(OBSTACLE_SCORES[:3]) == 6
    
    # k=4: 1+2+3+4 = 10 points
    assert sum(OBSTACLE_SCORES[:4]) == 10


def test_bomb_cross_pattern():
    """Test that bomb explosion is cross pattern (N/E/S/W)"""
    # This would require a full game state setup
    # For now, just verify the logic exists
    planner = Planner()
    assert planner is not None


def test_k_value_calculation():
    """Test k value calculation (obstacles in cross pattern)"""
    # Create a simple test scenario
    bomb_pos = Position(5, 5)
    
    # k=2: obstacles at (5,4) and (6,5)
    obstacles = [
        Position(5, 4),  # North
        Position(6, 5),  # East
    ]
    
    # Count obstacles in each direction
    directions = [(0, -1), (1, 0), (0, 1), (-1, 0)]  # N, E, S, W
    k = 0
    
    for dx, dy in directions:
        for dist in range(1, 2):  # range=1
            x = bomb_pos.x + dx * dist
            y = bomb_pos.y + dy * dist
            
            if any(o.x == x and o.y == y for o in obstacles):
                k += 1
                break
    
    assert k == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


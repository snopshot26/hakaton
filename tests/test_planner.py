"""
Unit tests for planner module
"""
import pytest
from src.models import Position, ArenaState, Bomber, Bomb
from src.planner import Planner
from src.world import WorldMemory


def test_bomb_tile_scoring_single_obstacle():
    """Test bomb tile scoring with single obstacle"""
    planner = Planner()
    world = WorldMemory()
    
    # Create minimal state
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[Position(5, 5)],
        walls=[],
        bombs=[],
        map_size=(20, 20),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    # Score tile at (4, 5) - should hit obstacle at (5, 5) to the right
    target = planner.score_bomb_tile(Position(4, 5), state, world)
    
    # Should return None (k < 2)
    assert target is None


def test_bomb_tile_scoring_two_obstacles():
    """Test bomb tile scoring with two obstacles"""
    planner = Planner()
    world = WorldMemory()
    
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[
            Position(5, 5),  # Right
            Position(3, 5)   # Left
        ],
        walls=[],
        bombs=[],
        map_size=(20, 20),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    # Score tile at (4, 5) - should hit both obstacles
    target = planner.score_bomb_tile(Position(4, 5), state, world)
    
    # Should return target with k=2
    assert target is not None
    assert target.obstacle_count == 2
    assert target.escape_pos is not None


def test_bomb_tile_scoring_four_obstacles():
    """Test bomb tile scoring with four obstacles (max)"""
    planner = Planner()
    world = WorldMemory()
    
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[
            Position(5, 5),  # Right
            Position(3, 5),  # Left
            Position(4, 6),  # Down
            Position(4, 4)   # Up
        ],
        walls=[],
        bombs=[],
        map_size=(20, 20),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    target = planner.score_bomb_tile(Position(4, 5), state, world)
    
    assert target is not None
    assert target.obstacle_count == 4
    assert target.score > 0


def test_bfs_path_simple():
    """Test BFS pathfinding for simple case"""
    planner = Planner()
    world = WorldMemory()
    
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[],
        walls=[],
        bombs=[],
        map_size=(10, 10),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    start = Position(0, 0)
    goal = Position(3, 3)
    
    path = planner.bfs_path(start, goal, state, world)
    
    assert path is not None
    assert len(path) > 0
    assert path[-1].x == goal.x and path[-1].y == goal.y


def test_bfs_path_blocked():
    """Test BFS pathfinding with blocked path"""
    planner = Planner()
    world = WorldMemory()
    
    # Create wall blocking path
    walls = [Position(1, 0), Position(1, 1), Position(1, 2)]
    for wall in walls:
        world.tiles[wall.to_tuple()] = world.TileInfo(is_wall=True, is_observed=True)
    
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[],
        walls=walls,
        bombs=[],
        map_size=(10, 10),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    start = Position(0, 1)
    goal = Position(2, 1)
    
    path = planner.bfs_path(start, goal, state, world)
    
    # Should find alternative path or return None
    if path:
        assert path[-1].x == goal.x and path[-1].y == goal.y


def test_bfs_path_max_length():
    """Test BFS respects max length"""
    planner = Planner()
    world = WorldMemory()
    
    state = ArenaState(
        bombers=[],
        enemies=[],
        mobs=[],
        obstacles=[],
        walls=[],
        bombs=[],
        map_size=(100, 100),
        round_name="test",
        raw_score=0,
        player_name="test"
    )
    
    start = Position(0, 0)
    goal = Position(50, 50)
    
    path = planner.bfs_path(start, goal, state, world, max_length=30)
    
    # Should either return None or path <= 30
    if path:
        assert len(path) <= 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


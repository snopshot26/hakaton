"""
Bomber decision-making logic
"""
from typing import List, Tuple, Optional, Dict
from core.state import Bomber, GameState
from utils.time import get_current_time


def manhattan_distance(pos1: Tuple[int, int], pos2: Tuple[int, int]) -> int:
    """Calculate Manhattan distance between two positions"""
    return abs(pos1[0] - pos2[0]) + abs(pos1[1] - pos2[1])


def is_position_safe(pos: Tuple[int, int], explosions: List[Tuple[int, int]], map_size: Tuple[int, int]) -> bool:
    """Check if a position is safe from explosions"""
    if pos[0] < 0 or pos[0] >= map_size[0] or pos[1] < 0 or pos[1] >= map_size[1]:
        return False
    
    for exp in explosions:
        if manhattan_distance(pos, exp) <= 1:
            return False
    
    return True


def get_neighbors(pos: Tuple[int, int], map_size: Tuple[int, int]) -> List[Tuple[int, int]]:
    """Get valid neighboring positions"""
    x, y = pos
    neighbors = []
    
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        new_x, new_y = x + dx, y + dy
        if 0 <= new_x < map_size[0] and 0 <= new_y < map_size[1]:
            neighbors.append((new_x, new_y))
    
    return neighbors


def find_safe_path(start: Tuple[int, int], target: Tuple[int, int], 
                   explosions: List[Tuple[int, int]], map_size: Tuple[int, int],
                   max_length: int = 10) -> Optional[List[Tuple[int, int]]]:
    """Find a safe path using simple BFS"""
    if start == target:
        return []
    
    queue = [(start, [start])]
    visited = {start}
    
    while queue and len(queue[0][1]) <= max_length:
        current, path = queue.pop(0)
        
        if current == target:
            return path[1:]  # Exclude start position
        
        for neighbor in get_neighbors(current, map_size):
            if neighbor not in visited and is_position_safe(neighbor, explosions, map_size):
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    
    return None


def find_escape_path(pos: Tuple[int, int], explosions: List[Tuple[int, int]], 
                     map_size: Tuple[int, int], max_length: int = 10) -> Optional[List[Tuple[int, int]]]:
    """Find path to escape from danger"""
    if is_position_safe(pos, explosions, map_size):
        return None  # Already safe
    
    # Try to find a safe position within max_length
    queue = [(pos, [pos])]
    visited = {pos}
    
    while queue and len(queue[0][1]) <= max_length:
        current, path = queue.pop(0)
        
        if is_position_safe(current, explosions, map_size):
            return path[1:]  # Exclude start position
        
        for neighbor in get_neighbors(current, map_size):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    
    return None


def find_nearest_obstacle(pos: Tuple[int, int], obstacles: List[Tuple[int, int]], 
                          explosions: List[Tuple[int, int]], map_size: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """Find nearest obstacle that can be safely farmed"""
    if not obstacles:
        return None
    
    best_obstacle = None
    best_distance = float('inf')
    
    for obstacle in obstacles:
        # Check if obstacle is safe to approach
        if not is_position_safe(obstacle, explosions, map_size):
            continue
        
        distance = manhattan_distance(pos, obstacle)
        if distance < best_distance and distance > 0:
            best_distance = distance
            best_obstacle = obstacle
    
    return best_obstacle


def get_bomber_positions(bombers: List[Bomber]) -> Dict[str, Tuple[int, int]]:
    """Get positions of all alive bombers"""
    return {bomber.id: bomber.position for bomber in bombers if bomber.alive}


def avoid_clustering(pos: Tuple[int, int], other_positions: Dict[str, Tuple[int, int]], 
                     map_size: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """Find a position that avoids clustering with other bombers"""
    neighbors = get_neighbors(pos, map_size)
    
    if not neighbors:
        return None
    
    # Score neighbors by distance to nearest other bomber
    scored = []
    for neighbor in neighbors:
        min_dist = float('inf')
        for other_pos in other_positions.values():
            if other_pos != pos:  # Don't count self
                dist = manhattan_distance(neighbor, other_pos)
                min_dist = min(min_dist, dist)
        
        scored.append((min_dist, neighbor))
    
    # Return neighbor with maximum minimum distance
    scored.sort(reverse=True)
    if scored:
        return scored[0][1]
    
    return None


def decide_bomber_action(bomber: Bomber, state: GameState, max_path_length: int = 10) -> Tuple[Optional[List[Tuple[int, int]]], List[Tuple[int, int]], str]:
    """
    Decide action for a bomber
    
    Returns:
        (path, bombs, reason)
    """
    # Rule 1: If moving, do nothing
    if bomber.moving:
        return None, [], "moving"
    
    # Rule 2: If dead, do nothing
    if not bomber.alive:
        return None, [], "dead"
    
    # Rule 1: Escape danger
    escape_path = find_escape_path(bomber.position, state.explosions, state.map_size, max_path_length)
    if escape_path:
        return escape_path, [], "escape_danger"
    
    # Rule 2: Finish current path (if target exists and is safe)
    if bomber.target and bomber.target != bomber.position:
        if is_position_safe(bomber.target, state.explosions, state.map_size):
            path = find_safe_path(bomber.position, bomber.target, state.explosions, state.map_size, max_path_length)
            if path:
                return path, [], "finish_path"
    
    # Rule 3: Farm nearest obstacle with guaranteed escape
    obstacle = find_nearest_obstacle(bomber.position, state.obstacles, state.explosions, state.map_size)
    if obstacle:
        path = find_safe_path(bomber.position, obstacle, state.explosions, state.map_size, max_path_length)
        if path:
            # Check if we can escape after planting bomb
            bomb_pos = path[-1] if path else bomber.position
            # Simple check: if we're at obstacle, we can plant and move away
            if bomb_pos == obstacle:
                # Find escape position
                escape_neighbors = [n for n in get_neighbors(bomb_pos, state.map_size) 
                                  if n != bomber.position and is_position_safe(n, state.explosions, state.map_size)]
                if escape_neighbors:
                    return path, [bomb_pos], "farm_obstacle"
            elif path:
                return path, [], "move_to_obstacle"
    
    # Rule 4: Spread bombers (avoid clustering)
    other_positions = get_bomber_positions(state.bombers)
    other_positions = {bid: pos for bid, pos in other_positions.items() if bid != bomber.id}
    
    if other_positions:
        spread_pos = avoid_clustering(bomber.position, other_positions, state.map_size)
        if spread_pos:
            path = find_safe_path(bomber.position, spread_pos, state.explosions, state.map_size, max_path_length)
            if path:
                return path, [], "spread"
    
    # Rule 5: Fallback - small movement to stay active
    neighbors = get_neighbors(bomber.position, state.map_size)
    safe_neighbors = [n for n in neighbors if is_position_safe(n, state.explosions, state.map_size)]
    if safe_neighbors:
        # Pick first safe neighbor
        return [safe_neighbors[0]], [], "stay_active"
    
    # No action possible
    return None, [], "no_safe_action"


"""
Advanced tactical decision-making for bombers
"""
from typing import List, Tuple, Optional, Dict
from core.state import Bomber, GameState
from core.tactical_state import TacticalState, FarmMemory, BomberTacticalState
from core.bomber_logic import (
    manhattan_distance, is_position_safe, get_neighbors,
    find_safe_path, find_escape_path
)
import config


def calculate_explosion_radius(bomb_pos: Tuple[int, int], bomb_range: int, 
                             obstacles: List[Tuple[int, int]], 
                             walls: List[Tuple[int, int]],
                             map_size: Tuple[int, int]) -> List[Tuple[int, int]]:
    """Calculate all positions that will be hit by bomb explosion (cross pattern)"""
    explosions = [bomb_pos]
    x, y = bomb_pos
    
    # Directions: up, down, left, right
    directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]
    
    for dx, dy in directions:
        for r in range(1, bomb_range + 1):
            check_pos = (x + dx * r, y + dy * r)
            
            # Check bounds
            if check_pos[0] < 0 or check_pos[0] >= map_size[0]:
                break
            if check_pos[1] < 0 or check_pos[1] >= map_size[1]:
                break
            
            explosions.append(check_pos)
            
            # Stop if hit obstacle or wall
            if check_pos in obstacles or check_pos in walls:
                break
    
    return explosions


def get_all_explosions(state: GameState) -> List[Tuple[int, int]]:
    """Get all current and future explosion positions"""
    explosions = list(state.explosions)
    
    # Add explosions from active bombs (from arena.bombs)
    # Note: We need to get bombs from arena, but for now use state.explosions
    # This should be enhanced to read from arena.bombs if available
    
    return explosions


def determine_tactical_state(bomber: Bomber, state: GameState, 
                            farm_memory: FarmMemory, current_tick: int) -> TacticalState:
    """Determine the tactical state for a bomber"""
    
    # DANGER: Check if bomber is in explosion radius
    explosions = get_all_explosions(state)
    if not is_position_safe(bomber.position, explosions, state.map_size):
        return TacticalState.DANGER
    
    # Check if bomber has active bomb nearby (simplified - check if moving)
    if bomber.moving:
        return TacticalState.WAIT
    
    # WAIT: If no bombs available, wait
    if bomber.bombs_available == 0:
        return TacticalState.WAIT
    
    # FARM: Check if there are valid farm targets
    valid_farm_targets = find_valid_farm_targets(
        bomber, state, farm_memory, current_tick
    )
    if valid_farm_targets:
        return TacticalState.FARM
    
    # RELOCATE: If no targets nearby, relocate
    if not state.obstacles or all(
        manhattan_distance(bomber.position, obs) > 10 
        for obs in state.obstacles
    ):
        return TacticalState.RELOCATE
    
    return TacticalState.IDLE


def find_valid_farm_targets(bomber: Bomber, state: GameState,
                           farm_memory: FarmMemory, current_tick: int) -> List[Tuple[Tuple[int, int], float]]:
    """Find valid farm targets with scores"""
    valid_targets = []
    
    for obstacle in state.obstacles:
        # Skip if recently farmed
        if farm_memory.was_farmed_recently(obstacle, current_tick):
            continue
        
        # Skip if not safe
        if not is_position_safe(obstacle, state.explosions, state.map_size):
            continue
        
        # Calculate score
        score = score_farm_target(
            bomber, obstacle, state, farm_memory, current_tick
        )
        
        if score > 0:  # Only consider positive scores
            valid_targets.append((obstacle, score))
    
    # Sort by score (highest first)
    valid_targets.sort(key=lambda x: x[1], reverse=True)
    return valid_targets


def score_farm_target(bomber: Bomber, target: Tuple[int, int], 
                     state: GameState, farm_memory: FarmMemory,
                     current_tick: int) -> float:
    """Score a farm target (higher is better)"""
    score = 100.0  # Base score
    
    # Penalty for path length
    path = find_safe_path(bomber.position, target, state.explosions, state.map_size, config.MAX_PATH_LENGTH)
    if path is None:
        return -1  # Invalid target
    
    path_length = len(path)
    score -= path_length * 5  # Penalty for longer paths
    
    # Bonus for escape path
    escape_neighbors = [
        n for n in get_neighbors(target, state.map_size)
        if n != bomber.position and is_position_safe(n, state.explosions, state.map_size)
    ]
    if not escape_neighbors:
        return -1  # No escape path
    
    # Penalty for distance to friendly bombers
    min_friendly_dist = float('inf')
    for other_bomber in state.bombers:
        if other_bomber.id != bomber.id and other_bomber.alive:
            dist = manhattan_distance(target, other_bomber.position)
            min_friendly_dist = min(min_friendly_dist, dist)
    
    if min_friendly_dist < 3:  # Too close to friendly
        score -= 50
    
    # Bonus for distance from enemies
    if state.enemies:
        min_enemy_dist = min(
            manhattan_distance(target, enemy) for enemy in state.enemies
        )
        if min_enemy_dist < 5:
            score -= 30  # Penalty for being near enemies
    
    # Check if recently farmed (shouldn't happen due to filter, but double-check)
    if farm_memory.was_farmed_recently(target, current_tick):
        score = -1
    
    return score


def decide_tactical_action(bomber: Bomber, state: GameState,
                           tactical_state: BomberTacticalState,
                           farm_memory: FarmMemory, current_tick: int) -> Tuple[Optional[List[Tuple[int, int]]], List[Tuple[int, int]], str]:
    """Decide action based on tactical state"""
    
    state_enum = tactical_state.state
    
    # DANGER: Only escape
    if state_enum == TacticalState.DANGER:
        escape_path = find_escape_path(
            bomber.position, state.explosions, state.map_size, config.MAX_PATH_LENGTH
        )
        if escape_path:
            return escape_path, [], "escape_danger"
        return None, [], "trapped"
    
    # WAIT: Do nothing
    if state_enum == TacticalState.WAIT:
        return None, [], "waiting"
    
    # FARM: Find best target and farm it
    if state_enum == TacticalState.FARM:
        valid_targets = find_valid_farm_targets(bomber, state, farm_memory, current_tick)
        if valid_targets:
            target, score = valid_targets[0]
            path = find_safe_path(
                bomber.position, target, state.explosions, state.map_size, config.MAX_PATH_LENGTH
            )
            if path:
                # Verify escape path exists
                bomb_pos = path[-1] if path else bomber.position
                escape_neighbors = [
                    n for n in get_neighbors(bomb_pos, state.map_size)
                    if n != bomber.position and is_position_safe(n, state.explosions, state.map_size)
                ]
                if escape_neighbors:
                    farm_memory.mark_farmed(target, current_tick)
                    tactical_state.last_farm_pos = target
                    return path, [bomb_pos], f"farm_obstacle(score={score:.1f})"
    
    # RELOCATE: Move to unexplored area
    if state_enum == TacticalState.RELOCATE:
        # Find direction away from current position and other bombers
        other_positions = {
            b.id: b.position for b in state.bombers 
            if b.id != bomber.id and b.alive
        }
        
        # Try to move to a position far from others
        best_pos = None
        best_score = -1
        
        for dx, dy in [(0, 5), (0, -5), (5, 0), (-5, 0), (3, 3), (3, -3), (-3, 3), (-3, -3)]:
            new_pos = (bomber.position[0] + dx, bomber.position[1] + dy)
            if (0 <= new_pos[0] < state.map_size[0] and 
                0 <= new_pos[1] < state.map_size[1] and
                is_position_safe(new_pos, state.explosions, state.map_size)):
                
                # Score by distance from other bombers
                min_dist = float('inf')
                for other_pos in other_positions.values():
                    dist = manhattan_distance(new_pos, other_pos)
                    min_dist = min(min_dist, dist)
                
                if min_dist > best_score:
                    best_score = min_dist
                    best_pos = new_pos
        
        if best_pos:
            path = find_safe_path(
                bomber.position, best_pos, state.explosions, state.map_size, config.MAX_PATH_LENGTH
            )
            if path:
                return path, [], "relocate"
    
    # IDLE: Small safe movement
    neighbors = get_neighbors(bomber.position, state.map_size)
    safe_neighbors = [
        n for n in neighbors 
        if is_position_safe(n, state.explosions, state.map_size)
    ]
    if safe_neighbors:
        return [safe_neighbors[0]], [], "idle_move"
    
    return None, [], "no_action"


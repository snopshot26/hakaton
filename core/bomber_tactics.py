"""
Advanced tactical decision-making for bombers
"""
from typing import List, Tuple, Optional, Dict
from core.state import Bomber, GameState
from core.tactical_state import TacticalState, FarmMemory, BomberTacticalState
from core.roles import BomberRole, RoleManager
from core.farm_controller import FarmController
from core.zone_control import ZoneControl
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
    
    # Note: state.explosions should already include active bomb positions
    # If we had access to arena.bombs with timer/range, we could calculate future explosions
    # For now, use the explosions list which should contain current danger zones
    
    return explosions


def determine_tactical_state(bomber: Bomber, state: GameState, 
                            farm_memory: FarmMemory, current_tick: int,
                            role_manager: RoleManager,
                            farm_controller: FarmController,
                            zone_control: ZoneControl) -> TacticalState:
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
    
    # FARM: Check if there are valid farm targets (only for farmers)
    role = role_manager.get_role(bomber.id)
    if role == BomberRole.FARMER:
        # FARMERS NEVER GO TO IDLE - must be FARM or RELOCATE
        valid_farm_targets = find_valid_farm_targets(
            bomber, state, farm_memory, current_tick,
            role_manager, farm_controller, zone_control
        )
        if valid_farm_targets:
            return TacticalState.FARM
        # No valid targets - relocate to find new area
        return TacticalState.RELOCATE
    elif role == BomberRole.SCOUT:
        # Scouts never farm, always relocate or explore
        return TacticalState.RELOCATE
    
    # RELOCATE: If no targets nearby, relocate
    if not state.obstacles or all(
        manhattan_distance(bomber.position, obs) > 10 
        for obs in state.obstacles
    ):
        return TacticalState.RELOCATE
    
    return TacticalState.IDLE


def find_valid_farm_targets(bomber: Bomber, state: GameState,
                           farm_memory: FarmMemory, current_tick: int,
                           role_manager: RoleManager,
                           farm_controller: FarmController,
                           zone_control: ZoneControl) -> List[Tuple[Tuple[int, int], float]]:
    """Find valid farm targets with scores (only above threshold)"""
    valid_targets = []
    
    # Only farmers can have farm targets
    role = role_manager.get_role(bomber.id)
    if role != BomberRole.FARMER:
        return []
    
    # Check bootstrap mode (no active farmers)
    bootstrap_mode = len(farm_controller.active_farmers) == 0
    alive_farmers = len([b for b in state.bombers 
                        if b.alive and role_manager.get_role(b.id) == BomberRole.FARMER])
    
    # Check if can start farming
    if not farm_controller.can_start_farming(bomber.id, role, alive_farmers):
        return []  # Can't farm due to limits
    
    for obstacle in state.obstacles:
        # Skip if recently farmed
        if farm_memory.was_farmed_recently(obstacle, current_tick):
            continue
        
        # Skip if not safe
        if not is_position_safe(obstacle, state.explosions, state.map_size):
            continue
        
        # Calculate score
        score = score_farm_target(
            bomber, obstacle, state, farm_memory, current_tick,
            role_manager, farm_controller, zone_control
        )
        
        # Check threshold (with bootstrap mode)
        if score > 0 and farm_controller.meets_threshold(score, bootstrap=bootstrap_mode):
            valid_targets.append((obstacle, score))
    
    # Sort by score (highest first)
    valid_targets.sort(key=lambda x: x[1], reverse=True)
    return valid_targets


def score_farm_target(bomber: Bomber, target: Tuple[int, int], 
                     state: GameState, farm_memory: FarmMemory,
                     current_tick: int, role_manager: RoleManager,
                     farm_controller: FarmController,
                     zone_control: ZoneControl) -> float:
    """Score a farm target with hard threshold (higher is better)"""
    
    # Only farmers can farm
    role = role_manager.get_role(bomber.id)
    if role != BomberRole.FARMER:
        return -1
    
    # Check if can start farming
    if not farm_controller.can_start_farming(bomber.id, role):
        return -1
    
    score = 0.0
    
    # BASE SCORE: Number of obstacles in blast radius
    # Count obstacles that would be destroyed
    obstacles_destroyed = 1  # The target itself
    bomb_range = 2  # Default bomb range (should come from state)
    
    # Count obstacles in cross pattern
    x, y = target
    directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]
    for dx, dy in directions:
        for r in range(1, bomb_range + 1):
            check_pos = (x + dx * r, y + dy * r)
            if check_pos in state.obstacles:
                obstacles_destroyed += 1
    
    # Score heavily favors multiple obstacles
    if obstacles_destroyed == 1:
        score = 20.0
    elif obstacles_destroyed == 2:
        score = 60.0
    elif obstacles_destroyed == 3:
        score = 120.0
    elif obstacles_destroyed >= 4:
        score = 200.0
    
    # Penalty for path length
    path = find_safe_path(bomber.position, target, state.explosions, state.map_size, config.MAX_PATH_LENGTH)
    if path is None:
        return -1  # Invalid target
    
    path_length = len(path)
    score -= path_length * 3  # Penalty for longer paths
    
    # CRITICAL: Escape path check
    escape_neighbors = [
        n for n in get_neighbors(target, state.map_size)
        if n != bomber.position and is_position_safe(n, state.explosions, state.map_size)
    ]
    if not escape_neighbors:
        return -1  # No escape path = invalid
    
    # Penalty for short escape path
    escape_path_length = 1  # At least one step away
    score -= (5 - escape_path_length) * 5  # Penalty if escape is too short
    
    # ZONE CONTROL: Massive penalty for farming outside zone
    zone_penalty = zone_control.get_zone_penalty(bomber.id, target)
    score -= zone_penalty
    
    # Penalty for distance to friendly bombers (blast radius overlap)
    min_friendly_dist = float('inf')
    for other_bomber in state.bombers:
        if other_bomber.id != bomber.id and other_bomber.alive:
            dist = manhattan_distance(target, other_bomber.position)
            min_friendly_dist = min(min_friendly_dist, dist)
            if dist <= bomb_range:  # Would hit friendly
                score -= 100  # Huge penalty
    
    if min_friendly_dist < config.MIN_BOMBER_SPACING:
        score -= 30
    
    # Penalty for being near enemies
    if state.enemies:
        min_enemy_dist = min(
            manhattan_distance(target, enemy) for enemy in state.enemies
        )
        if min_enemy_dist < 5:
            score -= 40
    
    # Check if recently farmed
    if farm_memory.was_farmed_recently(target, current_tick):
        return -1
    
    # Check overlap with active bombs
    for active_bomb_pos in farm_controller.active_bombs.keys():
        if manhattan_distance(target, active_bomb_pos) <= bomb_range:
            score -= 50  # Penalty for overlap
    
    return score


def decide_tactical_action(bomber: Bomber, state: GameState,
                           tactical_state: BomberTacticalState,
                           farm_memory: FarmMemory, current_tick: int,
                           role_manager: RoleManager,
                           farm_controller: FarmController,
                           zone_control: ZoneControl) -> Tuple[Optional[List[Tuple[int, int]]], List[Tuple[int, int]], str]:
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
        role = role_manager.get_role(bomber.id)
        if role == BomberRole.FARMER:
            # Check bootstrap mode
            alive_farmers = len([b for b in state.bombers 
                                if b.alive and role_manager.get_role(b.id) == BomberRole.FARMER])
            
            if farm_controller.can_start_farming(bomber.id, role, alive_farmers):
                valid_targets = find_valid_farm_targets(
                    bomber, state, farm_memory, current_tick,
                    role_manager, farm_controller, zone_control
                )
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
                            # Register farming BEFORE returning (critical fix)
                            farm_controller.start_farming(bomber.id, bomb_pos, current_tick)
                            farm_controller.set_farm_score(bomber.id, score)
                            farm_memory.mark_farmed(target, current_tick)
                            tactical_state.last_farm_pos = target
                            obstacles_count = len([o for o in state.obstacles 
                                                 if manhattan_distance(target, o) <= 2])
                            return path, [bomb_pos], f"farm(score={score:.1f},obs={obstacles_count})"
                else:
                    # No valid targets found - log why
                    from core.logger import SystemLogger
                    logger = SystemLogger()
                    logger.info(f"Bomber {bomber.id[:8]}: No valid farm targets (threshold={farm_controller.hard_threshold:.1f})")
    
    # POST_FARM: Must move away from farm position
    if state_enum == TacticalState.POST_FARM:
        if tactical_state.last_farm_pos:
            current_dist = manhattan_distance(bomber.position, tactical_state.last_farm_pos)
            if current_dist < tactical_state.min_farm_distance:
                # Move further away
                neighbors = get_neighbors(bomber.position, state.map_size)
                safe_neighbors = [
                    n for n in neighbors
                    if is_position_safe(n, state.explosions, state.map_size)
                ]
                # Prefer neighbors further from farm position
                if safe_neighbors:
                    best_neighbor = max(safe_neighbors, 
                                      key=lambda n: manhattan_distance(n, tactical_state.last_farm_pos))
                    return [best_neighbor], [], "post_farm_escape"
        return None, [], "post_farm_wait"
    
    # RELOCATE: Move to unexplored area (scouts and blockers)
    if state_enum == TacticalState.RELOCATE:
        role = role_manager.get_role(bomber.id)
        
        # Scouts: Move to explore new areas, far from team
        if role == BomberRole.SCOUT:
            other_positions = {
                b.id: b.position for b in state.bombers 
                if b.id != bomber.id and b.alive
            }
            
            # Try to move to a position far from others
            best_pos = None
            best_score = -1
            
            # Try various directions
            for dx, dy in [(0, 8), (0, -8), (8, 0), (-8, 0), (6, 6), (6, -6), (-6, 6), (-6, -6)]:
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
                    return path, [], "scout_explore"
        
        # Blockers: Support team, stay near but not too close
        else:
            # Move to support position (near farmers but not too close)
            farmers = [b for b in state.bombers 
                      if b.alive and role_manager.get_role(b.id) == BomberRole.FARMER]
            if farmers:
                # Move near a farmer but maintain spacing
                target_farmer = farmers[0]
                target_pos = target_farmer.position
                
                # Find position near farmer but with spacing
                neighbors = get_neighbors(target_pos, state.map_size)
                safe_neighbors = [
                    n for n in neighbors
                    if is_position_safe(n, state.explosions, state.map_size)
                ]
                if safe_neighbors:
                    path = find_safe_path(
                        bomber.position, safe_neighbors[0], state.explosions, state.map_size, config.MAX_PATH_LENGTH
                    )
                    if path:
                        return path, [], "blocker_support"
        
        # Fallback: small safe movement
        neighbors = get_neighbors(bomber.position, state.map_size)
        safe_neighbors = [
            n for n in neighbors
            if is_position_safe(n, state.explosions, state.map_size)
        ]
        if safe_neighbors:
            return [safe_neighbors[0]], [], "relocate_safe"
    
    # IDLE: Only for non-farmers, and only if truly no action possible
    role = role_manager.get_role(bomber.id)
    if role == BomberRole.FARMER:
        # FARMERS NEVER IDLE_MOVE - should have been caught earlier
        return None, [], "farmer_no_target"
    
    # For non-farmers, small safe movement only if needed
    neighbors = get_neighbors(bomber.position, state.map_size)
    safe_neighbors = [
        n for n in neighbors 
        if is_position_safe(n, state.explosions, state.map_size)
    ]
    if safe_neighbors:
        return [safe_neighbors[0]], [], "idle_move"
    
    return None, [], "no_action"


"""
Tactical planning: role assignment, target selection, pathing
"""
from typing import List, Optional, Tuple, Dict, Set
from collections import deque
from dataclasses import dataclass
from enum import Enum
import logging

from src.models import Bomber, ArenaState, Position, Bomb
from src.world import WorldMemory
from src.reservations import ReservationManager

logger = logging.getLogger(__name__)


class BomberRole(Enum):
    """Bomber roles"""
    ANCHOR = "ANCHOR"  # 1 bomber: survival priority
    FARMER = "FARMER"  # 3 bombers: main score engine
    SCOUT = "SCOUT"    # 2 bombers: map reveal + opportunistic


@dataclass
class BombTarget:
    """Target for bombing"""
    pos: Position
    obstacle_count: int  # k in [0..4]
    score: float
    escape_pos: Optional[Position] = None


class Planner:
    """Tactical planner"""
    
    def __init__(self, reservation_manager: Optional[ReservationManager] = None):
        self.roles: Dict[str, BomberRole] = {}
        self.failed_destinations: Dict[str, List[Tuple[int, int]]] = {}  # bomber_id -> failed dests
        self.destination_cooldown = 20  # Ticks before retrying failed destination
        # Track consecutive "no target found" failures per bomber
        self.no_target_count: Dict[str, int] = {}  # bomber_id -> consecutive failures
        self.stuck_threshold = 5  # N ticks before fallback triggers
        # Track consecutive "no target found" failures per bomber
        self.no_target_count: Dict[str, int] = {}  # bomber_id -> consecutive failures
        self.stuck_threshold = 5  # N ticks before fallback triggers
        # Reservation manager (2-phase system)
        self.reservation_manager = reservation_manager or ReservationManager()
        # Track last step per bomber to avoid reversing
        self.last_steps: Dict[str, Position] = {}  # bomber_id -> last step position
        # Track planned actions per bomber (to prevent replanning in same tick)
        self.planned_actions: Dict[str, Tuple[Optional[List[Position]], Optional[Position]]] = {}
        # Stuck detection: track progress per bomber
        self.last_targets: Dict[str, List[Tuple[int, int]]] = {}  # bomber_id -> list of recent targets
        self.last_positions: Dict[str, List[Tuple[int, int]]] = {}  # bomber_id -> list of recent positions
        self.last_points: Dict[str, List[int]] = {}  # bomber_id -> list of recent points
        self.target_blacklist: Dict[Tuple[int, int], int] = {}  # target -> until_tick (cooldown)
        # Shorter blacklist to avoid over-pruning viable tiles
        self.target_cooldown = 12  # Ticks to blacklist a target
        self.stuck_window = 8  # N ticks to check for stuck
        self.bomb_placements: Dict[str, List[Tuple[int, int, int]]] = {}  # bomber_id -> [(x, y, tick), ...]
        self.pending_explosions: Set[Tuple[int, int]] = set()  # Tiles with pending explosions
        # Cells rejected by API as walls/invalid placements (with TTL)
        self.invalid_bomb_cells: Dict[Tuple[int, int], int] = {}
        self.invalid_cell_ttl = 60  # ticks to avoid cells rejected by server
        # Rejection counters for periodic logging
        self.rejection_stats: Dict[str, int] = {}
    
    def assign_roles(self, bombers: List[Bomber]):
        """
        Assign roles:
        - When >3 alive: play aggressive (no dedicated anchor) → 4 FARMER, 2 SCOUT
        - When <=3 alive: keep 1 ANCHOR for survival, others FARMER/SCOUT
        """
        alive_bombers = [b for b in bombers if b.alive]
        if not alive_bombers:
            return

        # Only reassign if headcount changed
        if len(self.roles) == len(alive_bombers):
            return

        sorted_bombers = sorted(alive_bombers, key=lambda b: b.id)
        old_roles = self.roles.copy()
        self.roles.clear()

        if len(alive_bombers) > 3:
            # Aggressive farming: 4 FARMER, 2 SCOUT
            for idx, bomber in enumerate(sorted_bombers):
                if idx < 4:
                    self.roles[bomber.id] = BomberRole.FARMER
                else:
                    self.roles[bomber.id] = BomberRole.SCOUT
        else:
            # Low population: keep one ANCHOR, rest FARMER/SCOUT
            for idx, bomber in enumerate(sorted_bombers):
                if idx == 0:
                    self.roles[bomber.id] = BomberRole.ANCHOR
                elif idx <= 2:
                    self.roles[bomber.id] = BomberRole.FARMER
                else:
                    self.roles[bomber.id] = BomberRole.SCOUT

        # Log role changes
        for bomber_id, role in self.roles.items():
            if old_roles.get(bomber_id) != role:
                logger.info(f"🎭 {bomber_id[:8]}: Role assigned → {role.value}")
    
    def get_role(self, bomber_id: str) -> BomberRole:
        """Get role for bomber"""
        return self.roles.get(bomber_id, BomberRole.SCOUT)
    
    def score_bomb_tile(self, pos: Position, state: ArenaState, 
                       world: WorldMemory, bomber_id: str = "", min_k: int = 2,
                       require_escape: bool = True, bomber: Optional[Bomber] = None) -> Optional[BombTarget]:
        """
        Score a bomb tile by counting obstacle "first hits" in 4 directions.
        Returns k in [0..4] and escape position.
        """
        directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]  # up, down, left, right
        obstacle_hits = 0
        bomb_range = 1  # Default range is 1 (from spec: start radius R=1)
        hit_directions = []
        
        # Count obstacles that would be "first hit" in each direction
        for dx, dy in directions:
            hit_obstacle = False
            for r in range(1, bomb_range + 1):
                check_pos = Position(pos.x + dx * r, pos.y + dy * r)
                
                # Check bounds
                if (check_pos.x < 0 or check_pos.x >= state.map_size[0] or
                    check_pos.y < 0 or check_pos.y >= state.map_size[1]):
                    break
                
                # Stop at wall
                if world.is_blocked(check_pos):
                    break
                
                # Check for obstacle (first hit)
                if check_pos in state.obstacles:
                    obstacle_hits += 1
                    hit_obstacle = True
                    dir_name = ["UP", "DOWN", "LEFT", "RIGHT"][directions.index((dx, dy))]
                    hit_directions.append(f"{dir_name}@{r}")
                    break
                
                # Stop at existing bomb
                if any(b.pos.x == check_pos.x and b.pos.y == check_pos.y for b in state.bombs):
                    break
        
        # Check minimum k requirement (adaptive)
        if obstacle_hits < min_k:
            if bomber_id:
                logger.debug(f"  {bomber_id[:8]}: Tile ({pos.x},{pos.y}) rejected: k={obstacle_hits} < {min_k}")
            return None
        # Hard block k==0 even if min_k dropped
        if obstacle_hits == 0:
            return None
        
        # Find escape position (outside blast lines)
        # Check if bomber is stuck (consecutive failures)
        is_stuck = self.no_target_count.get(bomber_id, 0) >= self.stuck_threshold
        escape_pos = None
        if require_escape:
            # Get bomber's current position for escape path calculation
            bomber_current_pos = None
            if bomber_id:
                # Find bomber in state to get current position
                for b in state.bombers:
                    if b.id == bomber_id:
                        bomber_current_pos = b.pos
                        break
            
            escape_pos = self._find_escape_position(
                pos, state, world, bomb_range, 
                relaxed=is_stuck, 
                start_pos=bomber.pos if bomber else bomber_current_pos
            )
            if not escape_pos:
                # KAMIKAZE MODE: Even with require_escape=True, allow kamikaze if very stuck
                stuck_count = self.no_target_count.get(bomber_id, 0)
                if stuck_count >= 8:  # Higher threshold when escape was required
                    logger.info(f"💀 {bomber_id[:8]}: KAMIKAZE at ({pos.x},{pos.y}) k={obstacle_hits} - escape required but stuck={stuck_count}")
                    escape_pos = pos  # Die but score
                else:
                    if bomber_id:
                        logger.debug(f"  {bomber_id[:8]}: Tile ({pos.x},{pos.y}) rejected: no escape path (stuck={stuck_count})")
                    return None  # No safe escape
        else:
            # Very stuck: find any safe tile outside blast zone (blast is cross-shaped!)
            new_bomb_blast = {pos.to_tuple()}
            for ddx, ddy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                for r in range(1, bomb_range + 1):
                    bp = Position(pos.x + ddx * r, pos.y + ddy * r)
                    if world.is_blocked(bp) or bp in state.obstacles:
                        break  # Blast stops at obstacles
                    new_bomb_blast.add(bp.to_tuple())
            
            # Search in order: diagonals first (always safe from cross blast), then distance 2
            escape_candidates = [
                # Diagonals (safe from cross pattern)
                (1, 1), (-1, 1), (1, -1), (-1, -1),
                # Distance 2 on cardinals (outside range=1 blast)
                (0, 2), (0, -2), (2, 0), (-2, 0),
                # L-shapes
                (1, 2), (-1, 2), (1, -2), (-1, -2),
                (2, 1), (-2, 1), (2, -1), (-2, -1),
            ]
            for dx, dy in escape_candidates:
                neighbor = Position(pos.x + dx, pos.y + dy)
                if (neighbor.x < 0 or neighbor.x >= state.map_size[0] or
                    neighbor.y < 0 or neighbor.y >= state.map_size[1]):
                    continue
                if world.is_blocked(neighbor) or neighbor in state.obstacles:
                    continue
                # CRITICAL: Must be outside blast of NEW bomb
                if neighbor.to_tuple() in new_bomb_blast:
                    continue
                # Check safety from current bombs
                safe = True
                for bomb in state.bombs:
                    if bomb.timer <= 1.0 and self._in_bomb_blast(neighbor, bomb, state):
                        safe = False
                        break
                if safe:
                    escape_pos = neighbor
                    break
            if not escape_pos:
                # KAMIKAZE MODE: If stuck, allow bombing without escape (score points even if we die)
                stuck_count = self.no_target_count.get(bomber_id, 0)
                # Lower threshold for kamikaze when require_escape=False (we're already desperate)
                kamikaze_threshold = 5  # Lower than before (was 10)
                if stuck_count >= kamikaze_threshold:
                    logger.info(f"💀 {bomber_id[:8]}: KAMIKAZE at ({pos.x},{pos.y}) k={obstacle_hits} - no escape but stuck={stuck_count}")
                    escape_pos = pos  # Stay in place (will die but at least score points)
                else:
                    if bomber_id:
                        logger.debug(f"  {bomber_id[:8]}: Tile ({pos.x},{pos.y}) rejected: no safe escape (stuck={stuck_count}<{kamikaze_threshold})")
                    return None
        
        # Spacing penalties to reduce stacking on same area
        spacing_radius = 4
        spacing_penalty = 6.0  # stronger spacing penalty
        ally_penalty = 0.0
        for ally in state.bombers:
            if ally.id == bomber_id or not ally.alive:
                continue
            dist = abs(ally.pos.x - pos.x) + abs(ally.pos.y - pos.y)
            if dist <= 2:
                ally_penalty += spacing_penalty * (spacing_radius - dist + 1)  # harsh penalty when clustered
            elif dist < spacing_radius:
                ally_penalty += spacing_penalty * (spacing_radius - dist)
        
        reservation_penalty = 0.0
        if self.reservation_manager:
            reserved_positions = list(self.reservation_manager.soft_reservations.keys()) + list(self.reservation_manager.hard_reservations.keys())
            for rx, ry in reserved_positions:
                dist = abs(rx - pos.x) + abs(ry - pos.y)
                if dist < spacing_radius:
                    reservation_penalty += spacing_penalty * (spacing_radius - dist)
        
        # Calculate score using ACTUAL game point values:
        # k=1: 1pt, k=2: 3pts (1+2), k=3: 6pts (1+2+3), k=4: 10pts (1+2+3+4)
        actual_points = sum(range(1, obstacle_hits + 1))  # Triangular number
        score = actual_points * 10.0  # Scale up for better differentiation
        # Extra bonus for k>=3 (strategic value)
        if obstacle_hits >= 3:
            score *= 1.3
        if obstacle_hits >= 4:
            score *= 1.5
        score -= (ally_penalty + reservation_penalty)
        
        if bomber_id:
            logger.debug(
                f"  {bomber_id[:8]}: Tile ({pos.x},{pos.y}) scored: k={obstacle_hits} "
                f"({','.join(hit_directions)}), score={score:.1f}, escape=({escape_pos.x},{escape_pos.y})"
            )
        
        return BombTarget(
            pos=pos,
            obstacle_count=obstacle_hits,
            score=score,
            escape_pos=escape_pos
        )
    
    def _find_escape_position(self, bomb_pos: Position, state: ArenaState,
                              world: WorldMemory, bomb_range: int, 
                              relaxed: bool = False, start_pos: Optional[Position] = None) -> Optional[Position]:
        """
        Find safe escape position outside blast lines using BFS.
        SIMPLIFIED: Just find any tile outside blast zone that's not blocked.
        NO reservation checks - we just need physical reachability.
        """
        directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        blast_positions: Set[Tuple[int, int]] = {bomb_pos.to_tuple()}
        
        # Calculate all blast positions from the bomb we're placing
        for dx, dy in directions:
            for r in range(1, bomb_range + 1):
                check_pos = Position(bomb_pos.x + dx * r, bomb_pos.y + dy * r)
                if (check_pos.x < 0 or check_pos.x >= state.map_size[0] or
                    check_pos.y < 0 or check_pos.y >= state.map_size[1]):
                    break
                blast_positions.add(check_pos.to_tuple())
                # Stop at first obstacle/wall (they block blast)
                if world.is_blocked(check_pos) or check_pos in state.obstacles:
                    break
        
        # GENEROUS max steps: 15 normal, 25 relaxed
        queue = deque()
        visited: Set[Tuple[int, int]] = {bomb_pos.to_tuple()}
        if start_pos:
            visited.add(start_pos.to_tuple())
        max_steps = 25 if relaxed else 15
        
        # Get starting point for BFS
        search_start = start_pos if start_pos and start_pos != bomb_pos else bomb_pos
        
        # Add initial neighbors - ALLOW blast tiles in queue, just don't return them as escape
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            neighbor = Position(search_start.x + dx, search_start.y + dy)
            if (neighbor.x >= 0 and neighbor.x < state.map_size[0] and
                neighbor.y >= 0 and neighbor.y < state.map_size[1]):
                neighbor_tuple = neighbor.to_tuple()
                # Skip blocked tiles (walls/obstacles) - can't walk through
                if world.is_blocked(neighbor) or neighbor in state.obstacles:
                    continue
                # Skip tiles with existing bombs
                if any(b.pos.x == neighbor.x and b.pos.y == neighbor.y for b in state.bombs):
                    continue
                # NO reservation check - just physical reachability
                # NOTE: We allow blast tiles here - we'll check at return time
                
                visited.add(neighbor_tuple)
                queue.append((neighbor, 0))
        
        while queue:
            current, steps = queue.popleft()
            
            if steps >= max_steps:
                continue
            
            current_tuple = current.to_tuple()
            
            # Check if this is a valid escape position (outside blast, not blocked, no bomb)
            in_blast = current_tuple in blast_positions
            is_blocked = world.is_blocked(current) or current in state.obstacles
            has_bomb = any(b.pos.x == current.x and b.pos.y == current.y for b in state.bombs)
            
            if not in_blast and not is_blocked and not has_bomb:
                # Found valid escape!
                return current
            
            # Even if this tile is not valid escape, explore its neighbors
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                neighbor = Position(current.x + dx, current.y + dy)
                
                if (neighbor.x < 0 or neighbor.x >= state.map_size[0] or
                    neighbor.y < 0 or neighbor.y >= state.map_size[1]):
                    continue
                
                neighbor_tuple = neighbor.to_tuple()
                if neighbor_tuple in visited:
                    continue
                
                # Only add if potentially passable (not wall/obstacle)
                if world.is_blocked(neighbor) or neighbor in state.obstacles:
                    visited.add(neighbor_tuple)
                    continue
                
                visited.add(neighbor_tuple)
                queue.append((neighbor, steps + 1))
        
        # FALLBACK: If no escape found in normal BFS, try finding ANY tile outside blast
        # This handles edge cases where paths go through blast zones
        if relaxed:
            for dx in range(-max_steps, max_steps + 1):
                for dy in range(-max_steps, max_steps + 1):
                    if abs(dx) + abs(dy) > max_steps:
                        continue
                    check = Position(bomb_pos.x + dx, bomb_pos.y + dy)
                    if (check.x < 0 or check.x >= state.map_size[0] or
                        check.y < 0 or check.y >= state.map_size[1]):
                        continue
                    check_tuple = check.to_tuple()
                    if check_tuple in blast_positions:
                        continue
                    if world.is_blocked(check) or check in state.obstacles:
                        continue
                    # Found a potential escape - verify path exists
                    start = start_pos if start_pos else bomb_pos
                    test_path = self.bfs_path(start, check, state, world, max_length=max_steps)
                    if test_path is not None:
                        return check
        
        return None
    
    def _is_safe_from_explosions(self, pos: Position, state: ArenaState) -> bool:
        """Check if position is safe from current explosions"""
        for bomb in state.bombs:
            if bomb.timer <= 0.1:  # About to explode
                # Check if in blast radius
                if self._in_bomb_blast(pos, bomb, state):
                    return False
        return True
    
    def _in_bomb_blast(self, pos: Position, bomb: Bomb, state: ArenaState) -> bool:
        """Check if position is in bomb blast radius"""
        if pos.x == bomb.pos.x and pos.y == bomb.pos.y:
            return True
        
        directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        for dx, dy in directions:
            if (pos.x - bomb.pos.x) * dx + (pos.y - bomb.pos.y) * dy < 0:
                continue  # Wrong direction
            if abs((pos.x - bomb.pos.x) * (1 - abs(dx))) + abs((pos.y - bomb.pos.y) * (1 - abs(dy))) > 0:
                continue  # Not aligned
            
            dist = abs(pos.x - bomb.pos.x) + abs(pos.y - bomb.pos.y)
            if dist <= bomb.range:
                return True
        return False

    def _is_friendly_fire_risk(self, bomb_pos: Position, bomber_id: str, state: ArenaState, world: WorldMemory) -> bool:
        """
        Check if placing a bomb at bomb_pos would hit a friendly unit or existing bomb.
        """
        planned_bomb = Bomb(pos=bomb_pos, range=1, timer=8.0)

        # Friendly units in blast
        for ally in state.bombers:
            if ally.id == bomber_id or not ally.alive:
                continue
            if self._in_bomb_blast(ally.pos, planned_bomb, state):
                return True

        # Existing bombs that would be triggered
        for b in state.bombs:
            if self._in_bomb_blast(b.pos, planned_bomb, state):
                return True

        return False
    
    def _is_stuck(self, bomber: Bomber, state: ArenaState, current_tick: int) -> Tuple[bool, str]:
        """
        Check if bomber is stuck. Returns (is_stuck, reason).
        Reasons: same_target, no_movement, no_points
        """
        bomber_id = bomber.id
        current_pos = bomber.pos.to_tuple()
        current_points = state.raw_score
        
        # Initialize tracking
        if bomber_id not in self.last_targets:
            self.last_targets[bomber_id] = []
        if bomber_id not in self.last_positions:
            self.last_positions[bomber_id] = []
        if bomber_id not in self.last_points:
            self.last_points[bomber_id] = []
        
        # Add current state
        self.last_positions[bomber_id].append(current_pos)
        self.last_points[bomber_id].append(current_points)
        
        # Keep only recent history
        self.last_positions[bomber_id] = self.last_positions[bomber_id][-self.stuck_window:]
        self.last_points[bomber_id] = self.last_points[bomber_id][-self.stuck_window:]
        self.last_targets[bomber_id] = self.last_targets[bomber_id][-self.stuck_window:]
        
        # Check for stuck conditions
        if len(self.last_targets[bomber_id]) >= 5:
            # Same target repeated
            recent_targets = self.last_targets[bomber_id][-5:]
            if len(set(recent_targets)) == 1:
                return True, f"same_target={recent_targets[0]}"
        
        if len(self.last_positions[bomber_id]) >= 5:
            # No movement
            recent_positions = self.last_positions[bomber_id][-5:]
            if len(set(recent_positions)) == 1:
                return True, f"no_movement={recent_positions[0]}"
        
        if len(self.last_points[bomber_id]) >= 5:
            # No points growth
            recent_points = self.last_points[bomber_id][-5:]
            if len(set(recent_points)) == 1 and recent_points[0] == 0:
                return True, f"no_points={recent_points[0]}"
        
        return False, ""
    
    def _blacklist_target(self, target_pos: Position, current_tick: int):
        """Add target to blacklist with cooldown"""
        target_tuple = target_pos.to_tuple()
        self.target_blacklist[target_tuple] = current_tick + self.target_cooldown
        logger.warning(f"🚫 Blacklisted target {target_tuple} until tick {self.target_blacklist[target_tuple]}")
    
    def _is_blacklisted(self, target_pos: Position, current_tick: int) -> bool:
        """Check if target is blacklisted"""
        target_tuple = target_pos.to_tuple()
        if target_tuple in self.target_blacklist:
            until_tick = self.target_blacklist[target_tuple]
            if current_tick < until_tick:
                return True
            else:
                # Expired, remove
                del self.target_blacklist[target_tuple]
        return False
    
    def _cleanup_blacklist(self, current_tick: int):
        """Remove expired blacklist entries"""
        expired = [t for t, until in self.target_blacklist.items() if current_tick >= until]
        for target_tuple in expired:
            del self.target_blacklist[target_tuple]

        # Cleanup invalid bomb cells
        expired_invalid = [t for t, until in self.invalid_bomb_cells.items() if current_tick >= until]
        for cell in expired_invalid:
            del self.invalid_bomb_cells[cell]

    def mark_invalid_bomb_cell(self, pos: Position, current_tick: int):
        """Mark cell as invalid for bomb placement due to server rejection (wall, etc.)."""
        self.invalid_bomb_cells[pos.to_tuple()] = current_tick + self.invalid_cell_ttl
        logger.warning(f"🚫 Marked bomb cell invalid {pos.to_tuple()} until tick {self.invalid_bomb_cells[pos.to_tuple()]}")

    def _is_invalid_bomb_cell(self, pos: Position, current_tick: int) -> bool:
        """Check invalid bomb cell TTL."""
        self._cleanup_blacklist(current_tick)
        until = self.invalid_bomb_cells.get(pos.to_tuple())
        return until is not None and current_tick < until
    
    def find_best_target(self, bomber: Bomber, state: ArenaState,
                        world: WorldMemory, current_tick: int = 0) -> Optional[BombTarget]:
        """Find best bomb target for bomber based on role with adaptive threshold"""
        role = self.get_role(bomber.id)
        alive_count = sum(1 for b in state.bombers if b.alive)
        # Enemy proximity check (skip risky bombs when crowded)
        enemy_radius = 6
        enemies_near = [e for e in state.enemies if abs(e.pos.x - bomber.pos.x) + abs(e.pos.y - bomber.pos.y) <= enemy_radius]
        
        if role == BomberRole.ANCHOR:
            # Start with 2+, but can lower adaptively
            base_min_obstacles = 2
            max_risk = True  # Very conservative
        elif role == BomberRole.FARMER:
            # Start with 2+, but can lower adaptively
            base_min_obstacles = 2
            max_risk = False
        else:  # SCOUT
            # Opportunistic only
            return None
        
        # If no obstacles are known at all, avoid bombing attempts
        if len(state.obstacles) == 0:
            return None
        
        # Adaptive threshold based on stuck_count and lack of points
        stuck_count = self.no_target_count.get(bomber.id, 0)
        points_history = self.last_points.get(bomber.id, [])
        stagnant_points = len(points_history) >= 3 and len(set(points_history[-3:])) == 1 and points_history[-1] == state.raw_score
        # Strong stagnation flag for aggressive tightening
        hard_stagnant = len(points_history) >= 6 and len(set(points_history[-6:])) == 1 and points_history[-1] == state.raw_score

        if stuck_count > 10:
            # Very stuck: allow k>=0 and relax escape requirements
            min_obstacles_list = [base_min_obstacles, 1, 0]
            require_escape = False  # Critical: stop requiring escape when stuck!
        elif stuck_count > 5:
            # Moderately stuck: allow k>=1, relaxed escape
            min_obstacles_list = [base_min_obstacles, 1, 0]
            require_escape = True
        else:
            # Normal: try k>=2, then k>=1
            if stagnant_points or alive_count <= 1:
                min_obstacles_list = [base_min_obstacles, 1]
            else:
                min_obstacles_list = [base_min_obstacles, 1]
            require_escape = True
        
        # Cleanup expired blacklist
        self._cleanup_blacklist(current_tick)
        
        # Check if stuck
        is_stuck, stuck_reason = self._is_stuck(bomber, state, current_tick)
        if is_stuck:
            logger.warning(f"⚠️  {bomber.id[:8]} [{role.value}]: STUCK detected: {stuck_reason}")
            # Blacklist recent targets
            if self.last_targets.get(bomber.id):
                for target_tuple in set(self.last_targets[bomber.id][-3:]):
                    target_pos = Position(target_tuple[0], target_tuple[1])
                    self._blacklist_target(target_pos, current_tick)
        # If surrounded by enemies, avoid bombing unless stuck forces action
        if enemies_near and alive_count <= 1 and not is_stuck:
            # Solo survivor under threat: keep exploring/evading, skip bombs
            return None
        if len(enemies_near) >= 3 and not is_stuck:
            return None
        
        # Collect all candidates with scores (for top-K selection)
        all_candidates: List[Tuple[BombTarget, float]] = []
        
        # Try with preferred min_obstacles first, then lower if no results
        for attempt_min in min_obstacles_list:
            logger.debug(f"🔍 {bomber.id[:8]} [{role.value}]: Searching for targets (min_k={attempt_min})")
            
            best_target: Optional[BombTarget] = None
            best_score = -1.0
            candidates_checked = 0
            candidates_rejected = 0
            rejection_reasons: Dict[str, int] = {}
            
            # Search nearby obstacles and find adjacent empty tiles for bomb placement
            # CRITICAL: Bombs must be placed on EMPTY tiles adjacent to obstacles, NOT on obstacles themselves!
            # Prefer closer targets to speed up scoring (hard_stagnant tightens more)
            if hard_stagnant:
                search_radius = 6
            else:
                search_radius = 6 if (stagnant_points or alive_count <= 1) else 8
            bomb_candidates: Dict[Tuple[int, int], List[Position]] = {}  # bomb_pos -> list of obstacles it hits
            
            # CRITICAL: Always consider bomber's current position first!
            # The bomber is STANDING on an empty tile, so it's always valid for bombing
            bomber_pos_key = bomber.pos.to_tuple()
            bomb_candidates: Dict[Tuple[int, int], List[Position]] = {}
            bomb_candidates[bomber_pos_key] = []
            
            # Check what obstacles the bomber's current position can hit
            bomb_range = 1  # Default range is 1 (spec)
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                for r in range(1, bomb_range + 1):
                    check_pos = Position(bomber.pos.x + dx * r, bomber.pos.y + dy * r)
                    if (check_pos.x < 0 or check_pos.x >= state.map_size[0] or
                        check_pos.y < 0 or check_pos.y >= state.map_size[1]):
                        break
                    if world.is_blocked(check_pos):
                        break
                    if check_pos in state.obstacles:
                        bomb_candidates[bomber_pos_key].append(check_pos)
                        break
            
            for obstacle in state.obstacles:
                dist = abs(obstacle.x - bomber.pos.x) + abs(obstacle.y - bomber.pos.y)
                if dist > search_radius:
                    continue
                
                candidates_checked += 1
                
                # Check blacklist (for the obstacle, not bomb pos)
                if self._is_blacklisted(obstacle, current_tick):
                    rejection_reasons["blacklisted"] = rejection_reasons.get("blacklisted", 0) + 1
                    candidates_rejected += 1
                    continue
                
                # Check if pending explosion
                if obstacle.to_tuple() in self.pending_explosions:
                    rejection_reasons["pending_explosion"] = rejection_reasons.get("pending_explosion", 0) + 1
                    candidates_rejected += 1
                    continue
                
                # Find adjacent empty tiles where we can place a bomb to hit this obstacle
                # Bomb explosion is cross pattern, so we need empty tile adjacent to obstacle
                for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:  # N, E, S, W
                    # Check if obstacle is in this direction from a potential bomb position
                    # We want to place bomb at (obstacle.x - dx*r, obstacle.y - dy*r) where r=1
                    bomb_pos = Position(obstacle.x - dx, obstacle.y - dy)
                    
                    # Bounds check
                    if (bomb_pos.x < 0 or bomb_pos.x >= state.map_size[0] or
                        bomb_pos.y < 0 or bomb_pos.y >= state.map_size[1]):
                        continue
                    
                    # Bomber's current position is ALWAYS valid (they're standing there!)
                    if bomb_pos.to_tuple() == bomber_pos_key:
                        if obstacle not in bomb_candidates[bomber_pos_key]:
                            bomb_candidates[bomber_pos_key].append(obstacle)
                        continue
                    
                    # Bomb must be on a confirmed empty, observed tile (not wall/obstacle/bomb)
                    tile_info = world.tiles.get(bomb_pos.to_tuple())
                    if not tile_info or not tile_info.is_observed:
                        continue  # unknown → treat as blocked for placement (safe)
                    if tile_info.is_wall or tile_info.is_obstacle:
                        continue
                    if bomb_pos in state.walls:
                        continue
                    if any(b.pos.x == bomb_pos.x and b.pos.y == bomb_pos.y for b in state.bombs):
                        continue

                    # Skip cells the server already rejected as walls
                    if self._is_invalid_bomb_cell(bomb_pos, current_tick):
                        rejection_reasons["api_invalid"] = rejection_reasons.get("api_invalid", 0) + 1
                        continue
                    
                    # Check if reserved
                    if self.is_reserved(bomb_pos, bomber.id):
                        continue
                    
                    # Add to candidates: this bomb_pos can hit this obstacle
                    bomb_key = bomb_pos.to_tuple()
                    if bomb_key not in bomb_candidates:
                        bomb_candidates[bomb_key] = []
                    bomb_candidates[bomb_key].append(obstacle)
            
            # Now score each bomb position based on how many obstacles it can hit
            for bomb_pos_tuple, hit_obstacles in bomb_candidates.items():
                bomb_pos = Position(bomb_pos_tuple[0], bomb_pos_tuple[1])
                
                # Skip distant k=1 to prioritize fast scoring (more lenient when stuck)
                dist_to_bomber = abs(bomb_pos.x - bomber.pos.x) + abs(bomb_pos.y - bomber.pos.y)
                k1_max_dist = 8 if hard_stagnant else 6  # More lenient when stuck!
                if attempt_min == 1 and dist_to_bomber > k1_max_dist:
                    rejection_reasons["too_far_k1"] = rejection_reasons.get("too_far_k1", 0) + 1
                    candidates_rejected += 1
                    continue

                # Score this bomb position
                target = self.score_bomb_tile(bomb_pos, state, world, bomber.id, 
                                            min_k=attempt_min, require_escape=require_escape, bomber=bomber)
                if target and target.obstacle_count >= attempt_min:
                    # Block friendly blast
                    if self._is_friendly_fire_risk(target.pos, bomber.id, state, world):
                        rejection_reasons["ally_in_blast"] = rejection_reasons.get("ally_in_blast", 0) + 1
                        candidates_rejected += 1
                        continue

                    # Avoid friendly fire: if any ally in blast cross (range=1, walls/obstacles block)
                    def ally_in_blast(b_pos: Position) -> bool:
                        dirs = [(0,1),(0,-1),(1,0),(-1,0)]
                        for dx,dy in dirs:
                            for r in range(1, 1+1):  # range=1
                                cx, cy = b_pos.x + dx*r, b_pos.y + dy*r
                                if cx < 0 or cx >= state.map_size[0] or cy < 0 or cy >= state.map_size[1]:
                                    break
                                cpos = Position(cx, cy)
                                if world.is_obstacle(cpos) or cpos in state.walls:
                                    break
                                for ally in state.bombers:
                                    if ally.id != bomber.id and ally.alive and ally.pos.x == cx and ally.pos.y == cy:
                                        return True
                                # stop if obstacle blocks further (already handled)
                        return False
                    if ally_in_blast(bomb_pos):
                        rejection_reasons["ally_in_blast"] = rejection_reasons.get("ally_in_blast", 0) + 1
                        candidates_rejected += 1
                        continue
                    
                    # Safety: avoid enemies close to bomb or escape
                    danger_radius = 2
                    enemy_near_bomb = any(abs(e.pos.x - bomb_pos.x) + abs(e.pos.y - bomb_pos.y) <= danger_radius for e in state.enemies)
                    enemy_near_escape = target.escape_pos and any(
                        abs(e.pos.x - target.escape_pos.x) + abs(e.pos.y - target.escape_pos.y) <= danger_radius
                        for e in state.enemies
                    )
                    if enemy_near_bomb or enemy_near_escape:
                        rejection_reasons["enemy_near"] = rejection_reasons.get("enemy_near", 0) + 1
                        candidates_rejected += 1
                        continue
                    
                    # CRITICAL: Verify we can actually REACH the target via path
                    # Special case: if already at target, path is valid (empty list)
                    if bomber.pos.x == target.pos.x and bomber.pos.y == target.pos.y:
                        path_to_target = []  # Already there!
                    else:
                        path_to_target = self.bfs_path(bomber.pos, target.pos, state, world, max_length=14)
                        if path_to_target is None:  # None means no path, [] means already there
                            rejection_reasons["no_path"] = rejection_reasons.get("no_path", 0) + 1
                            candidates_rejected += 1
                            logger.debug(f"  {bomber.id[:8]}: Target ({bomb_pos.x},{bomb_pos.y}) rejected: no path from ({bomber.pos.x},{bomber.pos.y})")
                            continue
                    
                    # Path length check (prefer closer targets)
                    max_path_len = 10
                    if target.obstacle_count >= 2:
                        max_path_len = 12  # Allow longer paths for k>=2
                    if stuck_count >= 5:
                        max_path_len = 14  # More lenient when stuck
                    
                    if len(path_to_target) > max_path_len:
                        rejection_reasons["path_too_long"] = rejection_reasons.get("path_too_long", 0) + 1
                        candidates_rejected += 1
                        continue
                    
                    # Add to candidates - now we know it's reachable!
                    all_candidates.append((target, target.score))
                    
                    if target.score > best_score:
                        best_score = target.score
                        best_target = target
                else:
                    if target is None:
                        rejection_reasons["no_escape"] = rejection_reasons.get("no_escape", 0) + 1
                    else:
                        rejection_reasons["k_too_low"] = rejection_reasons.get("k_too_low", 0) + 1
                    candidates_rejected += 1
            
            if best_target:
                # Check if this target was recently used (cooldown check)
                target_tuple = best_target.pos.to_tuple()
                if bomber.id in self.last_targets and target_tuple in self.last_targets[bomber.id][-3:]:
                    # Recently used, try next best candidate
                    logger.debug(f"⏸️  {bomber.id[:8]}: Target {target_tuple} recently used, trying alternative")
                    # Sort all candidates by score
                    all_candidates.sort(key=lambda x: x[1], reverse=True)
                    # Find next best that's not recently used
                    for candidate, score in all_candidates:
                        candidate_tuple = candidate.pos.to_tuple()
                        if candidate_tuple not in self.last_targets.get(bomber.id, [])[-3:]:
                            best_target = candidate
                            best_score = score
                            break
                    else:
                        # All candidates recently used, use best anyway
                        logger.debug(f"⚠️  {bomber.id[:8]}: All candidates recently used, using best")
                
                # Reset failure counter on success
                self.no_target_count[bomber.id] = 0
                
                # Track target
                if bomber.id not in self.last_targets:
                    self.last_targets[bomber.id] = []
                self.last_targets[bomber.id].append(best_target.pos.to_tuple())
                
                escape_info = f", escape=({best_target.escape_pos.x},{best_target.escape_pos.y})" if best_target.escape_pos else ""
                rejection_summary = ", ".join(f"{k}={v}" for k, v in sorted(rejection_reasons.items())[:3])
                
                if attempt_min < base_min_obstacles:
                    logger.info(
                        f"✅ {bomber.id[:8]} [{role.value}]: Selected target (lowered threshold to k>={attempt_min}) "
                        f"({best_target.pos.x},{best_target.pos.y}) k={best_target.obstacle_count}, "
                        f"score={best_target.score:.1f}{escape_info} (checked {candidates_checked}, rejected {candidates_rejected}: {rejection_summary})"
                    )
                else:
                    logger.info(
                        f"✅ {bomber.id[:8]} [{role.value}]: Selected target ({best_target.pos.x},{best_target.pos.y}) "
                        f"k={best_target.obstacle_count}, score={best_target.score:.1f}{escape_info} "
                        f"(checked {candidates_checked}, rejected {candidates_rejected}: {rejection_summary})"
                    )
                return best_target
        
        # No target found even with k>=1
        # Increment failure counter
        self.no_target_count[bomber.id] = self.no_target_count.get(bomber.id, 0) + 1
        
        # Log top candidates for debugging
        if all_candidates:
            top_candidates = sorted(all_candidates, key=lambda x: x[1], reverse=True)[:3]
            top_info = ", ".join(
                f"({c.pos.x},{c.pos.y}) k={c.obstacle_count} score={s:.1f}"
                for c, s in top_candidates
            )
            logger.debug(
                f"❌ {bomber.id[:8]} [{role.value}]: No valid target found "
                f"(checked {candidates_checked}, rejected {candidates_rejected}, stuck_count={self.no_target_count[bomber.id]})"
            )
            logger.debug(f"   Top candidates: {top_info}")
        else:
            logger.debug(
                f"❌ {bomber.id[:8]} [{role.value}]: No valid target found "
                f"(checked {candidates_checked}, all rejected, stuck_count={self.no_target_count[bomber.id]})"
            )
        
        return None
    
    def bfs_path(self, start: Position, goal: Position, state: ArenaState,
                world: WorldMemory, max_length: int = 30) -> Optional[List[Position]]:
        """BFS shortest path, max length 30"""
        if start.x == goal.x and start.y == goal.y:
            return []
        
        queue = deque([(start, [start])])
        visited: Set[Tuple[int, int]] = {start.to_tuple()}
        
        while queue:
            current, path = queue.popleft()
            
            if len(path) > max_length:
                continue  # Too long
            
            if current.x == goal.x and current.y == goal.y:
                return path[1:]  # Exclude start
            
            # Check neighbors
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                neighbor = Position(current.x + dx, current.y + dy)
                
                # Bounds check
                if (neighbor.x < 0 or neighbor.x >= state.map_size[0] or
                    neighbor.y < 0 or neighbor.y >= state.map_size[1]):
                    continue
                
                neighbor_tuple = neighbor.to_tuple()
                if neighbor_tuple in visited:
                    continue
                
                # Blocked check
                if world.is_blocked(neighbor):
                    continue
                
                # Check for bombs (can't pass through)
                if any(b.pos.x == neighbor.x and b.pos.y == neighbor.y for b in state.bombs):
                    continue
                
                # Check for mobs (contact kills) - only awake mobs (safe_time <= 0)
                if any(m.pos.x == neighbor.x and m.pos.y == neighbor.y 
                      for m in state.mobs if m.safe_time <= 0):  # Only awake mobs
                    continue
                
                visited.add(neighbor_tuple)
                queue.append((neighbor, path + [neighbor]))
        
        return None
    
    def _find_open_space(self, bomber: Bomber, state: ArenaState, 
                        world: WorldMemory, exclude_reserved: bool = True) -> Optional[Position]:
        """
        Find nearest open space with fewer obstacles nearby (frontier exploration).
        Used as fallback when no valid targets found.
        """
        # Search in expanding radius for open space
        max_radius = 15
        best_pos: Optional[Position] = None
        best_score = -1
        
        for radius in range(3, max_radius + 1, 2):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    # Manhattan distance check
                    if abs(dx) + abs(dy) > radius:
                        continue
                    
                    candidate = Position(bomber.pos.x + dx, bomber.pos.y + dy)
                    
                    # Bounds check
                    if (candidate.x < 0 or candidate.x >= state.map_size[0] or
                        candidate.y < 0 or candidate.y >= state.map_size[1]):
                        continue
                    
                    # Must be walkable
                    if world.is_blocked(candidate):
                        continue
                    
                    # Must not have bomb
                    if any(b.pos.x == candidate.x and b.pos.y == candidate.y for b in state.bombs):
                        continue
                    
                    # Check if reserved by another agent
                    if exclude_reserved and self.is_reserved(candidate, None):
                        continue
                    
                    # Count obstacles in small radius (fewer = better)
                    obstacle_count = 0
                    for obs in state.obstacles:
                        dist = abs(obs.x - candidate.x) + abs(obs.y - candidate.y)
                        if dist <= 3:
                            obstacle_count += 1
                    
                    # Score: prefer fewer obstacles, closer to current position
                    distance_penalty = abs(dx) + abs(dy)
                    score = 100.0 - obstacle_count * 10.0 - distance_penalty * 0.5
                    
                    if score > best_score:
                        best_score = score
                        best_pos = candidate
        
        return best_pos
    
    def _find_safe_step(self, bomber: Bomber, state: ArenaState, 
                       world: WorldMemory, last_step: Optional[Position] = None,
                       ignore_reservations: bool = False) -> Optional[Position]:
        """
        Find any safe single step (always-act fallback).
        Returns a safe neighbor position, or None if truly no safe move exists.
        
        Args:
            last_step: Previous step position to avoid reversing (if known)
            ignore_reservations: If True, ignore soft reservations (for very stuck units)
        """
        # SPREAD OUT: Rotate direction order based on bomber ID to avoid clustering
        base_dirs = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        id_hash = sum(ord(c) for c in bomber.id[:8]) % 4
        directions = base_dirs[id_hash:] + base_dirs[:id_hash]  # Rotate based on ID
        
        neighbors = []
        for dx, dy in directions:
            neighbor = Position(bomber.pos.x + dx, bomber.pos.y + dy)
            if (neighbor.x >= 0 and neighbor.x < state.map_size[0] and
                neighbor.y >= 0 and neighbor.y < state.map_size[1]):
                neighbors.append(neighbor)
        
        # Score neighbors: prefer unblocked, unreserved, safe from explosions, not reversing
        scored = []
        for neighbor in neighbors:
            # Skip if blocked (walls/obstacles only - NOT allied units)
            if world.is_blocked(neighbor) or neighbor in state.obstacles:
                continue
            
            # Skip if has bomb
            if any(b.pos.x == neighbor.x and b.pos.y == neighbor.y for b in state.bombs):
                continue
            
            # Skip if reserved by another agent (unless ignoring reservations)
            if not ignore_reservations and self.is_reserved(neighbor, bomber.id):
                logger.debug(f"  {bomber.id[:8]}: Neighbor ({neighbor.x},{neighbor.y}) reserved, skipping")
                continue
            
            # Check immediate safety from existing bombs
            safe = True
            for bomb in state.bombs:
                if bomb.timer <= 1.5 and self._in_bomb_blast(neighbor, bomb, state):
                    safe = False
                    break
            
            if safe:
                # Score: prefer unreserved, fewer nearby obstacles, not reversing
                obstacle_count = sum(
                    1 for obs in state.obstacles
                    if abs(obs.x - neighbor.x) + abs(obs.y - neighbor.y) <= 2
                )
                score = 100.0 - obstacle_count * 5.0
                
                # Penalty for reversing (if we know last step)
                if last_step and neighbor.x == last_step.x and neighbor.y == last_step.y:
                    score -= 20.0
                
                # Bonus for moving to less crowded area (fewer nearby allies)
                nearby_allies = sum(
                    1 for b in state.bombers
                    if b.alive and b.id != bomber.id
                    and abs(b.pos.x - neighbor.x) + abs(b.pos.y - neighbor.y) <= 1
                )
                score -= nearby_allies * 10.0
                
                scored.append((score, neighbor))
        
        if scored:
            # Return highest scored neighbor (sort by score only, then by position for determinism)
            scored.sort(key=lambda x: (x[0], -x[1].x, -x[1].y), reverse=True)
            return scored[0][1]
        
        return None

    def _find_frontier_path(self, bomber: Bomber, state: ArenaState, world: WorldMemory,
                            max_length: int = 60) -> Optional[List[Position]]:
        """
        Find a path to the nearest unobserved (frontier) tile to explore more map area.
        Unknown tiles are treated as free (world.is_blocked already allows unknown).
        """
        start = bomber.pos
        queue = deque([(start, [])])
        visited = {start.to_tuple()}
        max_x, max_y = state.map_size
        
        while queue:
            current, path = queue.popleft()
            
            if len(path) > max_length:
                continue
            
            tile = world.tiles.get(current.to_tuple())
            if tile is None or not tile.is_observed:
                return path  # path from start to this frontier tile
            
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = current.x + dx, current.y + dy
                if nx < 0 or nx >= max_x or ny < 0 or ny >= max_y:
                    continue
                npos = Position(nx, ny)
                nt = npos.to_tuple()
                if nt in visited:
                    continue
                if world.is_blocked(npos):
                    continue
                visited.add(nt)
                queue.append((npos, path + [npos]))
        
        return None

    def _find_nearest_bombable_position(self, bomber: Bomber, state: ArenaState,
                                        world: WorldMemory, max_steps: int = 30) -> Optional[List[Position]]:
        """
        BFS to find nearest position where k>=1 (at least one adjacent obstacle).
        Returns the PATH to that position (empty list if already there).
        Only returns reachable positions.
        """
        from collections import deque
        
        # Build obstacle set for fast lookup
        obstacle_set = {obs.to_tuple() for obs in state.obstacles}
        
        def count_adjacent_obstacles(pos: Position) -> int:
            """Count obstacles adjacent to this position (k value)"""
            count = 0
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                adj = (pos.x + dx, pos.y + dy)
                if adj in obstacle_set:
                    count += 1
            return count
        
        # Check if already at a bombable position
        if count_adjacent_obstacles(bomber.pos) >= 1:
            return []  # Already here
        
        # BFS to find nearest bombable position
        start = bomber.pos
        queue = deque([(start, [])])  # (position, path_to_get_there)
        visited = {start.to_tuple()}
        
        while queue:
            current, path = queue.popleft()
            
            if len(path) > max_steps:
                continue
            
            # Check neighbors
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = current.x + dx, current.y + dy
                if nx < 0 or nx >= state.map_size[0] or ny < 0 or ny >= state.map_size[1]:
                    continue
                
                neighbor = Position(nx, ny)
                nt = neighbor.to_tuple()
                
                if nt in visited:
                    continue
                if world.is_blocked(neighbor) or neighbor in state.obstacles:
                    continue
                
                visited.add(nt)
                new_path = path + [neighbor]
                
                # Check if this position has k>=1
                if count_adjacent_obstacles(neighbor) >= 1:
                    return new_path
                
                queue.append((neighbor, new_path))
        
        return None  # No bombable position found

    def _find_obstacle_cluster_target(self, bomber: Bomber, state: ArenaState,
                                      world: WorldMemory, max_radius: int = 12) -> Optional[Position]:
        """
        Find nearest EMPTY TILE adjacent to obstacle cluster within max_radius.
        """
        if not state.obstacles:
            return None
        
        best_tile = None
        best_score = -1
        
        for obs in state.obstacles:
            dist = abs(obs.x - bomber.pos.x) + abs(obs.y - bomber.pos.y)
            if dist > max_radius:
                continue
            
            # Score by obstacle density in radius 2
            density = sum(
                1 for o in state.obstacles
                if abs(o.x - obs.x) + abs(o.y - obs.y) <= 2
            )
            
            # Find empty tile adjacent to this obstacle
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                adj_pos = Position(obs.x + dx, obs.y + dy)
                if (adj_pos.x < 0 or adj_pos.x >= state.map_size[0] or
                    adj_pos.y < 0 or adj_pos.y >= state.map_size[1]):
                    continue
                
                # Must be empty (not wall, not obstacle, not bomb)
                if world.is_blocked(adj_pos):
                    continue
                if any(b.pos.x == adj_pos.x and b.pos.y == adj_pos.y for b in state.bombs):
                    continue
                
                adj_dist = abs(adj_pos.x - bomber.pos.x) + abs(adj_pos.y - bomber.pos.y)
                score = density - adj_dist * 0.5
                
                if score > best_score:
                    best_score = score
                    best_tile = adj_pos
        
        # VERIFY REACHABILITY: Don't return unreachable targets
        if best_tile and (best_tile.x != bomber.pos.x or best_tile.y != bomber.pos.y):
            # Quick check if path exists (use short max_length for speed)
            test_path = self.bfs_path(bomber.pos, best_tile, state, world, max_length=max_radius + 5)
            if test_path is None:
                logger.debug(f"  Cluster target ({best_tile.x},{best_tile.y}) unreachable, skipping")
                best_tile = None
        
        return best_tile
    
    def reset_soft_reservations(self):
        """Reset SOFT reservations for new tick"""
        self.reservation_manager.reset_soft_reservations()
        self.planned_actions.clear()  # Clear planned actions for new tick
    
    def soft_reserve(self, pos: Position, owner: str, next_step: Optional[Position] = None,
                    current_tick: int = 0) -> bool:
        """Create SOFT reservation during planning"""
        return self.reservation_manager.soft_reserve(pos, owner, next_step, current_tick)
    
    def hard_reserve(self, pos: Position, owner: str, next_step: Optional[Position] = None,
                    current_tick: int = 0, ttl: int = 3) -> bool:
        """Create HARD reservation after successful API confirmation"""
        return self.reservation_manager.hard_reserve(pos, owner, next_step, current_tick, ttl)
    
    def is_reserved(self, pos: Position, owner: Optional[str] = None) -> bool:
        """Check if position is reserved (excluding self-reservations)"""
        return self.reservation_manager.is_reserved(pos, owner)
    
    def plan_move(self, bomber: Bomber, state: ArenaState, world: WorldMemory,
                 current_tick: int) -> Tuple[Optional[List[Position]], Optional[Position]]:
        """
        Plan move for bomber. Returns (path, bomb_pos).
        Bomb_pos is None if not bombing.
        
        Prevents replanning in same tick if already planned.
        """
        role = self.get_role(bomber.id)
        
        # Check if can move
        if not bomber.can_move:
            logger.debug(f"⏸️  {bomber.id[:8]} [{role.value}]: Cannot move (already moving)")
            return None, None
        
        # Check if already planned this tick (prevent replanning)
        if bomber.id in self.planned_actions:
            logger.debug(f"⏸️  {bomber.id[:8]} [{role.value}]: Already planned this tick, skipping replanning")
            return self.planned_actions[bomber.id]
        
        # Count alive units for adaptive risk/limits
        alive_count = sum(1 for b in state.bombers if b.alive)
        
        # CRITICAL FIX: Check if CURRENT position has k>=1 - if so, BOMB IMMEDIATELY!
        # This prevents units from wandering after reaching bombable positions
        obstacle_set = {obs.to_tuple() for obs in state.obstacles}
        current_k = sum(
            1 for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]
            if (bomber.pos.x + dx, bomber.pos.y + dy) in obstacle_set
        )
        if current_k >= 1 and bomber.bombs_available > 0:
            # We're at a bombable position with adjacent obstacles - try to bomb!
            stuck_count = self.no_target_count.get(bomber.id, 0)
            logger.info(
                f"🎯 {bomber.id[:8]} [{role.value}]: At bombable pos ({bomber.pos.x},{bomber.pos.y}) "
                f"k={current_k}, bombs={bomber.bombs_available}, stuck={stuck_count}"
            )
            # Try with escape first, then without if stuck
            bomb_target = self.score_bomb_tile(
                bomber.pos, state, world, bomber.id,
                min_k=1, require_escape=True, bomber=bomber
            )
            # If escape fails but we're stuck, try without escape requirement
            if not bomb_target and stuck_count >= 3:
                logger.debug(f"  {bomber.id[:8]}: Retrying bomb without escape (stuck={stuck_count})")
                bomb_target = self.score_bomb_tile(
                    bomber.pos, state, world, bomber.id,
                    min_k=1, require_escape=False, bomber=bomber
                )
            if bomb_target and bomb_target.obstacle_count >= 1:
                logger.info(
                    f"💣 {bomber.id[:8]} [{role.value}]: IMMEDIATE BOMB at current pos "
                    f"({bomber.pos.x},{bomber.pos.y}) k={bomb_target.obstacle_count}"
                )
                self.no_target_count[bomber.id] = 0  # Reset stuck counter
                result = ([], bomb_target.pos)
                self.planned_actions[bomber.id] = result
                return result
            else:
                logger.warning(
                    f"⚠️  {bomber.id[:8]} [{role.value}]: At bombable pos k={current_k} but score_bomb_tile FAILED!"
                )
        
        # Find target based on role
        if role in [BomberRole.ANCHOR, BomberRole.FARMER]:
            # Check if stuck before planning
            is_stuck, stuck_reason = self._is_stuck(bomber, state, current_tick)
            if is_stuck:
                logger.warning(f"⚠️  {bomber.id[:8]} [{role.value}]: STUCK detected in plan_move: {stuck_reason}")
            
            target = self.find_best_target(bomber, state, world, current_tick)
            if target:
                # Check blacklist
                if self._is_blacklisted(target.pos, current_tick):
                    logger.debug(f"⏸️  {bomber.id[:8]} [{role.value}]: Target ({target.pos.x},{target.pos.y}) is blacklisted")
                    target = None
            
            # Process valid target
            if target:
                # Path to target - [] means already there, None means no path
                path = self.bfs_path(bomber.pos, target.pos, state, world)
                if path is not None:  # [] is valid (already at target)!
                    # Adaptive max path length - more aggressive when alone or stuck
                    max_bomb_path = 10  # Increased from 8
                    if target.obstacle_count <= 1:
                        max_bomb_path = 8  # k=1 targets: slightly shorter
                    if alive_count <= 1:
                        max_bomb_path = 12  # Solo: allow longer paths to find targets
                    if is_stuck:
                        max_bomb_path = 14  # Stuck: be more lenient
                    
                    if len(path) > max_bomb_path:
                        logger.debug(
                            f"❌ {bomber.id[:8]} [{role.value}]: Path too long ({len(path)}>{max_bomb_path}) "
                            f"to bomb at ({target.pos.x},{target.pos.y}), skipping"
                        )
                        self.failed_destinations.setdefault(bomber.id, []).append(target.pos.to_tuple())
                        target = None
                        path = None
                    else:
                        # Try to SOFT reserve destination and first step
                        first_step = path[0] if path else None  # path=[] means bomber already at target
                        
                        # If already at target (path=[]), we should place bomb immediately
                        if not path:
                            # Already at target - just return to trigger bomb placement
                            logger.info(
                                f"💣 {bomber.id[:8]} [{role.value}]: Already at bomb position ({target.pos.x},{target.pos.y}), "
                                f"will place bomb (k={target.obstacle_count})"
                            )
                            result = ([], target.pos)  # Empty path = already there
                            self.planned_actions[bomber.id] = result
                            return result
                        
                        if self.soft_reserve(target.pos, bomber.id, first_step, current_tick):
                            # Also reserve first step if different
                            if first_step and first_step != target.pos:
                                self.soft_reserve(first_step, bomber.id, None, current_tick)
                            
                            if first_step:
                                self.last_steps[bomber.id] = first_step
                            
                            logger.info(
                                f"📍 {bomber.id[:8]} [{role.value}]: SOFT reserved destination ({target.pos.x},{target.pos.y}) "
                                f"and first step ({first_step.x},{first_step.y})" if first_step else 
                                f"📍 {bomber.id[:8]} [{role.value}]: SOFT reserved destination ({target.pos.x},{target.pos.y})"
                            )
                            
                            # Store planned action to prevent replanning
                            result = (path, target.pos)
                            self.planned_actions[bomber.id] = result
                            return result
                        else:
                            logger.debug(
                                f"⏸️  {bomber.id[:8]} [{role.value}]: Target "
                                f"({target.pos.x},{target.pos.y}) reservation failed"
                            )
                            target = None
                            path = None
                else:
                    # No path to target
                    logger.debug(f"❌ {bomber.id[:8]} [{role.value}]: No path to target ({target.pos.x},{target.pos.y})")
                    self.failed_destinations.setdefault(bomber.id, []).append(target.pos.to_tuple())
                    target = None
            else:
                # No bomb target found - try exploration
                logger.info(f"🔍 {bomber.id[:8]} [{role.value}]: No reachable bomb targets, exploring...")
                # When very stuck, increase search radius
                stuck_count = self.no_target_count.get(bomber.id, 0)
                search_radius = 20 if stuck_count >= 10 else 10
                cluster_target = self._find_obstacle_cluster_target(bomber, state, world, max_radius=search_radius)
                if cluster_target:
                    path = self.bfs_path(bomber.pos, cluster_target, state, world, max_length=12)
                    if path is not None:  # [] is valid (already at target)
                        # CRITICAL: If already at cluster (path=[]), try to place bomb HERE!
                        if len(path) == 0:
                            # We're at a cluster position - try placing bomb with relaxed requirements
                            bomb_target = self.score_bomb_tile(
                                bomber.pos, state, world, bomber.id, 
                                min_k=1, require_escape=False, bomber=bomber
                            )
                            if bomb_target and bomb_target.obstacle_count >= 1:
                                logger.info(
                                    f"💣 {bomber.id[:8]} [{role.value}]: AT CLUSTER - placing bomb k={bomb_target.obstacle_count}"
                                )
                                result = ([], bomb_target.pos)
                                self.planned_actions[bomber.id] = result
                                return result
                            # Can't bomb here, move away to try elsewhere
                            logger.debug(f"  {bomber.id[:8]}: At cluster but can't bomb, will try frontier")
                        else:
                            # Moving to cluster
                            first_step = path[0]
                            if self.soft_reserve(cluster_target, bomber.id, first_step, current_tick):
                                self.last_steps[bomber.id] = first_step
                                logger.info(
                                    f"🧭 {bomber.id[:8]} [{role.value}]: Moving to obstacle cluster at "
                                    f"({cluster_target.x},{cluster_target.y}) (path {len(path)} steps)"
                                )
                                result = (path, None)
                                self.planned_actions[bomber.id] = result
                                return result

                # NEW: BFS search for nearest position with k>=1 (guaranteed reachable)
                bombable_path = self._find_nearest_bombable_position(bomber, state, world, max_steps=30)
                if bombable_path is not None:
                    if len(bombable_path) == 0:
                        # Already at bombable position - place bomb!
                        bomb_target = self.score_bomb_tile(
                            bomber.pos, state, world, bomber.id,
                            min_k=1, require_escape=False, bomber=bomber
                        )
                        if bomb_target and bomb_target.obstacle_count >= 1:
                            logger.info(
                                f"💣 {bomber.id[:8]} [{role.value}]: AT BOMBABLE POS - placing bomb k={bomb_target.obstacle_count}"
                            )
                            result = ([], bomb_target.pos)
                            self.planned_actions[bomber.id] = result
                            return result
                    else:
                        first_step = bombable_path[0]
                        dest = bombable_path[-1]
                        if self.soft_reserve(dest, bomber.id, first_step, current_tick):
                            self.last_steps[bomber.id] = first_step
                            logger.info(
                                f"🎯 {bomber.id[:8]} [{role.value}]: Moving to bombable position "
                                f"({dest.x},{dest.y}) (path {len(bombable_path)} steps)"
                            )
                            result = (bombable_path, None)
                            self.planned_actions[bomber.id] = result
                            return result

                frontier_path = self._find_frontier_path(bomber, state, world, max_length=40)
                if frontier_path is not None and len(frontier_path) > 0:  # Need actual movement
                    first_step = frontier_path[0]
                    dest = frontier_path[-1]
                    if self.soft_reserve(dest, bomber.id, first_step, current_tick):
                        self.soft_reserve(first_step, bomber.id, None, current_tick)
                        self.last_steps[bomber.id] = first_step
                        logger.info(
                            f"🧭 {bomber.id[:8]} [{role.value}]: Exploring frontier to "
                            f"({dest.x},{dest.y}) (path {len(frontier_path)} steps)"
                        )
                        result = (frontier_path, None)
                        self.planned_actions[bomber.id] = result
                        return result
                
                # No target found - check if stuck and use fallback
                stuck_count = self.no_target_count.get(bomber.id, 0)
                if stuck_count >= self.stuck_threshold:
                    logger.info(
                        f"🔄 {bomber.id[:8]} [{role.value}]: STUCK (failures={stuck_count}), "
                        f"using fallback: move to open space"
                    )
                    open_space = self._find_open_space(bomber, state, world, exclude_reserved=True)
                    if open_space and not self.is_reserved(open_space, bomber.id):
                        path = self.bfs_path(bomber.pos, open_space, state, world, max_length=30)
                        if path:
                            first_step = path[0] if path else None
                            if self.soft_reserve(open_space, bomber.id, first_step, current_tick):
                                if first_step:
                                    self.last_steps[bomber.id] = first_step
                                logger.info(
                                    f"🗺️  {bomber.id[:8]} [{role.value}]: Fallback path to open space: "
                                    f"({bomber.pos.x},{bomber.pos.y}) → ({open_space.x},{open_space.y}) "
                                    f"({len(path)} steps) [SOFT RESERVED]"
                                )
                                # Reset stuck counter on fallback movement
                                self.no_target_count[bomber.id] = max(0, stuck_count - 2)
                                result = (path, None)
                                self.planned_actions[bomber.id] = result
                                return result
                    
                    # If open space fallback failed, try MOVE TO CENTER to escape corner
                    center_x, center_y = state.map_size[0] // 2, state.map_size[1] // 2
                    # Direction towards center based on bomber ID to spread out
                    id_offset = (sum(ord(c) for c in bomber.id[:8]) % 20) - 10
                    target_x = min(max(5, center_x + id_offset), state.map_size[0] - 5)
                    target_y = min(max(5, center_y + id_offset), state.map_size[1] - 5)
                    center_target = Position(target_x, target_y)
                    path_to_center = self.bfs_path(bomber.pos, center_target, state, world, max_length=50)
                    if path_to_center and len(path_to_center) > 0:
                        first_step = path_to_center[0]
                        if self.soft_reserve(first_step, bomber.id, first_step, current_tick):
                            self.last_steps[bomber.id] = first_step
                            logger.info(
                                f"🏃 {bomber.id[:8]} [{role.value}]: ESCAPE CORNER → center "
                                f"({target_x},{target_y}) (path {len(path_to_center)} steps)"
                            )
                            self.no_target_count[bomber.id] = max(0, stuck_count - 3)
                            result = (path_to_center, None)
                            self.planned_actions[bomber.id] = result
                            return result
                    
                    # DESPERATE ESCAPE: When very stuck, find LONGEST safe path in any direction
                    if stuck_count >= 15:
                        best_escape_path = None
                        best_escape_len = 0
                        # Try different directions based on bomber ID to spread out
                        dir_options = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]
                        id_hash = sum(ord(c) for c in bomber.id[:8])
                        for i in range(len(dir_options)):
                            dx, dy = dir_options[(i + id_hash) % len(dir_options)]
                            # Try walking 5-20 steps in this direction
                            for dist in [20, 15, 10, 5]:
                                target = Position(
                                    min(max(1, bomber.pos.x + dx * dist), state.map_size[0] - 2),
                                    min(max(1, bomber.pos.y + dy * dist), state.map_size[1] - 2)
                                )
                                if target.x == bomber.pos.x and target.y == bomber.pos.y:
                                    continue
                                path = self.bfs_path(bomber.pos, target, state, world, max_length=60)
                                if path and len(path) > best_escape_len and not self.is_reserved(path[0], bomber.id):
                                    best_escape_path = path
                                    best_escape_len = len(path)
                                    if best_escape_len >= 5:  # Good enough
                                        break
                            if best_escape_len >= 5:
                                break
                        
                        if best_escape_path and len(best_escape_path) > 0:
                            first_step = best_escape_path[0]
                            if self.soft_reserve(first_step, bomber.id, first_step, current_tick):
                                self.last_steps[bomber.id] = first_step
                                dest = best_escape_path[-1]
                                logger.info(
                                    f"🆘 {bomber.id[:8]} [{role.value}]: DESPERATE ESCAPE "
                                    f"→ ({dest.x},{dest.y}) (path {len(best_escape_path)} steps)"
                                )
                                self.no_target_count[bomber.id] = max(0, stuck_count - 5)
                                result = (best_escape_path, None)
                                self.planned_actions[bomber.id] = result
                                return result
                    
                    # If center fallback failed, try always-act safe step
                    # CRITICAL: Ignore reservations if VERY stuck (failures >= 20)
                    ignore_res = stuck_count >= 20
                    last_step = self.last_steps.get(bomber.id)
                    safe_step = self._find_safe_step(bomber, state, world, last_step=last_step, 
                                                    ignore_reservations=ignore_res)
                    if safe_step:
                        # Force reserve even if soft_reserve fails when ignoring reservations
                        reserved = self.soft_reserve(safe_step, bomber.id, safe_step, current_tick)
                        if reserved or ignore_res:
                            self.last_steps[bomber.id] = safe_step
                            mode = "FORCE MOVE (ignoring reservations)" if ignore_res else "SOFT RESERVED"
                            logger.info(
                                f"🔄 {bomber.id[:8]} [{role.value}]: Always-act fallback: "
                                f"single safe step to ({safe_step.x},{safe_step.y}) [{mode}]"
                            )
                            self.no_target_count[bomber.id] = max(0, stuck_count - 1)
                            result = ([safe_step], None)
                            self.planned_actions[bomber.id] = result
                            return result
        
        # Scout: explore or relocate
        if role == BomberRole.SCOUT:
            logger.debug(f"🔎 {bomber.id[:8]} [{role.value}]: Exploring new area")
            # Move to unexplored area - avoid repeating same path
            explored = world.get_observed_area()
            # Try different directions to avoid loops
            directions = [(5, 0), (-5, 0), (0, 5), (0, -5), (7, 0), (-7, 0), (0, 7), (0, -7)]
            for dx, dy in directions:
                target = Position(bomber.pos.x + dx, bomber.pos.y + dy)
                if (target.x >= 0 and target.x < state.map_size[0] and
                    target.y >= 0 and target.y < state.map_size[1]):
                    # Check if we've tried this destination recently
                    failed_dests = self.failed_destinations.get(bomber.id, [])
                    target_tuple = target.to_tuple()
                    if target_tuple in failed_dests[-3:]:  # Avoid last 3 failed destinations
                        continue
                    
                    # Check if destination is reserved by another agent
                    if self.is_reserved(target, bomber.id):
                        continue
                    
                    path = self.bfs_path(bomber.pos, target, state, world, max_length=15)
                    if path:
                        first_step = path[0] if path else None
                        if self.soft_reserve(target, bomber.id, first_step, current_tick):
                            logger.debug(
                                f"🗺️  {bomber.id[:8]} [{role.value}]: Exploration path: "
                                f"({bomber.pos.x},{bomber.pos.y}) → ({target.x},{target.y}) "
                                f"({len(path)} steps) [SOFT RESERVED]"
                            )
                            result = (path, None)
                            self.planned_actions[bomber.id] = result
                            return result
            
            # If all exploration directions failed, try open space fallback
            logger.debug(f"🔄 {bomber.id[:8]} [{role.value}]: Exploration failed, trying open space fallback")
            open_space = self._find_open_space(bomber, state, world, exclude_reserved=True)
            if open_space and not self.is_reserved(open_space, bomber.id):
                path = self.bfs_path(bomber.pos, open_space, state, world, max_length=20)
                if path:
                    first_step = path[0] if path else None
                    if self.soft_reserve(open_space, bomber.id, first_step, current_tick):
                        if first_step:
                            self.last_steps[bomber.id] = first_step
                        logger.info(
                            f"🗺️  {bomber.id[:8]} [{role.value}]: Fallback path to open space: "
                            f"({bomber.pos.x},{bomber.pos.y}) → ({open_space.x},{open_space.y}) "
                            f"({len(path)} steps) [SOFT RESERVED]"
                        )
                        result = (path, None)
                        self.planned_actions[bomber.id] = result
                        return result
            
            # Always-act fallback for scouts too
            scout_stuck = self.no_target_count.get(bomber.id, 0)
            ignore_res = scout_stuck >= 20
            last_step = self.last_steps.get(bomber.id)
            safe_step = self._find_safe_step(bomber, state, world, last_step=last_step,
                                            ignore_reservations=ignore_res)
            if safe_step:
                reserved = self.soft_reserve(safe_step, bomber.id, safe_step, current_tick)
                if reserved or ignore_res:
                    self.last_steps[bomber.id] = safe_step
                    mode = "FORCE MOVE" if ignore_res else "SOFT RESERVED"
                    logger.info(
                        f"🔄 {bomber.id[:8]} [{role.value}]: Always-act fallback: "
                        f"single safe step to ({safe_step.x},{safe_step.y}) [{mode}]"
                    )
                    result = ([safe_step], None)
                    self.planned_actions[bomber.id] = result
                    return result
        
        # Final always-act fallback (should rarely reach here)
        final_stuck = self.no_target_count.get(bomber.id, 0)
        ignore_res = final_stuck >= 20
        last_step = self.last_steps.get(bomber.id)
        safe_step = self._find_safe_step(bomber, state, world, last_step=last_step,
                                        ignore_reservations=ignore_res)
        if safe_step:
            reserved = self.soft_reserve(safe_step, bomber.id, safe_step, current_tick)
            if reserved or ignore_res:
                self.last_steps[bomber.id] = safe_step
                mode = "FORCE MOVE" if ignore_res else "SOFT RESERVED"
                logger.warning(
                    f"⚠️  {bomber.id[:8]} [{role.value}]: Final always-act fallback: "
                    f"single safe step to ({safe_step.x},{safe_step.y}) [{mode}]"
                )
                result = ([safe_step], None)
                self.planned_actions[bomber.id] = result
                return result
        
        logger.debug(f"⏸️  {bomber.id[:8]} [{role.value}]: No action planned (truly no safe move)")
        return None, None


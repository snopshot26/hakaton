"""
Action planner: generates candidate actions for each unit

Roles:
- FARMER: High-value obstacle bombing (k=2-4)
- SCOUT: Explore frontiers, reveal map
- ANCHOR: Low-risk farming, survival priority

Action types:
- FARM: move -> plant bomb -> retreat
- SCOUT: move to frontier
- EVADE: move to safe zone
"""
from typing import List, Optional, Tuple, Set, Dict
from dataclasses import dataclass
from enum import Enum
import logging

from bot.models import Position, ArenaState, Bomber
from bot.world_model import WorldModel
from bot.danger_map import DangerMap
from bot.pathfinding import bfs_path
from bot.config import (
    OBSTACLE_SCORES, KILL_SCORE, MOB_KILL_SCORE,
    ANCHOR_COUNT, FARMER_COUNT, SCOUT_COUNT
)

logger = logging.getLogger(__name__)


class UnitRole(Enum):
    """Unit role"""
    ANCHOR = "ANCHOR"
    FARMER = "FARMER"
    SCOUT = "SCOUT"


@dataclass
class CandidateAction:
    """Candidate action for a unit"""
    unit_id: str
    role: UnitRole
    action_type: str  # "FARM", "SCOUT", "EVADE"
    path: List[Position]
    bomb_pos: Optional[Position] = None  # Where to plant bomb
    retreat_pos: Optional[Position] = None  # Safe retreat position
    expected_points: float = 0.0
    obstacle_count: int = 0  # k value (0-4)
    path_length: int = 0
    risk_penalty: float = 0.0
    interference_penalty: float = 0.0
    info_gain: float = 0.0  # For scouts
    score: float = 0.0  # Final score


class Planner:
    """
    Generates candidate actions for each unit based on role.
    
    Scoring:
    - FARM: expectedPoints - alpha*pathLen - beta*riskPenalty - gamma*interferencePenalty
    - SCOUT: infoGain - alpha*pathLen - beta*riskPenalty
    - EVADE: -alpha*pathLen - beta*riskPenalty
    """
    
    def __init__(self):
        self.roles: Dict[str, UnitRole] = {}
        self.alpha = 0.1  # Path length penalty
        self.beta = 10.0  # Risk penalty
        self.gamma = 5.0  # Interference penalty
        self.delta = 20.0  # Info gain bonus (for scouts)
    
    def assign_roles(self, bombers: List[Bomber]):
        """Assign roles to bombers (persistent assignment)"""
        alive_bombers = [b for b in bombers if b.alive]
        
        # Maintain existing roles if bomber still alive
        existing_roles = {bid: self.roles[bid] for bid in self.roles.keys()}
        
        # Count existing roles
        anchor_count = sum(1 for r in existing_roles.values() if r == UnitRole.ANCHOR)
        farmer_count = sum(1 for r in existing_roles.values() if r == UnitRole.FARMER)
        scout_count = sum(1 for r in existing_roles.values() if r == UnitRole.SCOUT)
        
        # Assign missing roles
        for bomber in alive_bombers:
            if bomber.id not in self.roles:
                if anchor_count < ANCHOR_COUNT:
                    self.roles[bomber.id] = UnitRole.ANCHOR
                    anchor_count += 1
                elif farmer_count < FARMER_COUNT:
                    self.roles[bomber.id] = UnitRole.FARMER
                    farmer_count += 1
                elif scout_count < SCOUT_COUNT:
                    self.roles[bomber.id] = UnitRole.SCOUT
                    scout_count += 1
                else:
                    # Fallback: assign as farmer
                    self.roles[bomber.id] = UnitRole.FARMER
    
    def generate_candidates(
        self,
        bomber: Bomber,
        state: ArenaState,
        world: WorldModel,
        danger: DangerMap,
        reserved_cells: Set[Tuple[int, int]],
        max_candidates: int = 20
    ) -> List[CandidateAction]:
        """
        Generate candidate actions for a unit.
        
        Args:
            bomber: Unit to plan for
            state: Current arena state
            world: World model
            danger: Danger map
            reserved_cells: Cells reserved by other units
            max_candidates: Maximum candidates to generate
        
        Returns:
            List of candidate actions sorted by score
        """
        if not bomber.alive or not bomber.can_move:
            return []
        
        role = self.roles.get(bomber.id, UnitRole.FARMER)
        candidates = []
        
        if role == UnitRole.FARMER or role == UnitRole.ANCHOR:
            # Generate FARM actions
            farm_candidates = self._generate_farm_actions(
                bomber, state, world, danger, reserved_cells, role == UnitRole.ANCHOR
            )
            candidates.extend(farm_candidates)
        
        if role == UnitRole.SCOUT:
            # Generate SCOUT actions
            scout_candidates = self._generate_scout_actions(
                bomber, state, world, danger, reserved_cells
            )
            candidates.extend(scout_candidates)
        
        # Generate EVADE actions if in danger
        if not danger.is_safe(bomber.pos):
            evade_candidates = self._generate_evade_actions(
                bomber, state, world, danger, reserved_cells
            )
            candidates.extend(evade_candidates)
        
        # Sort by score
        candidates.sort(key=lambda a: a.score, reverse=True)
        return candidates[:max_candidates]
    
    def _generate_farm_actions(
        self,
        bomber: Bomber,
        state: ArenaState,
        world: WorldModel,
        danger: DangerMap,
        reserved_cells: Set[Tuple[int, int]],
        is_anchor: bool
    ) -> List[CandidateAction]:
        """Generate FARM actions (bomb obstacles)"""
        candidates = []
        search_radius = 10
        
        # Min obstacles required (anchor is more conservative)
        min_k = 2 if is_anchor else 2
        if is_anchor:
            # Anchor only takes safest opportunities
            min_k = 3
        
        for obstacle in state.obstacles:
            # Skip if too far
            dist = bomber.pos.manhattan_distance(obstacle)
            if dist > search_radius:
                continue
            
            # Skip if reserved
            if obstacle.to_tuple() in reserved_cells:
                continue
            
            # Skip if recently farmed
            if world.was_farmed_recently(obstacle):
                continue
            
            # Evaluate bomb placement at obstacle
            result = self._evaluate_bomb_tile(
                obstacle, bomber, state, world, danger, is_anchor
            )
            
            if result is None:
                continue
            
            bomb_pos, retreat_pos, k, expected_points = result
            
            # Check if meets minimum k
            if k < min_k:
                continue
            
            # Find path to bomb position
            path = bfs_path(bomber.pos, bomb_pos, state, world, max_length=15)
            if not path:
                continue
            
            # Check if retreat path exists
            if retreat_pos:
                retreat_path = bfs_path(bomb_pos, retreat_pos, state, world, max_length=8)
                if not retreat_path:
                    continue
            else:
                continue  # No safe retreat
            
            # Compute score
            path_length = len(path)
            risk = self._compute_risk(bomb_pos, retreat_pos, danger, state)
            interference = self._compute_interference(bomb_pos, retreat_pos, reserved_cells)
            
            score = (
                expected_points
                - self.alpha * path_length
                - self.beta * risk
                - self.gamma * interference
            )
            
            # Anchor penalty for risk
            if is_anchor and risk > 0.1:
                score *= 0.5
            
            candidates.append(CandidateAction(
                unit_id=bomber.id,
                role=UnitRole.ANCHOR if is_anchor else UnitRole.FARMER,
                action_type="FARM",
                path=path,
                bomb_pos=bomb_pos,
                retreat_pos=retreat_pos,
                expected_points=expected_points,
                obstacle_count=k,
                path_length=path_length,
                risk_penalty=risk,
                interference_penalty=interference,
                score=score
            ))
        
        return candidates
    
    def _evaluate_bomb_tile(
        self,
        obstacle_pos: Position,
        bomber: Bomber,
        state: ArenaState,
        world: WorldModel,
        danger: DangerMap,
        is_anchor: bool
    ) -> Optional[Tuple[Position, Optional[Position], int, float]]:
        """
        Evaluate bomb placement at obstacle position.
        
        Returns:
            (bomb_pos, retreat_pos, k, expected_points) or None
        """
        # Count obstacles in cross pattern
        bomb_range = 1  # Default, should get from bomber stats
        k = 0
        directions = [(0, -1), (1, 0), (0, 1), (-1, 0)]  # N, E, S, W
        
        for dx, dy in directions:
            for dist in range(1, bomb_range + 1):
                x = obstacle_pos.x + dx * dist
                y = obstacle_pos.y + dy * dist
                
                if (x < 0 or x >= state.map_size[0] or
                    y < 0 or y >= state.map_size[1]):
                    break
                
                # Check if obstacle in this direction
                if any(o.x == x and o.y == y for o in state.obstacles):
                    k += 1
                    break  # Ray stops at first obstacle
        
        # Calculate expected points
        if k == 0:
            return None
        
        expected_points = sum(OBSTACLE_SCORES[:k])
        
        # Find safe retreat position
        # Unit will be at obstacle_pos after planting, need to retreat
        retreat_pos = danger.get_safe_retreat_position(
            obstacle_pos, bomb_range, obstacle_pos, state, max_steps=8
        )
        
        if not retreat_pos:
            return None
        
        return (obstacle_pos, retreat_pos, k, expected_points)
    
    def _generate_scout_actions(
        self,
        bomber: Bomber,
        state: ArenaState,
        world: WorldModel,
        danger: DangerMap,
        reserved_cells: Set[Tuple[int, int]]
    ) -> List[CandidateAction]:
        """Generate SCOUT actions (explore frontiers)"""
        candidates = []
        
        # Get known tiles
        known_tiles = set(world.tiles.keys())
        
        # Get frontier tiles
        frontier = world.get_frontier_tiles(known_tiles)
        
        for frontier_pos_tuple in list(frontier)[:10]:  # Limit search
            frontier_pos = Position(frontier_pos_tuple[0], frontier_pos_tuple[1])
            
            # Skip if reserved
            if frontier_pos.to_tuple() in reserved_cells:
                continue
            
            # Find path
            path = bfs_path(bomber.pos, frontier_pos, state, world, max_length=20)
            if not path:
                continue
            
            # Compute info gain (tiles that will be revealed)
            info_gain = len(frontier) * 0.1  # Rough estimate
            
            # Compute score
            path_length = len(path)
            risk = self._compute_risk(frontier_pos, frontier_pos, danger, state)
            
            score = (
                self.delta * info_gain
                - self.alpha * path_length
                - self.beta * risk
            )
            
            candidates.append(CandidateAction(
                unit_id=bomber.id,
                role=UnitRole.SCOUT,
                action_type="SCOUT",
                path=path,
                info_gain=info_gain,
                path_length=path_length,
                risk_penalty=risk,
                score=score
            ))
        
        return candidates
    
    def _generate_evade_actions(
        self,
        bomber: Bomber,
        state: ArenaState,
        world: WorldModel,
        danger: DangerMap,
        reserved_cells: Set[Tuple[int, int]]
    ) -> List[CandidateAction]:
        """Generate EVADE actions (move to safety)"""
        candidates = []
        search_radius = 15
        
        # Find safe positions nearby
        for dx in range(-search_radius, search_radius + 1):
            for dy in range(-search_radius, search_radius + 1):
                if abs(dx) + abs(dy) > search_radius:
                    continue
                
                safe_pos = Position(bomber.pos.x + dx, bomber.pos.y + dy)
                
                # Bounds check
                if (safe_pos.x < 0 or safe_pos.x >= state.map_size[0] or
                    safe_pos.y < 0 or safe_pos.y >= state.map_size[1]):
                    continue
                
                # Skip if reserved
                if safe_pos.to_tuple() in reserved_cells:
                    continue
                
                # Check if safe
                if not danger.is_safe(safe_pos):
                    continue
                
                # Find path
                path = bfs_path(bomber.pos, safe_pos, state, world, max_length=15)
                if not path:
                    continue
                
                # Compute score (negative, prefer shorter paths)
                path_length = len(path)
                risk = self._compute_risk(safe_pos, safe_pos, danger, state)
                
                score = -self.alpha * path_length - self.beta * risk
                
                candidates.append(CandidateAction(
                    unit_id=bomber.id,
                    role=self.roles.get(bomber.id, UnitRole.FARMER),
                    action_type="EVADE",
                    path=path,
                    path_length=path_length,
                    risk_penalty=risk,
                    score=score
                ))
        
        return candidates
    
    def _compute_risk(
        self,
        pos: Position,
        retreat_pos: Optional[Position],
        danger: DangerMap,
        state: ArenaState
    ) -> float:
        """Compute risk penalty for position"""
        risk = 0.0
        
        # Danger from bombs
        if not danger.is_safe(pos):
            risk += 1.0
        
        # Danger from mobs
        for mob in state.mobs:
            if mob.safe_time <= 0:  # Awake
                dist = pos.manhattan_distance(mob.pos)
                if dist <= 2:
                    risk += 1.0 / (dist + 1)
        
        # Danger from enemies
        for enemy in state.enemies:
            dist = pos.manhattan_distance(enemy.pos)
            if dist <= 3:
                risk += 0.5 / (dist + 1)
        
        return risk
    
    def _compute_interference(
        self,
        bomb_pos: Position,
        retreat_pos: Optional[Position],
        reserved_cells: Set[Tuple[int, int]]
    ) -> float:
        """Compute interference penalty (overlap with other units)"""
        interference = 0.0
        
        if bomb_pos.to_tuple() in reserved_cells:
            interference += 1.0
        
        if retreat_pos and retreat_pos.to_tuple() in reserved_cells:
            interference += 0.5
        
        return interference


"""
Main bot orchestration loop
"""
import time
import logging
import re
from typing import Optional, List

from src.client import APIClient
from src.models import parse_arena_response, BoosterResponse, ArenaState, Position
from src.world import WorldMemory
from src.planner import Planner
from src.boosters import BoosterManager
from src.reservations import ReservationManager
from src.rate_limiter import RateLimiter, RequestScheduler

logger = logging.getLogger(__name__)


class Bot:
    """Main bot class"""
    
    def __init__(self, client: APIClient):
        self.client = client
        self.world = WorldMemory()
        
        # Initialize reservation manager and planner
        self.reservation_manager = ReservationManager()
        self.planner = Planner(reservation_manager=self.reservation_manager)
        
        # Global rate limiter and request scheduler
        self.rate_limiter = RateLimiter(base_rate=2.5, capacity=3.0)  # Slightly conservative
        self.request_scheduler = RequestScheduler(self.rate_limiter)
        
        self.booster_manager = BoosterManager()
        self.tick_count = 0
        self.last_arena_fetch = 0.0
        # Cache arena state to avoid duplicate fetches
        self.cached_state: Optional[ArenaState] = None
        self.cached_tick = -1
        self.arena_version = 0  # Track arena changes
    
    def run(self):
        """Main loop"""
        logger.info("Starting bot...")
        # Log rounds info once at start
        try:
            rounds = self.client.get_rounds()
            if rounds and "rounds" in rounds:
                for r in rounds.get("rounds", [])[:3]:
                    name = r.get("name")
                    duration = r.get("duration")
                    start_at = r.get("startAt")
                    end_at = r.get("endAt")
                    status = r.get("status")
                    logger.info(f"🕒 Round: {name} status={status} duration={duration}s start={start_at} end={end_at}")
        except Exception as e:
            logger.debug(f"Failed to fetch rounds info: {e}")
        
        try:
            while True:
                self.tick()
                time.sleep(0.4)  # ~400ms between arena fetches
        except KeyboardInterrupt:
            logger.info("Stopped by user")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise
    
    def tick(self):
        """Execute one tick"""
        self.tick_count += 1
        
        # Fetch arena state (only once per tick, use cache if available)
        if self.cached_tick == self.tick_count and self.cached_state:
            state = self.cached_state
            logger.debug(f"📦 Using cached arena state for tick {self.tick_count} (version={self.arena_version})")
        else:
            # Check rate limiter before fetching
            if not self.rate_limiter.acquire():
                wait_time = self.rate_limiter.wait_time()
                if wait_time > 0.1:  # Only skip if significant wait
                    logger.warning(f"⏸️  Rate limited, skipping arena fetch for tick {self.tick_count} (wait {wait_time:.1f}s)")
                    return
            
            arena_data = self.client.get_arena(rate_limiter=self.rate_limiter)
            if not arena_data:
                # Check if it was a 429 - handle via rate limiter
                logger.warning(f"⚠️  Failed to fetch arena state for tick {self.tick_count} (may be rate limited)")
                return
            
            try:
                state = parse_arena_response(arena_data)
                self.cached_state = state
                self.cached_tick = self.tick_count
                self.arena_version += 1
                self.rate_limiter.reset_429()  # Reset on successful fetch
                logger.debug(f"✅ Fetched arena state for tick {self.tick_count} (version={self.arena_version})")
            except Exception as e:
                logger.error(f"❌ Failed to parse arena response: {e}")
                return
        
        # Reset SOFT reservations for new tick (HARD reservations persist with TTL)
        self.planner.reset_soft_reservations()
        
        # Expire old HARD reservations
        self.reservation_manager.expire_old_reservations(self.tick_count)
        
        # Update world memory
        self.world.update(state, self.tick_count)
        
        # Assign roles
        self.planner.assign_roles(state.bombers)
        
        # Log round and score info (every 10 ticks or at start)
        if self.tick_count % 10 == 1 or self.tick_count == 1:
            self._log_round_status(state)
        
        # Process boosters
        self._process_boosters(state.raw_score)
        
        # Plan moves for ready bombers only (skip MOVING units to avoid API spam)
        # Each agent plans ONCE per tick using the same arena snapshot
        bomber_commands = []
        ready_count = 0
        skipped_moving = 0
        planned_agents = set()  # Track which agents have planned
        
        for bomber in state.bombers:
            if not bomber.alive:
                continue
            
            if not bomber.can_move:
                skipped_moving += 1
                role = self.planner.get_role(bomber.id)
                logger.debug(f"⏸️  {bomber.id[:8]} [{role.value}]: Skipping planning (MOVING state)")
                continue
            
            # Prevent duplicate planning in same tick
            if bomber.id in planned_agents:
                logger.debug(f"⏸️  {bomber.id[:8]}: Already planned this tick, skipping")
                continue
            
            ready_count += 1
            path, bomb_pos = self.planner.plan_move(bomber, state, self.world, self.tick_count)
            planned_agents.add(bomber.id)
            
            # path=None means no action, path=[] means already at target, path=[...] means move
            if path is not None:
                command = {
                    "id": bomber.id,
                    "path": [[p.x, p.y] for p in path],
                    "bombs": [[bomb_pos.x, bomb_pos.y]] if bomb_pos else []
                }
                bomber_commands.append(command)
                
                role = self.planner.get_role(bomber.id)
                start_pos = bomber.pos.to_tuple()
                
                # Handle empty path (already at target for bomb placement)
                if path:
                    destination = path[-1].to_tuple()
                else:
                    destination = start_pos  # Already at destination
                
                # Log progress metrics
                prev_pos = self.planner.last_positions.get(bomber.id, [])
                prev_points = self.planner.last_points.get(bomber.id, [])
                moved = len(prev_pos) > 0 and prev_pos[-1] != start_pos if prev_pos else False
                points_delta = state.raw_score - (prev_points[-1] if prev_points else 0)
                
                if bomb_pos:
                    if not path:  # Already at bomb position
                        logger.info(
                            f"💣 {bomber.id[:8]} [{role.value:7s}] "
                            f"({start_pos[0]:3d},{start_pos[1]:3d}) PLACING BOMB HERE "
                            f"(no move needed) [PLANNED] "
                            f"| moved={moved} pointsΔ={points_delta:+d}"
                        )
                    else:
                        logger.info(
                            f"🎯 {bomber.id[:8]} [{role.value:7s}] "
                            f"({start_pos[0]:3d},{start_pos[1]:3d}) → ({destination[0]:3d},{destination[1]:3d}) "
                            f"💣 BOMB at ({bomb_pos.x:3d},{bomb_pos.y:3d}) "
                            f"(path: {len(path)} steps) [PLANNED] "
                            f"| moved={moved} pointsΔ={points_delta:+d}"
                        )
                else:
                    logger.info(
                        f"➡️  {bomber.id[:8]} [{role.value:7s}] "
                        f"({start_pos[0]:3d},{start_pos[1]:3d}) → ({destination[0]:3d},{destination[1]:3d}) "
                        f"(path: {len(path)} steps) [PLANNED] "
                        f"| moved={moved} pointsΔ={points_delta:+d}"
                    )
        
        # Send move commands via request scheduler (batched, queued, rate-limited)
        if bomber_commands:
            logger.debug(f"📊 Planning summary: {ready_count} ready, {skipped_moving} moving, {len(bomber_commands)} commands")
            
            # Schedule move request (queued, will be processed by scheduler)
            queued = self.request_scheduler.schedule_move(bomber_commands)
            if queued:
                # Process queue (will handle rate limiting and 429)
                response = self.request_scheduler.process_queue(
                    lambda bombers: self.client.post_move(bombers, rate_limiter=self.rate_limiter)
                )
                
                success = False
                if response is not None:
                    # Detect API-side rejection even with 200 status
                    if isinstance(response, dict) and response.get("errors"):
                        logger.warning(f"🚫 /api/move responded with errors: {response.get('errors')}")
                        self._mark_invalid_from_errors(response.get("errors", []))
                    elif isinstance(response, dict) and response.get("code") not in (None, 0):
                        logger.warning(f"🚫 /api/move code={response.get('code')}, errors={response.get('errors')}")
                        self._mark_invalid_from_errors(response.get("errors", []))
                    else:
                        success = True
                
                if success:
                    # Success: upgrade SOFT reservations to HARD and track bomb placements
                    for command in bomber_commands:
                        bomber_id = command["id"]
                        path = command["path"]
                        bombs = command.get("bombs", [])
                        
                        if path:
                            destination = Position(path[-1][0], path[-1][1])
                            first_step = Position(path[0][0], path[0][1]) if len(path) > 0 else None
                            self.planner.hard_reserve(destination, bomber_id, first_step, self.tick_count, ttl=3)
                            logger.info(f"✅ {bomber_id[:8]}: HARD reserved after successful move")
                        
                        # Track bomb placements for pending explosions
                        if bombs:
                            for bomb_coords in bombs:
                                bomb_x, bomb_y = bomb_coords[0], bomb_coords[1]
                                bomb_pos_tuple = (bomb_x, bomb_y)
                                self.planner.pending_explosions.add(bomb_pos_tuple)
                                
                                # Track placement
                                if bomber_id not in self.planner.bomb_placements:
                                    self.planner.bomb_placements[bomber_id] = []
                                self.planner.bomb_placements[bomber_id].append((bomb_x, bomb_y, self.tick_count))
                                
                                logger.info(f"💣 {bomber_id[:8]}: Bomb placed at ({bomb_x},{bomb_y}), marked as pending explosion")
                    
                    logger.info(f"✅ Successfully sent {len(bomber_commands)} move commands (tick {self.tick_count})")
                else:
                    # Failure (429 or API errors): rollback SOFT/HARD reservations
                    for command in bomber_commands:
                        bomber_id = command["id"]
                        self.reservation_manager.rollback_owner(bomber_id, self.tick_count)
                        logger.warning(f"🔄 {bomber_id[:8]}: Rolled back reservations (move failed/rejected)")
            else:
                logger.warning(f"⚠️  Move queue full, dropping {len(bomber_commands)} commands")
        else:
            if ready_count > 0:
                logger.debug(f"📊 No commands generated for {ready_count} ready bombers")

    def _mark_invalid_from_errors(self, errors: List[str]):
        """
        Parse API error messages for invalid bomb cells (e.g., 'cannot place bomb on wall at [x y]')
        and blacklist those cells in the planner to avoid retry loops.
        """
        if not errors:
            return
        pattern = re.compile(r"cannot place bomb on wall at \[(\d+)\s+(\d+)\]", re.IGNORECASE)
        for err in errors:
            m = pattern.search(err)
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                self.planner.mark_invalid_bomb_cell(Position(x, y), self.tick_count)
    
    def _log_round_status(self, state: ArenaState):
        """Log friendly round status with units and points"""
        alive_bombers = [b for b in state.bombers if b.alive]
        dead_bombers = [b for b in state.bombers if not b.alive]
        
        # Count by role
        role_counts = {}
        for bomber in alive_bombers:
            role = self.planner.get_role(bomber.id)
            role_counts[role.value] = role_counts.get(role.value, 0) + 1
        
        logger.info("=" * 80)
        logger.info(f"🎮 ROUND: {state.round_name:20s} | ⏱️  TICK: {self.tick_count:4d} | ⭐ POINTS: {state.raw_score:4d}")
        logger.info(f"👥 UNITS: {len(alive_bombers)} alive, {len(dead_bombers)} dead | "
                   f"Roles: {', '.join(f'{k}={v}' for k, v in role_counts.items())}")
        logger.info(f"🗺️  MAP: {state.map_size[0]}x{state.map_size[1]} | "
                   f"Obstacles: {len(state.obstacles)} | "
                   f"Active Bombs: {len(state.bombs)} | "
                   f"Enemies: {len(state.enemies)} | "
                   f"Mobs: {len(state.mobs)}")
        logger.info("-" * 80)
        
        # Log each bomber's detailed status
        for bomber in state.bombers:
            role = self.planner.get_role(bomber.id)
            status = "✅ ALIVE" if bomber.alive else "❌ DEAD"
            can_move = "🚶 READY" if bomber.can_move else "⏸️  MOVING"
            pos = bomber.pos.to_tuple()
            bombs = bomber.bombs_available
            armor = bomber.armor
            safe_time = bomber.safe_time
            
            # Find nearby obstacles
            nearby_obstacles = sum(
                1 for obs in state.obstacles
                if abs(obs.x - pos[0]) + abs(obs.y - pos[1]) <= 5
            )
            
            # Check for nearby dangers
            nearby_bombs = sum(
                1 for bomb in state.bombs
                if abs(bomb.pos.x - pos[0]) + abs(bomb.pos.y - pos[1]) <= 3
            )
            nearby_enemies = sum(
                1 for enemy in state.enemies
                if abs(enemy.pos.x - pos[0]) + abs(enemy.pos.y - pos[1]) <= 5
            )
            nearby_mobs = sum(
                1 for mob in state.mobs
                if abs(mob.pos.x - pos[0]) + abs(mob.pos.y - pos[1]) <= 5 and mob.safe_time <= 0
            )
            
            danger_level = ""
            if nearby_bombs > 0 or nearby_enemies > 0 or nearby_mobs > 0:
                danger_level = f"⚠️  DANGER: {nearby_bombs} bombs, {nearby_enemies} enemies, {nearby_mobs} mobs"
            
            logger.info(
                f"  {bomber.id[:8]} [{role.value:7s}] {status} | "
                f"📍 ({pos[0]:3d},{pos[1]:3d}) | {can_move} | "
                f"💣 {bombs} | 🛡️  {armor} | ⏱️  {safe_time}ms | "
                f"🎯 {nearby_obstacles} obstacles nearby"
            )
            if danger_level:
                logger.info(f"      {danger_level}")
        
        logger.info("=" * 80)
    
    def _process_boosters(self, current_points: int):
        """Process booster purchases"""
        # Skip booster processing if disabled
        if self.booster_manager.disabled:
            return
        
        if not self.booster_manager.should_purchase(current_points, self.tick_count):
            return
        
        booster_data = self.client.get_booster()
        if not booster_data:
            return
        
        try:
            booster_response = BoosterResponse(**booster_data)
        except Exception as e:
            logger.error(f"Failed to parse booster response: {e}")
            return
        
        # Check if we have points
        if booster_response.points <= 0:
            return
        
        booster_idx = self.booster_manager.select_booster(
            booster_response.available_boosters,
            booster_response.state,
            booster_response.points
        )
        
        if booster_idx is not None:
            # Validate index is within bounds
            if booster_idx < 0 or booster_idx >= len(booster_response.available_boosters):
                logger.warning(f"Invalid booster index {booster_idx}, available count: {len(booster_response.available_boosters)}")
                return
            
            # Get booster info
            booster = booster_response.available_boosters[booster_idx]
            booster_type = booster.get("type", "unknown")
            cost = booster.get("cost", 1)
            if booster_response.points < cost:
                logger.debug(f"Cannot afford booster {booster_type}, cost={cost}, points={booster_response.points}")
                return
            
            # API expects booster type string, not index!
            response = self.client.post_booster(booster_type)
            if response:
                self.booster_manager.record_purchase(booster_type, self.tick_count)
                self.booster_manager.record_success()
                self.booster_manager.last_points = booster_response.points - cost
                logger.info(f"🎁 Purchased booster: {booster_type} (cost {cost})")
            else:
                logger.warning(f"Failed to purchase booster {booster_type}")
                self.booster_manager.record_failure()
                # Don't retry immediately on failure
                self.booster_manager.last_points = booster_response.points
        else:
            # No booster selected, update points
            self.booster_manager.last_points = booster_response.points


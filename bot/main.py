"""
Main entry point for DatsJingleBang bot

Usage:
    python -m bot

Environment variables:
    BASE_URL: API base URL (default: https://games-test.datsteam.dev)
    API_KEY: API token/key
    USE_BEARER: Use Authorization: Bearer header (default: true)
"""
import os
import sys
import time
import logging
from typing import Optional

from bot.config import BASE_URL, API_KEY, USE_BEARER, RATE_LIMIT_PER_SECOND
from bot.api_client import APIClient
from bot.models import parse_arena_response
from bot.rate_limiter import RateLimiter
from bot.world_model import WorldModel
from bot.danger_map import DangerMap
from bot.strategy.planner import Planner
from bot.strategy.coordinator import Coordinator
from bot.strategy.upgrades import UpgradeManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class Bot:
    """
    Main bot orchestrator.
    
    Responsibilities:
    - Fetch arena state (once per tick)
    - Update world model and danger map
    - Generate candidate actions for each unit
    - Coordinate actions (conflict resolution)
    - Send commands via API
    - Handle upgrades
    """
    
    def __init__(self, client: APIClient):
        self.client = client
        self.rate_limiter = RateLimiter(rate=RATE_LIMIT_PER_SECOND, capacity=RATE_LIMIT_PER_SECOND)
        self.world = WorldModel()
        self.danger = DangerMap()
        self.planner = Planner()
        self.coordinator = Coordinator()
        self.upgrade_manager = UpgradeManager()
        
        self.tick_count = 0
        self.last_arena_fetch = 0.0
        self.cached_state = None
        self.cached_tick = -1
    
    def run(self):
        """Main game loop"""
        logger.info("Starting bot...")
        
        while True:
            try:
                self.tick()
                time.sleep(0.05)  # ~50ms per tick
            except KeyboardInterrupt:
                logger.info("Stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in tick: {e}", exc_info=True)
                time.sleep(1.0)  # Backoff on error
    
    def tick(self):
        """Execute one game tick"""
        self.tick_count += 1
        
        # Fetch arena state (once per tick, use cache if available)
        if self.cached_tick == self.tick_count and self.cached_state:
            state = self.cached_state
            logger.debug(f"Using cached arena state for tick {self.tick_count}")
        else:
            # Check rate limit
            if self.rate_limiter.is_rate_limited():
                logger.warning(f"Rate limited, skipping tick {self.tick_count}")
                return
            
            arena_data = self.client.get_arena(rate_limiter=self.rate_limiter)
            if not arena_data:
                logger.warning(f"Failed to fetch arena state for tick {self.tick_count}")
                return
            
            try:
                state = parse_arena_response(arena_data)
                self.cached_state = state
                self.cached_tick = self.tick_count
                self.rate_limiter.reset_429()
                logger.debug(f"Fetched arena state for tick {self.tick_count}")
            except Exception as e:
                logger.error(f"Failed to parse arena response: {e}")
                return
        
        # Update world model
        self.world.update(state, self.tick_count)
        
        # Update danger map
        self.danger.update(state, current_time=0.0)  # TODO: track actual game time
        
        # Assign roles
        self.planner.assign_roles(state.bombers)
        
        # Log status periodically
        if self.tick_count % 10 == 1:
            self._log_status(state)
        
        # Process upgrades
        self._process_upgrades(state)
        
        # Generate candidate actions for each unit
        all_candidates = {}
        reserved_cells = self.coordinator.get_reserved_cells()
        
        for bomber in state.bombers:
            if not bomber.alive or not bomber.can_move:
                continue
            
            candidates = self.planner.generate_candidates(
                bomber, state, self.world, self.danger, reserved_cells
            )
            if candidates:
                all_candidates[bomber.id] = candidates
        
        # Coordinate actions (conflict resolution)
        assigned_actions = self.coordinator.select_actions(
            all_candidates, state, self.tick_count
        )
        
        # Send commands
        if assigned_actions:
            self._send_commands(assigned_actions)
    
    def _log_status(self, state):
        """Log current game status"""
        alive_count = sum(1 for b in state.bombers if b.alive)
        logger.info(
            f"Tick {self.tick_count} | "
            f"Score: {state.raw_score} | "
            f"Alive: {alive_count}/{len(state.bombers)} | "
            f"Obstacles: {len(state.obstacles)} | "
            f"Bombs: {len(state.bombs)}"
        )
    
    def _process_upgrades(self, state):
        """Process upgrade purchases"""
        if not self.upgrade_manager.should_purchase(self.tick_count, 0):
            return
        
        # Fetch booster state
        booster_data = self.client.get_booster()
        if not booster_data:
            return
        
        from bot.models import BoosterResponse
        booster_response = BoosterResponse(**booster_data)
        
        if booster_response.points <= 0:
            return
        
        # Select upgrade
        upgrade_idx = self.upgrade_manager.select_upgrade(
            booster_response.available_boosters,
            booster_response.points,
            booster_response.state
        )
        
        if upgrade_idx is not None:
            # Purchase upgrade
            result = self.client.post_booster(upgrade_idx)
            if result:
                # Extract upgrade type from response or available list
                upgrade_type = booster_response.available_boosters[upgrade_idx].get("type", "unknown")
                self.upgrade_manager.record_purchase(upgrade_type, self.tick_count)
    
    def _send_commands(self, actions):
        """Send move commands to API"""
        bomber_commands = []
        
        for action in actions:
            command = {
                "id": action.unit_id,
                "path": [[p.x, p.y] for p in action.path],
                "bombs": [[action.bomb_pos.x, action.bomb_pos.y]] if action.bomb_pos else []
            }
            bomber_commands.append(command)
            
            # Log action
            role = self.planner.roles.get(action.unit_id, "UNKNOWN")
            action_type = "FARM" if action.bomb_pos else "MOVE"
            logger.info(
                f"{action.unit_id[:8]} [{role.value}] {action_type}: "
                f"path={len(action.path)} steps"
                + (f", bomb=({action.bomb_pos.x},{action.bomb_pos.y})" if action.bomb_pos else "")
            )
        
        # Send via API
        response = self.client.post_move(bomber_commands, rate_limiter=self.rate_limiter)
        if response:
            logger.debug(f"Successfully sent {len(bomber_commands)} commands")
        else:
            logger.warning(f"Failed to send commands")


def main():
    """Main entry point"""
    if not API_KEY:
        logger.error("API_KEY or API_TOKEN environment variable not set")
        sys.exit(1)
    
    logger.info(f"Starting bot with BASE_URL={BASE_URL}")
    logger.info(f"Using {'Authorization: Bearer' if USE_BEARER else 'X-Auth-Token'} header")
    
    client = APIClient(BASE_URL, API_KEY, use_bearer=USE_BEARER)
    bot = Bot(client)
    bot.run()


if __name__ == "__main__":
    main()


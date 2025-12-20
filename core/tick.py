"""
Main game tick loop
"""
from typing import Optional, Dict
from core.api import APIClient
from core.state import GameState, BoosterState
from core.booster_manager import BoosterManager
from core.tactical_state import FarmMemory, BomberTacticalState, TacticalState
from core.roles import RoleManager
from core.farm_controller import FarmController
from core.zone_control import ZoneControl
from core.bomber_tactics import determine_tactical_state, decide_tactical_action
from core.bomber_logic import manhattan_distance, is_position_safe, get_neighbors
from core.logger import SystemLogger, GameLogger
from core.table_logger import log_game_table
from utils.time import get_current_time, sleep
import config

system_logger = SystemLogger()
game_logger = GameLogger()


class TickLoop:
    """Main game loop"""
    
    def __init__(self, api_client: APIClient):
        self.api_client = api_client
        self.booster_manager = BoosterManager(api_client, config.BOOSTER_COOLDOWN)
        self.current_state: Optional[GameState] = None
        self.tick_count = 0
        self.last_table_log_tick = 0
        
        # Tactical state tracking
        self.farm_memory = FarmMemory(cooldown_ticks=config.FARM_COOLDOWN_TICKS)
        self.bomber_states: Dict[str, BomberTacticalState] = {}
        self.role_manager = RoleManager(min_role_persistence=50)
        self.farm_controller = FarmController(max_active_farmers=2, max_active_bombs=3)
        self.zone_control = ZoneControl()
        
        # API rate limiting
        self.last_api_call_tick = 0
        self.min_api_interval = 1  # Minimum ticks between API calls
    
    def fetch_state(self) -> Optional[GameState]:
        """Fetch current game state from API"""
        response = self.api_client.get_state()
        if response:
            return GameState.from_dict(response, get_current_time())
        return None
    
    def update_state(self, new_state: GameState):
        """Update internal state"""
        self.current_state = new_state
        self.tick_count += 1  # Increment tick counter since API doesn't provide it
        
        # Assign roles
        self.role_manager.assign_roles(new_state.bombers, self.tick_count)
        
        # Assign zones to farmers
        self.zone_control.assign_zones(new_state.bombers, self.role_manager, new_state.map_size)
        
        # Initialize bomber states for new bombers
        for bomber in new_state.bombers:
            if bomber.id not in self.bomber_states:
                self.bomber_states[bomber.id] = BomberTacticalState(
                    bomber.id, 
                    min_action_interval=config.MIN_ACTION_INTERVAL,
                    farm_cooldown=config.FARM_COOLDOWN_TICKS
                )
        
        # Cleanup old farm memory and active bombs
        self.farm_memory.cleanup_old(self.tick_count)
        self.farm_controller.cleanup_old_bombs(self.tick_count)
    
    def should_log_table(self) -> bool:
        """Check if we should log table at this tick"""
        if self.current_state is None:
            return False
        
        # Log at round start (tick 0 or 1)
        if self.current_state.tick <= 1:
            return True
        
        # Log every N ticks
        if self.current_state.tick - self.last_table_log_tick >= config.TABLE_LOG_INTERVAL:
            return True
        
        return False
    
    def process_bombers(self):
        """Process all bombers and send actions using tactical state machine"""
        if self.current_state is None:
            return {}
        
        path_lengths = {}
        bomber_commands = []
        
        for bomber in self.current_state.bombers:
            # Skip if dead
            if not bomber.alive:
                continue
            
            # ABSOLUTE RULE: If moving, do nothing
            if bomber.moving:
                continue
            
            # Get or create tactical state
            tactical_state = self.bomber_states.get(bomber.id)
            if not tactical_state:
                tactical_state = BomberTacticalState(bomber.id)
                self.bomber_states[bomber.id] = tactical_state
            
            # Check if should skip action (rate limiting)
            role = self.role_manager.get_role(bomber.id)
            if tactical_state.should_skip_action(self.tick_count, role):
                continue
            
            # Check post-farm state transition
            if tactical_state.state == TacticalState.POST_FARM:
                # Check if moved far enough and cooldown expired
                if tactical_state.last_farm_pos:
                    dist_from_farm = manhattan_distance(bomber.position, tactical_state.last_farm_pos)
                    if dist_from_farm >= tactical_state.min_farm_distance and tactical_state.can_farm_again(self.tick_count):
                        # Exit post-farm
                        tactical_state.update_state(TacticalState.IDLE, self.tick_count, system_logger)
                        self.farm_controller.finish_farming(bomber.id, tactical_state.last_farm_pos, self.tick_count)
            
            # Determine tactical state
            new_tactical_state = determine_tactical_state(
                bomber, self.current_state, self.farm_memory, self.tick_count,
                self.role_manager, self.farm_controller, self.zone_control
            )
            tactical_state.update_state(new_tactical_state, self.tick_count, system_logger)
            
            # Update adaptive threshold
            self.farm_controller.update_adaptive_threshold(
                self.tick_count, self.current_state.points
            )
            
            # Decide action based on tactical state
            path, bombs, reason = decide_tactical_action(
                bomber, self.current_state, tactical_state, 
                self.farm_memory, self.tick_count,
                self.role_manager, self.farm_controller, self.zone_control
            )
            
            # Add command if we have one
            if path is not None:
                # Convert path to list format for API
                path_list = [[x, y] for x, y in path]
                bomb_list = [[x, y] for x, y in bombs]
                
                bomber_commands.append({
                    "id": bomber.id,
                    "path": path_list,
                    "bombs": bomb_list
                })
                
                path_lengths[bomber.id] = len(path)
                tactical_state.record_action(self.tick_count)
                
                # Handle post-farm state
                if bombs and tactical_state.state == TacticalState.FARM:
                    tactical_state.update_state(TacticalState.POST_FARM, self.tick_count, system_logger)
                    # Must move away from farm position
                    if path and len(path) < tactical_state.min_farm_distance:
                        # Extend path to move further away
                        current_end = path[-1]
                        escape_neighbors = [
                            n for n in get_neighbors(current_end, self.current_state.map_size)
                            if is_position_safe(n, self.current_state.explosions, self.current_state.map_size)
                        ]
                        if escape_neighbors:
                            path.append(escape_neighbors[0])
                
                # Log with role and tactical state
                role = self.role_manager.get_role(bomber.id).value
                state_name = tactical_state.state.value
                if path:
                    game_logger.movement(
                        f"Bomber {bomber.id[:8]} [{role}/{state_name}]: {reason} -> {path[-1]}"
                    )
                if bombs:
                    score = self.farm_controller.get_farm_score(bomber.id)
                    self.farm_controller.record_bomb_placed(self.tick_count)
                    game_logger.bomb(
                        f"Bomber {bomber.id[:8]} [{role}]: planting at {bombs[0]} (score={score:.1f})"
                    )
        
        # Send all commands in one request (rate limited)
        if bomber_commands and (self.tick_count - self.last_api_call_tick) >= self.min_api_interval:
            response = self.api_client.post_move(bomber_commands)
            if response:
                self.last_api_call_tick = self.tick_count
            else:
                system_logger.warning(f"Failed to send move commands for {len(bomber_commands)} bombers")
        
        return path_lengths
    
    def process_boosters(self):
        """Process booster purchases (rate limited)"""
        # Only check boosters every N ticks to reduce API calls
        if (self.tick_count - self.last_api_call_tick) < 10:
            return
        
        booster_state = self.booster_manager.fetch_boosters()
        if booster_state:
            self.booster_manager.try_purchase_booster(booster_state, self.tick_count)
    
    def tick(self):
        """Execute one game tick"""
        # Fetch state
        new_state = self.fetch_state()
        if new_state is None:
            system_logger.warning("Failed to fetch game state")
            return
        
        # Update state
        self.update_state(new_state)
        
        # Process bombers first to get path lengths
        path_lengths = self.process_bombers()
        
        # Log table if needed (after processing to include path lengths)
        if self.should_log_table():
            log_game_table(self.current_state, path_lengths, self.bomber_states, 
                         self.role_manager, self.farm_controller)
            # Log farm controller status
            system_logger.info(
                f"FarmController: active_farmers={len(self.farm_controller.active_farmers)}, "
                f"active_bombs={len(self.farm_controller.active_bombs)}"
            )
            self.last_table_log_tick = self.current_state.tick
        
        # Process boosters
        self.process_boosters()
    
    def run(self):
        """Run the main loop"""
        system_logger.info("Starting game loop...")
        
        try:
            while True:
                self.tick()
                sleep(config.TICK_DELAY)
        except KeyboardInterrupt:
            system_logger.info("Received interrupt signal, shutting down...")
        except Exception as e:
            system_logger.error(f"Unexpected error in game loop: {e}")
            raise


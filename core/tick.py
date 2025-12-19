"""
Main game tick loop
"""
from typing import Optional, Dict
from core.api import APIClient
from core.state import GameState, BoosterState
from core.booster_manager import BoosterManager
from core.tactical_state import FarmMemory, BomberTacticalState
from core.bomber_tactics import determine_tactical_state, decide_tactical_action
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
        self.farm_memory = FarmMemory(cooldown_ticks=30)
        self.bomber_states: Dict[str, BomberTacticalState] = {}
        
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
        
        # Initialize bomber states for new bombers
        for bomber in new_state.bombers:
            if bomber.id not in self.bomber_states:
                self.bomber_states[bomber.id] = BomberTacticalState(bomber.id)
        
        # Cleanup old farm memory
        self.farm_memory.cleanup_old(self.tick_count)
    
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
        """Process all bombers and send actions"""
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
            
            # Decide action
            path, bombs, reason = decide_bomber_action(
                bomber, 
                self.current_state, 
                config.MAX_PATH_LENGTH
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
                
                if path:
                    game_logger.movement(f"Bomber {bomber.id[:8]}: {reason} -> {path[-1]}")
                if bombs:
                    game_logger.bomb(f"Bomber {bomber.id[:8]}: planting at {bombs[0]}")
        
        # Send all commands in one request
        if bomber_commands:
            response = self.api_client.post_move(bomber_commands)
            if not response:
                system_logger.warning(f"Failed to send move commands for {len(bomber_commands)} bombers")
        
        return path_lengths
    
    def process_boosters(self):
        """Process booster purchases"""
        booster_state = self.booster_manager.fetch_boosters()
        if booster_state:
            self.booster_manager.try_purchase_booster(booster_state)
    
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
            log_game_table(self.current_state, path_lengths)
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


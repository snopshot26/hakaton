"""
Table-style logger for game state visualization
"""
from typing import List, Optional
from core.state import Bomber, GameState
from core.logger import SystemLogger

logger = SystemLogger()


def format_bomber_id(bomber_id: str) -> str:
    """Format bomber ID to short form"""
    if len(bomber_id) > 8:
        return bomber_id[:8]
    return bomber_id.ljust(8)


def format_position(pos: tuple) -> str:
    """Format position tuple"""
    return f"({pos[0]:3d}, {pos[1]:3d})"


def format_target(target: Optional[tuple]) -> str:
    """Format target position"""
    if target is None:
        return "—"
    return f"({target[0]:3d}, {target[1]:3d})"


def get_bomber_state(bomber: Bomber) -> str:
    """Get human-readable state of bomber"""
    if not bomber.alive:
        return "DEAD"
    if bomber.moving:
        return "MOVING"
    return "WAIT"


def get_bomber_action(bomber: Bomber, path_length: int = 0) -> str:
    """Get human-readable action description"""
    if not bomber.alive:
        return "died"
    if bomber.moving:
        if path_length > 0:
            return f"moving ({path_length} steps)"
        return "moving"
    if bomber.bombs_available > 0:
        return "ready"
    return "idle"


def log_game_table(state: GameState, path_lengths: dict = None, bomber_states: dict = None, 
                  role_manager=None, farm_controller=None):
    """
    Print game state as a formatted table
    
    Args:
        state: Current game state
        path_lengths: Dict mapping bomber_id to path length for action display
    """
    if path_lengths is None:
        path_lengths = {}
    
    # Header
    header = f"🎮 ROUND {state.round_id[:8]} | ⏱ Tick {state.tick} | ⭐ Points {state.points}"
    separator = "-" * 80
    table_header = f"{'ID':<10} | {'STATE':<8} | {'POS':<12} | {'TARGET':<12} | {'ACTION':<20}"
    
    # Build table rows
    rows = []
    for bomber in state.bombers:
        bomber_id = format_bomber_id(bomber.id)
        bomber_state = get_bomber_state(bomber)
        pos_str = format_position(bomber.position)
        target_str = format_target(bomber.target)
        path_len = path_lengths.get(bomber.id, 0) if path_lengths else 0
        action_str = get_bomber_action(bomber, path_len)
        
        # Add role and tactical state if available
        role_info = ""
        tactical_info = ""
        if role_manager:
            from core.roles import BomberRole
            role = role_manager.get_role(bomber.id)
            role_info = f" {role.value}"
        
        if bomber_states and bomber.id in bomber_states:
            tactical_state = bomber_states[bomber.id]
            tactical_info = f" [{tactical_state.state.value}]"
            if tactical_state.last_farm_pos:
                target_str = format_target(tactical_state.last_farm_pos)
        
        # Add farm score if available
        score_info = ""
        if farm_controller:
            score = farm_controller.get_farm_score(bomber.id)
            if score > 0:
                score_info = f" score={score:.0f}"
        
        row = f"{bomber_id:<10} | {bomber_state:<8} | {pos_str:<12} | {target_str:<12} | {action_str:<20}{role_info}{tactical_info}{score_info}"
        rows.append(row)
    
    # Combine all parts
    table_parts = [
        separator,
        header,
        separator,
        table_header,
        separator
    ]
    table_parts.extend(rows)
    table_parts.append(separator)
    
    # Log as single message
    logger.info("\n".join(table_parts))


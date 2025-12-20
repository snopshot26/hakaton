"""
Zone control system - divides map into zones for each farmer
"""
from typing import Dict, Tuple, List, Optional
from core.state import GameState, Bomber
from core.roles import BomberRole, RoleManager


class ZoneControl:
    """Manages map zones for farmers"""
    
    def __init__(self):
        self.zones: Dict[str, Tuple[int, int, int, int]] = {}  # bomber_id -> (x1, y1, x2, y2)
        self.zone_centers: Dict[str, Tuple[int, int]] = {}
    
    def assign_zones(self, bombers: List[Bomber], role_manager: RoleManager, map_size: Tuple[int, int]):
        """Assign zones to farmers"""
        farmers = [b for b in bombers if b.alive and role_manager.get_role(b.id) == BomberRole.FARMER]
        
        if not farmers:
            self.zones.clear()
            self.zone_centers.clear()
            return
        
        # Divide map into zones
        width, height = map_size
        zones_per_side = int(len(farmers) ** 0.5) + 1
        zone_width = width // zones_per_side
        zone_height = height // zones_per_side
        
        self.zones.clear()
        self.zone_centers.clear()
        
        for idx, farmer in enumerate(farmers):
            zone_x = (idx % zones_per_side) * zone_width
            zone_y = (idx // zones_per_side) * zone_height
            zone_x2 = min(zone_x + zone_width, width)
            zone_y2 = min(zone_y + zone_height, height)
            
            self.zones[farmer.id] = (zone_x, zone_y, zone_x2, zone_y2)
            center_x = (zone_x + zone_x2) // 2
            center_y = (zone_y + zone_y2) // 2
            self.zone_centers[farmer.id] = (center_x, center_y)
    
    def get_zone(self, bomber_id: str) -> Optional[Tuple[int, int, int, int]]:
        """Get zone bounds for a bomber"""
        return self.zones.get(bomber_id)
    
    def is_in_zone(self, bomber_id: str, pos: Tuple[int, int]) -> bool:
        """Check if position is in bomber's zone"""
        zone = self.get_zone(bomber_id)
        if not zone:
            return True  # No zone restriction if not assigned
        x1, y1, x2, y2 = zone
        x, y = pos
        return x1 <= x < x2 and y1 <= y < y2
    
    def get_zone_penalty(self, bomber_id: str, pos: Tuple[int, int]) -> float:
        """Get penalty for farming outside zone (0 = in zone, higher = further)"""
        zone = self.get_zone(bomber_id)
        if not zone:
            return 0.0
        
        if self.is_in_zone(bomber_id, pos):
            return 0.0
        
        # Calculate distance to zone
        x1, y1, x2, y2 = zone
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        from core.bomber_logic import manhattan_distance
        dist = manhattan_distance(pos, (center_x, center_y))
        return dist * 10.0  # Large penalty for farming outside zone


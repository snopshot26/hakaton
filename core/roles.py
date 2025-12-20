"""
Role-based bomber assignment system
"""
from enum import Enum
from typing import Dict, List, Optional
from core.state import Bomber


class BomberRole(Enum):
    """Bomber roles in the team"""
    FARMER = "FARMER"      # Plants bombs, farms obstacles
    SCOUT = "SCOUT"         # Explores map, never plants bombs
    BLOCKER = "BLOCKER"     # Occupies space, supports team


class RoleManager:
    """Manages role assignment and persistence"""
    
    def __init__(self, min_role_persistence: int = 50):
        self.roles: Dict[str, BomberRole] = {}
        self.role_assign_tick: Dict[str, int] = {}
        self.min_role_persistence = min_role_persistence
        self.max_farmers = 2
        self.max_scouts = 2
    
    def assign_roles(self, bombers: List[Bomber], current_tick: int):
        """Assign roles to bombers at round start or when needed"""
        alive_bombers = [b for b in bombers if b.alive]
        
        # Don't reassign if roles are too recent
        needs_reassignment = False
        for bomber in alive_bombers:
            if bomber.id not in self.roles:
                needs_reassignment = True
                break
            if bomber.id in self.role_assign_tick:
                if current_tick - self.role_assign_tick[bomber.id] > self.min_role_persistence:
                    needs_reassignment = True
                    break
        
        if not needs_reassignment and len(self.roles) == len(alive_bombers):
            return  # Keep existing roles
        
        # Count current roles
        current_farmers = sum(1 for r in self.roles.values() if r == BomberRole.FARMER)
        current_scouts = sum(1 for r in self.roles.values() if r == BomberRole.SCOUT)
        
        # Assign roles
        farmers_needed = min(self.max_farmers, len(alive_bombers))
        scouts_needed = min(self.max_scouts, len(alive_bombers) - farmers_needed)
        
        # Sort bombers by some criteria (e.g., position, ID for consistency)
        sorted_bombers = sorted(alive_bombers, key=lambda b: (b.position[0], b.position[1], b.id))
        
        farmer_count = 0
        scout_count = 0
        
        for bomber in sorted_bombers:
            if bomber.id not in self.roles or needs_reassignment:
                if farmer_count < farmers_needed:
                    self.roles[bomber.id] = BomberRole.FARMER
                    self.role_assign_tick[bomber.id] = current_tick
                    farmer_count += 1
                elif scout_count < scouts_needed:
                    self.roles[bomber.id] = BomberRole.SCOUT
                    self.role_assign_tick[bomber.id] = current_tick
                    scout_count += 1
                else:
                    self.roles[bomber.id] = BomberRole.BLOCKER
                    self.role_assign_tick[bomber.id] = current_tick
    
    def get_role(self, bomber_id: str) -> BomberRole:
        """Get role for a bomber"""
        return self.roles.get(bomber_id, BomberRole.BLOCKER)
    
    def can_farm(self, bomber_id: str) -> bool:
        """Check if bomber is allowed to farm"""
        return self.get_role(bomber_id) == BomberRole.FARMER


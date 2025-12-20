"""
ReservationManager: 2-phase reservation system (SOFT/HARD) with TTL and rollback
"""
from typing import Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from src.models import Position

logger = logging.getLogger(__name__)


class ReservationType(Enum):
    """Reservation type"""
    SOFT = "SOFT"  # During planning phase (current tick only)
    HARD = "HARD"  # After successful API confirmation (persists with TTL)


@dataclass
class Reservation:
    """Reservation entry"""
    pos: Tuple[int, int]
    owner: str  # bomber_id
    reservation_type: ReservationType
    tick_created: int
    ttl: int = 3  # Time to live in ticks
    next_step: Optional[Tuple[int, int]] = None  # First step position if applicable


class ReservationManager:
    """
    2-phase reservation system:
    - SOFT: Temporary reservations during planning (cleared each tick)
    - HARD: Confirmed reservations after successful API response (with TTL)
    """
    
    def __init__(self):
        # SOFT reservations (cleared each tick)
        self.soft_reservations: Dict[Tuple[int, int], Reservation] = {}
        
        # HARD reservations (persist with TTL)
        self.hard_reservations: Dict[Tuple[int, int], Reservation] = {}
        
        # Track reservations by owner for rollback
        self.owner_reservations: Dict[str, Set[Tuple[int, int]]] = {}
    
    def reset_soft_reservations(self):
        """Clear all SOFT reservations (called at start of each tick)"""
        self.soft_reservations.clear()
        logger.debug(f"🔄 Cleared {len(self.soft_reservations)} SOFT reservations")
    
    def soft_reserve(self, pos: Position, owner: str, next_step: Optional[Position] = None, 
                    current_tick: int = 0) -> bool:
        """
        Create SOFT reservation during planning.
        Returns True if successful, False if already reserved by another agent.
        """
        pos_tuple = pos.to_tuple()
        
        # Check if already reserved by another agent
        if pos_tuple in self.soft_reservations:
            existing = self.soft_reservations[pos_tuple]
            if existing.owner != owner:
                logger.debug(f"⏸️  {owner[:8]}: Position {pos_tuple} SOFT reserved by {existing.owner[:8]}")
                return False
        
        # Check HARD reservations
        if pos_tuple in self.hard_reservations:
            existing = self.hard_reservations[pos_tuple]
            if existing.owner != owner:
                logger.debug(f"⏸️  {owner[:8]}: Position {pos_tuple} HARD reserved by {existing.owner[:8]}")
                return False
        
        # Create SOFT reservation
        reservation = Reservation(
            pos=pos_tuple,
            owner=owner,
            reservation_type=ReservationType.SOFT,
            tick_created=current_tick,
            ttl=1,  # SOFT reservations last only current tick
            next_step=next_step.to_tuple() if next_step else None
        )
        
        self.soft_reservations[pos_tuple] = reservation
        
        # Track by owner
        if owner not in self.owner_reservations:
            self.owner_reservations[owner] = set()
        self.owner_reservations[owner].add(pos_tuple)
        
        logger.debug(f"📍 {owner[:8]}: SOFT reserved {pos_tuple}")
        return True
    
    def hard_reserve(self, pos: Position, owner: str, next_step: Optional[Position] = None,
                    current_tick: int = 0, ttl: int = 3) -> bool:
        """
        Create HARD reservation after successful API confirmation.
        Returns True if successful.
        """
        pos_tuple = pos.to_tuple()
        
        # Remove SOFT reservation if exists (upgrade to HARD)
        if pos_tuple in self.soft_reservations:
            soft = self.soft_reservations.pop(pos_tuple)
            if soft.owner != owner:
                logger.warning(f"⚠️  {owner[:8]}: Upgrading SOFT reservation from different owner {soft.owner[:8]}")
        
        # Create HARD reservation
        reservation = Reservation(
            pos=pos_tuple,
            owner=owner,
            reservation_type=ReservationType.HARD,
            tick_created=current_tick,
            ttl=ttl,
            next_step=next_step.to_tuple() if next_step else None
        )
        
        self.hard_reservations[pos_tuple] = reservation
        
        # Track by owner
        if owner not in self.owner_reservations:
            self.owner_reservations[owner] = set()
        self.owner_reservations[owner].add(pos_tuple)
        
        logger.info(f"✅ {owner[:8]}: HARD reserved {pos_tuple} (TTL={ttl})")
        return True
    
    def is_reserved(self, pos: Position, owner: Optional[str] = None) -> bool:
        """
        Check if position is reserved.
        If owner is provided, returns False if reserved by that owner (self-reservation allowed).
        """
        pos_tuple = pos.to_tuple()
        
        # Check SOFT reservations
        if pos_tuple in self.soft_reservations:
            existing = self.soft_reservations[pos_tuple]
            if owner and existing.owner == owner:
                return False  # Self-reservation is allowed
            return True
        
        # Check HARD reservations
        if pos_tuple in self.hard_reservations:
            existing = self.hard_reservations[pos_tuple]
            if owner and existing.owner == owner:
                return False  # Self-reservation is allowed
            return True
        
        return False
    
    def rollback_owner(self, owner: str, current_tick: int = 0):
        """
        Rollback all reservations for an owner (e.g., on API failure).
        """
        if owner not in self.owner_reservations:
            return
        
        rolled_back = 0
        for pos_tuple in list(self.owner_reservations[owner]):
            if pos_tuple in self.soft_reservations:
                del self.soft_reservations[pos_tuple]
                rolled_back += 1
            if pos_tuple in self.hard_reservations:
                del self.hard_reservations[pos_tuple]
                rolled_back += 1
        
        del self.owner_reservations[owner]
        
        if rolled_back > 0:
            logger.warning(f"🔄 {owner[:8]}: Rolled back {rolled_back} reservations (API failure)")
    
    def expire_old_reservations(self, current_tick: int):
        """
        Remove expired HARD reservations (TTL expired).
        """
        expired = []
        for pos_tuple, reservation in list(self.hard_reservations.items()):
            age = current_tick - reservation.tick_created
            if age >= reservation.ttl:
                expired.append(pos_tuple)
                # Remove from owner tracking
                if reservation.owner in self.owner_reservations:
                    self.owner_reservations[reservation.owner].discard(pos_tuple)
        
        for pos_tuple in expired:
            del self.hard_reservations[pos_tuple]
        
        if expired:
            logger.debug(f"⏰ Expired {len(expired)} HARD reservations (TTL)")
    
    def get_reservation_info(self, pos: Position) -> Optional[str]:
        """Get reservation info for logging"""
        pos_tuple = pos.to_tuple()
        if pos_tuple in self.soft_reservations:
            r = self.soft_reservations[pos_tuple]
            return f"SOFT by {r.owner[:8]}"
        if pos_tuple in self.hard_reservations:
            r = self.hard_reservations[pos_tuple]
            return f"HARD by {r.owner[:8]} (age={r.tick_created})"
        return None


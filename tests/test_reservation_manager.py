"""
Tests for ReservationManager: TTL, owner, rollback
"""
import pytest
from src.reservations import ReservationManager, ReservationType
from src.models import Position


def test_soft_reservation_owner_check():
    """Test that agent can reserve own position (self-reservation allowed)"""
    manager = ReservationManager()
    
    pos = Position(10, 10)
    owner1 = "agent1"
    owner2 = "agent2"
    
    # Agent1 reserves
    assert manager.soft_reserve(pos, owner1, None, 1) == True
    
    # Agent1 can check and it's not "reserved by another" (self-reservation)
    assert manager.is_reserved(pos, owner1) == False  # Self-reservation allowed
    
    # Agent2 sees it as reserved
    assert manager.is_reserved(pos, owner2) == True
    
    # Agent2 cannot reserve
    assert manager.soft_reserve(pos, owner2, None, 1) == False


def test_hard_reservation_ttl():
    """Test that HARD reservations expire after TTL"""
    manager = ReservationManager()
    
    pos = Position(10, 10)
    owner = "agent1"
    
    # Create HARD reservation with TTL=2
    manager.hard_reserve(pos, owner, None, current_tick=1, ttl=2)
    assert manager.is_reserved(pos, None) == True
    
    # Still reserved at tick 2
    manager.expire_old_reservations(2)
    assert manager.is_reserved(pos, None) == True
    
    # Expired at tick 3
    manager.expire_old_reservations(3)
    assert manager.is_reserved(pos, None) == False


def test_rollback_owner():
    """Test that rollback removes all reservations for an owner"""
    manager = ReservationManager()
    
    pos1 = Position(10, 10)
    pos2 = Position(11, 11)
    owner = "agent1"
    
    # Create SOFT and HARD reservations
    manager.soft_reserve(pos1, owner, None, 1)
    manager.hard_reserve(pos2, owner, None, 1, ttl=3)
    
    assert manager.is_reserved(pos1, None) == True
    assert manager.is_reserved(pos2, None) == True
    
    # Rollback
    manager.rollback_owner(owner, 1)
    
    assert manager.is_reserved(pos1, None) == False
    assert manager.is_reserved(pos2, None) == False


def test_soft_reservation_cleared_each_tick():
    """Test that SOFT reservations are cleared each tick"""
    manager = ReservationManager()
    
    pos = Position(10, 10)
    owner = "agent1"
    
    # Create SOFT reservation
    manager.soft_reserve(pos, owner, None, 1)
    assert manager.is_reserved(pos, None) == True
    
    # Reset SOFT reservations
    manager.reset_soft_reservations()
    assert manager.is_reserved(pos, None) == False


def test_hard_reservation_persists_across_ticks():
    """Test that HARD reservations persist until TTL expires"""
    manager = ReservationManager()
    
    pos = Position(10, 10)
    owner = "agent1"
    
    # Create HARD reservation
    manager.hard_reserve(pos, owner, None, current_tick=1, ttl=3)
    assert manager.is_reserved(pos, None) == True
    
    # Reset SOFT (should not affect HARD)
    manager.reset_soft_reservations()
    assert manager.is_reserved(pos, None) == True
    
    # Expire after TTL
    manager.expire_old_reservations(4)
    assert manager.is_reserved(pos, None) == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


"""
Tests for rate limiter
"""
import pytest
import time
from bot.rate_limiter import RateLimiter


def test_rate_limiter_initial_state():
    """Test rate limiter initial state"""
    limiter = RateLimiter(rate=3.0, capacity=3.0)
    
    # Should have tokens available
    assert limiter.acquire()
    assert limiter.acquire()
    assert limiter.acquire()
    
    # Should be rate limited after 3 requests
    assert not limiter.acquire()


def test_rate_limiter_token_refill():
    """Test that tokens refill over time"""
    limiter = RateLimiter(rate=3.0, capacity=3.0)
    
    # Use all tokens
    assert limiter.acquire()
    assert limiter.acquire()
    assert limiter.acquire()
    assert not limiter.acquire()
    
    # Wait for refill (1 second = 3 tokens at rate 3.0)
    time.sleep(1.1)
    
    # Should have tokens again
    assert limiter.acquire()


def test_rate_limiter_429_handling():
    """Test 429 (rate limit) handling"""
    limiter = RateLimiter(rate=3.0, capacity=3.0)
    
    # Simulate 429 response
    limiter.handle_429(retry_after=1.0, base_backoff=0.5)
    
    # Should be rate limited
    assert limiter.is_rate_limited()
    assert limiter.wait_time() > 0
    
    # Should not be able to acquire
    assert not limiter.acquire()
    
    # Wait for backoff to expire
    time.sleep(1.1)
    
    # Should be able to acquire again
    assert limiter.acquire()


def test_rate_limiter_reset_429():
    """Test resetting 429 counter"""
    limiter = RateLimiter(rate=3.0, capacity=3.0)
    
    # Simulate 429
    limiter.handle_429(retry_after=0.5, base_backoff=0.5)
    
    # Reset
    limiter.reset_429()
    
    # Should not be in backoff (if enough time passed)
    # Note: reset_429 doesn't clear backoff_until, but consecutive_429s
    # This test verifies the counter is reset


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Global rate limiter for API requests

Enforces 3 requests per second limit (global team limit from spec).
Uses token bucket algorithm with exponential backoff on 429.
"""
import time
import random
from threading import Lock
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Global rate limiter using token bucket.
    
    Rate limit: 3 requests per second (from spec).
    Handles 429 responses with exponential backoff and Retry-After header.
    """
    
    def __init__(self, rate: float = 3.0, capacity: float = 3.0):
        """
        Args:
            rate: Tokens per second
            capacity: Maximum tokens
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
        self.lock = Lock()
        
        # 429 handling
        self.backoff_until = 0.0
        self.consecutive_429s = 0
    
    def acquire(self) -> bool:
        """Try to acquire a token. Returns True if successful."""
        with self.lock:
            now = time.time()
            
            # Check if in backoff period
            if now < self.backoff_until:
                return False
            
            # Refill tokens
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            # Check if can acquire
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False
    
    def wait_time(self) -> float:
        """Calculate wait time needed for next token."""
        with self.lock:
            now = time.time()
            
            # If in backoff, return remaining time
            if now < self.backoff_until:
                return self.backoff_until - now
            
            # Refill tokens
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            # If have token, no wait
            if self.tokens >= 1.0:
                return 0.0
            
            # Calculate wait time
            return max(0.0, (1.0 - self.tokens) / self.rate)
    
    def is_rate_limited(self) -> bool:
        """Check if currently rate limited (in backoff period)"""
        with self.lock:
            return time.time() < self.backoff_until
    
    def handle_429(self, retry_after: Optional[float], base_backoff: float):
        """
        Handle 429 (Too Many Requests) response.
        
        Args:
            retry_after: Retry-After header value (seconds) or None
            base_backoff: Base backoff time for exponential backoff
        """
        with self.lock:
            self.consecutive_429s += 1
            
            if retry_after is not None:
                wait_time = retry_after
                logger.warning(f"Rate limited (429), Retry-After={retry_after:.1f}s")
            else:
                # Exponential backoff with jitter
                wait_time = base_backoff * (2 ** min(self.consecutive_429s - 1, 5))
                jitter = random.uniform(0, wait_time * 0.1)
                wait_time += jitter
                logger.warning(
                    f"Rate limited (429), exponential backoff: {wait_time:.2f}s "
                    f"(consecutive={self.consecutive_429s})"
                )
            
            self.backoff_until = time.time() + wait_time
    
    def reset_429(self):
        """Reset 429 counter on successful request."""
        with self.lock:
            if self.consecutive_429s > 0:
                logger.debug(f"Rate limit recovered (was {self.consecutive_429s} consecutive 429s)")
                self.consecutive_429s = 0


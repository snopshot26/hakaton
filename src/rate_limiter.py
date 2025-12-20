"""
Global rate limiter and request scheduler with 429 handling
"""
import time
import random
import logging
from typing import Optional, Dict, Any, List
from collections import deque
from threading import Lock
import requests

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Global rate limiter with exponential backoff and jitter for 429 errors.
    Supports Retry-After header.
    """
    
    def __init__(self, base_rate: float = 3.0, capacity: float = 3.0):
        """
        Args:
            base_rate: Base requests per second
            capacity: Maximum tokens
        """
        self.base_rate = base_rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
        self.lock = Lock()
        
        # 429 backoff state
        self.backoff_until = 0.0
        self.consecutive_429s = 0
    
    def acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens, returns True if successful"""
        with self.lock:
            now = time.time()
            
            # Check if we're in backoff period
            if now < self.backoff_until:
                return False
            
            # Update tokens
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.base_rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def wait_time(self, tokens: float = 1.0) -> float:
        """Calculate wait time needed for tokens"""
        with self.lock:
            now = time.time()
            
            # Check backoff period
            if now < self.backoff_until:
                return self.backoff_until - now
            
            # Update tokens
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.base_rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                return 0.0
            return (tokens - self.tokens) / self.base_rate
    
    def handle_429(self, retry_after: Optional[float] = None, base_backoff: float = 0.5):
        """
        Handle 429 rate limit error.
        
        Args:
            retry_after: Retry-After header value in seconds (if provided)
            base_backoff: Base backoff time for exponential backoff
        """
        with self.lock:
            self.consecutive_429s += 1
            
            if retry_after is not None:
                # Use Retry-After header
                wait_time = retry_after
                logger.warning(f"⚠️  Rate limited (429), Retry-After={retry_after:.1f}s")
            else:
                # Exponential backoff with jitter
                wait_time = base_backoff * (2 ** min(self.consecutive_429s - 1, 5))
                jitter = random.uniform(0, wait_time * 0.1)  # 10% jitter
                wait_time += jitter
                logger.warning(
                    f"⚠️  Rate limited (429), exponential backoff: {wait_time:.2f}s "
                    f"(consecutive={self.consecutive_429s})"
                )
            
            self.backoff_until = time.time() + wait_time
    
    def reset_429(self):
        """Reset 429 counter on successful request"""
        with self.lock:
            if self.consecutive_429s > 0:
                logger.debug(f"✅ Rate limit recovered (was {self.consecutive_429s} consecutive 429s)")
                self.consecutive_429s = 0


class RequestScheduler:
    """
    Request scheduler with queue for /api/move (1 request at a time).
    """
    
    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter
        self.move_queue: deque = deque()
        self.move_in_progress = False
        self.lock = Lock()
    
    def schedule_move(self, bombers: List[Dict[str, Any]]) -> bool:
        """
        Schedule a move request. Returns True if queued, False if queue full.
        """
        with self.lock:
            if len(self.move_queue) >= 5:  # Max queue size
                logger.warning(f"⚠️  Move queue full ({len(self.move_queue)}), dropping request")
                return False
            
            self.move_queue.append(bombers)
            logger.debug(f"📋 Queued move request ({len(bombers)} bombers), queue size: {len(self.move_queue)}")
            return True
    
    def process_queue(self, make_request_func) -> Optional[Dict[str, Any]]:
        """
        Process next move request from queue.
        Returns response or None if queue empty or rate limited.
        
        Args:
            make_request_func: Function to make the actual HTTP request
        """
        with self.lock:
            if self.move_in_progress:
                return None  # Already processing
            
            if not self.move_queue:
                return None  # Queue empty
            
            self.move_in_progress = True
            bombers = self.move_queue.popleft()
        
        try:
            # Wait for rate limit
            wait_time = self.rate_limiter.wait_time()
            if wait_time > 0:
                logger.debug(f"⏳ Waiting {wait_time:.2f}s for rate limit")
                time.sleep(wait_time)
            
            if not self.rate_limiter.acquire():
                logger.warning("⚠️  Rate limit still active, requeuing move request")
                with self.lock:
                    self.move_queue.appendleft(bombers)  # Put back at front
                    self.move_in_progress = False
                return None
            
            # Make request
            response = make_request_func(bombers)
            
            if response is not None:
                self.rate_limiter.reset_429()
            
            return response
        finally:
            with self.lock:
                self.move_in_progress = False


"""
HTTP client with rate limiting and retry logic
"""
import time
import json
import requests
from typing import Optional, Dict, Any, List
from collections import deque
import logging

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket rate limiter"""
    
    def __init__(self, rate: float, capacity: float):
        """
        Args:
            rate: Tokens per second
            capacity: Maximum tokens
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
    
    def acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens, returns True if successful"""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def wait_time(self, tokens: float = 1.0) -> float:
        """Calculate wait time needed for tokens"""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now
        
        if self.tokens >= tokens:
            return 0.0
        return (tokens - self.tokens) / self.rate
    
    def reset_429(self):
        """Reset after successful request - restore normal rate"""
        pass  # Token bucket auto-recovers, no action needed
    
    def handle_429(self, retry_after: float = None, base_backoff: float = 0.5):
        """Handle 429 rate limit - drain tokens and wait"""
        self.tokens = 0  # Drain all tokens
        wait_time = retry_after if retry_after else base_backoff
        time.sleep(wait_time)


class APIClient:
    """HTTP client for DatsJingleBang API"""
    
    def __init__(self, base_url: str, api_key: str, use_bearer: bool = True):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        # Don't set Content-Type manually - requests.post(json=...) will set it correctly
        
        # Support both Authorization: Bearer (default) and X-Auth-Token
        if use_bearer:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        else:
            # Use X-Auth-Token (OpenAPI spec format)
            self.session.headers["X-Auth-Token"] = api_key
        
        # Rate limiter: 3 req/sec
        self.rate_limiter = TokenBucket(rate=3.0, capacity=3.0)
        self.max_retries = 3
        self.base_backoff = 0.5
    
    def _wait_for_rate_limit(self):
        """Wait if rate limit would be exceeded"""
        if not self.rate_limiter.acquire():
            wait_time = self.rate_limiter.wait_time()
            if wait_time > 0:
                time.sleep(wait_time)
                self.rate_limiter.acquire()
    
    def _request(self, method: str, endpoint: str, json_data: Optional[Dict] = None,
                rate_limiter=None) -> Optional[Dict[str, Any]]:
        """
        Make HTTP request with rate limiting and retry.
        
        Args:
            rate_limiter: Optional global RateLimiter (if None, uses internal token bucket)
        """
        url = f"{self.base_url}{endpoint}"
        
        # Use global rate limiter if provided, otherwise use internal
        limiter = rate_limiter if rate_limiter else self.rate_limiter
        
        for attempt in range(self.max_retries):
            try:
                # Wait for rate limit (global or internal)
                if rate_limiter:
                    wait_time = limiter.wait_time()
                    if wait_time > 0:
                        time.sleep(wait_time)
                    if not limiter.acquire():
                        return None  # Rate limited
                else:
                    self._wait_for_rate_limit()
                
                # Debug logging for POST requests (especially booster)
                if method == "POST" and json_data is not None:
                    body_preview = json.dumps(json_data)[:200]
                    logger.debug(
                        f"POST {url}\n"
                        f"  Headers: {dict(self.session.headers)}\n"
                        f"  Body type: {type(json_data).__name__}\n"
                        f"  Body preview: {body_preview}"
                    )
                
                if method == "GET":
                    response = self.session.get(url, timeout=10)
                elif method == "POST":
                    # Ensure json_data is a dict, not a string
                    if json_data is not None and not isinstance(json_data, dict):
                        logger.error(f"json_data must be dict, got {type(json_data)}")
                        return None
                    # Use json= parameter (requests will serialize and set Content-Type)
                    response = self.session.post(url, json=json_data, timeout=10)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                # Debug response
                if method == "POST":
                    logger.debug(
                        f"Response: {response.status_code}\n"
                        f"  Body: {response.text[:200]}"
                    )
                
                if response.status_code == 200:
                    if limiter:
                        limiter.reset_429()
                    return response.json()
                elif response.status_code == 429:
                    # Rate limited - check Retry-After header
                    retry_after = None
                    if "Retry-After" in response.headers:
                        try:
                            retry_after = float(response.headers["Retry-After"])
                        except ValueError:
                            pass
                    
                    # Handle via rate limiter if provided
                    if limiter:
                        limiter.handle_429(retry_after, self.base_backoff)
                    else:
                        # Fallback to internal handling
                        wait_time = self.base_backoff * (2 ** attempt)
                        logger.warning(f"⚠️  Rate limited (429) on {endpoint}, waiting {wait_time:.1f}s")
                        time.sleep(wait_time)
                    
                    logger.warning(f"⚠️  Rate limited (429) on {endpoint}, Retry-After={retry_after}")
                    return None  # Let RateLimiter handle backoff
                elif response.status_code == 400:
                    logger.error(f"Bad request (400) to {endpoint}: {response.text}")
                    return None
                else:
                    logger.error(f"Unexpected status {response.status_code} from {endpoint}: {response.text}")
                    if attempt < self.max_retries - 1:
                        wait_time = self.base_backoff * (2 ** attempt)
                        time.sleep(wait_time)
                    else:
                        return None
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error to {endpoint}: {e}")
                if attempt < self.max_retries - 1:
                    wait_time = self.base_backoff * (2 ** attempt)
                    time.sleep(wait_time)
                else:
                    return None
        
        return None
    
    def get_rounds(self) -> Optional[Dict[str, Any]]:
        """GET /api/rounds"""
        return self._request("GET", "/api/rounds")
    
    def get_arena(self, rate_limiter=None) -> Optional[Dict[str, Any]]:
        """GET /api/arena"""
        return self._request("GET", "/api/arena", rate_limiter=rate_limiter)
    
    def post_move(self, bombers: List[Dict[str, Any]], rate_limiter=None) -> Optional[Dict[str, Any]]:
        """POST /api/move"""
        json_data = {"bombers": bombers}
        return self._request("POST", "/api/move", json_data=json_data, rate_limiter=rate_limiter)
    
    def get_booster(self) -> Optional[Dict[str, Any]]:
        """GET /api/booster"""
        return self._request("GET", "/api/booster")
    
    def post_booster(self, booster_type: str) -> Optional[Dict[str, Any]]:
        """POST /api/booster
        
        Note: API expects booster type string (e.g. "bomb_range", "speed")
        """
        json_data = {"booster": booster_type}
        return self._request("POST", "/api/booster", json_data=json_data)


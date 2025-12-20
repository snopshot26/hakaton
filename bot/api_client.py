"""
API Client for DatsJingleBang

Extracted from OpenAPI spec:
- Endpoints:
  - GET /api/arena - Returns player state (bombers, enemies, mobs, arena layout)
  - POST /api/move - Commands for bombers (path max 30, bombs on path)
  - GET /api/booster - Available boosters and current state
  - POST /api/booster - Purchase booster ({"booster": <integer_index>})
  - GET /api/rounds - Round schedule
- Auth: ApiKeyAuth via X-Auth-Token header (or Authorization: Bearer)
- Rate limit: 3 requests per second (global team limit)
- Request format: JSON, Content-Type: application/json
- Response format: JSON
"""
import time
import json
import requests
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class APIClient:
    """HTTP client for DatsJingleBang API with rate limiting"""
    
    def __init__(self, base_url: str, api_key: str, use_bearer: bool = True):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL (e.g., https://games-test.datsteam.dev)
            api_key: API token/key
            use_bearer: If True, use Authorization: Bearer, else X-Auth-Token
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        
        # Set auth header
        if use_bearer:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        else:
            self.session.headers["X-Auth-Token"] = api_key
        
        self.max_retries = 3
        self.base_backoff = 0.5
    
    def _request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: Optional[Dict[str, Any]] = None,
        rate_limiter=None
    ) -> Optional[Dict[str, Any]]:
        """
        Make HTTP request with exponential backoff.
        
        Args:
            method: HTTP method (GET/POST)
            endpoint: API endpoint (e.g., /api/arena)
            json_data: Request body (for POST)
            rate_limiter: Optional global rate limiter
        
        Returns:
            Response JSON or None on error
        """
        url = f"{self.base_url}{endpoint}"
        
        for attempt in range(self.max_retries):
            try:
                # Wait for rate limit if limiter provided
                if rate_limiter:
                    wait_time = rate_limiter.wait_time()
                    if wait_time > 0:
                        time.sleep(wait_time)
                    if not rate_limiter.acquire():
                        logger.warning(f"Rate limited, skipping {endpoint}")
                        return None
                
                # Make request
                if method == "GET":
                    response = self.session.get(url, timeout=10)
                elif method == "POST":
                    if json_data is not None and not isinstance(json_data, dict):
                        logger.error(f"json_data must be dict, got {type(json_data)}")
                        return None
                    response = self.session.post(url, json=json_data, timeout=10)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                # Handle response
                if response.status_code == 200:
                    if rate_limiter:
                        rate_limiter.reset_429()
                    return response.json()
                elif response.status_code == 429:
                    # Rate limited
                    retry_after = None
                    if "Retry-After" in response.headers:
                        try:
                            retry_after = float(response.headers["Retry-After"])
                        except ValueError:
                            pass
                    
                    if rate_limiter:
                        rate_limiter.handle_429(retry_after, self.base_backoff)
                    else:
                        wait_time = self.base_backoff * (2 ** attempt)
                        logger.warning(f"Rate limited (429) on {endpoint}, waiting {wait_time:.1f}s")
                        time.sleep(wait_time)
                    
                    if attempt < self.max_retries - 1:
                        continue
                    return None
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
    
    def get_arena(self, rate_limiter=None) -> Optional[Dict[str, Any]]:
        """
        GET /api/arena
        
        Returns player state including:
        - bombers: List of player's bombers
        - enemies: Enemy bombers in vision
        - mobs: Mobs in vision
        - arena: Arena layout (walls, obstacles, bombs)
        - map_size: [width, height]
        - raw_score: Current score
        """
        return self._request("GET", "/api/arena", rate_limiter=rate_limiter)
    
    def post_move(self, bombers: List[Dict[str, Any]], rate_limiter=None) -> Optional[Dict[str, Any]]:
        """
        POST /api/move
        
        Args:
            bombers: List of bomber commands, each with:
                - id: Bomber ID
                - path: List of [x, y] coordinates (max 30 steps)
                - bombs: List of [x, y] coordinates where to plant bombs (must be on path)
        """
        json_data = {"bombers": bombers}
        return self._request("POST", "/api/move", json_data=json_data, rate_limiter=rate_limiter)
    
    def get_booster(self) -> Optional[Dict[str, Any]]:
        """
        GET /api/booster
        
        Returns:
            - available: List of available boosters with cost/type
            - state: Current booster state (points, stats)
        """
        return self._request("GET", "/api/booster")
    
    def post_booster(self, booster_index: int) -> Optional[Dict[str, Any]]:
        """
        POST /api/booster
        
        Args:
            booster_index: Integer index in available boosters array
        
        Request body: {"booster": <integer_index>}
        """
        json_data = {"booster": int(booster_index)}
        return self._request("POST", "/api/booster", json_data=json_data)
    
    def get_rounds(self) -> Optional[Dict[str, Any]]:
        """
        GET /api/rounds
        
        Returns round schedule and current round info.
        """
        return self._request("GET", "/api/rounds")


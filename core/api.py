"""
API client for DatsJingleBang bot
"""
import time
import requests
from typing import Dict, Any, Optional, List
from core.logger import SystemLogger

logger = SystemLogger()


class APIClient:
    """Client for interacting with the game API"""
    
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "X-Auth-Token": token
        })
    
    def _request(self, method: str, endpoint: str, json_data: Optional[Dict] = None, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """Make HTTP request with exponential backoff for rate limits"""
        url = f"{self.base_url}{endpoint}"
        
        for attempt in range(max_retries):
            try:
                if method == "GET":
                    response = self.session.get(url, timeout=10)
                elif method == "POST":
                    response = self.session.post(url, json=json_data, timeout=10)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    # Rate limit - exponential backoff
                    wait_time = (2 ** attempt) * 0.5
                    logger.warning(f"Rate limited, waiting {wait_time:.1f}s before retry")
                    time.sleep(wait_time)
                    continue
                elif response.status_code == 400:
                    # Bad request - log and don't retry
                    logger.error(f"Bad request to {endpoint}: {response.text}")
                    return None
                else:
                    logger.error(f"Unexpected status {response.status_code} from {endpoint}: {response.text}")
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 0.5
                        time.sleep(wait_time)
                    else:
                        return None
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error to {endpoint}: {e}")
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 0.5
                    time.sleep(wait_time)
                else:
                    return None
        
        return None
    
    def get_state(self) -> Optional[Dict[str, Any]]:
        """GET /api/arena - Game arena, viewed by player"""
        return self._request("GET", "/api/arena")
    
    def post_move(self, bombers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """POST /api/move - Commands for player's bombermans
        
        Args:
            bombers: List of bomber commands, each with 'id', 'path', and 'bombs'
        """
        json_data = {
            "bombers": bombers
        }
        return self._request("POST", "/api/move", json_data=json_data)
    
    def get_booster(self) -> Optional[Dict[str, Any]]:
        """GET /api/booster"""
        return self._request("GET", "/api/booster")
    
    def post_booster(self, booster_index: int) -> Optional[Dict[str, Any]]:
        """POST /api/booster with exact format: {"booster": <INTEGER_INDEX>}"""
        json_data = {"booster": booster_index}
        return self._request("POST", "/api/booster", json_data=json_data)


# api_client.py
import time
import requests
import json
from config import API_TOKEN, SAFE_BUFFER_SEC

class ApiClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.headers = {
            "X-Auth-Token": API_TOKEN,
            "Content-Type": "application/json"
        }
        self.last_request_time = 0

    def _wait_for_rate_limit(self):
        current_time = time.time()
        diff = current_time - self.last_request_time
        if diff < SAFE_BUFFER_SEC:
            time.sleep(SAFE_BUFFER_SEC - diff)
        self.last_request_time = time.time()

    def get_game_state(self):
        self._wait_for_rate_limit()
        try:
            response = requests.get(f"{self.base_url}/api/arena", headers=self.headers)
            if response.status_code == 200:
                return response.json()
            # 429 = Too Many Requests
            if response.status_code == 429:
                time.sleep(1)
            return None
        except Exception as e:
            print(f"[API] Error: {e}")
            return None

    def send_move(self, payload):
        self._wait_for_rate_limit()
        try:
            requests.post(f"{self.base_url}/api/move", headers=self.headers, json=payload)
        except Exception as e:
            print(f"[API] Move Error: {e}")

    def get_available_boosters(self):
        self._wait_for_rate_limit()
        try:
            response = requests.get(f"{self.base_url}/api/booster", headers=self.headers)
            if response.status_code == 200:
                return response.json()
            return None
        except:
            return None

    def buy_booster(self, booster_type):
        """
        booster_type: string (например 'bomb_range', 'speed')
        """
        self._wait_for_rate_limit()
        try:
            payload = {"booster": booster_type}
            resp = requests.post(f"{self.base_url}/api/booster", headers=self.headers, json=payload)
            if resp.status_code == 200:
                return True
            return False
        except Exception as e:
            print(f"[API] Buy Error: {e}")
            return False
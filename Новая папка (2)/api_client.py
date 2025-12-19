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
        """Гарантирует задержку между запросами"""
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
            else:
                print(f"[API] Error getting state: {response.status_code} {response.text}")
                return None
        except Exception as e:
            print(f"[API] Connection error: {e}")
            return None

    def send_move(self, payload):
        self._wait_for_rate_limit()
        try:
            response = requests.post(f"{self.base_url}/api/move", headers=self.headers, json=payload)
            if response.status_code != 200:
                print(f"[API] Move error: {response.status_code} {response.text}")
            return response.json()
        except Exception as e:
            print(f"[API] Move connection error: {e}")
            return None

    def buy_booster(self, booster_code):
        # booster_code: int (ID бустера)
        self._wait_for_rate_limit()
        try:
            payload = {"booster": booster_code}
            requests.post(f"{self.base_url}/api/booster", headers=self.headers, json=payload)
        except Exception as e:
            print(f"[API] Booster buy error: {e}")
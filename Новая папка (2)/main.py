# main.py
import time
import traceback
from api_client import ApiClient
from game_map import GameMap
from data_structures import Bomber, Point
import strategy
from config import BASE_URL

# --- GLOBAL STATE ---
CURRENT_STATS = {
    "bomb_range": 1,
    "speed": 2,
    "max_bombs": 1,
    "points": 0
}

PREVIOUS_RAW_SCORE = 0
LAST_BOOSTER_UPDATE = 0
BOOSTER_UPDATE_INTERVAL = 1.0


def handle_boosters(client):
    global LAST_BOOSTER_UPDATE, CURRENT_STATS
    if time.time() - LAST_BOOSTER_UPDATE < BOOSTER_UPDATE_INTERVAL:
        return

    try:
        response = client.get_available_boosters()
        if response and 'state' in response:
            state = response['state']

            old_range = CURRENT_STATS["bomb_range"]
            new_range = state.get("bomb_range", 1)
            old_speed = CURRENT_STATS["speed"]
            new_speed = state.get("speed", 2)

            if new_range > old_range: print(f"⚡ UPGRADE: RADIUS {old_range} -> {new_range}")
            if new_speed > old_speed: print(f"⚡ UPGRADE: SPEED {old_speed} -> {new_speed}")

            CURRENT_STATS["bomb_range"] = new_range
            CURRENT_STATS["speed"] = new_speed
            CURRENT_STATS["max_bombs"] = state.get("bombs", 1)
            points = state.get("points", 0)
            CURRENT_STATS["points"] = points

            bought = False
            if not bought and CURRENT_STATS["bomb_range"] < 3 and points >= 1:
                if client.buy_booster("bomb_range"): bought = True; print("🛒 BUY: RADIUS")

            if not bought and CURRENT_STATS["speed"] < 3 and points >= 1:
                if client.buy_booster("speed"): bought = True; print("🛒 BUY: SPEED")

            if not bought and CURRENT_STATS["max_bombs"] < 2 and points >= 1:
                if client.buy_booster("bombs"): bought = True; print("🛒 BUY: AMMO")

            if not bought and CURRENT_STATS["bomb_range"] < 5 and points >= 1:
                if client.buy_booster("bomb_range"): bought = True; print("🛒 BUY: RADIUS MAX")

        LAST_BOOSTER_UPDATE = time.time()
    except Exception:
        pass


def main():
    print("==========================================")
    print("🚀 DATSJINGLEBANG BOT: FINAL V10")
    print("==========================================")

    client = ApiClient(BASE_URL)
    global PREVIOUS_RAW_SCORE

    while True:
        try:
            handle_boosters(client)
            state = client.get_game_state()
            if not state: time.sleep(0.5); continue
            if 'bombers' not in state: print(f"⏳ Waiting... {state.get('round', '')}"); time.sleep(1); continue

            cur_score = state.get('raw_score', 0)
            diff = cur_score - PREVIOUS_RAW_SCORE
            if diff > 0: print(f"\n💰💰💰 +{diff} (Total: {cur_score}) 💰💰💰\n")
            PREVIOUS_RAW_SCORE = cur_score

            game_map = GameMap(state)

            my_bombers = []
            for b_data in state['bombers']:
                if b_data.get('alive', True):
                    bomber = Bomber(b_data['id'], Point(b_data['pos'][0], b_data['pos'][1]), True,
                                    b_data.get('bombs_available', 0))
                    my_bombers.append(bomber)

            move_payload = {"bombers": []}
            reserved_cells = set()
            bombs_placed_this_tick = []

            for b in my_bombers: reserved_cells.add((b.pos.x, b.pos.y))
            my_bombers.sort(key=lambda b: b.bombs_available, reverse=True)

            print(
                f"--- TICK (R:{CURRENT_STATS['bomb_range']} | S:{CURRENT_STATS['speed']} | Box:{game_map.total_boxes}) ---")

            for bomber in my_bombers:
                # ВАЖНО: передаем my_bombers
                path, bombs, log = strategy.get_bomber_action(
                    bomber,
                    game_map,
                    my_bombers,
                    CURRENT_STATS["bomb_range"],
                    reserved_cells,
                    bombs_placed_this_tick
                )

                print(f"🤖 {bomber.id.split('-')[0]} [{bomber.pos.x},{bomber.pos.y}]: {log}")

                if bombs:
                    for b in bombs: bombs_placed_this_tick.append(Point(b[0], b[1]))

                if path or bombs:
                    cmd = {"id": bomber.id, "path": path}
                    if bombs: cmd["bombs"] = bombs
                    move_payload["bombers"].append(cmd)

            if move_payload["bombers"]: client.send_move(move_payload)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERR: {e}");
            traceback.print_exc();
            time.sleep(1)


if __name__ == "__main__": main()
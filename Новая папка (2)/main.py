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
    "points": 0
}

PREVIOUS_RAW_SCORE = 0
LAST_BOOSTER_UPDATE = 0
BOOSTER_UPDATE_INTERVAL = 1.0  # Проверяем чаще, чтобы быстро покупать


def handle_boosters(client):
    """Логика авто-покупки"""
    global LAST_BOOSTER_UPDATE, CURRENT_STATS

    if time.time() - LAST_BOOSTER_UPDATE < BOOSTER_UPDATE_INTERVAL:
        return

    try:
        response = client.get_available_boosters()
        if response and 'state' in response:
            state = response['state']

            # Update stats
            CURRENT_STATS["bomb_range"] = state.get("bomb_range", 1)
            CURRENT_STATS["speed"] = state.get("speed", 2)
            points = state.get("points", 0)
            CURRENT_STATS["points"] = points

            # --- AUTO BUY LOGIC ---
            # Priority: Bomb Range (max 3) -> Speed (max 4) -> Bomb Count
            # Цены обычно ~1-2 очка.
            available = response.get('available', [])

            bought = False

            # 1. RANGE (Самое важное для фарма и убийств)
            if CURRENT_STATS["bomb_range"] < 3 and points >= 1:
                # Ищем тип 'bomb_range' или похожий в available
                # Но по Swagger мы шлем "booster": "string_type"
                if client.buy_booster("bomb_range"):
                    print("🛒 КУПИЛ: BOMB RANGE +1")
                    bought = True

            # 2. SPEED (Важно для выживания)
            if not bought and CURRENT_STATS["speed"] < 4 and points >= 1:
                if client.buy_booster("speed"):
                    print("🛒 КУПИЛ: SPEED +1")
                    bought = True

            # 3. BOMBS COUNT (Для каскадов)
            if not bought and points >= 1:
                if client.buy_booster("bombs"):  # Проверить точный type в swagger/response
                    print("🛒 КУПИЛ: BOMB COUNT +1")

        LAST_BOOSTER_UPDATE = time.time()
    except Exception as e:
        print(f"Booster Error: {e}")


def main():
    print("==========================================")
    print("🚀 DATSJINGLEBANG BOT: HUNTER UPDATE v5")
    print("==========================================")

    client = ApiClient(BASE_URL)
    global PREVIOUS_RAW_SCORE

    while True:
        try:
            # 1. Boosters & Stats
            handle_boosters(client)

            # 2. Get State
            state = client.get_game_state()
            if not state:
                time.sleep(0.5)
                continue

            if 'bombers' not in state:
                print(f"⏳ Waiting... {state.get('round', '')}")
                time.sleep(1)
                continue

            # 3. Score Tracker
            current_score = state.get('raw_score', 0)
            score_diff = current_score - PREVIOUS_RAW_SCORE
            if score_diff > 0:
                print(f"\n💰💰💰 +{score_diff} ОЧКОВ! (Всего: {current_score}) 💰💰💰\n")
            PREVIOUS_RAW_SCORE = current_score

            # 4. Map & Entities
            game_map = GameMap(state)

            my_bombers = []
            for b_data in state['bombers']:
                if b_data.get('alive', True):
                    bomber = Bomber(
                        id=b_data['id'],
                        pos=Point(b_data['pos'][0], b_data['pos'][1]),
                        alive=True,
                        bombs_available=b_data.get('bombs_available', 0)
                    )
                    my_bombers.append(bomber)

            move_payload = {"bombers": []}
            reserved_cells = set()
            bombs_placed_this_tick = []

            for b in my_bombers:
                reserved_cells.add((b.pos.x, b.pos.y))

            # Сортировка: Сначала убегают те, кто в опасности
            my_bombers.sort(key=lambda b: (game_map.is_safe(b.pos.x, b.pos.y), -b.bombs_available))

            print(
                f"--- TICK (R:{CURRENT_STATS['bomb_range']} | S:{CURRENT_STATS['speed']} | Box:{game_map.total_boxes}) ---")

            for bomber in my_bombers:
                path, bombs, action_desc = strategy.get_bomber_action(
                    bomber,
                    game_map,
                    bomb_range=CURRENT_STATS["bomb_range"],
                    reserved_cells=reserved_cells,
                    bombs_placed_this_tick=bombs_placed_this_tick
                )

                short_id = bomber.id.split('-')[0]
                pos_str = f"[{bomber.pos.x}, {bomber.pos.y}]"
                print(f"🤖 {short_id} {pos_str}: {action_desc}")

                if bombs:
                    for bp in bombs:
                        bombs_placed_this_tick.append(Point(bp[0], bp[1]))

                if path or bombs:
                    command = {"id": bomber.id, "path": path}
                    if bombs: command["bombs"] = bombs
                    move_payload["bombers"].append(command)

            if move_payload["bombers"]:
                client.send_move(move_payload)

        except KeyboardInterrupt:
            print("\n🛑 Stop.")
            break
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
            traceback.print_exc()
            time.sleep(1)


if __name__ == "__main__":
    main()
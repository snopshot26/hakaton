# main.py
import time
from api_client import ApiClient
from game_map import GameMap
from data_structures import Bomber, Point
import strategy
from config import BASE_URL


def main():
    print("🚀 Bot starting...")
    client = ApiClient(BASE_URL)

    while True:
        try:
            # 1. Получаем состояние игры
            state = client.get_game_state()
            if not state:
                time.sleep(1)
                continue

            # Проверка, идет ли раунд
            # Если бот мертв или раунд не начался - просто ждем
            if 'bombers' not in state:
                print("Waiting for game start...")
                time.sleep(1)
                continue

            # 2. Парсим карту
            game_map = GameMap(state)

            # Парсим моих бомберов
            my_bombers = []
            for b in state['bombers']:
                bomber = Bomber(
                    id=b['id'],
                    pos=Point(b['pos'][0], b['pos'][1]),
                    alive=b.get('alive', True),  # Иногда API не шлет поле если жив
                    bombs_available=b.get('bombs_available', 0)
                )
                my_bombers.append(bomber)

            # 3. Принимаем решения
            move_payload = {"bombers": []}

            for bomber in my_bombers:
                # Пропускаем мертвых или двигающихся
                is_moving = False  # В этой версии API нет флага is_moving в явном виде, считаем что можем слать команды

                path, bombs = strategy.get_bomber_action(bomber, game_map)

                if path or bombs:
                    command = {
                        "id": bomber.id,
                        "path": path,
                    }
                    if bombs:
                        command["bombs"] = bombs

                    move_payload["bombers"].append(command)

            # 4. Отправляем команды
            if move_payload["bombers"]:
                client.send_move(move_payload)
                print(f"Sent moves for {len(move_payload['bombers'])} bombers")
            else:
                print("Idle...")

            # (Опционально) Покупка бустеров
            # Можно добавить логику: если state.get('points', 0) > 5 -> client.buy_booster(type)

        except KeyboardInterrupt:
            print("Stopping...")
            break
        except Exception as e:
            print(f"CRITICAL ERROR in main loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)


if __name__ == "__main__":
    main()
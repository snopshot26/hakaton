# strategy.py
import random
from data_structures import Point
from pathfinding import get_path_a_star, find_nearest_safe_tile, find_nearest_destructible


def get_bomber_action(bomber, game_map):
    """
    Возвращает (move_path, bomb_coords)
    move_path: список списков [[x,y], [x,y]]
    bomb_coords: список списков [[x,y]] или пустой
    """

    # 1. ПРОВЕРКА БЕЗОПАСНОСТИ (Survival Instinct)
    # Если мы стоим в огне - БЕЖАТЬ
    if not game_map.is_safe(bomber.pos.x, bomber.pos.y):
        escape_path = find_nearest_safe_tile(bomber.pos, game_map)
        if escape_path:
            # Преобразуем Points в list[int]
            return [p.to_list() for p in escape_path], []

    # 2. АТАКА / ФАРМ (Если бомбы есть)
    if bomber.bombs_available > 0:
        # Ищем ближайшую позицию для уничтожения ящика
        farm_path = find_nearest_destructible(bomber.pos, game_map)

        if farm_path is not None:
            # Если мы уже на позиции (путь пустой или длина 0), ставим бомбу
            if len(farm_path) == 0:
                # ВАЖНО: Если ставим бомбу, надо сразу запланировать отход!
                # Пока просто ставим и надеемся, что в следующем тике сработает "Safety Check"
                # Но лучше сделать шаг в сторону
                return [], [bomber.pos.to_list()]
            else:
                # Идем к цели
                return [p.to_list() for p in farm_path], []

    # 3. ЕСЛИ НЕЧЕГО ДЕЛАТЬ (Random Walk / Camp)
    # Просто идем в случайную безопасную свободную клетку
    neighbors = []
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        nx, ny = bomber.pos.x + dx, bomber.pos.y + dy
        if game_map.is_walkable(nx, ny) and game_map.is_safe(nx, ny):
            neighbors.append([nx, ny])

    if neighbors:
        return [random.choice(neighbors)], []

    return [], []
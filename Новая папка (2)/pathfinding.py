# pathfinding.py
from collections import deque
from data_structures import Point


def get_path_a_star(start: Point, target: Point, game_map, ignore_danger=False):
    """Поиск пути A*. Возвращает список Point или None"""
    if not game_map.is_valid(target.x, target.y):
        return None

    # Очередь: (cost, x, y, path)
    # В питоне heapq удобнее, но для простоты на сетке BFS+dist тоже сойдет
    # Используем упрощенный BFS, так как веса ребер одинаковые

    queue = deque([(start, [])])
    visited = {(start.x, start.y)}

    max_depth = 20  # Ограничение глубины, чтобы не виснуть

    while queue:
        current, path = queue.popleft()

        if len(path) > max_depth:
            continue

        if current == target:
            return path  # Возвращаем путь (без стартовой точки)

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy

            if not game_map.is_valid(nx, ny):
                continue

            # Проверка проходимости
            if not game_map.is_walkable(nx, ny):
                continue

            # Проверка безопасности (если не сказано игнорировать)
            if not ignore_danger and not game_map.is_safe(nx, ny):
                continue

            if (nx, ny) not in visited:
                visited.add((nx, ny))
                new_path = path + [Point(nx, ny)]
                queue.append((Point(nx, ny), new_path))

    return None


def find_nearest_safe_tile(start: Point, game_map):
    """Ищет ближайшую безопасную клетку (BFS)"""
    queue = deque([(start, [])])
    visited = {(start.x, start.y)}

    while queue:
        current, path = queue.popleft()

        # Если нашли безопасную и это не стартовая (если старт опасен)
        if game_map.is_safe(current.x, current.y):
            return path if path else [current]  # Возвращаем путь или саму точку

        if len(path) > 10:  # Не ищем слишком далеко
            continue

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if game_map.is_valid(nx, ny) and game_map.is_walkable(nx, ny):
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((Point(nx, ny), path + [Point(nx, ny)]))
    return []


def find_nearest_destructible(start: Point, game_map):
    """Ищет ближайшую координату рядом с ящиком"""
    queue = deque([(start, [])])
    visited = {(start.x, start.y)}

    while queue:
        current, path = queue.popleft()

        if len(path) > 15:
            continue

        # Проверяем соседей текущей клетки на наличие ящика
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if game_map.is_valid(nx, ny) and game_map.grid[ny][nx] == 2:
                # Нашли ящик рядом! Текущая клетка - хорошая позиция для атаки
                return path

                # Продолжаем поиск пути по свободным клеткам
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if game_map.is_valid(nx, ny) and game_map.is_walkable(nx, ny) and game_map.is_safe(nx, ny):
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((Point(nx, ny), path + [Point(nx, ny)]))
    return None
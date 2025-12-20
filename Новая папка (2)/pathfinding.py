# pathfinding.py
from collections import deque
from data_structures import Point


def get_path_to_point(start: Point, target: Point, game_map, ignore_danger=False):
    if not game_map.is_valid(target.x, target.y): return None

    # Оптимизация: Если цель слишком далеко, используем простую эвристику (Manhattan)
    # Но для начала просто увеличим лимит
    queue = deque([(start, [])])
    visited = {(start.x, start.y)}

    # --- FIX: Увеличиваем лимит шагов для больших карт ---
    max_depth = 300

    while queue:
        current, path = queue.popleft()
        if len(path) > max_depth: continue
        if current == target: return path

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if not game_map.is_valid(nx, ny): continue

            safe = True
            if not ignore_danger and not game_map.is_safe(nx, ny): safe = False

            if game_map.is_walkable(nx, ny) and safe:
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((Point(nx, ny), path + [Point(nx, ny)]))
    return None


def find_nearest_safe_tile(start: Point, game_map):
    queue = deque([(start, [])])
    visited = {(start.x, start.y)}
    while queue:
        current, path = queue.popleft()
        if game_map.is_safe(current.x, current.y) and len(path) > 0:
            return path
        if len(path) > 20: continue  # Чуть увеличили поиск спасения

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if game_map.is_valid(nx, ny) and game_map.is_walkable(nx, ny):
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((Point(nx, ny), path + [Point(nx, ny)]))
    return []


def find_best_bombing_spot(start: Point, game_map, bomb_range, reserved_cells):
    best_spot = None
    best_value = -1
    best_path = []

    queue = deque([(start, [])])
    visited = {(start.x, start.y)}

    # Если ящиков нет, ищем очень далеко (чтобы найти врага)
    max_steps = 100 if game_map.total_boxes < 5 else 20

    while queue:
        current, path = queue.popleft()

        if (current.x, current.y) not in reserved_cells:
            dist = len(path)
            score = game_map.calculate_potential_score(current.x, current.y, bomb_range, dist)
            if score > 0:
                value = (score ** 2) / (dist + 2)
                if value > best_value:
                    best_value = value
                    best_spot = current
                    best_path = path

        if len(path) >= max_steps: continue

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if game_map.is_valid(nx, ny) and game_map.is_walkable(nx, ny) and game_map.is_safe(nx, ny):
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((Point(nx, ny), path + [Point(nx, ny)]))
    return best_path if best_spot else None
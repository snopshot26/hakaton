# pathfinding.py
from collections import deque
from data_structures import Point


def get_path_to_point(start: Point, target: Point, game_map, ignore_danger=False):
    if not game_map.is_valid(target.x, target.y): return None

    queue = deque([(start, [])])
    visited = {(start.x, start.y)}
    max_depth = 40

    while queue:
        current, path = queue.popleft()
        if len(path) > max_depth: continue
        if current == target: return path

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if not game_map.is_valid(nx, ny): continue

            is_safe_step = True
            if not ignore_danger and not game_map.is_safe(nx, ny):
                is_safe_step = False

            if game_map.is_walkable(nx, ny) and is_safe_step:
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    new_path = path + [Point(nx, ny)]
                    queue.append((Point(nx, ny), new_path))
    return None


def find_nearest_safe_tile(start: Point, game_map):
    queue = deque([(start, [])])
    visited = {(start.x, start.y)}

    while queue:
        current, path = queue.popleft()
        if game_map.is_safe(current.x, current.y) and len(path) > 0:
            return path
        if len(path) > 15: continue

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
    max_steps = 15

    while queue:
        current, path = queue.popleft()

        if (current.x, current.y) not in reserved_cells:
            dist = len(path)
            # Передаем dist в расчет очков!
            potential_score = game_map.calculate_potential_score(current.x, current.y, bomb_range, dist)

            if potential_score > 0:
                # Value formula
                # Если цель близко - value высокий. Если цель далеко, score должен быть огромным.
                value = (potential_score ** 2) / (dist + 2)

                if value > best_value:
                    best_value = value
                    best_spot = current
                    best_path = path

        if len(path) >= max_steps:
            continue

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = current.x + dx, current.y + dy
            if game_map.is_valid(nx, ny) and game_map.is_walkable(nx, ny) and game_map.is_safe(nx, ny):
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((Point(nx, ny), path + [Point(nx, ny)]))

    return best_path if best_spot else None
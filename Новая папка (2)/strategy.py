# strategy.py
import time
import random
import math
from data_structures import Point
from pathfinding import find_nearest_safe_tile, find_best_bombing_spot, get_path_to_point

LOCKED_TARGETS = {}
FAILED_TARGETS = {}


def get_bomber_action(bomber, game_map, all_bombers, bomb_range=1, reserved_cells=None, bombs_placed_this_tick=None):
    if reserved_cells is None: reserved_cells = set()
    if bombs_placed_this_tick is None: bombs_placed_this_tick = []
    global LOCKED_TARGETS, FAILED_TARGETS

    cur_time = time.time()
    if bomber.id in FAILED_TARGETS:
        t, ts = FAILED_TARGETS[bomber.id]
        if cur_time - ts > 2.0: del FAILED_TARGETS[bomber.id]

    # --- 1. SURVIVAL ---
    if not game_map.is_safe(bomber.pos.x, bomber.pos.y):
        if bomber.id in LOCKED_TARGETS: del LOCKED_TARGETS[bomber.id]

        path = find_nearest_safe_tile(bomber.pos, game_map)
        if path:
            return [p.to_list() for p in path], [], "🏃 RUN"
        else:
            # PANIC MOVE
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = bomber.pos.x + dx, bomber.pos.y + dy
                if game_map.is_walkable(nx, ny):
                    return [[nx, ny]], [], "😱 PANIC"

            # KAMIKAZE MOVE (Walking into enemies allowed)
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = bomber.pos.x + dx, bomber.pos.y + dy
                if game_map.is_valid(nx, ny):
                    c = game_map.grid[ny][nx]
                    if c != 1 and c != 2 and c != 3:
                        return [[nx, ny]], [], "💀 KAMIKAZE"

            return [], [], "💀 TRAPPED"

    # Helper
    def is_safe_to_plant(pos):
        for b in game_map.bombs:
            if pos.dist_manhattan(b.pos) <= 2: return False
        for b in bombs_placed_this_tick:
            if pos.dist_manhattan(b) <= 2: return False

        blast_zone = set()
        blast_zone.add((pos.x, pos.y))
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            for r in range(1, bomb_range + 1):
                nx, ny = pos.x + dx * r, pos.y + dy * r
                if not game_map.is_valid(nx, ny): break
                if game_map.grid[ny][nx] == 1: break
                blast_zone.add((nx, ny))
                if game_map.grid[ny][nx] == 2: break

        for ally in all_bombers:
            if ally.id == bomber.id: continue
            if not ally.alive: continue
            if (ally.pos.x, ally.pos.y) in blast_zone:
                return False

        # Simulation
        game_map.danger_grid[pos.y][pos.x] = 1
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            for r in range(1, bomb_range + 1):
                nx, ny = pos.x + dx * r, pos.y + dy * r
                if not game_map.is_valid(nx, ny): break
                if game_map.grid[ny][nx] == 1: break
                game_map.danger_grid[ny][nx] = 1
                if game_map.grid[ny][nx] == 2: break

        can_escape = False
        if find_nearest_safe_tile(pos, game_map): can_escape = True

        # Rollback
        game_map.danger_grid = [[0] * game_map.width for _ in range(game_map.height)]
        game_map._calculate_danger_zones()
        for b_pos in bombs_placed_this_tick:
            game_map.register_virtual_bomb(b_pos.x, b_pos.y, bomb_range)

        return can_escape

    # --- 2. LOCKED TARGET ---
    if bomber.id in LOCKED_TARGETS:
        target = LOCKED_TARGETS[bomber.id]
        valid = True
        if bomber.id in FAILED_TARGETS and FAILED_TARGETS[bomber.id][0] == target:
            valid = False
        elif not game_map.is_walkable(target.x, target.y):
            valid = False
        elif game_map.calculate_potential_score(target.x, target.y, bomb_range, 0) == 0:
            valid = False

        if valid:
            if bomber.pos == target:
                if is_safe_to_plant(bomber.pos):
                    game_map.register_virtual_bomb(bomber.pos.x, bomber.pos.y, bomb_range)
                    del LOCKED_TARGETS[bomber.id]
                    # Try to move immediately
                    esc = find_nearest_safe_tile(bomber.pos, game_map)
                    move = [esc[0].to_list()] if esc else []
                    return move, [[bomber.pos.x, bomber.pos.y]], f"💣 BOOM"
                else:
                    FAILED_TARGETS[bomber.id] = (target, time.time())
                    del LOCKED_TARGETS[bomber.id]
            else:
                path = get_path_to_point(bomber.pos, target, game_map)
                if path:
                    reserved_cells.add((target.x, target.y))
                    return [p.to_list() for p in path], [], f"🔒 TARGET"
                else:
                    del LOCKED_TARGETS[bomber.id]
        else:
            del LOCKED_TARGETS[bomber.id]

    # --- 3. NEW TARGET ---
    if bomber.bombs_available > 0:
        cur = (bomber.pos.x, bomber.pos.y)
        if cur in reserved_cells: reserved_cells.remove(cur)
        path = find_best_bombing_spot(bomber.pos, game_map, bomb_range, reserved_cells)
        reserved_cells.add(cur)

        if path is not None:
            if len(path) == 0:
                if is_safe_to_plant(bomber.pos):
                    game_map.register_virtual_bomb(bomber.pos.x, bomber.pos.y, bomb_range)
                    esc = find_nearest_safe_tile(bomber.pos, game_map)
                    move = [esc[0].to_list()] if esc else []
                    return move, [[bomber.pos.x, bomber.pos.y]], f"💣 INSTANT"
            else:
                tgt = Point(path[-1].x, path[-1].y)
                if not (bomber.id in FAILED_TARGETS and FAILED_TARGETS[bomber.id][0] == tgt):
                    LOCKED_TARGETS[bomber.id] = tgt
                    reserved_cells.add((tgt.x, tgt.y))
                    return [p.to_list() for p in path], [], f"🆕 NEW"

    # --- 4. LATE GAME / IDLE ---
    is_late_game = game_map.total_boxes < 10

    if is_late_game:
        center = Point(game_map.width // 2, game_map.height // 2)

        # 1. Try A* Path to Center
        if bomber.pos.dist_manhattan(center) > 5:
            path = get_path_to_point(bomber.pos, center, game_map)
            if path:
                return [p.to_list() for p in path[:1]], [], "👑 CENTER"

            # 2. COMPASS FALLBACK (Если A* не нашел путь)
            # Просто идем в сторону центра
            best_move = None
            min_dist = 99999

            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = bomber.pos.x + dx, bomber.pos.y + dy
                if game_map.is_walkable(nx, ny) and game_map.is_safe(nx, ny):
                    # Считаем дистанцию до центра
                    d = abs(nx - center.x) + abs(ny - center.y)
                    if d < min_dist:
                        min_dist = d
                        best_move = [nx, ny]

            if best_move:
                return [best_move], [], "🧭 COMPASS"

    # Random walk
    neighbors = []
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        nx, ny = bomber.pos.x + dx, bomber.pos.y + dy
        if game_map.is_walkable(nx, ny) and game_map.is_safe(nx, ny):
            neighbors.append([nx, ny])
    if neighbors:
        return [random.choice(neighbors)], [], "🎲 WALK"

    return [], [], "💤 IDLE"
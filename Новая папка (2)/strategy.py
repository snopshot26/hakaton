# strategy.py
import time
import random
from data_structures import Point
from pathfinding import find_nearest_safe_tile, find_best_bombing_spot, get_path_to_point

# ПАМЯТЬ ЦЕЛЕЙ: { 'bomber_id': Point(x, y) }
LOCKED_TARGETS = {}

# ЧЕРНЫЙ СПИСОК: { 'bomber_id': (Point(x, y), timestamp) }
# Если бот пришел на точку и не смог поставить бомбу (суицид), он запоминает это.
FAILED_TARGETS = {}


def get_bomber_action(bomber, game_map, bomb_range=1, reserved_cells=None, bombs_placed_this_tick=None):
    if reserved_cells is None: reserved_cells = set()
    if bombs_placed_this_tick is None: bombs_placed_this_tick = []

    global LOCKED_TARGETS, FAILED_TARGETS

    # 0. ОЧИСТКА СТАРЫХ ФЕЙЛОВ (3 сек)
    current_time = time.time()
    if bomber.id in FAILED_TARGETS:
        target, ts = FAILED_TARGETS[bomber.id]
        if current_time - ts > 3.0:
            del FAILED_TARGETS[bomber.id]

    # --- 1. ПРИОРИТЕТ ВЫЖИВАНИЯ (SURVIVAL) ---
    if not game_map.is_safe(bomber.pos.x, bomber.pos.y):
        # Если стоим в огне - сбрасываем цель и бежим
        if bomber.id in LOCKED_TARGETS:
            del LOCKED_TARGETS[bomber.id]

        escape_path = find_nearest_safe_tile(bomber.pos, game_map)
        if escape_path:
            return [p.to_list() for p in escape_path], [], "🏃 БЕГУ ИЗ ОГНЯ!"
        return [], [], "😱 ПАНИКА"

    # --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: БЕЗОПАСНОСТЬ УСТАНОВКИ ---
    def is_safe_to_plant_here(pos: Point):
        # Социальная дистанция для бомб: не ставить ближе 2 клеток к другой бомбе
        min_dist = 2

        # 1. Проверка существующих бомб
        for existing_bomb in game_map.bombs:
            if pos.dist_manhattan(existing_bomb.pos) <= min_dist:
                return False

        # 2. Проверка бомб, которые ставят союзники прямо сейчас
        for new_bomb_pos in bombs_placed_this_tick:
            if pos.dist_manhattan(new_bomb_pos) <= min_dist:
                return False

        return True

    # --- 2. ОБРАБОТКА ЗАФИКСИРОВАННОЙ ЦЕЛИ (LOCKED TARGET) ---
    if bomber.id in LOCKED_TARGETS:
        target = LOCKED_TARGETS[bomber.id]
        is_valid = True

        # Проверяем валидность цели:
        # 1. Не в черном списке
        if bomber.id in FAILED_TARGETS and FAILED_TARGETS[bomber.id][0] == target:
            is_valid = False

        # 2. Не стена (могло измениться)
        elif not game_map.is_walkable(target.x, target.y):
            is_valid = False

        # 3. Есть ли там очки? (dist=0, т.к. мы оцениваем саму точку)
        # Если 0 очков, но мы шли туда - возможно, кто-то уже все взорвал.
        elif game_map.calculate_potential_score(target.x, target.y, bomb_range, 0) == 0:
            is_valid = False

        if is_valid:
            if bomber.pos == target:
                # МЫ НА МЕСТЕ

                # Проверка: не слишком ли тесно?
                if not is_safe_to_plant_here(bomber.pos):
                    del LOCKED_TARGETS[bomber.id]
                    return [], [], "⚠️ ТЕСНО (Отмена)"

                # Проверка: суицид?
                game_map.danger_grid[bomber.pos.y][bomber.pos.x] = 1
                escape = find_nearest_safe_tile(bomber.pos, game_map)
                game_map.danger_grid[bomber.pos.y][bomber.pos.x] = 0

                if escape:
                    # УСПЕХ: Ставим бомбу
                    score = game_map.calculate_potential_score(bomber.pos.x, bomber.pos.y, bomb_range, 0)
                    game_map.register_virtual_bomb(bomber.pos.x, bomber.pos.y, bomb_range)
                    del LOCKED_TARGETS[bomber.id]

                    log_msg = f"💣 БУМ! (+{score})"
                    if score >= 10: log_msg = f"⚔️ УБИВАЮ! (+{score})"

                    return [escape[0].to_list()], [bomber.pos.to_list()], log_msg
                else:
                    # ПРОВАЛ: Нет пути отхода
                    FAILED_TARGETS[bomber.id] = (target, time.time())
                    del LOCKED_TARGETS[bomber.id]
                    return [], [], "⛔ НЕТ ВЫХОДА"
            else:
                # ИДЕМ К ЦЕЛИ
                path = get_path_to_point(bomber.pos, target, game_map)
                if path:
                    reserved_cells.add((target.x, target.y))
                    return [p.to_list() for p in path], [], f"🔒 К ЦЕЛИ ({len(path)} ш.)"
                else:
                    # Путь заблокирован
                    del LOCKED_TARGETS[bomber.id]
        else:
            # Цель невалидна -> сброс
            del LOCKED_TARGETS[bomber.id]

    # --- 3. ПОИСК НОВОЙ ЦЕЛИ (NEW TARGET) ---
    if bomber.bombs_available > 0:
        # Временно убираем себя из резерва, чтобы найти цель под ногами
        current_pos_tuple = (bomber.pos.x, bomber.pos.y)
        if current_pos_tuple in reserved_cells:
            reserved_cells.remove(current_pos_tuple)

        target_path = find_best_bombing_spot(bomber.pos, game_map, bomb_range, reserved_cells)

        # Возвращаем в резерв
        reserved_cells.add(current_pos_tuple)

        if target_path is not None:
            if len(target_path) == 0:
                # МЫ УЖЕ СТОИМ НА ХОРОШЕМ МЕСТЕ (но Locked Target не было)
                if not is_safe_to_plant_here(bomber.pos):
                    pass  # Нельзя ставить
                else:
                    game_map.danger_grid[bomber.pos.y][bomber.pos.x] = 1
                    escape = find_nearest_safe_tile(bomber.pos, game_map)
                    game_map.danger_grid[bomber.pos.y][bomber.pos.x] = 0

                    if escape:
                        score = game_map.calculate_potential_score(bomber.pos.x, bomber.pos.y, bomb_range, 0)
                        game_map.register_virtual_bomb(bomber.pos.x, bomber.pos.y, bomb_range)

                        log_msg = f"💣 БУМ! (+{score})"
                        if score >= 10: log_msg = f"⚔️ УБИВАЮ! (+{score})"
                        return [escape[0].to_list()], [bomber.pos.to_list()], log_msg
                    else:
                        FAILED_TARGETS[bomber.id] = (bomber.pos, time.time())
                        return [], [], "⛔ ОПАСНО"
            else:
                # НАШЛИ НОВУЮ ЦЕЛЬ ВДАЛЕКЕ
                target_pt = Point(target_path[-1].x, target_path[-1].y)

                # Проверка на фейл (не идем туда, где только что облажались)
                if bomber.id in FAILED_TARGETS and FAILED_TARGETS[bomber.id][0] == target_pt:
                    return [], [], "🔄 Игнор Failed"

                LOCKED_TARGETS[bomber.id] = target_pt
                reserved_cells.add((target_pt.x, target_pt.y))

                score = game_map.calculate_potential_score(target_pt.x, target_pt.y, bomb_range, 0)

                log_msg = f"🆕 ЦЕЛЬ ({len(target_path)} ш.)"
                if score >= 10: log_msg = f"😈 ОХОТА ({score})"

                return [p.to_list() for p in target_path], [], log_msg

    # --- 4. РАЗВЕДКА / КОНТРОЛЬ ЦЕНТРА ---
    # Если ящиков мало (< 20), идем в центр
    is_late_game = game_map.total_boxes < 20

    if is_late_game:
        center = Point(game_map.width // 2, game_map.height // 2)
        if bomber.pos.dist_manhattan(center) > 5:
            # Ищем путь в центр, игнорируя опасность (рискуем ради позиции) или аккуратно
            path_to_center = get_path_to_point(bomber.pos, center, game_map)
            if path_to_center:
                # Берем только первый шаг, не лочим цель, просто дрейфуем
                return [p.to_list() for p in path_to_center[:1]], [], "👑 К ЦЕНТРУ"

    # Случайное блуждание (чтобы не стоять AFK)
    neighbors = []
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        nx, ny = bomber.pos.x + dx, bomber.pos.y + dy
        if (nx, ny) in reserved_cells: continue
        if game_map.is_walkable(nx, ny) and game_map.is_safe(nx, ny):
            neighbors.append([nx, ny])

    if neighbors:
        pick = random.choice(neighbors)
        return [pick], [], "🔍 РАЗВЕДКА"

    return [], [], "💤 IDLE"
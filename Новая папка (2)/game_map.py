# game_map.py
from data_structures import Point, Bomb, Bomber, Enemy


class GameMap:
    def __init__(self, state_json):
        self.width = state_json['map_size'][0]
        self.height = state_json['map_size'][1]

        # grid: 0=пусто, 1=стена, 2=ящик, 3=бомба, 4=враг, 5=АКТИВНЫЙ моб, 6=СПЯЩИЙ моб
        self.grid = [[0 for _ in range(self.width)] for _ in range(self.height)]
        self.danger_grid = [[0 for _ in range(self.width)] for _ in range(self.height)]

        self.bombs = []
        self.enemies = []
        self.mobs = []
        # Словарь таймеров сна для мобов: {(x,y): safe_time_ms}
        self.mob_timers = {}

        self.walls = set()
        self.obstacles = set()

        self._parse_arena(state_json['arena'])
        self._parse_enemies(state_json.get('enemies', []))
        self._parse_mobs(state_json.get('mobs', []))
        self._calculate_danger_zones()

        self.total_boxes = len(self.obstacles)

    def _parse_arena(self, arena):
        for w in arena['walls']:
            x, y = w[0], w[1]
            if self.is_valid(x, y):
                self.grid[y][x] = 1
                self.walls.add((x, y))

        for o in arena['obstacles']:
            x, y = o[0], o[1]
            if self.is_valid(x, y):
                self.grid[y][x] = 2
                self.obstacles.add((x, y))

        for b in arena['bombs']:
            pos = Point(b['pos'][0], b['pos'][1])
            bomb = Bomb(pos, b.get('timer', 8), b.get('range', 1))
            self.bombs.append(bomb)
            if self.is_valid(pos.x, pos.y):
                self.grid[pos.y][pos.x] = 3

    def _parse_enemies(self, enemies_list):
        for e in enemies_list:
            pos = Point(e['pos'][0], e['pos'][1])
            self.enemies.append(Enemy(e['id'], pos))
            if self.is_valid(pos.x, pos.y):
                self.grid[pos.y][pos.x] = 4  # 4 = Enemy Player

    def _parse_mobs(self, mobs_list):
        for m in mobs_list:
            pos = Point(m['pos'][0], m['pos'][1])
            mob_info = {
                'pos': pos,
                'type': m.get('type', 'patrol'),
                'safe_time': m.get('safe_time', 0)
            }
            self.mobs.append(mob_info)

            if self.is_valid(pos.x, pos.y):
                if mob_info['safe_time'] > 0:
                    # Моб спит
                    self.grid[pos.y][pos.x] = 6  # 6 = Sleeping Mob
                    self.mob_timers[(pos.x, pos.y)] = mob_info['safe_time']
                else:
                    # Моб активен и опасен
                    self.grid[pos.y][pos.x] = 5  # 5 = Active Mob

    def _calculate_danger_zones(self):
        # 1. Бомбы
        for bomb in self.bombs:
            self.register_virtual_bomb(bomb.pos.x, bomb.pos.y, bomb.range)

        # 2. Враги (Kiting - держим дистанцию 1 клетку)
        for enemy in self.enemies:
            self._mark_radius_danger(enemy.pos.x, enemy.pos.y, radius=1)

        # 3. Активные мобы
        for mob in self.mobs:
            if mob['safe_time'] > 0:
                continue  # Спящий не опасен (пока)

            ignore_walls = (mob['type'] == 'ghost')
            self._mark_radius_danger(mob['pos'].x, mob['pos'].y, radius=1, ignore_walls=ignore_walls)

    def _mark_radius_danger(self, x, y, radius, ignore_walls=False):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx == 0 and dy == 0: continue
                nx, ny = x + dx, y + dy
                if not self.is_valid(nx, ny): continue
                if not ignore_walls and self.grid[ny][nx] == 1: continue
                self._mark_danger(nx, ny)

    def register_virtual_bomb(self, x, y, bomb_range):
        self._mark_danger(x, y)
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            for r in range(1, bomb_range + 1):
                nx, ny = x + dx * r, y + dy * r
                if not self.is_valid(nx, ny): break
                cell = self.grid[ny][nx]
                if cell == 1: break
                self._mark_danger(nx, ny)
                if cell == 2: break

    def _mark_danger(self, x, y):
        if self.is_valid(x, y):
            self.danger_grid[y][x] = 1

    def is_valid(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x, y):
        if not self.is_valid(x, y): return False
        cell = self.grid[y][x]
        # Можно ходить по пустому (0) и по СПЯЩИМ мобам (6)
        # По активным (5) и врагам (4) ходить нельзя - смерть
        return cell == 0 or cell == 6

    def is_safe(self, x, y):
        if not self.is_valid(x, y): return False
        return self.danger_grid[y][x] == 0

    def calculate_potential_score(self, x, y, bomb_range, dist_to_target):
        """
        УМНЫЙ ПОДСЧЕТ ОЧКОВ
        dist_to_target: сколько шагов боту идти до точки установки бомбы.
        Используется для отсеивания далеких врагов.
        """
        score = 0
        boxes_hit = 0

        # Таймер взрыва нашей бомбы (стандарт 8 сек = 8000 мс)
        # Если есть бустер на фитиль, тут надо менять, но пока считаем 8000
        MY_FUSE_TIME = 8000

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            for r in range(1, bomb_range + 1):
                nx, ny = x + dx * r, y + dy * r
                if not self.is_valid(nx, ny): break
                cell = self.grid[ny][nx]

                if cell == 1: break  # Стена

                if cell == 2:  # Ящик
                    boxes_hit += 1
                    score += min(boxes_hit, 4)  # 1+2+3+4
                    break

                    # --- ЛОГИКА ОХОТЫ НА АКТИВНЫХ ---
                if cell == 4 or cell == 5:  # Враг или Активный Моб
                    # КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ:
                    # Если враг далеко (> 4 клеток), мы считаем его за 0 очков.
                    # Не бегаем за призраками!
                    if dist_to_target <= 4:
                        score += 10
                    else:
                        pass  # Игнорируем далеких врагов

                # --- ЛОГИКА СПЯЩИХ (SPAWN KILL) ---
                if cell == 6:  # Спящий моб
                    safe_time = self.mob_timers.get((nx, ny), 0)

                    # Логика:
                    # Мы хотим, чтобы бомба (8с) взорвалась СРАЗУ как моб проснется.
                    # Значит, ставить надо, когда safe_time ≈ 8000.
                    # Даем окно: от 2000 до 9000 мс.
                    # Если меньше 2000 - опасно, проснется раньше чем взорвется.
                    # Если больше 9000 - долго ждать.

                    if 2000 <= safe_time <= 9000:
                        score += 15  # БОНУС! Приоритет выше чем у врага
                    else:
                        # Если он проснется через 1 сек, а бомба через 8 - он уйдет. 0 очков.
                        pass

                if cell == 3:  # Другая бомба
                    score += 1
                    break
        return score
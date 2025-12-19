# game_map.py
from data_structures import Point, Bomb, Bomber, Enemy


class GameMap:
    def __init__(self, state_json):
        self.width = state_json['map_size'][0]
        self.height = state_json['map_size'][1]
        self.grid = [[0 for _ in range(self.width)] for _ in range(self.height)]
        self.danger_grid = [[0 for _ in range(self.width)] for _ in range(self.height)]

        self.bombs = []
        self.enemies = []
        self.walls = set()
        self.obstacles = set()

        self._parse_arena(state_json['arena'])
        self._parse_enemies(state_json['enemies'])
        self._calculate_danger_zones()

    def _parse_arena(self, arena):
        # 1. Стены (неразрушимые) = 1
        for w in arena['walls']:
            x, y = w[0], w[1]
            if self.is_valid(x, y):
                self.grid[y][x] = 1
                self.walls.add((x, y))

        # 2. Ящики (разрушаемые) = 2
        for o in arena['obstacles']:
            x, y = o[0], o[1]
            if self.is_valid(x, y):
                self.grid[y][x] = 2
                self.obstacles.add((x, y))

        # 3. Бомбы = 3
        for b in arena['bombs']:
            pos = Point(b['pos'][0], b['pos'][1])
            # В Swagger timer это float (seconds), range int
            bomb = Bomb(pos, b.get('timer', 8), b.get('range', 1))
            self.bombs.append(bomb)
            if self.is_valid(pos.x, pos.y):
                self.grid[pos.y][pos.x] = 3

    def _parse_enemies(self, enemies_list):
        for e in enemies_list:
            pos = Point(e['pos'][0], e['pos'][1])
            self.enemies.append(Enemy(e['id'], pos))
            # Враги тоже препятствия для движения
            if self.is_valid(pos.x, pos.y):
                self.grid[pos.y][pos.x] = 4

    def _calculate_danger_zones(self):
        """Заполняет danger_grid там, где скоро будет взрыв"""
        for bomb in self.bombs:
            # Центр
            self._mark_danger(bomb.pos.x, bomb.pos.y)

            # Лучи взрыва
            directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
            for dx, dy in directions:
                for r in range(1, bomb.range + 1):
                    nx, ny = bomb.pos.x + dx * r, bomb.pos.y + dy * r

                    if not self.is_valid(nx, ny):
                        break

                    # Стена блокирует взрыв
                    if self.grid[ny][nx] == 1:
                        break

                    self._mark_danger(nx, ny)

                    # Ящик блокирует взрыв, но сам взрывается (опасно стоять)
                    if self.grid[ny][nx] == 2:
                        break

    def _mark_danger(self, x, y):
        if self.is_valid(x, y):
            self.danger_grid[y][x] = 1

    def is_valid(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x, y):
        """Можно ли физически встать на клетку (нет стены/ящика/бомбы)"""
        if not self.is_valid(x, y):
            return False
        return self.grid[y][x] == 0 or self.grid[y][
            x] == 4  # Можно пытаться пройти сквозь врага (убьет, но технически проходимо)

    def is_safe(self, x, y):
        """Безопасно ли стоять (нет опасности взрыва)"""
        if not self.is_valid(x, y): return False
        return self.danger_grid[y][x] == 0
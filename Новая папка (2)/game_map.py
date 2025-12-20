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
        self.obstacles = set()

        # ВАЖНО: Атрибут для хранения позиций союзников
        self.ally_positions = set()

        self._parse_arena(state_json['arena'])
        self._parse_enemies(state_json.get('enemies', []))
        self._parse_allies(state_json.get('bombers', []))
        self._calculate_danger_zones()
        self.total_boxes = len(self.obstacles)

    def _parse_arena(self, arena):
        for w in arena['walls']:
            if self.is_valid(w[0], w[1]): self.grid[w[1]][w[0]] = 1
        for o in arena['obstacles']:
            if self.is_valid(o[0], o[1]):
                self.grid[o[1]][o[0]] = 2
                self.obstacles.add((o[0], o[1]))
        for b in arena['bombs']:
            pos = Point(b['pos'][0], b['pos'][1])
            self.bombs.append(Bomb(pos, b.get('timer', 8), b.get('range', 1)))
            if self.is_valid(pos.x, pos.y): self.grid[pos.y][pos.x] = 3

    def _parse_enemies(self, enemies):
        for e in enemies:
            pos = Point(e['pos'][0], e['pos'][1])
            self.enemies.append(Enemy(e['id'], pos))
            if self.is_valid(pos.x, pos.y): self.grid[pos.y][pos.x] = 4

    def _parse_allies(self, bombers):
        for b in bombers:
            if b.get('alive', True):
                self.ally_positions.add((b['pos'][0], b['pos'][1]))

    def _calculate_danger_zones(self):
        # 1. Бомбы
        for bomb in self.bombs:
            self.register_virtual_bomb(bomb.pos.x, bomb.pos.y, bomb.range)
        # 2. Враги (Держим дистанцию)
        for enemy in self.enemies:
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    nx, ny = enemy.pos.x + dx, enemy.pos.y + dy
                    if self.is_valid(nx, ny): self.danger_grid[ny][nx] = 1

    def register_virtual_bomb(self, x, y, bomb_range):
        """Помечает зоны опасности от бомбы. Используется и при старте, и при планировании."""
        self._mark_danger(x, y)
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            for r in range(1, bomb_range + 1):
                nx, ny = x + dx * r, y + dy * r
                if not self.is_valid(nx, ny) or self.grid[ny][nx] == 1: break
                self._mark_danger(nx, ny)
                if self.grid[ny][nx] == 2: break

    def _mark_danger(self, x, y):
        if self.is_valid(x, y): self.danger_grid[y][x] = 1

    def is_valid(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x, y):
        if not self.is_valid(x, y): return False
        return self.grid[y][x] == 0  # Только по пустому

    def is_safe(self, x, y):
        if not self.is_valid(x, y): return False
        return self.danger_grid[y][x] == 0

    def calculate_potential_score(self, x, y, bomb_range, dist):
        score = 0
        boxes = 0
        # Агрессивность зависит от стадии игры
        enemy_value = 10 if self.total_boxes > 20 else 50

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            for r in range(1, bomb_range + 1):
                nx, ny = x + dx * r, y + dy * r
                if not self.is_valid(nx, ny) or self.grid[ny][nx] == 1: break

                cell = self.grid[ny][nx]
                if cell == 2:  # Ящик
                    boxes += 1
                    score += min(boxes, 4) * 2
                    break
                if cell == 4:  # Враг
                    if dist <= 6: score += enemy_value
                if cell == 3: score += 1; break
        return score
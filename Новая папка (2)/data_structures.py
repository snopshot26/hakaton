# data_structures.py
from dataclasses import dataclass
from typing import List, Tuple

@dataclass(eq=True, frozen=True)
class Point:
    x: int
    y: int

    def to_list(self) -> List[int]:
        return [self.x, self.y]

    def dist_manhattan(self, other: 'Point') -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)

@dataclass
class Bomb:
    pos: Point
    timer: int
    range: int

@dataclass
class Bomber:
    id: str
    pos: Point
    alive: bool
    bombs_available: int

@dataclass
class Enemy:
    id: str
    pos: Point
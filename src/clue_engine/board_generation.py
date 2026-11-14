"""Seeded procedural geometry for the standard board."""

import random
from dataclasses import replace

from .board import (
    BoardLayout,
    Room,
    Square,
    _connected,
    _neighbors,
    _random_doors_for_rooms,
)


def _room_shape(room_id: int, box: tuple[int, int, int, int], shape: str) -> Room:
    x, y, width, height = box
    squares = set()
    for row in range(height):
        for column in range(width):
            if (
                shape == "rectangle" or row < 3
                or (shape == "left" and column < 3)
                or (shape == "right" and column >= width - 3)
                or (shape == "tee" and (width - 3) // 2 <= column < (width - 3) // 2 + 3)
            ):
                squares.add(Square(x + column, y + row))
    return Room(room_id, frozenset(squares))


def _open_without_dead_ends(hallways: set[Square]) -> bool:
    return all(sum(neighbor in hallways for neighbor in _neighbors(square)) >= 2 for square in hallways)


def generate_board_layout(
    layout: BoardLayout,
    rng: random.Random,
    door_rng: random.Random,
    *,
    randomize_doors: bool = False,
) -> BoardLayout:
    """Generate rooms and a connected hallway network without hallway dead ends."""
    from .board import DEFAULT_BOARD

    if (
        (layout.width, layout.height) != (DEFAULT_BOARD.width, DEFAULT_BOARD.height)
        or [room.squares for room in layout.rooms] != [room.squares for room in DEFAULT_BOARD.rooms]
        or layout.starts != DEFAULT_BOARD.starts
    ):
        raise ValueError("procedural maps require the standard board geometry")

    grid = {Square(x, y) for y in range(layout.height) for x in range(layout.width)}
    for _ in range(100):
        widths = [rng.randint(5, 6), rng.randint(5, 7), rng.randint(5, 6),
                  rng.randint(5, 6), rng.randint(5, 6), rng.randint(5, 6),
                  rng.randint(5, 6), rng.randint(5, 7), rng.randint(5, 6)]
        heights = [rng.randint(5, 6), rng.randint(5, 6), rng.randint(5, 6),
                   rng.randint(5, 7), 5, 5,
                   rng.randint(5, 6), rng.randint(5, 6), rng.randint(5, 6)]
        boxes = [
            (0, 0, widths[0], heights[0]),
            ((25 - widths[1]) // 2, 0, widths[1], heights[1]),
            (25 - widths[2], 0, widths[2], heights[2]),
            (0, 10 + rng.randrange(8 - heights[3]), widths[3], heights[3]),
            (25 - widths[4], 7, widths[4], heights[4]),
            (25 - widths[5], 14, widths[5], heights[5]),
            (0, 27 - heights[6], widths[6], heights[6]),
            ((25 - widths[7]) // 2, 27 - heights[7], widths[7], heights[7]),
            (25 - widths[8], 27 - heights[8], widths[8], heights[8]),
        ]
        generated = tuple(
            _room_shape(room.card_id, boxes[index], "rectangle" if index in (0, 2, 6, 8)
                        else rng.choice(("rectangle", "left", "right", "tee")))
            for index, room in enumerate(layout.rooms)
        )
        occupied = set().union(*(room.squares for room in generated))
        hallways = grid - occupied
        starts = {start.square for start in layout.starts}
        if not starts <= hallways or not _connected(frozenset(hallways)) or not _open_without_dead_ends(hallways):
            continue
        counts = {
            room.card_id: len(layout.doors_for(room.card_id))
            for room in generated
        }
        try:
            doors = _random_doors_for_rooms(
                generated,
                frozenset(hallways),
                counts,
                door_rng,
                randomize_counts=randomize_doors,
            )
        except ValueError:
            continue
        protected = starts | {door.hallway_square for door in doors}
        for door in doors:
            dx = door.hallway_square.x - door.room_square.x
            dy = door.hallway_square.y - door.room_square.y
            protected.update(
                Square(door.hallway_square.x - offset * dy, door.hallway_square.y + offset * dx)
                for offset in (-1, 1)
            )
        left, right = rng.randint(9, 10), rng.randint(15, 16)
        top, bottom = rng.randint(10, 11), rng.randint(15, 17)
        center = {Square(x, y) for x in range(left, right) for y in range(top, bottom)}
        if center & protected:
            continue
        hallways.difference_update(center)
        if not _connected(frozenset(hallways)) or not _open_without_dead_ends(hallways):
            continue
        walls = set(center)
        for _ in range(160):
            horizontal = rng.choice((True, False))
            length = rng.randint(2, 4)
            x, y = rng.randrange(1, layout.width - 1), rng.randrange(1, layout.height - 1)
            segment = {Square(x + (i if horizontal else 0), y + (0 if horizontal else i))
                       for i in range(length)}
            if not segment <= hallways or segment & protected:
                continue
            remaining = hallways - segment
            if not _open_without_dead_ends(remaining) or not _connected(frozenset(remaining)):
                continue
            hallways = remaining
            walls.update(segment)
            if len(walls) >= 70:
                break
        if len(walls) < 55:
            continue
        return replace(layout, rooms=generated, hallways=frozenset(hallways),
                       walls=frozenset(walls), doors=tuple(doors))
    raise ValueError("could not generate a playable board layout")

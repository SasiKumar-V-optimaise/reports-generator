"""Dependency-free polygon geometry.

Convex clipping uses the Sutherland-Hodgman algorithm and supports clockwise or
counter-clockwise clip polygons.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Point

EPSILON = 1e-9


def signed_area(points: Sequence[Point]) -> float:
    if len(points) < 3:
        return 0.0
    return (
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(points, (*points[1:], points[0]), strict=False)
        )
        / 2.0
    )


def polygon_area(points: Sequence[Point]) -> float:
    return abs(signed_area(points))


def cross_product(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def point_on_segment(
    point: Point,
    start: Point,
    end: Point,
    *,
    epsilon: float = EPSILON,
) -> bool:
    return (
        abs(cross_product(start, end, point)) <= epsilon
        and min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
        and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon
    )


def point_in_polygon(
    point: Point,
    polygon: Sequence[Point],
    *,
    epsilon: float = EPSILON,
) -> bool:
    """Ray-cast a point, considering polygon boundaries inside."""

    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if point_on_segment(point, previous, current, epsilon=epsilon):
            return True
        xi, yi = current
        xj, yj = previous
        if (yi > y) != (yj > y):
            x_intersection = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x_intersection >= x - epsilon:
                inside = not inside
        previous = current
    return inside


def line_intersection(
    segment_start: Point,
    segment_end: Point,
    clip_start: Point,
    clip_end: Point,
    *,
    epsilon: float = EPSILON,
) -> Point:
    sx, sy = segment_start
    ex, ey = segment_end
    cx, cy = clip_start
    dx, dy = clip_end
    ray = (ex - sx, ey - sy)
    clip_ray = (dx - cx, dy - cy)
    denominator = ray[0] * clip_ray[1] - ray[1] * clip_ray[0]
    if abs(denominator) <= epsilon:
        return segment_end
    offset = (cx - sx, cy - sy)
    distance = (offset[0] * clip_ray[1] - offset[1] * clip_ray[0]) / denominator
    return sx + distance * ray[0], sy + distance * ray[1]


def convex_polygon_intersection(
    subject: Sequence[Point],
    clip_polygon: Sequence[Point],
    *,
    epsilon: float = EPSILON,
) -> tuple[Point, ...]:
    """Clip ``subject`` by a convex polygon."""

    output = list(subject)
    if len(output) < 3 or len(clip_polygon) < 3:
        return ()
    if polygon_area(clip_polygon) <= epsilon:
        return ()

    orientation = 1.0 if signed_area(clip_polygon) >= 0 else -1.0

    def is_inside(point: Point, edge_start: Point, edge_end: Point) -> bool:
        return cross_product(edge_start, edge_end, point) * orientation >= -epsilon

    for index, clip_start in enumerate(clip_polygon):
        clip_end = clip_polygon[(index + 1) % len(clip_polygon)]
        input_polygon, output = output, []
        if not input_polygon:
            break
        segment_start = input_polygon[-1]
        for segment_end in input_polygon:
            end_inside = is_inside(segment_end, clip_start, clip_end)
            start_inside = is_inside(segment_start, clip_start, clip_end)
            if end_inside:
                if not start_inside:
                    output.append(
                        line_intersection(
                            segment_start,
                            segment_end,
                            clip_start,
                            clip_end,
                            epsilon=epsilon,
                        )
                    )
                output.append(segment_end)
            elif start_inside:
                output.append(
                    line_intersection(
                        segment_start,
                        segment_end,
                        clip_start,
                        clip_end,
                        epsilon=epsilon,
                    )
                )
            segment_start = segment_end
    return tuple(output)


clip_polygon = convex_polygon_intersection

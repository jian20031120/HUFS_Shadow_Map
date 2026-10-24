"""Destination routing on campus ground assumed movable outside known buildings."""
import math
import heapq

import numpy as np
import shapely
from shapely.geometry import LineString, Point, mapping
from shapely.ops import nearest_points, transform, unary_union

from .shadow_model import TO_G, TO_M

BUILDING_NUMERIC_MARGIN_M = 0.05
ASSUMPTION = 'campus_nonbuilding_ground_assumed_walkable'


def _polygons(geometry):
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if geometry.geom_type in {'MultiPolygon', 'GeometryCollection'}:
        return [part for item in geometry.geoms for part in _polygons(item)]
    return []


def _polygonal(geometry):
    if geometry is None or geometry.is_empty:
        return unary_union([])
    return unary_union(_polygons(shapely.make_valid(geometry)))


def _lines(geometry):
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == 'LineString':
        return [geometry] if geometry.length > 1e-8 else []
    if geometry.geom_type in {'MultiLineString', 'GeometryCollection'}:
        return [part for item in geometry.geoms for part in _lines(item)]
    return []


def _empty_collection():
    return {'type': 'FeatureCollection', 'features': []}


def _line_collection(lines, category):
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': f'{category}-{index}',
         'geometry': mapping(transform(TO_G, line)),
         'properties': {'length_m': line.length, 'category': category,
                        'assumption': ASSUMPTION}}
        for index, line in enumerate(lines)]}


def _result(status, message, grid_size):
    return {'status': status, 'message': message, 'route': _empty_collection(),
            'shaded_route': _empty_collection(), 'sunny_route': _empty_collection(),
            'target': None, 'target_area': None, 'distance_m': 0.0,
            'sunny_distance_m': 0.0, 'shaded_distance_m': 0.0,
            'assumption': ASSUMPTION, 'grid_size_m': grid_size,
            'target_kind': 'building_approach_unverified_entrance'}


def _target(point, destination, *, inside=False):
    return {'type': 'Feature', 'geometry': mapping(transform(TO_G, point)),
            'properties': {'destination_distance_m': point.distance(destination),
                           'target_kind': 'already_at_destination' if inside else 'building_approach_unverified_entrance',
                           'assumption': ASSUMPTION}}


def _edge_exposure(lines, lengths, shade):
    """Exact sunny lengths, avoiding expensive intersections for clear cases."""
    lengths = np.asarray(lengths, dtype=float)
    sunny = lengths.copy()
    if shade.is_empty or not len(lines):
        return sunny
    covered = np.asarray(shapely.covers(shade, lines), dtype=bool)
    sunny[covered] = 0.0
    crossing = ~covered & ~np.asarray(shapely.disjoint(shade, lines), dtype=bool)
    if crossing.any():
        shaded = shapely.length(shapely.intersection(lines[crossing], shade))
        sunny[crossing] = np.maximum(0.0, lengths[crossing]-shaded)
    # Suppress floating-point remnants below a tenth of a micrometre.
    sunny[sunny < 1e-7] = 0.0
    return sunny


def _lexicographic_path(sources, targets, sunny, lengths, node_count, start, goal):
    """Dijkstra on (sunny metres, total metres), with no weighted compromise."""
    order = np.argsort(sources, kind='stable')
    targets, sunny, lengths = targets[order], sunny[order], lengths[order]
    offsets = np.r_[0, np.cumsum(np.bincount(sources, minlength=node_count))]
    best_sun = np.full(node_count, np.inf)
    best_length = np.full(node_count, np.inf)
    predecessor = np.full(node_count, -1, dtype=int)
    best_sun[start] = best_length[start] = 0.0
    queue = [(0.0, 0.0, int(start))]
    while queue:
        sunlight, distance, current = heapq.heappop(queue)
        if (sunlight, distance) != (best_sun[current], best_length[current]):
            continue
        if current == goal:
            break
        for edge in range(offsets[current], offsets[current+1]):
            neighbour = int(targets[edge])
            candidate = (sunlight+sunny[edge], distance+lengths[edge])
            if candidate < (best_sun[neighbour], best_length[neighbour]):
                best_sun[neighbour], best_length[neighbour] = candidate
                predecessor[neighbour] = current
                heapq.heappush(queue, (float(candidate[0]), float(candidate[1]), neighbour))
    if not math.isfinite(float(best_sun[goal])):
        return None
    path, current = [], int(goal)
    while current != start:
        if current < 0 or len(path) > node_count:
            return None
        path.append(current)
        current = int(predecessor[current])
    path.append(int(start))
    path.reverse()
    return path


def build_destination_guidance(campus, building_footprints, shadow_metric, origin,
                               destination_geometry, *, grid_size=3.0):
    """Minimize sunny distance, then total distance, to a building approach.

    Inputs use WGS84 except EPSG:32652 shadows; output geometry uses WGS84.
    Campus ground outside known buildings is assumed movable. Actual entrances
    and passage are not verified. Exposure uses exact metric intersections.
    """
    try:
        latitude, longitude = origin['latitude'], origin['longitude']
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            raise ValueError
        latitude, longitude = float(latitude), float(longitude)
        if not (math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('현재 위치의 위도·경도를 확인하세요.') from error
    if not math.isfinite(grid_size) or grid_size <= 0:
        raise ValueError('격자 간격은 양수여야 합니다.')
    campus_metric = _polygonal(transform(TO_M, campus))
    destination = _polygonal(transform(TO_M, destination_geometry))
    start = transform(TO_M, Point(longitude, latitude))
    if (campus_metric.is_empty or not (math.isfinite(start.x) and math.isfinite(start.y))
            or not campus_metric.covers(start)):
        return _result('outside', '현재 위치가 캠퍼스 분석 범위 밖입니다.', grid_size)
    if destination.is_empty or destination.distance(campus_metric) > 2:
        return _result('no_route', '선택한 건물의 외곽 접근점이 분석 범위 밖입니다.', grid_size)
    target_area = mapping(transform(TO_G, destination))
    if destination.covers(start):
        result = _result('arrived', '현재 위치가 선택한 목적지 건물 범위 안에 있습니다.', grid_size)
        result.update(target=_target(start, destination, inside=True), target_area=target_area,
                      target_kind='already_at_destination')
        return result
    buildings = unary_union([destination]+[_polygonal(transform(TO_M, item)) for item in building_footprints])
    ground = _polygonal(campus_metric.difference(buildings.buffer(BUILDING_NUMERIC_MARGIN_M)))
    if not ground.covers(start):
        return _result('no_route', '현재 위치가 알려진 건물 바닥과 겹쳐 출발 경로를 계산할 수 없습니다.', grid_size)
    if start.distance(destination) <= 2:
        result = _result('arrived', '선택한 건물 외곽에 도착했습니다. 실제 출입구 위치는 확인되지 않았습니다.', grid_size)
        result.update(target=_target(start, destination), target_area=target_area)
        return result
    shade = _polygonal(_polygonal(shadow_metric).intersection(ground))
    shapely.prepare(ground)
    shapely.prepare(shade)
    shapely.prepare(destination)

    west, south, east, north = campus_metric.bounds
    effective_grid = float(grid_size)
    while True:
        left, right = math.floor((west-start.x)/effective_grid)-1, math.ceil((east-start.x)/effective_grid)+1
        bottom, top = math.floor((south-start.y)/effective_grid)-1, math.ceil((north-start.y)/effective_grid)+1
        columns, rows_count = right-left+1, top-bottom+1
        if columns*rows_count <= 100_000:
            break
        effective_grid += .5
        if effective_grid > max(10, grid_size*4):
            return _result('no_route', '전체 분석 범위를 계산할 격자 크기를 확보하지 못했습니다.', effective_grid)
    xx, yy = np.meshgrid(start.x+np.arange(left, right+1)*effective_grid,
                         start.y+np.arange(bottom, top+1)*effective_grid)
    flat_x, flat_y = xx.ravel(), yy.ravel()
    point_array = shapely.points(flat_x, flat_y)
    valid = np.asarray(shapely.covers(ground, point_array), dtype=bool).reshape(xx.shape)
    node_count = columns*rows_count
    start_index = (-bottom)*columns-left
    destination_distance = np.asarray(shapely.distance(destination, point_array))
    candidate_indices = np.flatnonzero(valid.ravel() & (destination_distance <= effective_grid*math.sqrt(2)+2))
    goal_edges = {}
    for index in candidate_indices:
        node = Point(float(flat_x[index]), float(flat_y[index]))
        distance = float(destination_distance[index])
        if distance <= 2:
            target = node
        else:
            boundary = nearest_points(destination, node)[0]
            target = Point(boundary.x+(node.x-boundary.x)/distance,
                           boundary.y+(node.y-boundary.y)/distance)
        if not ground.covers(target) or target.distance(destination) > 2+1e-7:
            continue
        connector = LineString([node, target]) if node.distance(target) > 1e-8 else None
        if connector is not None and not ground.covers(connector):
            continue
        length = node.distance(target)
        sunlight = 0.0 if connector is None else float(_edge_exposure(np.array([connector], dtype=object), [length], shade)[0])
        goal_edges[int(index)] = (sunlight, length, target)
    if not goal_edges:
        return _result('no_route', '선택한 건물 바닥 밖에 연결 가능한 접근점을 찾지 못했습니다.', effective_grid)

    row_numbers, column_numbers = np.indices(xx.shape)
    edge_sources, edge_targets, edge_sunny, edge_lengths = [], [], [], []
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        target_rows, target_cols = row_numbers+dr, column_numbers+dc
        bounded = ((target_rows >= 0) & (target_rows < rows_count)
                   & (target_cols >= 0) & (target_cols < columns))
        rr, cc = row_numbers[bounded], column_numbers[bounded]
        tr, tc = target_rows[bounded], target_cols[bounded]
        allowed = valid[rr, cc] & valid[tr, tc]
        if dr and dc:
            allowed &= valid[rr, tc] & valid[tr, cc]
        source_indices, target_indices = rr[allowed]*columns+cc[allowed], tr[allowed]*columns+tc[allowed]
        if not len(source_indices):
            continue
        coordinates = np.stack([np.column_stack((flat_x[source_indices], flat_y[source_indices])),
                                np.column_stack((flat_x[target_indices], flat_y[target_indices]))], axis=1)
        lines = shapely.linestrings(coordinates)
        covered = np.asarray(shapely.covers(ground, lines), dtype=bool)
        source_indices, target_indices, lines = source_indices[covered], target_indices[covered], lines[covered]
        if not len(source_indices):
            continue
        lengths = np.full(len(lines), effective_grid*math.hypot(dr, dc))
        sunlight = _edge_exposure(lines, lengths, shade)
        edge_sources.extend([source_indices, target_indices])
        edge_targets.extend([target_indices, source_indices])
        edge_sunny.extend([sunlight, sunlight])
        edge_lengths.extend([lengths, lengths])
    goal_indices = np.array(list(goal_edges), dtype=int)
    edge_sources.append(goal_indices)
    edge_targets.append(np.full(len(goal_indices), node_count, dtype=int))
    edge_sunny.append(np.array([goal_edges[index][0] for index in goal_indices]))
    edge_lengths.append(np.array([goal_edges[index][1] for index in goal_indices]))
    route_indices = _lexicographic_path(np.concatenate(edge_sources), np.concatenate(edge_targets),
                                        np.concatenate(edge_sunny), np.concatenate(edge_lengths),
                                        node_count+1, start_index, node_count)
    if route_indices is None:
        return _result('no_route', '가정한 이동 영역 안에서 선택 건물까지 연결되는 경로를 찾지 못했습니다.', effective_grid)
    goal_index = route_indices[-2]
    coordinates = [(float(flat_x[index]), float(flat_y[index])) for index in route_indices[:-1]]
    target = goal_edges[goal_index][2]
    if Point(coordinates[-1]).distance(target) > 1e-8:
        coordinates.append((target.x, target.y))
    if len(coordinates) < 2:
        return _result('no_route', '유효한 목적지 이동 선분을 만들지 못했습니다.', effective_grid)
    route_metric = LineString(coordinates)
    if not ground.covers(route_metric):
        return _result('no_route', '복원한 경로가 계산 이동 영역을 벗어났습니다.', effective_grid)
    shaded_lines, sunny_lines = _lines(route_metric.intersection(shade)), _lines(route_metric.difference(shade))
    result = _result('ok', '선택한 건물 외곽까지 햇빛 노출 거리를 우선 줄인 모의 경로입니다.', effective_grid)
    result.update(route=_line_collection([route_metric], 'route'),
                  shaded_route=_line_collection(shaded_lines, 'shaded'),
                  sunny_route=_line_collection(sunny_lines, 'sunny'),
                  target=_target(target, destination), target_area=target_area,
                  distance_m=route_metric.length,
                  sunny_distance_m=sum(line.length for line in sunny_lines),
                  shaded_distance_m=sum(line.length for line in shaded_lines))
    return result

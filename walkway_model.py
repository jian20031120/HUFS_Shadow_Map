"""Shade intersections of mapped footways; no destination routing is implied."""
import copy
import json
import math
from pathlib import Path

from shapely.geometry import Point, mapping, shape
from shapely.ops import nearest_points, transform, unary_union

from fetch_walkways import independent_kind, is_walkable, line_parts, source_tag_basis
from public_buildings import PublicDataError, campus_id
from shadow_model import TO_G, TO_M


def load_walkways(path, campus):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        meta = data['metadata']
        if (data['type'] != 'FeatureCollection' or meta['schema_version'] != 2
                or meta['campus_id'] != campus_id(campus) or meta['crs'] != 'EPSG:4326'
                or meta['source_kind'] != 'osm_explicit_footways'):
            raise ValueError('보행로 자료의 캠퍼스·좌표계·형식 불일치')
        if not 0 < len(data['features']) <= 5000:
            raise ValueError('보행로 도형 수 오류')
        identifiers = set()
        for feature in data['features']:
            identifier = str(feature['id'])
            geom = shape(feature['geometry'])
            if (identifier in identifiers or geom.is_empty or not geom.is_valid
                    or geom.geom_type != 'LineString' or not is_walkable(feature['properties'])
                    or not campus.buffer(1e-9).covers(geom)
                    or feature['properties'].get('independent_kind') != independent_kind(feature['properties'])
                    or feature['properties'].get('guidance_class') != 'independent_walkway'
                    or feature['properties'].get('reference_only') is not False):
                raise ValueError('보행로 식별자·기하·통행 태그 오류')
            identifiers.add(identifier)
            if not feature['properties'].get('source_way_id'):
                raise ValueError('원본 보행로 식별자 없음')
            original_tags = feature['properties'].get('osm_tags')
            if (not isinstance(original_tags, dict) or not is_walkable(original_tags)
                    or feature['properties'].get('source_tag_basis') != source_tag_basis(original_tags)):
                raise ValueError('원본 보행유형 태그·선택 근거 오류')
            if any(feature['properties'].get(key) != value for key, value in original_tags.items()
                   if key in {'highway', 'footway', 'sidewalk', 'crossing', 'foot', 'access'}
                   or key.startswith(('sidewalk:', 'footway:', 'crossing:'))):
                raise ValueError('표시 속성과 원본 보행 태그 불일치')
        return data
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PublicDataError(f'보행로 자료를 읽을 수 없습니다: {error}') from error


def load_shared_ways(path, campus):
    """Load separate road references; this does not assert pedestrian access."""
    from fetch_shared_ways import is_shared_reference
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        meta = data['metadata']
        if (data['type'] != 'FeatureCollection' or meta['schema_version'] != 1
                or meta['campus_id'] != campus_id(campus) or meta['crs'] != 'EPSG:4326'
                or meta['source_kind'] != 'osm_shared_roads_reference'
                or meta.get('reference_only') is not True):
            raise ValueError('참고 도로의 캠퍼스·좌표계·형식 불일치')
        if not 0 < len(data['features']) <= 5000:
            raise ValueError('참고 도로 도형 수 오류')
        identifiers = set()
        for feature in data['features']:
            identifier = str(feature['id'])
            properties = feature['properties']
            geom = shape(feature['geometry'])
            if (identifier in identifiers or geom.is_empty or not geom.is_valid
                    or geom.geom_type != 'LineString' or not is_shared_reference(properties)
                    or not campus.buffer(1e-9).covers(geom)
                    or properties.get('guidance_class') != 'shared_road_reference'
                    or properties.get('reference_only') is not True):
                raise ValueError('참고 도로 식별자·기하·참고용 표기 오류')
            identifiers.add(identifier)
            if not properties.get('source_way_id') or not isinstance(properties.get('osm_tags'), dict):
                raise ValueError('참고 도로 원본 식별자·태그 없음')
        return data
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PublicDataError(f'참고 도로 자료를 읽을 수 없습니다: {error}') from error


def shade_walkways(walkways, shade_metric_geometry, building_footprints=None, min_length_m=1.0):
    """Return WGS84 shaded line segments and their metric lengths.

    `shade_metric_geometry` and optional `building_footprints` use EPSG:32652.
    The latter can be one geometry or a list. The source footways are WGS84.
    """
    if min_length_m <= 0:
        raise ValueError('Minimum segment length must be positive')
    shaded = shade_metric_geometry
    if shaded is None or shaded.is_empty:
        return {'type': 'FeatureCollection', 'features': [],
                'metadata': {'length_crs': 'EPSG:32652', 'total_shaded_length_m': 0.0,
                             'footway_source': copy.deepcopy(walkways.get('metadata', {}))}}
    if building_footprints is not None:
        footprints = unary_union(building_footprints) if isinstance(building_footprints, (list, tuple)) else building_footprints
        if not footprints.is_empty:
            shaded = shaded.difference(footprints)
    features = []
    for path in walkways['features']:
        line = transform(TO_M, shape(path['geometry']))
        pieces = [part for part in line_parts(line.intersection(shaded)) if part.length >= min_length_m]
        fraction = sum(part.length for part in pieces)/line.length
        for index, piece in enumerate(pieces):
            properties = copy.deepcopy(path['properties'])
            identifier = f"{path['id']}-SHADE-{index}"
            properties.update(segment_id=identifier, source_feature_id=str(path['id']),
                              length_m=piece.length, path_length_m=line.length,
                              shaded_path_fraction=min(1.0, fraction),
                              guidance_kind='shade_section_not_route')
            features.append({'type': 'Feature', 'id': identifier,
                             'geometry': mapping(transform(TO_G, piece)), 'properties': properties})
    return {'type': 'FeatureCollection', 'features': features,
            'metadata': {'length_crs': 'EPSG:32652',
                         'total_shaded_length_m': sum(f['properties']['length_m'] for f in features),
                         'footway_source': copy.deepcopy(walkways.get('metadata', {})),
                         'scope_note': '등록된 보행로와 추정 그늘이 겹치는 선분입니다. 연결 경로나 전 구간 그늘을 보장하지 않습니다.'}}


def nearby_shaded_walkways(segments, userlatlon, radius_m=250, maxresults=3):
    """Nearby independent OSM ways ranked by straight-line distance.

    Input location is (latitude, longitude). No location is persisted. Returned
    `nearest_point` uses named latitude/longitude keys; geometry remains GeoJSON.
    """
    if len(userlatlon) != 2 or any(isinstance(value, bool) for value in userlatlon):
        raise ValueError('위도·경도 형식을 확인하세요.')
    latitude, longitude = map(float, userlatlon)
    if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError('위도·경도 범위를 확인하세요.')
    if not math.isfinite(radius_m) or radius_m <= 0 or not 1 <= maxresults <= 20:
        raise ValueError('주변 검색 범위 또는 개수를 확인하세요.')
    location = transform(TO_M, Point(longitude, latitude))
    if not (math.isfinite(location.x) and math.isfinite(location.y)):
        return []
    candidates = []
    for feature in segments['features']:
        if (feature['properties'].get('guidance_class') == 'shared_road_reference'
                or feature['properties'].get('reference_only') is True
                or not is_walkable(feature['properties'])):
            continue
        line = transform(TO_M, shape(feature['geometry']))
        distance = location.distance(line)
        if distance > radius_m:
            continue
        nearest = transform(TO_G, nearest_points(location, line)[1])
        candidates.append({**copy.deepcopy(feature), 'distance_m': distance,
                           'nearest_point': {'latitude': nearest.y, 'longitude': nearest.x},
                           'distance_kind': 'straight_line_not_route'})
    candidates.sort(key=lambda item: (item['distance_m'], str(item['id'])))
    output, seen_ways = [], set()
    for candidate in candidates:
        way_id = str(candidate['properties']['source_way_id'])
        if way_id in seen_ways:
            continue
        seen_ways.add(way_id)
        output.append(candidate)
        if len(output) == maxresults:
            break
    return output

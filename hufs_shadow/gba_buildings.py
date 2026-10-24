"""Conservative spatial association of GBA estimates with existing GIS geometry.

Matching confidence concerns geometry only. It is NOT height validation.
"""
import copy
import json
import math
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import transform, unary_union

from .data_utils import PublicDataError, campus_id, positive
from .shadow_model import TO_M

MIN_IOU = 0.60
MIN_COVERAGE = 0.70
MIN_MARGIN = 0.20
MAX_CENTROID_DISTANCE = 20.0


def supplement_footprints(features, osm_features, campus):
    """Add cached OSM footprints only where GIS covers at most 1% of their area.

    This is geometry coverage repair, not a claim of present-day completeness.
    Tiny structures and overlapping alternative outlines are not added.
    """
    occupied = unary_union([transform(TO_M, shape(f['geometry'])) for f in features])
    extra = []
    for item in osm_features:
        geom = shape(item['geometry'])
        if geom.is_empty or not geom.is_valid or not geom.intersects(campus):
            continue
        metric = transform(TO_M, geom)
        overlap = metric.intersection(occupied).area / metric.area
        if metric.area < 100 or overlap > 0.01:
            continue
        original = item['properties']
        identifier = 'OSM-' + str(original['osm_id'])
        extra.append({'type': 'Feature', 'id': identifier, 'geometry': copy.deepcopy(item['geometry']),
                      'properties': {'public_id': identifier, 'name': original.get('name', ''),
                                     'dong_name': '', 'height_m': None, 'aboveground_floors': None,
                                     'A16': None, 'A26': None, 'geometry_source': 'OSM 보완',
                                     'source_file': original.get('source_url', 'OpenStreetMap'),
                                     'data_date': original.get('osm_updated', ''),
                                     'geometry_note': 'GIS 중첩 면적 1% 이하 · 현재 실물 확인 전',
                                     'gis_overlap_ratio': overlap}})
        occupied = unary_union([occupied, metric])
    return extra


def load_gba(path, campus):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        meta = data['metadata']
        if (data['type'] != 'FeatureCollection' or meta['schema_version'] != 1
                or meta['campus_id'] != campus_id(campus) or meta['crs'] != 'OGC:CRS84'
                or meta['height_kind'] != 'machine_learning_estimate_not_survey'):
            raise ValueError('캠퍼스·좌표계·자료 형식 불일치')
        seen = set()
        if not 0 < len(data['features']) <= 2000:
            raise ValueError('캠퍼스 자료의 건물 수를 확인하세요.')
        for feature in data['features']:
            identifier = str(feature['id'])
            geom = shape(feature['geometry'])
            if identifier in seen or geom.is_empty or not geom.is_valid or geom.geom_type not in ('Polygon', 'MultiPolygon') or not geom.intersects(campus):
                raise ValueError('GBA 식별자 또는 도형 오류')
            seen.add(identifier)
            # Missing/invalid estimated heights remain visible in the audit, never used.
            feature['properties']['height'] = positive(feature['properties'].get('height'))
        return data
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PublicDataError(f'GBA 자료를 읽을 수 없습니다: {error}') from error


def match_gba(features, gba_features):
    """Require reciprocal dominant overlap, coverage, IoU and close centroids."""
    targets = [transform(TO_M, shape(f['geometry'])) for f in features]
    sources = [transform(TO_M, shape(f['geometry'])) for f in gba_features]
    pairs, reverse = {}, {}
    for i, target in enumerate(targets):
        candidates = []
        for j, source in enumerate(sources):
            intersection = target.intersection(source).area
            if intersection <= 0:
                continue
            iou = intersection / (target.area + source.area - intersection)
            candidate = {'j': j, 'iou': iou, 'gis_coverage': intersection / target.area,
                         'gba_coverage': intersection / source.area,
                         'centroid_distance_m': target.centroid.distance(source.centroid)}
            candidates.append(candidate)
            reverse.setdefault(j, []).append((iou, i))
        pairs[i] = sorted(candidates, key=lambda c: c['iou'], reverse=True)
    for values in reverse.values():
        values.sort(reverse=True)
    result = {}
    for i, feature in enumerate(features):
        candidates = pairs[i]
        row = {'gis_id': feature['properties']['public_id'], 'status': '겹치는 GBA 도형 없음',
               'gba_id': None, 'height_m': None, 'accepted': False, 'iou': 0.0,
               'gis_coverage': 0.0, 'gba_coverage': 0.0, 'centroid_distance_m': None,
               'footprint_source': None, 'height_variance': None,
               'expanded_accepted': False, 'expanded_status': '추가 추정 근거 부족'}
        if candidates:
            best = candidates[0]
            j = best['j']
            source = gba_features[j]
            height = positive(source['properties'].get('height'))
            row.update({k: v for k, v in best.items() if k != 'j'})
            row.update(gba_id=str(source['id']), height_m=height,
                       footprint_source=source['properties'].get('source'),
                       height_variance=source['properties'].get('var'))
            next_iou = candidates[1]['iou'] if len(candidates) > 1 else 0.0
            reverse_iou = reverse[j][1][0] if len(reverse[j]) > 1 else 0.0
            if (best['iou'] < MIN_IOU or min(best['gis_coverage'], best['gba_coverage']) < MIN_COVERAGE
                    or best['centroid_distance_m'] > MAX_CENTROID_DISTANCE):
                row['status'] = '윤곽 차이 큼 · 적용 안 함'
            elif (best['iou'] - next_iou < MIN_MARGIN or reverse[j][0][1] != i
                  or best['iou'] - reverse_iou < MIN_MARGIN):
                row['status'] = '여러 도형과 중복 · 적용 안 함'
            elif height is None or not math.isfinite(height) or not 1 <= height <= 200:
                row['status'] = '유효 높이 없음 · 적용 안 함'
            else:
                row['status'] = '윤곽 조건 통과 · 높이는 추정값'
                row['accepted'] = True
            # Optional broader association for split outlines. A group-average
            # height can be used for multiple parts, but is explicitly lower confidence.
            # Do not copy heights from merely nearby or tiny overlapping structures.
            coverage_runner_up = max((c['gis_coverage'] for c in candidates[1:]), default=0.0)
            area_floor = 0.05 if feature['properties'].get('geometry_source') == 'OSM 보완' else 0.10
            contained_part = (best['gis_coverage'] >= 0.70 and best['gba_coverage'] >= area_floor
                              and sources[j].buffer(3).covers(targets[i].representative_point()))
            similar_outline = (best['iou'] >= 0.50 and min(best['gis_coverage'], best['gba_coverage']) >= 0.50
                               and best['centroid_distance_m'] <= MAX_CENTROID_DISTANCE)
            duplicate_outline = any(k != i and min(targets[k].area, targets[i].area) / max(targets[k].area, targets[i].area) >= 0.5
                                    and targets[k].intersection(targets[i]).area / min(targets[k].area, targets[i].area) >= 0.7
                                    for _, k in reverse[j])
            if (not row['accepted'] and height is not None and 1 <= height <= 200
                    and targets[i].area >= 100 and (contained_part or similar_outline)
                    and not duplicate_outline
                    and best['gis_coverage'] - coverage_runner_up >= 0.20):
                row['expanded_accepted'] = True
                row['expanded_status'] = '부분·변경 윤곽에 건물군 평균 적용 · 낮은 신뢰'
        result[row['gis_id']] = row
    return result


def apply_gba(features, matches, enabled=True, expanded=False):
    output = copy.deepcopy(features)
    for feature in output:
        props = feature['properties']
        match = matches.get(props['public_id'])
        props.pop('gba_height_m', None)
        props.pop('gba_height_source', None)
        props['gba_match'] = copy.deepcopy(match)
        if enabled and match and match['accepted']:
            props['gba_height_m'] = match['height_m']
            props['gba_height_source'] = 'GBA 위성 추정'
        elif enabled and expanded and match and match.get('expanded_accepted'):
            props['gba_height_m'] = match['height_m']
            props['gba_height_source'] = 'GBA 확장 추정 (낮은 신뢰)'
    return output

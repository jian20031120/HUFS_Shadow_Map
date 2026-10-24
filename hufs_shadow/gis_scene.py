"""GIS-only height resolution and planar scene. No OSM building matching."""
from shapely.geometry import shape
from shapely.ops import unary_union, transform
from .data_utils import positive
from .shadow_model import projected_shadow, TO_M


def build_scene(features, overrides, floor_height, fallback, include_unknown=True):
    buildings, records = [], []
    for f in features:
        p = f['properties']
        manual = positive(overrides.get(p['public_id']))
        if p.get('match_status') == '사용자 매칭':
            height = p.get('matched_height')
            if height is not None:
                source = '표제부 실제높이'
            else:
                height, source = p['matched_floors'] * floor_height, '표제부 층수 기반'
        elif manual is not None and p.get('match_status') != '자동 매칭':
            height, source = manual, '사용자 입력'
        elif p['height_m'] is not None:
            height, source = p['height_m'], 'A16 실제 높이'
        elif p['aboveground_floors'] is not None:
            height, source = p['aboveground_floors'] * floor_height, 'A26 층수 기반'
        elif positive(p.get('gba_height_m')) is not None and p.get('gba_height_source') != 'GBA 확장 추정 (낮은 신뢰)':
            height, source = positive(p['gba_height_m']), p.get('gba_height_source', 'GBA 위성 추정')
        elif positive(p.get('gba_raster_height_m')) is not None:
            height, source = positive(p['gba_raster_height_m']), 'GBA 3m 격자 추정'
        elif positive(p.get('gba_height_m')) is not None:
            height, source = positive(p['gba_height_m']), p['gba_height_source']
        elif include_unknown:
            height, source = fallback, 'fallback'
        else:
            height, source = None, '계산 제외'
        buildings.append((shape(f['geometry']), height))
        records.append({'건물':p['name'] or p['dong_name'] or '이름 미등록',
                        'GIS ID':p['public_id'], 'A16':p.get('A16',p['height_m']), 'A26':p.get('A26',p['aboveground_floors']),
                        '최종 높이 (m)':height, '높이 근거':source, '사용자 높이 (m)':manual,
                        '매칭 상태':p.get('match_status', '미매칭'), '표제부 PK':p.get('record_pk', ''),
                        'GBA ID':(p.get('gba_match') or {}).get('gba_id'),
                        'GBA 연결 상태':(p.get('gba_match') or {}).get('status', '미사용'),
                        'GBA 윤곽 IoU':(p.get('gba_match') or {}).get('iou'),
                        '도형 출처':p.get('geometry_source', 'GIS'),
                        '격자 판단':(p.get('gba_raster_sample') or {}).get('status'),
                        '격자 신뢰도':(p.get('gba_raster_sample') or {}).get('confidence'),
                        '격자 수':(p.get('gba_raster_sample') or {}).get('pixel_count'),
                        '원본 파일':p['source_file'], '자료 기준일':p['data_date']})
    return buildings, records


def flat_shade(campus, buildings, elevation, azimuth):
    # Same metric sweep principle reviewed in shadenav/shadows.py and salusshadow.py.
    # Reuse our existing concave/multipart-aware routine; no upstream source copied.
    ground = transform(TO_M, campus)
    footprints = unary_union([transform(TO_M, geom) for geom, _ in buildings])
    shadows = [projected_shadow(geom, height, elevation, azimuth)
               for geom, height in buildings if height is not None] if elevation >= 3 else []
    return unary_union(shadows).difference(footprints).intersection(ground)

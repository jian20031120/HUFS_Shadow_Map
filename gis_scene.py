"""GIS-only height resolution and planar scene. No OSM building matching."""
from shapely.geometry import shape
from shapely.ops import unary_union, transform
from public_buildings import positive
from shadow_model import projected_shadow, TO_M


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
        elif include_unknown:
            height, source = fallback, 'fallback'
        else:
            height, source = None, '계산 제외'
        buildings.append((shape(f['geometry']), height))
        records.append({'건물':p['name'] or p['dong_name'] or '이름 미등록',
                        'GIS ID':p['public_id'], 'A16':p.get('A16',p['height_m']), 'A26':p.get('A26',p['aboveground_floors']),
                        '최종 높이 (m)':height, '높이 근거':source, '사용자 높이 (m)':manual,
                        '매칭 상태':p.get('match_status', '미매칭'), '표제부 PK':p.get('record_pk', ''),
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


def select_major_buildings(features, minimum_area=100.0, included_ids=()):
    """Measure in EPSG:5186; retain named buildings and explicit user inclusions."""
    from pyproj import Transformer
    to_area = Transformer.from_crs(4326, 5186, always_xy=True).transform
    included_ids = set(included_ids)
    selected, audit = [], []
    for feature in features:
        props = feature['properties']
        area = transform(to_area, shape(feature['geometry'])).area
        named = any(str(props.get(key) or '').strip()
                    for key in ('name', 'dong_name', 'BLD_NM', 'DONG_NM'))
        default = area >= minimum_area or named
        keep = default or props['public_id'] in included_ids
        audit.append({'GIS ID': props['public_id'], '건물': props.get('name') or props.get('dong_name') or '이름 미등록',
                      '면적 (m²)': area, '기본 포함': default, '사용': keep})
        if keep:
            selected.append(feature)
    return selected, audit

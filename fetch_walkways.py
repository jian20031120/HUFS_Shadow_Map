"""Extract explicitly mapped campus footways from a bounded OSM map snapshot.

The default input is the already downloaded official OSM bbox response. This
script never turns an untagged service road or parking aisle into a footway.
"""
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import LineString, mapping, shape
from shapely.ops import transform, unary_union

from public_buildings import campus_id, save_json
from shadow_model import TO_M

ROOT = Path(__file__).parent
SOURCE_URL = 'https://api.openstreetmap.org/api/0.6/map?bbox=127.2555,37.3327,127.2766,37.3406'
EXPLICIT_HIGHWAYS = {'footway', 'path', 'pedestrian', 'steps'}
BLOCKED_ACCESS = {'no', 'private'}


def is_walkable(tags):
    """Select independently mapped walking types for the public walking layer.

    A road's foot=yes permits walking but does not make its centerline a sidewalk.
    Likewise sidewalk=yes/left/right on a road does not give sidewalk geometry.
    """
    if str(tags.get('access', '')).lower() in BLOCKED_ACCESS or str(tags.get('foot', '')).lower() in BLOCKED_ACCESS:
        return False
    if tags.get('area') == 'yes':
        return False  # A pedestrian plaza perimeter is not a mapped walking line.
    return tags.get('highway') in EXPLICIT_HIGHWAYS


def independent_kind(tags):
    if tags.get('highway') == 'steps':
        return 'steps'
    if tags.get('highway') == 'path':
        return 'path'
    if tags.get('highway') == 'footway' and tags.get('footway') == 'sidewalk':
        return 'sidewalk'
    return 'footway'


def source_tag_basis(tags):
    return [f'{key}={value}' for key, value in tags.items()
            if key in {'highway', 'footway', 'sidewalk', 'crossing', 'foot', 'access'}
            or key.startswith(('sidewalk:', 'footway:', 'crossing:'))]


def line_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'LineString':
        return [geometry]
    if geometry.geom_type in {'MultiLineString', 'GeometryCollection'}:
        return [line for part in geometry.geoms for line in line_parts(part)]
    return []


def extract_walkways(xml_bytes, campus):
    document = ET.fromstring(xml_bytes)
    nodes = {node.attrib['id']: (float(node.attrib['lon']), float(node.attrib['lat']))
             for node in document.findall('node')}
    features, matched_ways, incomplete_ways = [], set(), []
    excluded_foot_access_roads = []
    occupied = unary_union([])
    removed_duplicate_length_m = 0.0
    for way in document.findall('way'):
        tags = {tag.attrib['k']: tag.attrib['v'] for tag in way.findall('tag')}
        if not is_walkable(tags):
            if (tags.get('highway') and tags.get('foot') in {'yes', 'designated'}
                    and str(tags.get('access', '')).lower() not in BLOCKED_ACCESS
                    and tags.get('area') != 'yes'):
                references = [node.attrib['ref'] for node in way.findall('nd')]
                if len(references) >= 2 and all(ref in nodes for ref in references):
                    road = LineString([nodes[ref] for ref in references])
                    clipped_length = transform(TO_M, road.intersection(campus)).length
                    if clipped_length > 0.5:
                        excluded_foot_access_roads.append({'source_way_id': way.attrib['id'],
                                                           'highway': tags['highway'], 'foot': tags['foot'],
                                                           'length_m': clipped_length,
                                                           'reason': '보행 허용 태그는 있으나 전용 보행유형 선형이 아니어서 공개 보행로에서 제외. 보행 금지 판정이 아님.'})
            continue
        references = [node.attrib['ref'] for node in way.findall('nd')]
        if len(references) < 2 or any(ref not in nodes for ref in references):
            incomplete_ways.append(way.attrib['id'])
            continue
        geometry = LineString([nodes[ref] for ref in references])
        if not geometry.is_valid or not geometry.intersects(campus):
            continue
        clipped = geometry.intersection(campus)
        removed_duplicate_length_m += transform(TO_M, clipped.intersection(occupied)).length
        parts = line_parts(clipped.difference(occupied))
        for index, part in enumerate(parts):
            length = transform(TO_M, part).length
            if length < 0.5:
                continue
            identifier = f"OSM-WAY-{way.attrib['id']}-P{index}"
            properties = {key: value for key, value in tags.items() if key in {
                'name', 'highway', 'foot', 'access', 'surface', 'incline', 'footway', 'sidewalk', 'crossing',
                'wheelchair', 'step_count', 'bridge', 'tunnel', 'layer'}
                or key.startswith(('sidewalk:', 'footway:', 'crossing:'))}
            properties.update(source_way_id=way.attrib['id'], length_m=length,
                              name=tags.get('name') or ('계단' if tags.get('highway') == 'steps' else '이름 없는 보행로'),
                              source_url=f"https://www.openstreetmap.org/way/{way.attrib['id']}",
                              access_basis='walking_highway', independent_kind=independent_kind(tags),
                              source_tag_basis=source_tag_basis(tags), osm_tags=tags,
                              guidance_class='independent_walkway', reference_only=False)
            features.append({'type': 'Feature', 'id': identifier,
                             'geometry': mapping(part), 'properties': properties})
            matched_ways.add(way.attrib['id'])
            occupied = unary_union([occupied, part])
    return {'type': 'FeatureCollection', 'features': features,
            'metadata': {'schema_version': 2, 'source': 'OpenStreetMap contributors',
                         'source_kind': 'osm_explicit_footways', 'source_url': SOURCE_URL,
                         'source_xml_sha256': hashlib.sha256(xml_bytes).hexdigest(),
                         'extracted_at': datetime.now(timezone.utc).isoformat(),
                         'crs': 'EPSG:4326', 'length_crs': 'EPSG:32652',
                         'campus_id': campus_id(campus), 'license': 'ODbL 1.0',
                         'attribution_url': 'https://www.openstreetmap.org/copyright',
                         'source_way_count': len(matched_ways),
                         'clipped_feature_count': len(features),
                         'total_length_m': sum(f['properties']['length_m'] for f in features),
                         'incomplete_source_ways': incomplete_ways,
                         'removed_duplicate_length_m': removed_duplicate_length_m,
                         'excluded_foot_access_roads': excluded_foot_access_roads,
                         'selection_rule': 'independent_linear_walking_types_only',
                         'scope_note': '독립 선형으로 매핑된 footway/path/pedestrian/steps만 포함. 캠퍼스 보행로 전체를 포괄하지 않으며 연결 경로나 현재 통행 가능 여부를 보장하지 않습니다.',
                         'excluded_roads_note': '차도·임도·주차 통로 중심선은 foot=yes/designated가 있어도 공개 보행로로 표시하지 않습니다. 이는 보행 금지가 아니라 전용 보행유형만 표시하는 정책입니다. 도로의 sidewalk=yes/left/right를 인도 선형으로 바꾸거나 임의 offset하지 않습니다.'}}


def download_xml(path):
    response = requests.get(SOURCE_URL, timeout=45, stream=True)
    response.raise_for_status()
    chunks, size = [], 0
    for chunk in response.iter_content(65536):
        size += len(chunk)
        if size > 10_000_000:
            raise ValueError('OSM bbox response exceeded 10 MB limit')
        chunks.append(chunk)
    response.close()
    payload = b''.join(chunks)
    ET.fromstring(payload)  # Parse successfully before replacing the snapshot.
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(payload)
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true', help='Read the bounded bbox from the official OSM map API')
    args = parser.parse_args()
    xml_path = ROOT/'.test_tmp/osm_current_buildings.xml'
    payload = download_xml(xml_path) if args.refresh else xml_path.read_bytes()
    campus = shape(json.loads((ROOT/'data/campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
    result = extract_walkways(payload, campus)
    if not result['features']:
        raise ValueError('No explicit campus footways; existing output was not changed')
    save_json(ROOT/'data/campus_walkways.geojson', result)
    print(json.dumps(result['metadata'], ensure_ascii=False, indent=2))

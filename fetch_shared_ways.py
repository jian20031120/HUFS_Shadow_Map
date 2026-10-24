"""Extract OSM road centerlines as separate visual references, never footways.

Foot permission is unknown for most of these roads. They must not be used as
automatic pedestrian guidance or described as safe walking paths.
"""
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import LineString, mapping, shape
from shapely.ops import transform, unary_union

from fetch_walkways import BLOCKED_ACCESS, SOURCE_URL, download_xml, extract_walkways, is_walkable, line_parts
from public_buildings import campus_id, save_json
from shadow_model import TO_M

ROOT = Path(__file__).parent
REFERENCE_HIGHWAYS = {'service', 'residential', 'living_street', 'unclassified', 'tertiary'}


def is_shared_reference(tags):
    return (tags.get('highway') in REFERENCE_HIGHWAYS and tags.get('area') != 'yes'
            and str(tags.get('access', '')).lower() not in BLOCKED_ACCESS
            and str(tags.get('foot', '')).lower() not in BLOCKED_ACCESS
            and tags.get('foot') not in {'yes', 'designated'}
            and not is_walkable(tags))


def extract_shared_ways(xml_bytes, campus):
    document = ET.fromstring(xml_bytes)
    nodes = {node.attrib['id']: (float(node.attrib['lon']), float(node.attrib['lat']))
             for node in document.findall('node')}
    explicit = extract_walkways(xml_bytes, campus)
    explicit_ids = {feature['properties']['source_way_id'] for feature in explicit['features']}
    explicit_geometry = unary_union([shape(feature['geometry']) for feature in explicit['features']])
    features, matched_ids, incomplete = [], set(), []
    removed_overlap_m = 0.0
    for way in document.findall('way'):
        tags = {tag.attrib['k']: tag.attrib['v'] for tag in way.findall('tag')}
        way_id = way.attrib['id']
        if not is_shared_reference(tags) or way_id in explicit_ids:
            continue
        references = [node.attrib['ref'] for node in way.findall('nd')]
        if len(references) < 2 or any(reference not in nodes for reference in references):
            incomplete.append(way_id)
            continue
        geometry = LineString([nodes[reference] for reference in references])
        if not geometry.is_valid or not geometry.intersects(campus):
            continue
        clipped = geometry.intersection(campus)
        overlap = clipped.intersection(explicit_geometry)
        removed_overlap_m += transform(TO_M, overlap).length
        distinct = clipped.difference(explicit_geometry)
        for index, part in enumerate(line_parts(distinct)):
            length = transform(TO_M, part).length
            if length < 0.5:
                continue
            properties = {key: tags[key] for key in (
                'highway', 'foot', 'access', 'service', 'surface', 'incline', 'wheelchair',
                'bridge', 'tunnel', 'covered', 'layer', 'oneway', 'lanes', 'maxspeed') if key in tags}
            properties.update(source_way_id=way_id,
                              name=tags.get('name') or ('주차장 통로 (참고)' if tags.get('service') == 'parking_aisle' else '교내 도로 (참고)'),
                              length_m=length, guidance_class='shared_road_reference', reference_only=True,
                              foot_permission=tags.get('foot', 'unknown'), osm_tags=tags,
                              osm_version=way.attrib.get('version'), osm_timestamp=way.attrib.get('timestamp'),
                              source_url=f'https://www.openstreetmap.org/way/{way_id}',
                              safety_note='차량 통행 도로의 중심선입니다. 보행 허용·보도·횡단시설·현재 안전성을 확인하지 못했습니다.')
            features.append({'type': 'Feature', 'id': f'OSM-ROAD-{way_id}-P{index}',
                             'geometry': mapping(part), 'properties': properties})
            matched_ids.add(way_id)
    metric_union = unary_union([transform(TO_M, shape(feature['geometry'])) for feature in features])
    explicit_metric_union = unary_union([transform(TO_M, shape(feature['geometry'])) for feature in explicit['features']])
    return {'type': 'FeatureCollection', 'features': features,
            'metadata': {'schema_version': 1, 'source': 'OpenStreetMap contributors',
                         'source_kind': 'osm_shared_roads_reference', 'source_url': SOURCE_URL,
                         'source_xml_sha256': hashlib.sha256(xml_bytes).hexdigest(),
                         'extracted_at': datetime.now(timezone.utc).isoformat(),
                         'crs': 'EPSG:4326', 'length_crs': 'EPSG:32652',
                         'campus_id': campus_id(campus), 'license': 'ODbL 1.0',
                         'attribution_url': 'https://www.openstreetmap.org/copyright',
                         'source_way_count': len(matched_ids), 'clipped_feature_count': len(features),
                         'total_length_m': sum(feature['properties']['length_m'] for feature in features),
                         'unique_total_length_m': metric_union.length,
                         'explicit_footway_shared_ids': sorted(matched_ids.intersection(explicit_ids)),
                         'explicit_footway_overlap_length_m': metric_union.intersection(explicit_metric_union).length,
                         'removed_explicit_overlap_length_m': removed_overlap_m,
                         'incomplete_source_ways': incomplete,
                         'guidance_class': 'shared_road_reference', 'reference_only': True,
                         'scope_note': '차량 도로·주차 통로의 지도상 참고 선형입니다. 명시 보행로와 별도이며 보행 가능·안전·연속 경로를 보장하지 않습니다.',
                         'exclusion_note': '명시 보행로와 중복 source way 및 겹치는 선형, access/foot=no/private, 면형 도로 제외.'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true', help='Read the bounded official OSM bbox response')
    args = parser.parse_args()
    xml_path = ROOT/'.test_tmp/osm_current_buildings.xml'
    payload = download_xml(xml_path) if args.refresh else xml_path.read_bytes()
    campus = shape(json.loads((ROOT/'data/campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
    result = extract_shared_ways(payload, campus)
    if not result['features']:
        raise ValueError('No campus reference roads; existing output was not changed')
    save_json(ROOT/'data/campus_shared_ways.geojson', result)
    print(json.dumps(result['metadata'], ensure_ascii=False, indent=2))

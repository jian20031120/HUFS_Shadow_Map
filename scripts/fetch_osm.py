"""Explicitly refresh campus boundary and OSM building footprints."""
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import requests
from shapely.geometry import Polygon, mapping

from hufs_shadow.data_utils import save_json
from hufs_shadow.paths import ROOT


def main():
    response = requests.get('https://api.openstreetmap.org/api/0.6/map',
                            params={'bbox': '127.253,37.331,127.279,37.342'}, timeout=60)
    response.raise_for_status()
    document = ET.fromstring(response.content)
    nodes = {node.get('id'): (float(node.get('lon')), float(node.get('lat')))
             for node in document.findall('node')}

    def tags(element):
        return {tag.get('k'): tag.get('v') for tag in element.findall('tag')}

    def polygon(element):
        refs = [node.get('ref') for node in element.findall('nd')]
        if len(refs) < 4 or refs[0] != refs[-1] or any(ref not in nodes for ref in refs):
            return None
        geometry = Polygon([nodes[ref] for ref in refs])
        return geometry if geometry.is_valid else geometry.buffer(0)

    campus_way = next(way for way in document.findall('way')
                      if tags(way).get('name') == '한국외국어대학교 글로벌캠퍼스')
    campus = polygon(campus_way)
    features = []
    for way in document.findall('way'):
        properties = tags(way)
        if properties.get('building') in (None, 'no'):
            continue
        geometry = polygon(way)
        if geometry is None or geometry.is_empty or not campus.covers(geometry.representative_point()):
            continue
        features.append({'type': 'Feature', 'geometry': mapping(geometry), 'properties': {
            'osm_id': way.get('id'), 'name': properties.get('name', ''),
            'height': properties.get('height'), 'levels': properties.get('building:levels'),
            'source_url': 'https://www.openstreetmap.org/way/'+way.get('id'),
            'osm_updated': way.get('timestamp')}})
    metadata = {'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'source': response.url, 'license': 'ODbL 1.0 / © OpenStreetMap contributors',
                'boundary_osm_id': campus_way.get('id')}
    save_json(ROOT/'data/buildings.geojson', {'type': 'FeatureCollection', 'features': features,
              'campus': mapping(campus), 'metadata': metadata})
    save_json(ROOT/'data/campus_boundary.geojson', {'type': 'Feature', 'geometry': mapping(campus),
              'properties': {'name': '한국외국어대학교 글로벌캠퍼스'}, 'metadata': metadata})
    print(f'Saved campus boundary and {len(features)} OSM buildings.')


if __name__ == '__main__':
    main()

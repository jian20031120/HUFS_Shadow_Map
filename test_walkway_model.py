import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.ops import transform

from fetch_walkways import extract_walkways, is_walkable
from public_buildings import PublicDataError
from shadow_model import TO_G, TO_M
from walkway_model import load_walkways, nearby_shaded_walkways, shade_walkways


def path_feature(identifier, metric_line, source_way_id=None):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(transform(TO_G, metric_line)),
            'properties': {'name': '테스트 보행로', 'highway': 'footway',
                           'source_way_id': source_way_id or identifier}}


class WalkwayTests(unittest.TestCase):
    def test_road_access_is_not_guessed(self):
        for tags in ({'highway': 'service'}, {'highway': 'tertiary'},
                     {'highway': 'service', 'service': 'parking_aisle'},
                     {'highway': 'service', 'foot': 'yes'},
                     {'highway': 'residential', 'foot': 'designated'},
                     {'highway': 'track', 'foot': 'yes'},
                     {'highway': 'residential', 'sidewalk': 'yes'},
                     {'highway': 'tertiary', 'sidewalk:both': 'yes'},
                     {'highway': 'service', 'sidewalk:left': 'yes'},
                     {'highway': 'footway', 'foot': 'no'},
                     {'highway': 'path', 'access': 'private'},
                     {'highway': 'pedestrian', 'area': 'yes'}):
            self.assertFalse(is_walkable(tags))
        self.assertTrue(is_walkable({'highway': 'steps'}))
        self.assertTrue(is_walkable({'highway': 'footway', 'footway': 'sidewalk'}))

    def test_extract_clips_to_campus_preserves_steps_and_rejects_incomplete_way(self):
        xml = b'''<osm>
        <node id="1" lon="127.24" lat="37.34"/><node id="2" lon="127.28" lat="37.34"/>
        <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="steps"/><tag k="wheelchair" v="no"/></way>
        <way id="20"><nd ref="1"/><nd ref="2"/><tag k="highway" v="service"/></way>
        <way id="30"><nd ref="1"/><nd ref="99"/><tag k="highway" v="footway"/></way>
        </osm>'''
        campus = box(127.25, 37.33, 127.27, 37.35)
        result = extract_walkways(xml, campus)
        self.assertEqual(len(result['features']), 1)
        feature = result['features'][0]
        self.assertTrue(campus.covers(shape(feature['geometry'])))
        self.assertEqual(feature['properties']['wheelchair'], 'no')
        self.assertEqual(feature['properties']['highway'], 'steps')
        self.assertEqual(feature['properties']['independent_kind'], 'steps')
        self.assertEqual(result['metadata']['incomplete_source_ways'], ['30'])

    def test_independent_sidewalk_and_crossing_tags_survive_without_inventing_road_offsets(self):
        xml = b'''<osm>
        <node id="1" lon="127.24" lat="37.34"/><node id="2" lon="127.28" lat="37.34"/>
        <node id="3" lon="127.24" lat="37.335"/><node id="4" lon="127.28" lat="37.335"/>
        <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/>
        <tag k="footway" v="sidewalk"/><tag k="sidewalk:both" v="raised"/></way>
        <way id="20"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
        <way id="30"><nd ref="3"/><nd ref="4"/><tag k="highway" v="service"/>
        <tag k="foot" v="yes"/><tag k="sidewalk" v="both"/><tag k="sidewalk:left" v="yes"/></way>
        <way id="40"><nd ref="3"/><nd ref="4"/><tag k="highway" v="footway"/>
        <tag k="footway" v="crossing"/><tag k="crossing" v="uncontrolled"/><tag k="crossing:signals" v="no"/></way>
        </osm>'''
        campus = box(127.25, 37.33, 127.27, 37.35)
        result = extract_walkways(xml, campus)
        by_way = {feature['properties']['source_way_id']: feature for feature in result['features']}
        self.assertEqual(set(by_way), {'10', '40'})
        sidewalk = by_way['10']['properties']
        self.assertEqual(sidewalk['independent_kind'], 'sidewalk')
        self.assertEqual(sidewalk['footway'], 'sidewalk')
        self.assertEqual(sidewalk['sidewalk:both'], 'raised')
        self.assertIn('footway=sidewalk', sidewalk['source_tag_basis'])
        crossing = by_way['40']['properties']
        self.assertEqual(crossing['independent_kind'], 'footway')
        self.assertEqual(crossing['crossing'], 'uncontrolled')
        self.assertEqual(crossing['crossing:signals'], 'no')
        self.assertEqual(crossing['osm_tags']['footway'], 'crossing')
        self.assertGreater(result['metadata']['removed_duplicate_length_m'], 1000)
        self.assertEqual(result['metadata']['excluded_foot_access_roads'][0]['source_way_id'], '30')
        for feature in result['features']:
            self.assertAlmostEqual(shape(feature['geometry']).bounds[0], 127.25)
            self.assertAlmostEqual(shape(feature['geometry']).bounds[2], 127.27)

    def test_shadow_cannot_turn_building_interiors_into_walkable_sections(self):
        line = LineString([(347000, 4134005), (347100, 4134005)])
        paths = {'type': 'FeatureCollection', 'features': [path_feature('way1', line)]}
        shade = box(347020, 4134000, 347080, 4134010)
        footprint = box(347040, 4134000, 347050, 4134010)
        result = shade_walkways(paths, shade, [footprint])
        self.assertEqual(len(result['features']), 2)
        self.assertAlmostEqual(result['metadata']['total_shaded_length_m'], 50, places=3)
        for feature in result['features']:
            metric = transform(TO_M, shape(feature['geometry']))
            self.assertLess(metric.intersection(footprint).length, 1e-5)
            self.assertEqual(feature['properties']['source_way_id'], 'way1')
            self.assertEqual(feature['properties']['guidance_kind'], 'shade_section_not_route')

    def test_empty_shade_gives_no_invented_recommendation(self):
        paths = {'features': [path_feature('way1', LineString([(347000, 4134005), (347100, 4134005)]))]}
        result = shade_walkways(paths, box(347200, 4134000, 347210, 4134010))
        self.assertEqual(result['features'], [])
        self.assertEqual(nearby_shaded_walkways(result, (37.33, 127.26)), [])

    def test_nearby_is_straight_line_radius_filtered_and_deduplicated(self):
        segments = {'features': [
            path_feature('a', LineString([(347020, 4134000), (347020, 4134010)]), 'shared-way'),
            path_feature('a2', LineString([(347040, 4134000), (347040, 4134010)]), 'shared-way'),
            path_feature('b', LineString([(347060, 4134000), (347060, 4134010)]), 'another-way')]}
        location = transform(TO_G, Point(347000, 4134005))
        result = nearby_shaded_walkways(segments, (location.y, location.x), radius_m=100)
        self.assertEqual([item['id'] for item in result], ['a', 'b'])
        self.assertAlmostEqual(result[0]['distance_m'], 20, places=3)
        self.assertEqual(result[0]['distance_kind'], 'straight_line_not_route')
        self.assertEqual(set(result[0]['nearest_point']), {'latitude', 'longitude'})
        self.assertEqual(nearby_shaded_walkways(segments, (location.y, location.x), radius_m=10), [])

    def test_invalid_locations_are_rejected(self):
        for location in ((91, 127), (37, float('nan')), (True, 127), (37,)):
            with self.assertRaises(ValueError):
                nearby_shaded_walkways({'features': []}, location)

    def test_foot_permitted_vehicle_track_does_not_enter_nearby_walking_suggestions(self):
        track = path_feature('track', LineString([(347001, 4134000), (347001, 4134010)]))
        track['properties'].update(highway='track', foot='yes')
        walking = path_feature('walk', LineString([(347020, 4134000), (347020, 4134010)]))
        location = transform(TO_G, Point(347000, 4134005))
        nearby = nearby_shaded_walkways({'features': [track, walking]}, (location.y, location.x))
        self.assertEqual([feature['id'] for feature in nearby], ['walk'])

    def test_real_snapshot_is_bounded_and_campus_specific(self):
        root = Path(__file__).parent/'data'
        campus = shape(json.loads((root/'campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
        data = load_walkways(root/'campus_walkways.geojson', campus)
        self.assertEqual(len(data['features']), 3)
        self.assertEqual(data['metadata']['schema_version'], 2)
        self.assertAlmostEqual(data['metadata']['total_length_m'], 469.819030, places=3)
        self.assertEqual({feature['id'] for feature in data['features']}, {
            'OSM-WAY-470462814-P0', 'OSM-WAY-1152823216-P0', 'OSM-WAY-1152823219-P0'})
        self.assertEqual(data['metadata']['excluded_foot_access_roads'][0]['highway'], 'track')
        self.assertEqual(data['metadata']['excluded_foot_access_roads'][0]['foot'], 'yes')
        self.assertTrue(all(is_walkable(feature['properties']) for feature in data['features']))
        self.assertTrue(all(campus.buffer(1e-9).covers(shape(feature['geometry'])) for feature in data['features']))
        with self.assertRaises(PublicDataError):
            load_walkways(root/'campus_walkways.geojson', campus.buffer(.001))
        duplicate = copy.deepcopy(data)
        duplicate['features'].append(duplicate['features'][0])
        with patch.object(Path, 'read_text', return_value=json.dumps(duplicate)):
            with self.assertRaises(PublicDataError):
                load_walkways('unused', campus)
        mismatched = copy.deepcopy(data)
        mismatched['features'][0]['properties']['sidewalk'] = 'invented'
        mismatched['features'][0]['properties']['osm_tags']['sidewalk'] = 'yes'
        mismatched['features'][0]['properties']['source_tag_basis'].append('sidewalk=yes')
        with patch.object(Path, 'read_text', return_value=json.dumps(mismatched)):
            with self.assertRaises(PublicDataError):
                load_walkways('unused', campus)


if __name__ == '__main__':
    unittest.main()

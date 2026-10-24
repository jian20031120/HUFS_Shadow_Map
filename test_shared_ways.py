import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import LineString, Point, box, shape
from shapely.ops import transform, unary_union

from fetch_shared_ways import extract_shared_ways, is_shared_reference
from public_buildings import PublicDataError
from shadow_model import TO_G, TO_M
from test_walkway_model import path_feature
from walkway_model import load_shared_ways, load_walkways, nearby_shaded_walkways, shade_walkways


class SharedRoadTests(unittest.TestCase):
    def test_explicit_walking_access_and_prohibited_roads_are_not_reference_duplicates(self):
        self.assertTrue(is_shared_reference({'highway': 'service'}))
        self.assertTrue(is_shared_reference({'highway': 'tertiary', 'access': 'destination'}))
        for tags in ({'highway': 'service', 'foot': 'yes'},
                     {'highway': 'service', 'foot': 'designated'},
                     {'highway': 'residential', 'access': 'private'},
                     {'highway': 'service', 'foot': 'no'},
                     {'highway': 'motorway'}, {'highway': 'footway'}):
            self.assertFalse(is_shared_reference(tags))

    def test_geometry_overlap_is_removed_and_original_road_attributes_are_kept(self):
        xml = b'''<osm>
        <node id="1" lon="127.24" lat="37.34"/><node id="2" lon="127.28" lat="37.34"/>
        <node id="3" lon="127.24" lat="37.335"/><node id="4" lon="127.28" lat="37.335"/>
        <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
        <way id="20"><nd ref="1"/><nd ref="2"/><tag k="highway" v="service"/></way>
        <way id="30"><nd ref="3"/><nd ref="4"/><tag k="highway" v="service"/>
        <tag k="service" v="parking_aisle"/><tag k="bridge" v="yes"/><tag k="layer" v="1"/><tag k="source" v="survey"/></way>
        </osm>'''
        campus = box(127.25, 37.33, 127.27, 37.35)
        result = extract_shared_ways(xml, campus)
        self.assertEqual(len(result['features']), 1)
        feature = result['features'][0]
        self.assertEqual(feature['properties']['source_way_id'], '30')
        self.assertEqual(feature['properties']['bridge'], 'yes')
        self.assertEqual(feature['properties']['layer'], '1')
        self.assertEqual(feature['properties']['osm_tags']['source'], 'survey')
        self.assertEqual(feature['properties']['guidance_class'], 'shared_road_reference')
        self.assertTrue(feature['properties']['reference_only'])
        self.assertTrue(campus.covers(shape(feature['geometry'])))
        self.assertGreater(result['metadata']['removed_explicit_overlap_length_m'], 1000)
        self.assertAlmostEqual(result['metadata']['explicit_footway_overlap_length_m'], 0)

    def test_reference_lines_cannot_be_recommended_even_in_mixed_inputs(self):
        reference = path_feature('road', LineString([(347001, 4134000), (347001, 4134010)]))
        reference['properties'].update(guidance_class='shared_road_reference', reference_only=True)
        walking = path_feature('walk', LineString([(347020, 4134000), (347020, 4134010)]))
        location = transform(TO_G, Point(347000, 4134005))
        for marker in ({'guidance_class': 'shared_road_reference'}, {'reference_only': True}):
            candidate = copy.deepcopy(reference)
            candidate['properties'].pop('guidance_class', None)
            candidate['properties'].pop('reference_only', None)
            candidate['properties'].update(marker)
            nearby = nearby_shaded_walkways({'features': [candidate, walking]}, (location.y, location.x))
            self.assertEqual([item['id'] for item in nearby], ['walk'])
        self.assertEqual(nearby_shaded_walkways({'features': [reference]}, (location.y, location.x)), [])

    def test_shade_clipping_keeps_reference_classification(self):
        reference = path_feature('road', LineString([(347000, 4134005), (347100, 4134005)]))
        reference['properties'].update(guidance_class='shared_road_reference', reference_only=True)
        result = shade_walkways({'features': [reference]}, box(347020, 4134000, 347080, 4134010),
                                [box(347040, 4134000, 347050, 4134010)])
        self.assertAlmostEqual(result['metadata']['total_shaded_length_m'], 50, places=3)
        self.assertTrue(all(feature['properties']['reference_only'] for feature in result['features']))
        self.assertTrue(all(feature['properties']['guidance_class'] == 'shared_road_reference' for feature in result['features']))

    def test_real_datasets_are_separate_bounded_and_validate_their_role(self):
        root = Path(__file__).parent/'data'
        campus = shape(json.loads((root/'campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
        references = load_shared_ways(root/'campus_shared_ways.geojson', campus)
        walking = load_walkways(root/'campus_walkways.geojson', campus)
        self.assertEqual(references['metadata']['source_way_count'], 20)
        self.assertEqual(len(references['features']), 22)
        self.assertAlmostEqual(references['metadata']['total_length_m'], 4325.376, places=3)
        self.assertEqual(references['metadata']['explicit_footway_shared_ids'], [])
        shared_ids = {feature['properties']['source_way_id'] for feature in references['features']}
        walking_ids = {feature['properties']['source_way_id'] for feature in walking['features']}
        self.assertFalse(shared_ids.intersection(walking_ids))
        ref_geometry = unary_union([transform(TO_M, shape(feature['geometry'])) for feature in references['features']])
        walking_geometry = unary_union([transform(TO_M, shape(feature['geometry'])) for feature in walking['features']])
        self.assertAlmostEqual(ref_geometry.intersection(walking_geometry).length, 0, places=5)
        self.assertTrue(all(campus.buffer(1e-9).covers(shape(feature['geometry'])) for feature in references['features']))
        for loader, path in ((load_walkways, root/'campus_shared_ways.geojson'),
                             (load_shared_ways, root/'campus_walkways.geojson')):
            with self.assertRaises(PublicDataError):
                loader(path, campus)
        invalid = copy.deepcopy(references)
        invalid['features'][0]['properties']['reference_only'] = False
        with patch.object(Path, 'read_text', return_value=json.dumps(invalid)):
            with self.assertRaises(PublicDataError):
                load_shared_ways('unused', campus)


if __name__ == '__main__':
    unittest.main()

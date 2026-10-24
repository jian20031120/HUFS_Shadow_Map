from pathlib import Path
import copy
import unittest
from unittest.mock import patch

from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform, unary_union

from campus_scene import load_campus_scene
from destination_catalog import build_destination_catalog
from shadow_model import TO_G


def feature(identifier, geometry, name='', **properties):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(geometry),
            'properties': {'public_id': identifier, 'name': name, **properties}}


def osm(identifier, geometry, name):
    return {'type': 'Feature', 'geometry': mapping(geometry),
            'properties': {'osm_id': identifier, 'name': name,
                           'source_url': f'https://www.openstreetmap.org/way/{identifier}'}}


def geographic(bounds):
    return transform(TO_G, box(*bounds))


class DestinationCatalogTests(unittest.TestCase):
    def test_spatial_name_transfer_preserves_original_wings_and_gaps(self):
        left = geographic((347000, 4134000, 347020, 4134040))
        right = geographic((347030, 4134000, 347050, 4134040))
        source = geographic((347000, 4134000, 347050, 4134040))
        features = [feature('left', left, '연구동'), feature('right', right, '강의동')]
        original = copy.deepcopy(features)
        with patch('destination_catalog._load_osm_features', return_value=[osm('1', source, '국제사회교육원')]):
            catalog = build_destination_catalog({'all_building_features': features})
        self.assertEqual(len(catalog), 1)
        destination = catalog[0]
        result = shape(destination['geometry'])
        self.assertEqual(destination['footprint_ids'], ['left', 'right'])
        self.assertTrue(result.equals(unary_union([left, right])))
        self.assertFalse(result.covers(transform(TO_G, Point(347025, 4134020))))
        self.assertIn('연구동', destination['aliases'])
        self.assertIn('강의동', destination['label'])
        self.assertEqual(features, original)

    def test_nearby_or_tiny_overlaps_do_not_create_a_named_destination(self):
        target = geographic((347000, 4134000, 347040, 4134040))
        adjacent = geographic((347041, 4134000, 347081, 4134040))
        slight_overlap = geographic((347039, 4134000, 347079, 4134040))
        with patch('destination_catalog._load_osm_features', return_value=[osm('1', adjacent, '도서관'), osm('2', slight_overlap, '공학관')]):
            catalog = build_destination_catalog({'features': [feature('unnamed', target)]})
        self.assertEqual(catalog, [])

    def test_conflicting_equal_overlap_names_are_not_guessed(self):
        geometry = geographic((347000, 4134000, 347040, 4134040))
        with patch('destination_catalog._load_osm_features', return_value=[osm('1', geometry, '도서관'), osm('2', geometry, '공학관')]):
            catalog = build_destination_catalog({'features': [feature('unnamed', geometry)]})
        self.assertEqual(catalog, [])

    def test_duplicate_human_names_get_distinct_labels_and_stable_ids(self):
        west = geographic((347000, 4134000, 347020, 4134040))
        east = geographic((347080, 4134000, 347100, 4134040))
        features = [feature('w', west), feature('e', east)]
        sources = [osm('10', west, '모현학사'), osm('20', east, '모현학사')]
        with patch('destination_catalog._load_osm_features', return_value=sources):
            forward = build_destination_catalog({'features': features})
        with patch('destination_catalog._load_osm_features', return_value=list(reversed(sources))):
            reverse = build_destination_catalog({'features': list(reversed(features))})
        self.assertEqual(forward, reverse)
        self.assertEqual(len({item['label'] for item in forward}), 2)
        self.assertEqual({item['id'] for item in forward}, {'DEST-OSM-10', 'DEST-OSM-20'})
        self.assertTrue(all('footprint' not in item['label'] for item in forward))

    def test_generated_unknowns_registry_ids_and_generic_wings_are_not_labels(self):
        geometry = geographic((347000, 4134000, 347040, 4134040))
        names = ['이름 미등록 건물 123456789', '11161100367008', 'PK11161100367008', 'A동']
        with patch('destination_catalog._load_osm_features', return_value=[]):
            for name in names:
                self.assertEqual(build_destination_catalog({'features': [feature('x', geometry, name)]}), [])
            campus_parent = feature('x', geometry, '한국외국어대학교용인캠퍼스', dong_name='교양학부강의동')
            self.assertEqual(build_destination_catalog({'features': [campus_parent]}), [])

    def test_a_meaningful_original_footprint_name_is_retained(self):
        geometry = geographic((347000, 4134000, 347040, 4134040))
        with patch('destination_catalog._load_osm_features', return_value=[]):
            catalog = build_destination_catalog({'features': [feature('local-gym', geometry, '체육관')]})
        self.assertEqual(catalog[0]['name'], '체육관')
        self.assertTrue(shape(catalog[0]['geometry']).equals(geometry))

    def test_real_campus_catalog_has_verified_names_and_only_scene_geometry(self):
        scene = load_campus_scene(Path(__file__).parent)
        self.assertEqual(len(scene['all_building_features']), 84)
        catalog = build_destination_catalog(scene)
        self.assertTrue({'공학관', '도서관', '자연과학관', '인문경상관'}.issubset({item['name'] for item in catalog}))
        self.assertEqual(len(catalog), 17)
        self.assertEqual(len({item['id'] for item in catalog}), len(catalog))
        self.assertEqual(len({item['label'] for item in catalog}), len(catalog))
        footprints = {feature['properties']['public_id']: shape(feature['geometry']) for feature in scene['all_building_features']}
        for destination in catalog:
            geometry = shape(destination['geometry'])
            self.assertTrue(geometry.is_valid)
            expected = unary_union([footprints[identifier] for identifier in destination['footprint_ids']])
            self.assertTrue(geometry.equals(expected))
            self.assertNotIn('미등록', destination['label'])


if __name__ == '__main__':
    unittest.main()

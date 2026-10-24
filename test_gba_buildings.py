import copy
import io
import json
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from fetch_gba import HTTPRangeFile, feature_id
from gba_buildings import load_gba, match_gba, apply_gba, supplement_footprints
from gis_scene import build_scene, select_major_buildings
from public_buildings import PublicDataError, campus_id
from shadow_model import TO_G


def footprint(identifier, geom, **props):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(geom),
            'properties': {'public_id': identifier, 'name': '', 'dong_name': '',
                           'height_m': None, 'aboveground_floors': None,
                           'source_file': 'test', 'data_date': '', **props}}


def estimated(identifier, geom, height=12):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(geom),
            'properties': {'height': height, 'source': 'test', 'id': '0'}}


class GBATests(unittest.TestCase):
    def setUp(self):
        self.geom = transform(TO_G, box(347000, 4134000, 347040, 4134040))
        self.target = footprint('gis1', self.geom)
        self.gba = estimated('gba1', self.geom)

    def test_fill_missing_preserve_geometry_and_height_priority(self):
        matches = match_gba([self.target], [self.gba])
        enriched = apply_gba([self.target], matches, expanded=True)
        self.assertEqual(enriched[0]['geometry'], self.target['geometry'])
        self.assertNotIn('gba_height_m', self.target['properties'])
        for props, override, expected in [({}, {}, 12), ({'height_m': 24}, {}, 24),
                                          ({'aboveground_floors': 5}, {}, 15),
                                          ({'height_m': 24}, {'gis1': 31}, 31),
                                          ({'match_status': '사용자 매칭', 'matched_height': 27}, {}, 27)]:
            feature = copy.deepcopy(enriched[0])
            feature['properties'].update(props)
            self.assertEqual(build_scene([feature], override, 3, 15)[0][0][1], expected)
        disabled = apply_gba(enriched, matches, enabled=False, expanded=True)
        self.assertNotIn('gba_height_m', disabled[0]['properties'])
        self.assertIsNone(build_scene(disabled, {}, 3, 15, False)[0][0][1])

    def test_parts_are_only_available_in_explicit_expanded_mode(self):
        left = transform(TO_G, box(347000, 4134000, 347020, 4134040))
        right = transform(TO_G, box(347020, 4134000, 347040, 4134040))
        parts = [footprint('a', left), footprint('b', right)]
        matches = match_gba(parts, [self.gba])
        self.assertTrue(all(not m['accepted'] and m['expanded_accepted'] for m in matches.values()))
        self.assertTrue(all('gba_height_m' not in f['properties'] for f in apply_gba(parts, matches)))
        records = build_scene(apply_gba(parts, matches, expanded=True), {}, 3, 15)[1]
        self.assertTrue(all(r['높이 근거'] == 'GBA 확장 추정 (낮은 신뢰)' for r in records))

    def test_duplicate_or_unrelated_outlines_are_not_resolved_by_expansion(self):
        duplicate = footprint('duplicate', self.geom)
        matches = match_gba([self.target, duplicate], [self.gba])
        self.assertTrue(all(not m['accepted'] and not m['expanded_accepted'] for m in matches.values()))
        remote = estimated('remote', transform(TO_G, box(347100, 4134000, 347140, 4134040)))
        match = match_gba([self.target], [remote])['gis1']
        self.assertFalse(match['accepted'] or match['expanded_accepted'])

    def test_invalid_height_and_ambiguous_sources_never_apply(self):
        for value in (0, None, -10, float('nan'), float('inf'), 999):
            match = match_gba([self.target], [estimated('bad', self.geom, value)])['gis1']
            self.assertFalse(match['accepted'] or match['expanded_accepted'])
        matches = match_gba([self.target], [self.gba, estimated('duplicate', self.geom, 35)])
        self.assertFalse(matches['gis1']['accepted'] or matches['gis1']['expanded_accepted'])

    def test_footprint_supplement_does_not_duplicate_gis(self):
        campus = self.geom.buffer(0.01)
        other = transform(TO_G, box(347100, 4134000, 347120, 4134020))
        osm = [{'geometry': mapping(geom), 'properties': {'osm_id': str(i), 'name': 'test'}}
               for i, geom in enumerate([self.geom, other, other])]
        extra = supplement_footprints([self.target], osm, campus)
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0]['properties']['geometry_source'], 'OSM 보완')
        self.assertIsNone(extra[0]['properties']['height_m'])

    def test_cache_rejects_wrong_campus_and_duplicate_ids(self):
        campus = self.geom.buffer(0.01)
        data = {'type': 'FeatureCollection', 'metadata': {'schema_version': 1,
                'campus_id': campus_id(campus), 'crs': 'OGC:CRS84',
                'height_kind': 'machine_learning_estimate_not_survey'}, 'features': [self.gba]}
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            self.assertEqual(len(load_gba('unused', campus)['features']), 1)
            with self.assertRaises(PublicDataError):
                load_gba('unused', campus.buffer(0.1))
        data['features'].append(self.gba)
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            with self.assertRaises(PublicDataError):
                load_gba('unused', campus)

    def test_source_zero_ids_are_distinguished_by_geometry(self):
        self.assertNotEqual(feature_id(self.geom, 'source', '0'),
                            feature_id(self.geom.buffer(0.001), 'source', '0'))

    def test_http_range_refuses_full_download_and_excess_budget(self):
        session = MagicMock()
        session.head.return_value.headers = {'Content-Length': '1000', 'ETag': 'test'}
        response = session.get.return_value.__enter__.return_value
        response.status_code = 200
        response.headers = {}
        with patch('fetch_gba.requests.Session', return_value=session):
            with HTTPRangeFile('https://example.invalid', budget=20) as reader:
                with self.assertRaises(ValueError):
                    reader.read(30)
                session.get.assert_not_called()
                with self.assertRaises(ValueError):
                    reader.read(10)
                response.raw.read.assert_not_called()
                response.status_code = 206
                response.headers = {'Content-Range': 'bytes 0-9/1000'}
                response.raw = io.BytesIO(b'1234567890')
                self.assertEqual(reader.read(10), b'1234567890')
                self.assertEqual(reader.downloaded, 10)

    def test_real_campus_all_unknowns_remain_explicit(self):
        root = Path(__file__).parent / 'data'
        campus = shape(json.loads((root/'campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
        features = json.loads((root/'gis_buildings_cache.json').read_text(encoding='utf-8'))['normalized']['features']
        osm = json.loads((root/'buildings.geojson').read_text(encoding='utf-8'))['features']
        gba = load_gba(root/'gba_campus.geojson', campus)
        extra = supplement_footprints(features, osm, campus)
        self.assertEqual((len(features), len(gba['features']), len(extra)), (75, 27, 9))
        all_features = features + extra
        matches = match_gba(all_features, gba['features'])
        enriched = apply_gba(all_features, matches, expanded=True)
        records = build_scene(enriched, {}, 3, 15)[1]
        counts = Counter(r['높이 근거'] for r in records)
        self.assertEqual(counts['A16 실제 높이'], 6)
        self.assertEqual(counts['A26 층수 기반'], 5)
        self.assertEqual(counts['GBA 위성 추정'], 10)
        self.assertGreater(counts['GBA 확장 추정 (낮은 신뢰)'], 0)
        self.assertGreater(counts['fallback'], 0)
        self.assertEqual(sum(counts.values()), 84)
        records = build_scene(enriched, {}, 3, 15, False)[1]
        self.assertEqual(sum(r['최종 높이 (m)'] is None for r in records), counts['fallback'])


if __name__ == '__main__':
    unittest.main()

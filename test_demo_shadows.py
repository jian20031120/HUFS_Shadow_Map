import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pvlib
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from demo_scene import resolved_buildings
from gba_buildings import apply_gba, load_gba, match_gba, supplement_footprints
from gba_raster import apply_raster, load_height_raster, sample_all
from gis_scene import build_scene, flat_shade
from shadow_model import TO_G, TO_M, projected_shadow, raster_shadows
from tree_model import canopy_shadow


class DemoShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent / 'data'
        cls.campus = shape(json.loads((root/'campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
        features = json.loads((root/'gis_buildings_cache.json').read_text(encoding='utf-8'))['normalized']['features']
        osm = json.loads((root/'buildings.geojson').read_text(encoding='utf-8'))['features']
        features += supplement_footprints(features, osm, cls.campus)
        gba = load_gba(root/'gba_campus.geojson', cls.campus)
        features = apply_gba(features, match_gba(features, gba['features']), expanded=True)
        raster = load_height_raster(root/'gba_height_campus.npz', root/'gba_height_campus_meta.json', cls.campus)
        features = apply_raster(features, sample_all(features, raster))
        cls.buildings, cls.records = build_scene(features, {}, 3, 15, include_unknown=False)
        cls.active = resolved_buildings(cls.buildings)

    def setUp(self):
        self.x, self.y = 347000., 4134000.
        def geo(bounds):
            return transform(TO_G, box(*bounds))
        self.known = geo((self.x, self.y, self.x+10, self.y+10))
        self.unresolved = geo((self.x+2, self.y+12, self.x+6, self.y+16))
        self.test_campus = geo((self.x-10, self.y-10, self.x+30, self.y+40))
        self.scene = [(self.known, 10.), (self.unresolved, None)]

    def test_real_campus_retains_audit_and_calculates_only_74(self):
        self.assertEqual(len(self.buildings), 84)
        self.assertEqual(len(self.records), 84)
        self.assertEqual(sum(height is None for _, height in self.buildings), 10)
        self.assertEqual(sum(row['높이 근거'] == '계산 제외' for row in self.records), 10)
        self.assertEqual(len(self.active), 74)
        self.assertTrue(all(np.isfinite(height) and height > 0 for _, height in self.active))
        self.assertTrue(all(row['높이 근거'] != 'fallback' for row in self.records))

    def test_excluded_outline_does_not_cut_a_hole_in_planar_shadow(self):
        active = resolved_buildings(self.scene)
        shade = flat_shade(self.test_campus, active, 45, 180)
        self.assertAlmostEqual(shade.area, 100., places=4)
        # The unresolved polygon lies completely inside the known shadow.
        # It is ground for this demo, not a masking footprint.
        area = shade.intersection(transform(TO_M, self.unresolved)).area
        self.assertAlmostEqual(area, 16., places=4)
        self.assertIsNone(self.scene[1][1])

    def test_excluded_outline_does_not_cut_a_hole_in_canopy_shadow(self):
        trees = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': mapping(self.known),
             'properties': {'tree_id': 'TREE-test', 'height_m': 10.}}]}
        shade = canopy_shadow(trees, self.test_campus, 45, 180, resolved_buildings(self.scene))
        self.assertAlmostEqual(shade.area, 100., places=4)
        self.assertAlmostEqual(shade.intersection(transform(TO_M, self.unresolved)).area, 16., places=4)

    def test_excluded_outline_keeps_terrain_ground_and_image_intact(self):
        xs = np.arange(self.x-20, self.x+51, 5)
        ys = np.arange(self.y-20, self.y+61, 5)
        terrain = (xs, ys, np.zeros((len(ys), len(xs))))
        expected = raster_shadows(self.test_campus, [(self.known, 10.)], terrain, 45, 180, step=5, reach=30)
        actual = raster_shadows(self.test_campus, resolved_buildings(self.scene), terrain, 45, 180, step=5, reach=30)
        self.assertEqual(actual['ground_area'], expected['ground_area'])
        self.assertEqual(actual['ground_area'], 1700.)
        self.assertEqual(actual['shaded_area'], expected['shaded_area'])
        np.testing.assert_array_equal(actual['image'], expected['image'])

    def test_demo_time_changes_real_scene_and_shadow_direction(self):
        moments = pd.DatetimeIndex([
            datetime(2026, 6, 21, hour, tzinfo=ZoneInfo('Asia/Seoul')) for hour in (9, 15)])
        sun = pvlib.solarposition.get_solarposition(moments, self.campus.centroid.y, self.campus.centroid.x)
        shades = []
        single_shadows = []
        for _, position in sun.iterrows():
            elevation, azimuth = float(position.apparent_elevation), float(position.azimuth)
            self.assertGreater(elevation, 3.)
            shade = flat_shade(self.campus, self.active, elevation, azimuth)
            self.assertTrue(shade.is_valid)
            self.assertFalse(shade.is_empty)
            self.assertLess(shade.difference(transform(TO_M, self.campus)).area, 1e-5)
            shades.append(shade)
            single_shadows.append(projected_shadow(self.known, 10., elevation, azimuth))
        self.assertGreater(shades[0].symmetric_difference(shades[1]).area, 100.)
        self.assertGreater(abs(shades[0].area - shades[1].area), 10.)
        # Morning sunlight casts west, afternoon sunlight casts east.
        center_x = transform(TO_M, self.known).centroid.x
        self.assertLess(single_shadows[0].centroid.x, center_x)
        self.assertGreater(single_shadows[1].centroid.x, center_x)


if __name__ == '__main__':
    unittest.main()

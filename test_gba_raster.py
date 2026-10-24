import unittest
import numpy as np
from shapely.geometry import box
from shapely.ops import transform
from shadow_model import TO_G
from gba_raster import sample_height, apply_raster
from gis_scene import build_scene
from test_gba_buildings import footprint


class RasterHeightTests(unittest.TestCase):
    def setUp(self):
        self.raster = {'height': np.full((4, 4), 8.0),
                       'transform': np.array([3., 0., 347000., 0., -3., 4134012.])}

    def feature(self, bounds, **props):
        return footprint('test', transform(TO_G, box(*bounds)), **props)

    def test_weights_follow_area_not_number_of_touched_pixels(self):
        self.raster['height'][:, 1:] = 30
        feature = self.feature((347000, 4134000, 347003.2, 4134012))
        result = sample_height(feature, self.raster)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['height_m'], 8)
        self.assertAlmostEqual(result['valid_area_ratio'], 1)

    def test_zero_and_nodata_do_not_become_invented_positive_heights(self):
        feature = self.feature((347000, 4134000, 347012, 4134012))
        for invalid in (0, -1, np.nan, np.inf):
            self.raster['height'][:] = invalid
            result = sample_height(feature, self.raster)
            self.assertFalse(result['accepted'])
            self.assertIsNone(result['height_m'])
        self.raster['height'][:] = 0
        self.raster['height'][:, 0] = 20
        self.assertFalse(sample_height(feature, self.raster)['accepted'])

    def test_tiny_polygon_has_explicit_mixed_pixel_uncertainty(self):
        feature = self.feature((347001, 4134001, 347002, 4134002))
        result = sample_height(feature, self.raster)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['height_m'], 8)
        self.assertEqual(result['pixel_count'], 1)
        self.assertIn('매우 낮음', result['confidence'])
        self.assertAlmostEqual(result['max_pixel_purity'], 1/9, places=5)

    def test_outside_raster_and_mostly_missing_area_are_rejected(self):
        outside = self.feature((347100, 4134000, 347110, 4134010))
        partial = self.feature((346990, 4134000, 347003, 4134012))
        self.assertFalse(sample_height(outside, self.raster)['accepted'])
        self.assertFalse(sample_height(partial, self.raster)['accepted'])

    def test_registered_and_strict_heights_precede_raster_but_group_average_does_not(self):
        base = self.feature((347000, 4134000, 347012, 4134012))
        samples = {'test': sample_height(base, self.raster)}
        for props, expected in [({}, 8), ({'height_m': 25}, 25), ({'aboveground_floors': 5}, 15),
                                ({'gba_height_m': 14, 'gba_height_source': 'GBA 위성 추정'}, 14),
                                ({'gba_height_m': 14, 'gba_height_source': 'GBA 확장 추정 (낮은 신뢰)'}, 8)]:
            feature = self.feature((347000, 4134000, 347012, 4134012), **props)
            result = apply_raster([feature], samples)
            self.assertEqual(build_scene(result, {}, 3, 15)[0][0][1], expected)
        result = apply_raster(apply_raster([base], samples), samples, enabled=False)
        self.assertIsNone(build_scene(result, {}, 3, 15, False)[0][0][1])

    def test_downloaded_campus_raster_integrity_and_coverage(self):
        import json
        from pathlib import Path
        from shapely.geometry import shape
        from gba_raster import load_height_raster, sample_all
        from public_buildings import PublicDataError
        root = Path(__file__).parent/'data'
        campus = shape(json.loads((root/'campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
        raster = load_height_raster(root/'gba_height_campus.npz', root/'gba_height_campus_meta.json', campus)
        self.assertEqual(raster['height'].shape, (325, 648))
        with self.assertRaises(PublicDataError):
            load_height_raster(root/'gba_height_campus.npz', root/'gba_height_campus_meta.json', campus.buffer(.01))
        features = json.loads((root/'gis_buildings_cache.json').read_text(encoding='utf-8'))['normalized']['features']
        samples = sample_all(features, raster)
        self.assertTrue(all(s['valid_area_ratio'] > .99 for s in samples.values()))
        self.assertEqual(sum(not s['accepted'] for s in samples.values()), 10)


if __name__ == '__main__':
    unittest.main()

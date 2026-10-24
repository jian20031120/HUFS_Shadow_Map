from datetime import datetime
from pathlib import Path
import unittest

from shapely.geometry import shape
from shapely.ops import transform

from hufs_shadow.campus_scene import load_campus_scene, sun_and_shade, display_moment, KST
from hufs_shadow.shadow_model import TO_M


class CampusSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = load_campus_scene(Path(__file__).resolve().parents[1])

    def test_map_contains_only_resolved_buildings_but_retains_exclusion_audit(self):
        self.assertEqual(len(self.scene['buildings']), 74)
        self.assertEqual(len(self.scene['features']), 74)
        self.assertEqual(self.scene['excluded_count'], 10)
        self.assertEqual(len(self.scene['records']), 84)
        self.assertEqual(len(self.scene['all_building_footprints']), 84)
        self.assertTrue(all(not footprint.is_empty and footprint.is_valid
                            for footprint in self.scene['all_building_footprints']))
        self.assertTrue(all(height is not None for _, height in self.scene['buildings']))

    def test_night_produces_no_solar_shadow(self):
        output = sun_and_shade(self.scene, datetime(2026, 6, 21, 0, 0, tzinfo=KST))
        self.assertLess(output['elevation'], 3)
        self.assertTrue(shape(output['shadow']).is_empty)

    def test_daylight_shadows_remain_inside_campus_and_outside_known_buildings(self):
        output = sun_and_shade(self.scene, datetime(2026, 10, 25, 15, 0, tzinfo=KST))
        self.assertGreater(output['elevation'], 3)
        shade = output['shadow_metric']
        self.assertGreater(shade.area, 0)
        self.assertLess(shade.difference(transform(TO_M, self.scene['campus'])).area, .001)
        for building, _ in self.scene['buildings']:
            self.assertLess(shade.intersection(transform(TO_M, building)).area, .001)

    def test_time_presets_use_today_in_korean_time(self):
        now = datetime(2026, 10, 25, 1, 42, 30, tzinfo=KST)
        self.assertEqual(display_moment('current', now), now.replace(second=0))
        self.assertEqual(display_moment('morning', now).hour, 9)
        self.assertEqual(display_moment('noon', now).hour, 12)
        self.assertEqual(display_moment('afternoon', now).hour, 15)

    def test_noon_export_keeps_valid_faces_and_metric_geometry(self):
        output = sun_and_shade(self.scene, datetime(2026, 10, 25, 12, 0, tzinfo=KST))
        metric = output['shadow_metric']
        geographic = shape(output['shadow'])
        self.assertTrue(metric.is_valid)
        self.assertTrue(geographic.is_valid)
        self.assertIn(geographic.geom_type, ('Polygon', 'MultiPolygon'))
        self.assertAlmostEqual(metric.area, output['shade_area_m2'], places=7)
        restored = transform(TO_M, geographic)
        self.assertLess(abs(restored.area - metric.area), .001)
        # Candidate selection uses original metres, not a geographic round trip.
        self.assertGreaterEqual(metric.intersection(transform(TO_M, self.scene['campus'])).area, 0)


if __name__ == '__main__':
    unittest.main()

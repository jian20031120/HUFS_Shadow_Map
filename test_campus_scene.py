from datetime import datetime
from pathlib import Path
import unittest

from shapely.geometry import shape
from shapely.ops import transform

from campus_scene import load_campus_scene, sun_and_shade, display_moment, KST
from shadow_model import TO_M


class CampusSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = load_campus_scene(Path(__file__).parent)

    def test_map_contains_only_resolved_buildings_but_retains_exclusion_audit(self):
        self.assertEqual(len(self.scene['buildings']), 74)
        self.assertEqual(len(self.scene['features']), 74)
        self.assertEqual(self.scene['excluded_count'], 10)
        self.assertEqual(len(self.scene['records']), 84)
        self.assertEqual(len(self.scene['all_building_footprints']), 84)
        self.assertTrue(all(not footprint.is_empty and footprint.is_valid
                            for footprint in self.scene['all_building_footprints']))
        self.assertTrue(all(height is not None for _, height in self.scene['buildings']))

    def test_night_produces_no_shade_walkway_recommendations(self):
        output = sun_and_shade(self.scene, datetime(2026, 6, 21, 0, 0, tzinfo=KST))
        self.assertLess(output['elevation'], 3)
        self.assertTrue(shape(output['shadow']).is_empty)
        self.assertEqual(output['shaded_walkways']['features'], [])

    def test_daylight_shaded_sections_are_on_real_walkways_and_inside_campus(self):
        output = sun_and_shade(self.scene, datetime(2026, 10, 25, 15, 0, tzinfo=KST))
        self.assertGreater(output['elevation'], 3)
        self.assertGreater(len(output['shaded_walkways']['features']), 0)
        shade = transform(TO_M, shape(output['shadow']))
        for feature in output['shaded_walkways']['features']:
            line = transform(TO_M, shape(feature['geometry']))
            self.assertLess(line.difference(shade.buffer(.01)).length, .001)
            self.assertTrue(self.scene['campus'].buffer(1e-9).covers(shape(feature['geometry'])))

    def test_unshaded_walking_network_is_not_filled_with_vehicle_road_sections(self):
        output = sun_and_shade(self.scene, datetime(2026,10,25,9,0,tzinfo=KST))
        self.assertGreater(output['shade_area_m2'],0)
        self.assertEqual(output['shaded_walkways']['features'],[])

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

import unittest

from shapely.geometry import LineString, Point, box, shape
from shapely.ops import transform, unary_union

from shade_guidance import build_shade_guidance
from shadow_model import TO_G, TO_M


class ShadeGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.campus_metric = box(347000, 4134000, 347120, 4134120)
        self.campus = transform(TO_G, self.campus_metric)

    def origin(self, x, y):
        point = transform(TO_G, Point(x, y))
        return {'latitude': point.y, 'longitude': point.x}

    def metric_route(self, result):
        self.assertEqual(len(result['route']['features']), 1)
        return transform(TO_M, shape(result['route']['features'][0]['geometry']))

    def test_route_is_continuous_inside_campus_and_avoids_building(self):
        obstacle = box(347035, 4134000, 347065, 4134080)
        shade = box(347080, 4134020, 347110, 4134050)
        origin = self.origin(347020, 4134030)
        result = build_shade_guidance(self.campus, [transform(TO_G, obstacle)], shade,
                                      origin, search_radius=120)
        self.assertEqual(result['status'], 'ok')
        route = self.metric_route(result)
        self.assertLess(route.difference(self.campus_metric.buffer(1e-5)).length, 1e-4)
        self.assertTrue(route.intersection(obstacle).is_empty)
        self.assertLess(Point(route.coords[0]).distance(Point(347020, 4134030)), 1e-5)
        self.assertAlmostEqual(result['distance_m'], result['sunny_distance_m']+result['shaded_distance_m'], places=5)
        self.assertGreaterEqual(result['target']['properties']['clearance_m'], 3-1e-5)
        self.assertLess(Point(route.coords[-1]).distance(transform(TO_M, shape(result['target']['geometry']))), 1e-5)

    def test_no_diagonal_corner_cut_or_thin_wall_crossing(self):
        wall = box(347058, 4134000, 347059, 4134120)
        shade = box(347080, 4134030, 347110, 4134060)
        result = build_shade_guidance(self.campus, [transform(TO_G, wall)], shade,
                                      self.origin(347030, 4134045), search_radius=100)
        self.assertEqual(result['status'], 'no_route')
        self.assertEqual(result['route']['features'], [])

    def test_already_shaded_and_outside_are_explicit(self):
        shade = box(347020, 4134020, 347050, 4134050)
        result = build_shade_guidance(self.campus, [], shade, self.origin(347030, 4134030))
        self.assertEqual(result['status'], 'already_shaded')
        self.assertEqual(result['distance_m'], 0)
        self.assertEqual(result['route']['features'], [])
        result = build_shade_guidance(self.campus, [], shade, self.origin(347200, 4134030))
        self.assertEqual(result['status'], 'outside')
        self.assertIsNone(result['target'])

    def test_empty_tiny_distant_or_too_thin_shade_is_not_invented(self):
        origin = self.origin(347020, 4134030)
        for shade in (unary_union([]), box(347040, 4134020, 347042, 4134022)):
            result = build_shade_guidance(self.campus, [], shade, origin, search_radius=80)
            self.assertEqual(result['status'], 'no_shade')
        result = build_shade_guidance(self.campus, [], box(347080, 4134020, 347110, 4134050), origin, search_radius=20)
        self.assertEqual(result['status'], 'no_shade')
        result = build_shade_guidance(self.campus, [], box(347040, 4134020, 347044, 4134050), origin, search_radius=80)
        self.assertEqual(result['status'], 'no_route')

    def test_narrow_but_valid_interior_gets_a_verified_final_connector(self):
        shade = box(347050.1, 4134050.1, 347056.5, 4134056.5)
        result = build_shade_guidance(self.campus, [], shade, self.origin(347020, 4134020), search_radius=80)
        self.assertEqual(result['status'], 'ok')
        route = self.metric_route(result)
        self.assertTrue(self.campus_metric.buffer(1e-5).covers(route))
        self.assertGreaterEqual(result['target']['properties']['clearance_m'], 3-1e-5)

    def test_longer_shady_detour_is_preferred_over_shorter_full_sun(self):
        # Four-metre corridors are too narrow to supply a 3 m interior target.
        # Only the wide patch at the right qualifies. A longer trip along the
        # upper shaded corridor should beat the short sunny straight line.
        target_patch = box(347085, 4134015, 347105, 4134035)
        shade = unary_union([box(347008, 4134024, 347012, 4134045),
                             box(347010, 4134043, 347097, 4134047),
                             box(347093, 4134033, 347097, 4134045), target_patch])
        origin = self.origin(347010, 4134020)
        result = build_shade_guidance(self.campus, [], shade, origin, search_radius=110)
        self.assertEqual(result['status'], 'ok')
        route = self.metric_route(result)
        target = transform(TO_M, shape(result['target']['geometry']))
        self.assertTrue(target_patch.buffer(1e-5).covers(target))
        direct = LineString([(347010, 4134020), (target.x, target.y)])
        self.assertGreater(result['distance_m'], direct.length+20)
        self.assertGreater(direct.difference(shade).length, 60)
        self.assertLess(result['sunny_distance_m'], 15)
        self.assertGreater(result['shaded_distance_m'], 80)
        self.assertGreater(route.bounds[3], 4134043)

    def test_invalid_origin_and_unbounded_grid_are_rejected(self):
        for origin in ({'latitude': True, 'longitude': 127},
                       {'latitude': 91, 'longitude': 127},
                       {'latitude': float('nan'), 'longitude': 127}, {}):
            with self.assertRaises(ValueError):
                build_shade_guidance(self.campus, [], unary_union([]), origin)
        with self.assertRaises(ValueError):
            build_shade_guidance(self.campus, [], unary_union([]), self.origin(347020, 4134020), grid_size=.1)


if __name__ == '__main__':
    unittest.main()

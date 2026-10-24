import unittest

from shapely.geometry import LineString, Point, box, shape
from shapely.ops import transform, unary_union

from shade_guidance import build_destination_guidance
from shadow_model import TO_G, TO_M


class DestinationGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.campus_metric = box(347000, 4134000, 347120, 4134120)
        self.campus = transform(TO_G, self.campus_metric)
        self.destination_metric = box(347090, 4134015, 347110, 4134035)
        self.destination = transform(TO_G, self.destination_metric)

    def origin(self, x, y):
        point = transform(TO_G, Point(x, y))
        return {'latitude': point.y, 'longitude': point.x}

    def route_metric(self, result):
        self.assertEqual(len(result['route']['features']), 1)
        return transform(TO_M, shape(result['route']['features'][0]['geometry']))

    def test_destination_is_approached_outside_and_not_through_its_centre(self):
        obstacle = box(347040, 4134000, 347060, 4134070)
        result = build_destination_guidance(self.campus, [transform(TO_G, obstacle), self.destination],
                                             unary_union([]), self.origin(347020, 4134020), self.destination)
        self.assertEqual(result['status'], 'ok')
        route = self.route_metric(result)
        target = transform(TO_M, shape(result['target']['geometry']))
        self.assertTrue(self.campus_metric.buffer(1e-5).covers(route))
        self.assertTrue(route.intersection(obstacle).is_empty)
        self.assertTrue(route.intersection(self.destination_metric).is_empty)
        self.assertGreater(target.distance(self.destination_metric), 0)
        self.assertLessEqual(target.distance(self.destination_metric), 2+1e-5)
        self.assertLess(Point(route.coords[0]).distance(Point(347020, 4134020)), 1e-5)
        self.assertLess(Point(route.coords[-1]).distance(target), 1e-5)
        self.assertAlmostEqual(result['distance_m'], result['sunny_distance_m']+result['shaded_distance_m'], places=4)

    def test_a_longer_all_shade_path_has_priority_and_shaded_start_keeps_routing(self):
        shade = unary_union([box(347007, 4134017, 347013, 4134047),
                             box(347010, 4134042, 347100, 4134048),
                             box(347094, 4134030, 347100, 4134047)])
        origin = self.origin(347010, 4134020)
        result = build_destination_guidance(self.campus, [self.destination], shade, origin, self.destination)
        self.assertEqual(result['status'], 'ok')
        route = self.route_metric(result)
        target = transform(TO_M, shape(result['target']['geometry']))
        direct = LineString([(347010, 4134020), (target.x, target.y)])
        self.assertGreater(result['distance_m'], direct.length+20)
        self.assertAlmostEqual(result['sunny_distance_m'], 0, places=4)
        self.assertGreater(direct.difference(shade).length, 60)
        self.assertGreater(route.bounds[3], 4134042)

    def test_less_sun_beats_shorter_distance_even_when_some_sun_is_unavoidable(self):
        shade = unary_union([box(347008, 4134024, 347012, 4134045),
                             box(347010, 4134043, 347099, 4134047),
                             box(347095, 4134033, 347099, 4134047)])
        result = build_destination_guidance(self.campus, [self.destination], shade,
                                             self.origin(347010, 4134020), self.destination)
        self.assertEqual(result['status'], 'ok')
        self.assertGreater(result['distance_m'], 100)
        self.assertLess(result['sunny_distance_m'], 10)
        self.assertGreater(result['shaded_distance_m'], 80)

    def test_sunny_tie_chooses_shorter_route(self):
        result = build_destination_guidance(self.campus, [self.destination], unary_union([]),
                                             self.origin(347010, 4134020), self.destination)
        self.assertEqual(result['status'], 'ok')
        self.assertAlmostEqual(result['sunny_distance_m'], result['distance_m'], places=4)
        self.assertAlmostEqual(result['distance_m'], 78, places=3)

    def test_building_enclosure_has_no_route_and_start_is_not_relocated(self):
        wall = box(347050, 4134000, 347051, 4134120)
        result = build_destination_guidance(self.campus, [transform(TO_G, wall), self.destination],
                                             unary_union([]), self.origin(347020, 4134020), self.destination)
        self.assertEqual(result['status'], 'no_route')
        self.assertEqual(result['route']['features'], [])
        result = build_destination_guidance(self.campus, [transform(TO_G, wall), self.destination], unary_union([]),
                                             self.origin(347050.5, 4134020), self.destination)
        self.assertEqual(result['status'], 'no_route')
        self.assertIsNone(result['target'])

    def test_arrival_and_outside_are_distinct(self):
        arrived = build_destination_guidance(self.campus, [self.destination], unary_union([]),
                                              self.origin(347088.5, 4134020), self.destination)
        self.assertEqual(arrived['status'], 'arrived')
        self.assertEqual(arrived['route']['features'], [])
        inside = build_destination_guidance(self.campus, [self.destination], unary_union([]),
                                             self.origin(347100, 4134020), self.destination)
        self.assertEqual(inside['status'], 'arrived')
        self.assertEqual(inside['target_kind'], 'already_at_destination')
        self.assertEqual(inside['target']['properties']['target_kind'], 'already_at_destination')
        self.assertEqual(inside['route']['features'], [])
        outside = build_destination_guidance(self.campus, [self.destination], unary_union([]),
                                              self.origin(346990, 4134020), self.destination)
        self.assertEqual(outside['status'], 'outside')

    def test_exact_edge_exposure_includes_shade_missed_by_midpoint_sampling(self):
        narrow_shade = box(347040.1, 4134000, 347040.4, 4134120)
        result = build_destination_guidance(self.campus, [self.destination], narrow_shade,
                                             self.origin(347010, 4134020), self.destination)
        self.assertEqual(result['status'], 'ok')
        route = self.route_metric(result)
        self.assertAlmostEqual(result['distance_m'], 78, places=3)
        self.assertAlmostEqual(result['shaded_distance_m'], .3, places=4)
        self.assertAlmostEqual(result['sunny_distance_m'], 77.7, places=4)
        self.assertAlmostEqual(route.intersection(narrow_shade).length, result['shaded_distance_m'], places=4)

    def test_destination_search_is_not_limited_to_250_metres(self):
        campus = transform(TO_G, box(347000, 4134000, 347900, 4134120))
        destination = transform(TO_G, box(347800, 4134015, 347820, 4134035))
        result = build_destination_guidance(campus, [destination], unary_union([]),
                                             self.origin(347010, 4134020), destination)
        self.assertEqual(result['status'], 'ok')
        self.assertGreater(result['distance_m'], 750)
        self.assertIsNone(result['search_radius_m'])


if __name__ == '__main__':
    unittest.main()

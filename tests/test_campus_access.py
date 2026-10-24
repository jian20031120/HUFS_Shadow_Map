import unittest

from shapely.geometry import box
from shapely.ops import transform

from hufs_shadow.campus_access import campus_access
from hufs_shadow.shadow_model import TO_G


class CampusAccessTests(unittest.TestCase):
    def setUp(self):
        self.campus = transform(TO_G, box(347000, 4134000, 347400, 4134400))

    def location(self, x, y, accuracy=5):
        lon, lat = TO_G(x, y)
        return {'latitude': lat, 'longitude': lon, 'accuracy': accuracy}

    def test_inside_only_allows_nearby_suggestions(self):
        result = campus_access(self.campus, self.location(347200, 4134200))
        self.assertEqual(result['status'], 'inside')
        self.assertTrue(result['can_recommend'])

    def test_outside_keeps_preview_but_disables_suggestions(self):
        result = campus_access(self.campus, self.location(347600, 4134200))
        self.assertEqual(result['status'], 'outside')
        self.assertFalse(result['can_recommend'])

    def test_uncertainty_crossing_campus_boundary_is_not_treated_as_inside(self):
        for x in (347002, 346998):
            result = campus_access(self.campus, self.location(x, 4134200, accuracy=10))
            self.assertEqual(result['status'], 'boundary')
            self.assertFalse(result['can_recommend'])

    def test_missing_and_imprecise_location_fail_closed(self):
        self.assertFalse(campus_access(self.campus, None)['can_recommend'])
        result = campus_access(self.campus, self.location(347200, 4134200, accuracy=500))
        self.assertEqual(result['status'], 'inaccurate')
        self.assertFalse(result['can_recommend'])


if __name__ == '__main__':
    unittest.main()

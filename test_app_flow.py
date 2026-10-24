from datetime import datetime
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from campus_scene import load_campus_scene, KST
from destination_catalog import build_destination_catalog
from map_app import _demo_origin


class PublicMapFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).parent
        cls.scene = load_campus_scene(cls.root)
        cls.catalog = build_destination_catalog(cls.scene)
        cls.destination = next(item for item in cls.catalog if '공학관' in item['label'])

    def setUp(self):
        clock = patch('map_app.display_moment', return_value=datetime(2026,10,25,15,0,tzinfo=KST))
        clock.start()
        self.addCleanup(clock.stop)

    def run_map(self, location=None, destination=False, force_osm=False, choose_after_mount=False):
        controls = {'location': location, 'time_mode': 'afternoon', 'viewport_height': 800}
        with patch('map_app.location_controls', return_value=controls), \
             patch('map_app.dotenv_values', return_value={'TMAP_APP_KEY': 'dummy-local-test-key'}), \
             patch.dict('os.environ', {'TMAP_APP_KEY': ''}), \
             patch('map_app._scene', return_value=self.scene), \
             patch('map_app.render_tmap') as tmap, patch('map_app._osm_map') as osm:
            app = AppTest.from_file(str(self.root/'app.py'), default_timeout=90)
            if force_osm:
                app.query_params['map'] = 'osm'
            if destination:
                app.session_state['destination_building'] = self.destination['id']
            app.run()
            if choose_after_mount:
                app.selectbox[0].set_value(self.destination['id']).run()
            self.assertFalse(app.exception, [error.message for error in app.exception])
            self.assertFalse(app.error, [error.value for error in app.error])
            return app, tmap.call_args, osm.call_args

    def fix(self, latitude, longitude, accuracy=1):
        return {'status': 'success', 'latitude': latitude, 'longitude': longitude,
                'accuracy': accuracy, 'timestamp': time.time()*1000-1000}

    def campus_fix(self):
        point = _demo_origin(self.scene)
        return self.fix(point['latitude'], point['longitude'])

    def test_first_screen_has_searchable_destination_and_no_fake_start(self):
        app, tmap, osm = self.run_map()
        self.assertIsNotNone(tmap)
        self.assertIsNone(osm)
        self.assertEqual((len(app.metric), len(app.dataframe), len(app.expander), len(app.text_input)), (0, 0, 0, 0))
        self.assertEqual(len(app.selectbox), 1)
        self.assertIn('도착', app.selectbox[0].label)
        self.assertTrue(any('공학관' in item for item in app.selectbox[0].options))
        self.assertIsNone(tmap.kwargs['user_location'])
        self.assertIsNone(tmap.kwargs['guidance']['origin'])
        self.assertEqual(tmap.kwargs['guidance']['status'], 'choose_destination')
        self.assertEqual(tmap.kwargs['guidance']['route']['features'], [])
        self.assertFalse(tmap.kwargs['guidance']['is_demo'])

    def test_search_selection_is_preserved_while_waiting_for_current_location(self):
        app, tmap, _ = self.run_map(choose_after_mount=True)
        self.assertEqual(app.selectbox[0].value, self.destination['id'])
        self.assertEqual(tmap.kwargs['guidance']['status'], 'waiting_location')
        self.assertEqual(tmap.kwargs['guidance']['destination_id'], self.destination['id'])
        self.assertEqual(tmap.kwargs['guidance']['route']['features'], [])

    def test_inside_current_fix_routes_to_selected_building(self):
        fix = self.campus_fix()
        app, tmap, _ = self.run_map(fix, destination=True)
        guide = tmap.kwargs['guidance']
        self.assertIsNotNone(tmap.kwargs['user_location'])
        self.assertFalse(guide['is_demo'])
        self.assertEqual(guide['origin'], {'latitude': fix['latitude'], 'longitude': fix['longitude']})
        self.assertEqual(guide['status'], 'ok')
        self.assertEqual(guide['destination_id'], self.destination['id'])
        self.assertGreater(guide['distance_m'], 0)
        self.assertGreater(len(guide['route']['features']), 0)
        self.assertTrue(any(self.destination['name'] in item.value for item in app.caption))

    def test_current_location_without_destination_does_not_make_a_nearby_shade_route(self):
        _, tmap, _ = self.run_map(self.campus_fix())
        self.assertIsNotNone(tmap.kwargs['user_location'])
        self.assertEqual(tmap.kwargs['guidance']['status'], 'choose_destination')
        self.assertEqual(tmap.kwargs['guidance']['route']['features'], [])

    def test_outside_fix_never_becomes_a_campus_demo_route(self):
        app, tmap, _ = self.run_map(self.fix(37.5,127.0), destination=True)
        self.assertIsNone(tmap.kwargs['user_location'])
        self.assertIsNone(tmap.kwargs['guidance']['origin'])
        self.assertFalse(tmap.kwargs['guidance']['is_demo'])
        self.assertEqual(tmap.kwargs['guidance']['status'], 'waiting_location')
        self.assertEqual(tmap.kwargs['guidance']['route']['features'], [])
        self.assertTrue(any('캠퍼스 밖' in item.value for item in app.caption))

    def test_denied_and_expired_fixes_keep_destination_without_faking_start(self):
        for fix in ({'status': 'denied'}, self.campus_fix() | {'timestamp': time.time()*1000-600000}):
            _, tmap, _ = self.run_map(fix, destination=True)
            self.assertIsNone(tmap.kwargs['user_location'])
            self.assertEqual(tmap.kwargs['guidance']['status'], 'waiting_location')
            self.assertIsNone(tmap.kwargs['guidance']['origin'])

    def test_fallback_uses_the_same_destination_and_route(self):
        _, tmap, osm = self.run_map(self.campus_fix(), destination=True, force_osm=True)
        self.assertIsNone(tmap)
        self.assertIsNotNone(osm)
        self.assertEqual(osm.args[3]['status'], 'ok')
        self.assertEqual(osm.args[3]['destination_id'], self.destination['id'])
        self.assertGreater(len(osm.args[3]['route']['features']), 0)
        from map_app import _osm_map
        with patch('map_app.st_folium') as rendered:
            _osm_map(*osm.args)
        page = rendered.call_args.args[0].get_root().render()
        self.assertIn(self.destination['name'], page)
        self.assertIn('#2563eb', page)


if __name__ == '__main__':
    unittest.main()

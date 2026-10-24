from html.parser import HTMLParser
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import parse_qs, urlparse
import unittest
from zoneinfo import ZoneInfo

from tmap_view import map_html


ROOT = Path(__file__).parent
NODE = shutil.which('node')


@lru_cache(maxsize=1)
def runtime_html_fixtures():
    """Build real destination-route pages for CLI/REPL runtime regression.

    Only dummy-key and a fixed public sample GPS value are used. Actual device
    location and .env are not read. The application destination helper keeps
    these pages aligned with the current-location-to-building map flow.
    """
    from campus_scene import load_campus_scene, sun_and_shade
    from destination_catalog import build_destination_catalog
    from map_app import _demo_origin, _destination_guide
    from shapely.geometry import mapping

    scene = load_campus_scene(ROOT)
    campus = scene['campus']
    # This is a public, deterministic test coordinate, never a device reading.
    origin = _demo_origin(scene)
    catalog = build_destination_catalog(scene)
    destination = next((item for name in ('공학관', '도서관') for item in catalog if item['name'] == name), None)
    if destination is None:
        raise AssertionError('A known campus destination must be present in the geometry-linked catalog')
    buildings = [{'geometry': feature['geometry'], 'color': '#64748b',
                  'showLabel': False, 'title': '교내 건물'} for feature in scene['features']]
    fixtures = {}
    for label, hour in (('afternoon', 15), ('noon', 12)):
        moment = datetime(2026, 10, 25, hour, tzinfo=ZoneInfo('Asia/Seoul'))
        shade = sun_and_shade(scene, moment)
        guidance = _destination_guide(scene, shade, origin, destination)
        if label == 'afternoon':
            if not guidance.get('route', {}).get('features') or guidance.get('distance_m', 0) <= 0:
                raise AssertionError('The actual afternoon destination request must produce a route')
        fixtures[label+'Html'] = map_html(
            'dummy-key', [campus.centroid.y, campus.centroid.x], mapping(campus), buildings,
            shadow=shade['shadow'], guidance=guidance, user_location={**origin, 'accuracy': 20},
            map_height=600, allow_tree_edit=False,
        )
    return fixtures


def write_runtime_fixtures(directory=None):
    """Optional local debugging export; CI sends the same pages via stdin."""
    directory = Path(directory) if directory is not None else ROOT/'.test_tmp'
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, content in runtime_html_fixtures().items():
        label = key.removesuffix('Html')
        path = directory/f'tmap_runtime_{label}.html'
        path.write_text(content, encoding='utf-8')
        paths[label] = str(path)
    return paths


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.current = {'attrs': dict(attrs), 'text': ''}

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(self.current)
            self.current = None


class TmapLoaderTests(unittest.TestCase):
    def html(self, key='dummy-key', guidance=None):
        return map_html(key, [37.336,127.266],
                        {'type':'Polygon','coordinates':[[[127.26,37.33],[127.27,37.33],[127.27,37.34],[127.26,37.33]]]},
                        [], map_height=500, guidance=guidance)

    def test_document_write_sdk_is_parser_inserted_before_initialization(self):
        parser = Scripts()
        parser.feed(self.html())
        external = [(index, script) for index, script in enumerate(parser.scripts) if 'src' in script['attrs']]
        self.assertEqual(len(external), 1)
        index, sdk = external[0]
        self.assertNotIn('async', sdk['attrs'])
        self.assertNotIn('defer', sdk['attrs'])
        self.assertIn('setTimeout', parser.scripts[index-1]['text'])
        self.assertEqual(parser.scripts[index+1]['text'].strip(), 'initialize();')
        self.assertEqual(urlparse(sdk['attrs']['src']).netloc, 'apis.openapi.sk.com')

    def test_html_encoding_preserves_the_exact_app_key(self):
        key='dummy +&<>"key'
        parser=Scripts(); parser.feed(self.html(key))
        sdk=next(s for s in parser.scripts if 'src' in s['attrs'])
        self.assertEqual(parse_qs(urlparse(sdk['attrs']['src']).query)['appKey'],[key])

    def test_fallback_and_minimal_controls_survive_sdk_failure(self):
        content=self.html()
        self.assertIn('href="/?map=osm"',content)
        self.assertIn('onerror="fail()"',content)
        self.assertIn('typeof Tmapv2.Map',content)
        self.assertNotIn('수관 그리기',content)

    def test_destination_text_cannot_create_inline_html_or_scripts(self):
        label = '도착: 도서관</script><img src=x onerror=alert(1)>'
        guidance = {'destination_name': label, 'target_label': label,
                    'destination_geometry': {'type': 'Polygon', 'coordinates': [
                        [[127.26, 37.33], [127.27, 37.33], [127.27, 37.34], [127.26, 37.33]]]},
                    'target': {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [127.26, 37.33]}}}
        content = self.html(guidance=guidance)
        parser = Scripts()
        parser.feed(content)
        self.assertEqual(len(parser.scripts), 3)
        self.assertNotIn(label, content)
        self.assertNotIn('<img src=x', content)
        payload = json.loads(re.search(r'const data=(.*?);\s*const status=', parser.scripts[0]['text'], re.S).group(1))
        self.assertEqual(payload['guidance']['target_label'], label)

    @unittest.skipUnless(NODE, 'Node CLI is unavailable; run test_tmap_runtime.js through the provided Node REPL.')
    def test_actual_demo_runtime_and_original_border_failure(self):
        result = subprocess.run(
            [NODE, str(ROOT/'test_tmap_runtime.js'), '--stdin'],
            input=json.dumps(runtime_html_fixtures(), ensure_ascii=False),
            capture_output=True, text=True, encoding='utf-8', timeout=45,
            cwd=ROOT, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['passed'])
        self.assertTrue(report['originalBugMutationDetected'])
        self.assertTrue(all(report['guidanceVariants'].values()))
        self.assertTrue(all(report['destinationVariants'].values()))


if __name__ == '__main__':
    unittest.main()

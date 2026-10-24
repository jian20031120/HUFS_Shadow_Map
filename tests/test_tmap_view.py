from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urlparse
import unittest

from hufs_shadow.tmap_view import js_json, map_html


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
    def html(self, key='dummy-key', **options):
        return map_html(key, [37.336,127.266],
                        {'type':'Polygon','coordinates':[[[127.26,37.33],[127.27,37.33],[127.27,37.34],[127.26,37.33]]]},
                        [], **options)

    def payload(self, content):
        parser = Scripts()
        parser.feed(content)
        return json.loads(re.search(r'const data=(.*?);\s*const status=', parser.scripts[0]['text'], re.S).group(1))

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
        self.assertIn('15000', content)
        self.assertIn('if(group)group.push(path)', content)
        self.assertIn('strokeOpacity:0', content)
        self.assertNotIn('수관 그리기',content)
        self.assertNotIn('GroundOverlay', content)
        self.assertNotIn('시연 시작점', content)

    def test_destination_text_cannot_create_inline_html_or_scripts(self):
        label = '도착: 도서관</script><img src=x onerror=alert(1)> __SDK_URL_HTML__'
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

    def test_payload_contains_only_current_map_inputs_and_bounded_height(self):
        location = {'latitude':37.336, 'longitude':127.266, 'accuracy':8,
                    'timestamp':1700000000000, 'extra':'not forwarded'}
        payload = self.payload(self.html(user_location=location, map_height=2000))
        self.assertEqual(set(payload), {'center','campus','buildings','shadow','userLocation',
                                        'guidance','campusBorder','mapHeight'})
        self.assertEqual(payload['userLocation'], {'latitude':37.336,'longitude':127.266,'accuracy':8})
        self.assertEqual(payload['campusBorder']['type'], 'MultiLineString')
        self.assertTrue(payload['campusBorder']['coordinates'])
        self.assertEqual(payload['mapHeight'], 1600)
        self.assertEqual(self.payload(self.html(map_height=1))['mapHeight'], 320)
        self.assertEqual(self.payload(self.html(map_height=float('nan')))['mapHeight'], 650)

    def test_nonfinite_data_and_invalid_coordinates_never_reach_the_sdk(self):
        for bad in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError):
                js_json({'height':bad})
            with self.assertRaises(ValueError):
                self.html(shadow={'type':'Point','coordinates':[bad,37.336]})
        for bad in (True, '37.336', float('nan'), 86, 10**1000):
            payload = self.payload(self.html(user_location={'latitude':bad,'longitude':127.266,'accuracy':8}))
            self.assertIsNone(payload['userLocation'])
        payload = self.payload(self.html(user_location={'latitude':37.336,'longitude':127.266,'accuracy':True}))
        self.assertIsNone(payload['userLocation']['accuracy'])
        for bad_center in ([True,127.266], ['37.336',127.266], [86,127.266], [37.336,181]):
            with self.assertRaises(ValueError):
                map_html('dummy-key',bad_center,{},[])


if __name__ == '__main__':
    unittest.main()

import copy
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

from hufs_shadow import browser_location
from hufs_shadow.browser_location import location_controls, validate_location


ROOT = Path(__file__).resolve().parents[1]
NOW = 1_700_000_000_000


# Run through a local Node executable when available. The same harness can be
# executed by the provided Node REPL, using synthetic navigator/window objects.
JS_TEST_HARNESS = r"""
const assert = (await import('node:assert/strict')).default;
class MockElement {
  constructor() { this.disabled = false; this.hidden = false; this.textContent = ''; this.value = ''; this.dataset = {}; this.listeners = new Map(); }
  addEventListener(type, callback) { if (!this.listeners.has(type)) this.listeners.set(type, new Set()); this.listeners.get(type).add(callback); }
  removeEventListener(type, callback) { this.listeners.get(type)?.delete(callback); }
  emit(type) { if (type === 'click' && this.disabled) return; for (const fn of this.listeners.get(type) || []) fn({}); }
}
const setup = (data = {}, supported = true) => {
  const nodes = new Map(['[data-locate]', '[data-locate-label]', '[data-clear-location]', '[data-time-mode]', '[data-location-status]'].map(key => [key, new MockElement()]));
  const root = { querySelector: key => nodes.get(key) };
  const parent = { querySelector: key => key === '[data-location-controls]' ? root : null };
  const window = new MockElement();
  window.innerHeight = 780;
  window.visualViewport = new MockElement();
  window.visualViewport.height = 780;
  const frames = new Map(); let nextFrame = 1;
  window.requestAnimationFrame = callback => { const id = nextFrame++; frames.set(id, callback); return id; };
  window.cancelAnimationFrame = id => frames.delete(id);
  const flush = () => { const current = [...frames.values()]; frames.clear(); current.forEach(callback => callback()); };
  const requests = [];
  const navigator = supported ? { geolocation: { getCurrentPosition: (success, failure, options) => requests.push({ success, failure, options }) } } : {};
  const writes = [];
  const cleanup = renderComponent({ data, setStateValue: (name, value) => writes.push([name, structuredClone(value)]), parentElement: parent },
    { navigator, window, now: () => 1700000000000 });
  return { nodes, window, frames, flush, requests, writes, cleanup,
    locate: nodes.get('[data-locate]'), label: nodes.get('[data-locate-label]'), clear: nodes.get('[data-clear-location]'), select: nodes.get('[data-time-mode]'), status: nodes.get('[data-location-status]') };
};
const fix = { coords: { latitude: 37.51, longitude: 127.01, accuracy: 8 }, timestamp: 1700000000000 };

const state = setup({ time_mode: 'current', viewport_height: 800 });
assert.equal(state.requests.length, 0, 'Mount must not request location permission');
assert.equal(state.select.value, 'current');
assert.equal(state.status.hidden, true);
state.flush();
assert.deepEqual(state.writes, [['viewport_height', 780]]);
state.window.innerHeight = 700; state.window.visualViewport.height = 700;
state.window.emit('resize'); state.window.emit('resize'); state.window.visualViewport.emit('resize');
assert.equal(state.frames.size, 1, 'Resize notifications must be coalesced');
state.flush();
assert.deepEqual(state.writes.at(-1), ['viewport_height', 700]);
state.window.emit('resize'); state.flush();
assert.equal(state.writes.filter(([name]) => name === 'viewport_height').length, 2, 'Identical viewport sizes must not cause rerun loops');
state.locate.emit('click');
assert.equal(state.requests.length, 1);
assert.deepEqual(state.requests[0].options, { enableHighAccuracy: true, timeout: 12000, maximumAge: 15000 });
assert.equal(state.locate.disabled, true);
state.requests[0].success(fix);
assert.equal(state.writes.at(-1)[0], 'location');
assert.equal(state.writes.at(-1)[1].status, 'success');
assert.equal(state.label.textContent, '위치 갱신');
assert(!state.status.textContent.includes('37.51') && !state.status.textContent.includes('127.01'), 'Coordinates must not appear in the control text');
state.select.value = 'afternoon'; state.select.emit('change');
assert.deepEqual(state.writes.at(-1), ['time_mode', 'afternoon']);
state.select.value = 'unexpected'; const beforeBadMode = state.writes.length; state.select.emit('change');
assert.equal(state.writes.length, beforeBadMode);
state.clear.emit('click');
assert.equal(state.writes.at(-1)[1].status, 'cleared');
assert.equal(state.writes.at(-1)[1].latitude, null);
assert.equal(state.writes.at(-1)[1].longitude, null);
assert.equal(state.label.textContent, '내 위치로 찾기');
state.cleanup();

const denied = setup();
denied.locate.emit('click'); denied.requests[0].failure({ code: 1, message: 'private browser detail' });
assert.equal(denied.writes.at(-1)[1].status, 'denied');
assert(denied.status.textContent.includes('허용하지'));
assert(!denied.status.textContent.includes('private'));
denied.locate.emit('click'); denied.requests[1].failure({ code: 3 });
assert.equal(denied.writes.at(-1)[1].status, 'error');
assert(denied.status.textContent.includes('시간이 초과'));
denied.cleanup();

const clearedPending = setup();
clearedPending.locate.emit('click'); clearedPending.clear.emit('click');
const writesAfterClear = clearedPending.writes.length;
clearedPending.requests[0].success(fix);
assert.equal(clearedPending.writes.length, writesAfterClear, 'A cleared pending request must not restore coordinates');
clearedPending.cleanup();

const disposed = setup();
disposed.locate.emit('click'); disposed.cleanup();
const writesAfterDispose = disposed.writes.length;
disposed.requests[0].success(fix); disposed.requests[0].failure({ code: 1 });
disposed.window.emit('resize'); disposed.window.visualViewport.emit('resize'); disposed.flush();
assert.equal(disposed.writes.length, writesAfterDispose, 'A stale callback must not update component state');
assert.equal(disposed.frames.size, 0);
assert.equal(disposed.window.listeners.get('resize').size, 0);

const unavailable = setup({}, false);
unavailable.locate.emit('click');
assert.equal(unavailable.writes.at(-1)[1].status, 'error');
assert.equal(unavailable.requests.length, 0);
unavailable.cleanup();
return { passed: true, scenarios: ['no automatic permission request', 'click and options', 'success without coordinate text', 'time selection', 'deny and timeout', 'clear pending fix', 'cleanup guard', 'coalesced viewport', 'unsupported browser'] };
"""


class BrowserLocationTests(unittest.TestCase):
    def fix(self, **updates):
        return {'status': 'success', 'latitude': 37.51, 'longitude': 127.01,
                'accuracy': 8, 'timestamp': NOW, **updates}

    def test_recent_fix_returns_only_defined_numeric_fields(self):
        value = self.fix(extra='ignored')
        original = copy.deepcopy(value)
        result = validate_location(value, NOW)
        self.assertEqual(result, self.fix())
        self.assertEqual(value, original)
        self.assertTrue(all(isinstance(result[key], float) for key in ('latitude', 'longitude', 'accuracy', 'timestamp')))

    def test_boolean_string_and_nonfinite_numbers_are_rejected(self):
        for field in ('latitude', 'longitude', 'accuracy', 'timestamp'):
            for bad in (True, False, '37.51', None, float('nan'), float('inf'), -float('inf')):
                with self.subTest(field=field, bad=type(bad).__name__):
                    self.assertIsNone(validate_location(self.fix(**{field: bad}), NOW))

    def test_coordinate_and_accuracy_bounds(self):
        for updates in ({'latitude': -90}, {'latitude': 90}, {'longitude': -180},
                        {'longitude': 180}, {'accuracy': 0}, {'accuracy': 100000}):
            self.assertIsNotNone(validate_location(self.fix(**updates), NOW))
        for updates in ({'latitude': -90.01}, {'latitude': 90.01}, {'longitude': -180.01},
                        {'longitude': 180.01}, {'accuracy': -0.1}, {'accuracy': 100000.1}):
            self.assertIsNone(validate_location(self.fix(**updates), NOW))

    def test_old_future_and_non_success_events_are_rejected(self):
        self.assertIsNotNone(validate_location(self.fix(timestamp=NOW-300000), NOW))
        for timestamp in (NOW-300001, NOW+1, -1):
            self.assertIsNone(validate_location(self.fix(timestamp=timestamp), NOW))
        for value in (None, [], 'success', self.fix(status='denied'), self.fix(status='error'), self.fix(status='cleared')):
            self.assertIsNone(validate_location(value, NOW))
        self.assertIsNone(validate_location(self.fix(), NOW, -1))
        self.assertIsNone(validate_location(self.fix(), True))

    def test_wrapper_mounts_explicit_callbacks_and_preserves_session_events(self):
        state = {'display_moment': {'time_mode': 'afternoon', 'location': self.fix(), 'viewport_height': 720}}
        renderer = Mock(return_value={'time_mode': 'afternoon', 'location': self.fix(status='cleared'), 'viewport_height': 720})
        with patch.object(browser_location.st, 'session_state', state), patch.object(browser_location, '_component_renderer', return_value=renderer):
            result = location_controls(key='display_moment')
        self.assertEqual(result['location']['status'], 'cleared')
        self.assertIsNone(result['location']['latitude'])
        self.assertIsNone(result['location']['longitude'])
        self.assertEqual(result['time_mode'], 'afternoon')
        self.assertEqual(result['viewport_height'], 720)
        passed = renderer.call_args.kwargs
        self.assertEqual(passed['data']['location'], self.fix())
        self.assertTrue(all(callable(passed[name]) for name in ('on_location_change', 'on_time_mode_change', 'on_viewport_height_change')))

    def test_wrapper_defaults_and_rejects_invalid_control_state(self):
        renderer = Mock(return_value={'time_mode': 'unexpected', 'location': 'not-a-location', 'viewport_height': True})
        with patch.object(browser_location.st, 'session_state', {}), patch.object(browser_location, '_component_renderer', return_value=renderer):
            self.assertEqual(location_controls(), {'location': None, 'time_mode': 'current', 'viewport_height': 800})
        self.assertEqual(renderer.call_args.kwargs['default'], {'location': None, 'time_mode': 'current', 'viewport_height': 800})

    @unittest.skipUnless(shutil.which('node'), 'Node executable is unavailable; the JS harness can run through the provided Node REPL.')
    def test_component_with_mock_navigator_and_dom(self):
        source = ROOT/'components/location_controls.js'
        prelude = "const { renderLocationControls: renderComponent } = await import((await import('node:url')).pathToFileURL(process.argv[1]).href);\n"
        script = prelude + '(async () => {\n' + JS_TEST_HARNESS + '\n})().then(result => { if (!result.passed) process.exitCode = 1; });'
        result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script, str(source)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

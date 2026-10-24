/**
 * Execute map_html('dummy-key', ...) inline JavaScript with SDK/DOM doubles.
 * This checks our initialization/control flow, not real TMAP SDK compatibility.
 *
 * Fixtures (offline, no .env or device location):
 *   test_tmap_view.runtime_html_fixtures() returns the stdin payload.
 *   test_tmap_view.write_runtime_fixtures() writes local debugging HTML files.
 * CLI:
 *   node test_tmap_runtime.js [afternoon.html noon.html]
 *   node test_tmap_runtime.js --stdin < fixtures.json
 * stdin JSON: {"afternoonHtml":"...", "noonHtml":"..."}
 * Node REPL:
 *   const suite = await import('file:///.../test_tmap_runtime.js');
 *   await suite.runFromFiles();
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';


class ElementDouble {
  constructor(id, attributes = '') {
    this.id = id;
    this.disabled = /\bdisabled\b/.test(attributes);
    this.checked = /\bchecked\b/.test(attributes);
    this.onclick = null;
    this.onchange = null;
    this.listeners = new Map();
    this._text = '';
    this._html = '';
  }
  set textContent(value) { this._text = String(value); this._html = String(value); }
  get textContent() { return this._text; }
  set innerHTML(value) { this._html = String(value); this._text = String(value).replace(/<[^>]*>/g, ''); }
  get innerHTML() { return this._html; }
  addEventListener(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(callback);
  }
  click() { if (!this.disabled && this.onclick) this.onclick({ target: this }); }
  change(checked) { this.checked = checked; this.onchange?.({ target: this }); }
}


function inlineScripts(html) {
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
    .map(match => ({ attributes: match[1], source: match[2] }));
  const external = scripts.filter(item => /\bsrc\s*=/.test(item.attributes));
  assert.equal(external.length, 1, 'Exactly one parser-inserted SDK loader is expected');
  const sdkSource = external[0].attributes.match(/\bsrc\s*=\s*["']([^"']+)["']/)?.[1];
  const sdkUrl = new URL((sdkSource || '').replace(/&amp;/g, '&'));
  // Never run this harness with an HTML page containing a user's real key.
  assert.equal(sdkUrl.searchParams.get('appKey'), 'dummy-key', 'Fixtures must use dummy-key');
  return scripts.filter(item => !/\bsrc\s*=/.test(item.attributes)).map(item => item.source);
}


function createSdk(records) {
  class LatLng {
    constructor(latitude, longitude) {
      assert(Number.isFinite(latitude) && Math.abs(latitude) <= 90, 'Latitude must be finite');
      assert(Number.isFinite(longitude) && Math.abs(longitude) <= 180, 'Longitude must be finite');
      this.latitude = latitude;
      this.longitude = longitude;
    }
    lat() { return this.latitude; }
    lng() { return this.longitude; }
  }
  class LatLngBounds {
    constructor(...points) { this.points = [...points]; }
    extend(point) { assert(point instanceof LatLng); this.points.push(point); return this; }
  }
  class MapDouble {
    constructor(id, options) {
      assert.equal(id, 'map');
      assert(options.center instanceof LatLng);
      this.options = options;
      this.fitCalls = [];
      this.centerCalls = [];
      this.zoomCalls = [];
      this.listeners = new Map();
      records.maps.push(this);
    }
    fitBounds(bounds) { assert(bounds instanceof LatLngBounds); this.fitCalls.push(bounds); }
    setCenter(point) { assert(point instanceof LatLng); this.centerCalls.push(point); }
    setZoom(zoom) { assert(Number.isFinite(zoom)); this.zoomCalls.push(zoom); }
    addListener(name, callback) { this.listeners.set(name, callback); }
  }
  const isPath = path => Array.isArray(path) && path.length >= 2 && path.every(point => point instanceof LatLng);
  class OverlayDouble {
    constructor(kind, options) {
      assert(options.map instanceof MapDouble, `${kind} requires a map`);
      this.kind = kind;
      this.options = options;
      this.currentMap = options.map;
      this.mapHistory = [options.map];
      records[kind].push(this);
    }
    setMap(map) {
      assert(map === null || map instanceof MapDouble);
      this.currentMap = map;
      this.mapHistory.push(map);
    }
  }
  class Polygon extends OverlayDouble {
    constructor(options) {
      const paths = options.paths;
      assert(isPath(paths) || (Array.isArray(paths) && paths.length > 0 && paths.every(isPath)), 'Polygon requires a valid path or rings');
      super('polygons', options);
    }
  }
  class Polyline extends OverlayDouble {
    constructor(options) { assert(isPath(options.path), 'Polyline requires a valid path'); super('polylines', options); }
  }
  class Marker extends OverlayDouble {
    constructor(options) { assert(options.position instanceof LatLng); super('markers', options); }
  }
  class Circle extends OverlayDouble {
    constructor(options) {
      assert(options.center instanceof LatLng);
      assert(Number.isFinite(options.radius) && options.radius > 0);
      super('circles', options);
    }
  }
  class GroundOverlay extends OverlayDouble {
    constructor(options) {
      assert.equal(typeof options.url, 'string');
      assert(options.bounds instanceof LatLngBounds);
      super('groundOverlays', options);
    }
  }
  return { Map: MapDouble, LatLng, LatLngBounds, Polygon, Polyline, Marker, Circle, GroundOverlay };
}


export function executeMapHtml(html) {
  assert.equal(typeof html, 'string');
  const scripts = inlineScripts(html);
  const elements = new Map();
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/gi)) {
    elements.set(match[3], new ElementDouble(match[3], match[2]));
  }
  const records = { maps: [], polygons: [], polylines: [], markers: [], circles: [], groundOverlays: [] };
  const timers = new Map(); let nextTimer = 1;
  const sdk = createSdk(records);
  const sandbox = {
    window: { Tmapv2: sdk }, Tmapv2: sdk,
    document: {
      getElementById: id => {
        assert(elements.has(id), `Expected DOM element ${id}`);
        return elements.get(id);
      },
      createElement: () => new ElementDouble('dynamic'),
    },
    setTimeout: callback => { const id = nextTimer++; timers.set(id, callback); return id; },
    clearTimeout: id => timers.delete(id),
  };
  const context = vm.createContext(sandbox);
  for (const script of scripts) vm.runInContext(script, context, { timeout: 3000, filename: 'dummy-tmap-inline.js' });
  const payload = JSON.parse(vm.runInContext('JSON.stringify(data)', context));
  return { context, payload, records, elements, timers,
    evaluate: code => vm.runInContext(code, context, { timeout: 3000 }) };
}


function assertReady(runtime) {
  assert.equal(runtime.evaluate('loaded'), true, 'initialize() must complete');
  assert.equal(runtime.elements.get('map-controls').disabled, false, 'Map controls must be enabled');
  assert.equal(runtime.elements.get('status').textContent, '', 'Loading/failure banner must clear after initialization');
  assert.equal(runtime.timers.size, 0, 'Initialization timeout must be cleared');
  assert.equal(runtime.records.maps.length, 1);
}


function assertToggle(runtime, id, overlays) {
  assert.equal(typeof runtime.elements.get(id).onchange, 'function', `${id} must have a handler`);
  const map = runtime.records.maps[0];
  runtime.elements.get(id).change(false);
  assert(overlays.every(item => item.currentMap === null), `${id} must hide all grouped overlays`);
  runtime.elements.get(id).change(true);
  assert(overlays.every(item => item.currentMap === map), `${id} must restore all grouped overlays`);
}


function payloadVariant(html, update) {
  const original = executeMapHtml(html);
  const payload = original.payload;
  update(payload);
  const json = JSON.stringify(payload).replace(/[<>&]/g, char =>
    ({ '<': '\\u003c', '>': '\\u003e', '&': '\\u0026' })[char]);
  const prefix = html.indexOf('const data=');
  const endMatch = /;\r?\nconst status=/.exec(html.slice(prefix));
  const end = prefix + (endMatch?.index ?? -1);
  assert(prefix >= 0 && endMatch && end > prefix, 'Locate the trusted inline payload for input variants');
  return executeMapHtml(html.slice(0, prefix) + 'const data=' + json + html.slice(end));
}


function guidanceOverlays(runtime) {
  const targetTitle = guidanceTargetTitle(runtime.payload.guidance);
  return [
    ...runtime.records.polylines.filter(item =>
      ['#ffffff', '#166534', '#f59e0b'].includes(item.options.strokeColor) &&
      [11, 7, 5].includes(item.options.strokeWeight)),
    ...runtime.records.markers.filter(item => [targetTitle, '시연 시작점'].includes(item.options.title)),
    ...runtime.records.polygons.filter(item => item.options.strokeColor === '#2563eb' && item.options.fillOpacity === .08),
  ];
}


function guidanceTargetTitle(guide) {
  const label = typeof guide?.target_label === 'string' ? guide.target_label.trim() : '';
  const name = typeof guide?.destination_name === 'string' ? guide.destination_name.trim() : '';
  return label || (name ? '도착: ' + name : '가까운 그늘');
}


function assertGuidance(runtime) {
  const guide = runtime.payload.guidance;
  assert(guide && guide.route?.features.length > 0, 'Actual demo guidance must contain a route');
  assert(guide.shaded_route?.features.length > 0, 'The route must include its shaded portion');
  assert(guide.sunny_route?.features.length > 0, 'The route must expose its sunny portion');
  assert(guide.distance_m > 0 && guide.sunny_distance_m >= 0);
  if (!guide.is_demo && guide.destination_name) {
    const routeStart = guide.route.features[0].geometry.coordinates[0];
    assert(Math.abs(routeStart[0] - guide.origin.longitude) < 1e-9, 'Destination route must start at the supplied current longitude');
    assert(Math.abs(routeStart[1] - guide.origin.latitude) < 1e-9, 'Destination route must start at the supplied current latitude');
  }
  const lines = runtime.records.polylines;
  for (const [color, width, opacity] of [['#ffffff', 11, .9], ['#166534', 7, .95], ['#f59e0b', 5, .95]]) {
    assert(lines.some(item => item.options.strokeColor === color && item.options.strokeWeight === width && item.options.strokeOpacity === opacity),
      `Route layer ${color} must use the declared visible style`);
  }
  const target = runtime.records.markers.find(item => item.options.title === guidanceTargetTitle(guide));
  assert(target, 'The destination shade marker must render');
  assert(target.options.iconHTML.includes('🏁'), 'Guidance destination must have the fixed finish flag');
  assert.equal(guide.target.geometry.type, 'Point');
  assert.equal(target.options.position.lng(), guide.target.geometry.coordinates[0]);
  assert.equal(target.options.position.lat(), guide.target.geometry.coordinates[1]);
  if (guide.is_demo) {
    assert.equal(runtime.payload.userLocation, null, 'Demo origin must not masquerade as a device location');
    const origin = runtime.records.markers.find(item => item.options.title === '시연 시작점');
    assert(origin, 'Demo origin must be labelled as a demonstration start');
    assert.equal(origin.options.position.lat(), guide.origin.latitude);
    assert.equal(origin.options.position.lng(), guide.origin.longitude);
    assert.equal(runtime.records.maps[0].centerCalls.at(-1).lat(), guide.origin.latitude);
    assert.equal(runtime.records.maps[0].centerCalls.at(-1).lng(), guide.origin.longitude);
    assert(!runtime.records.markers.some(item => (item.options.title || '').startsWith('현재 위치')),
      'Demo marker titles must not claim the current device location');
    assert.equal(runtime.elements.get('my-location').disabled, true);
  } else if (runtime.payload.userLocation) {
    assert.equal(runtime.elements.get('my-location').disabled, false);
    assert(!runtime.records.markers.some(item => item.options.title === '시연 시작점'));
    assert(runtime.records.markers.some(item => (item.options.title || '').startsWith('현재 위치')));
  }
  if (guide.destination_geometry) {
    assert(runtime.records.polygons.some(item => item.options.fillColor === '#2563eb' &&
      item.options.strokeColor === '#2563eb' && item.options.fillOpacity === .08),
      'Selected destination footprint must have the declared blue highlight');
  }
  assertToggle(runtime, 'show-walkways', guidanceOverlays(runtime));
}


export function runGuidanceVariants(html) {
  const empty = { type: 'FeatureCollection', features: [] };
  const sunnyOnly = payloadVariant(html, payload => {
    payload.guidance.sunny_route = payload.guidance.route;
    payload.guidance.shaded_route = empty;
    payload.guidance.sunny_distance_m = payload.guidance.distance_m;
  });
  assertReady(sunnyOnly);
  assert(sunnyOnly.records.polylines.some(item => item.options.strokeColor === '#f59e0b'));
  assert(!sunnyOnly.records.polylines.some(item => item.options.strokeColor === '#166534'));
  assertToggle(sunnyOnly, 'show-walkways', guidanceOverlays(sunnyOnly));

  const shadedOnly = payloadVariant(html, payload => {
    payload.guidance.shaded_route = payload.guidance.route;
    payload.guidance.sunny_route = empty;
    payload.guidance.sunny_distance_m = 0;
  });
  assertReady(shadedOnly);
  assert(shadedOnly.records.polylines.some(item => item.options.strokeColor === '#166534'));
  assert(!shadedOnly.records.polylines.some(item => item.options.strokeColor === '#f59e0b'));

  const noRoute = payloadVariant(html, payload => {
    payload.guidance = { ...payload.guidance, status: 'unavailable', route: empty,
      shaded_route: empty, sunny_route: empty, target: null, target_area: null,
      distance_m: 0, sunny_distance_m: 0 };
  });
  assertReady(noRoute);
  assert(!noRoute.records.polylines.some(item => ['#ffffff', '#166534', '#f59e0b'].includes(item.options.strokeColor)));
  assert(!noRoute.records.markers.some(item => item.options.title === guidanceTargetTitle(noRoute.payload.guidance)));
  assertToggle(noRoute, 'show-walkways', guidanceOverlays(noRoute));

  const realLocation = payloadVariant(html, payload => {
    payload.userLocation = { ...payload.guidance.origin, accuracy: 20 };
    payload.guidance.is_demo = false;
  });
  assertReady(realLocation);
  assert(!realLocation.records.markers.some(item => item.options.title === '시연 시작점'));
  const deviceMarker = realLocation.records.markers.find(item => (item.options.title || '').startsWith('현재 위치'));
  assert(deviceMarker, 'Accepted device-location mode must render its location marker');
  const map = realLocation.records.maps[0];
  const centers = map.centerCalls.length;
  assert.equal(realLocation.elements.get('my-location').disabled, false);
  realLocation.elements.get('my-location').click();
  assert.equal(map.centerCalls.length, centers + 1);
  assert.equal(map.zoomCalls.at(-1), 17);
  assert.equal(map.centerCalls.at(-1).lat(), realLocation.payload.userLocation.latitude);
  assert.equal(map.centerCalls.at(-1).lng(), realLocation.payload.userLocation.longitude);
  realLocation.elements.get('show-walkways').change(false);
  assert.equal(deviceMarker.currentMap, map, 'Hiding guidance must not hide the accepted device location');
  assertToggle(realLocation, 'show-walkways', guidanceOverlays(realLocation));
  assert.equal(deviceMarker.currentMap, map, 'Hiding guidance must not hide the accepted device location');

  const legacyDemo = payloadVariant(html, payload => {
    payload.userLocation = null;
    payload.guidance.is_demo = true;
  });
  assertReady(legacyDemo);
  assert(legacyDemo.records.markers.some(item => item.options.title === '시연 시작점'));
  assert(!legacyDemo.records.markers.some(item => (item.options.title || '').startsWith('현재 위치')));
  assertToggle(legacyDemo, 'show-walkways', guidanceOverlays(legacyDemo));
  return { sunnyOnly: true, shadedOnly: true, emptyRoute: true, demoAndDeviceLocationSeparated: true };
}


export function runDestinationVariants(html) {
  const named = payloadVariant(html, payload => {
    payload.guidance.destination_name = '샘플 도서관';
    delete payload.guidance.target_label;
    payload.guidance.destination_geometry = { type: 'Feature',
      geometry: payload.buildings[0].geometry, properties: {} };
  });
  assertReady(named);
  assert(named.records.markers.some(item => item.options.title === '도착: 샘플 도서관'));
  const highlighted = named.records.polygons.filter(item => item.options.strokeColor === '#2563eb' && item.options.fillOpacity === .08);
  assert(highlighted.length > 0, 'Feature-wrapped destination geometry must render');
  assertToggle(named, 'show-walkways', guidanceOverlays(named));

  const unsafeLabel = '도착: 도서관</script><img src=x onerror=alert(1)>';
  const labelled = payloadVariant(html, payload => {
    payload.guidance.destination_name = '다른 건물';
    payload.guidance.target_label = unsafeLabel;
  });
  assertReady(labelled);
  const marker = labelled.records.markers.find(item => item.options.title === unsafeLabel);
  assert(marker, 'The target label must remain a marker text property');
  assert(!marker.options.iconHTML.includes(unsafeLabel));
  assert(!marker.options.iconHTML.includes('<img'));
  assert(!marker.options.iconHTML.includes('onerror'));
  assert(marker.options.iconHTML.includes('🏁'));

  const noGuidance = payloadVariant(html, payload => { payload.guidance = null; });
  assertReady(noGuidance);
  assert(!noGuidance.records.markers.some(item => item.options.iconHTML?.includes('🏁')));
  assert(!noGuidance.records.polygons.some(item => item.options.strokeColor === '#2563eb' && item.options.fillOpacity === .08));
  return { destinationTitle: true, destinationOutlineToggle: true, labelOutsideIconHtml: true, optionalGuidance: true };
}


export function runTmapRuntimeTests({ afternoonHtml, noonHtml }) {
  const afternoon = executeMapHtml(afternoonHtml);
  assertReady(afternoon);
  assert.equal(afternoon.payload.buildings.length, 74, 'Use the actual resolved campus scene');
  const guided = !!afternoon.payload.guidance;
  if (guided) {
    assert.equal(afternoon.payload.shadedWalkways.features.length, 0, 'The public guidance view must not add the old walkway filter');
    assert.equal(afternoon.payload.nearbyWalkways.features.length, 0);
    assertGuidance(afternoon);
  } else {
    assert(afternoon.payload.shadedWalkways.features.length > 0, 'Legacy fixture must contain real shaded walkways');
    assert(afternoon.payload.nearbyWalkways.features.length > 0, 'Legacy fixture must contain nearby walkway highlights');
    assert(afternoon.payload.userLocation, 'Legacy fixture needs a synthetic public campus position');
  }

  const border = afternoon.records.polylines.filter(item => item.options.strokeColor === '#94a3b8');
  assert(border.length > 0, 'Campus border must draw without a group argument');
  const beforeDirectBoundary = afternoon.records.polylines.length;
  afternoon.context.__mapForTest = afternoon.records.maps[0];
  afternoon.evaluate("drawLineGeometry(data.campusBorder,{strokeColor:'#94a3b8'},__mapForTest)");
  assert(afternoon.records.polylines.length > beforeDirectBoundary, 'Explicit no-group boundary call must also succeed');

  const buildingColors = new Set(afternoon.payload.buildings.map(item => item.color));
  const buildings = afternoon.records.polygons.filter(item => buildingColors.has(item.options.fillColor));
  const shadows = afternoon.records.polygons.filter(item => item.options.fillColor === '#4ade80');
  const walkways = afternoon.records.polylines.filter(item => ['#166534', '#fde047', '#15803d'].includes(item.options.strokeColor));
  assert(buildings.length >= 74, 'Resolved building polygons must be rendered');
  assert(shadows.length > 0, 'Actual afternoon shadow polygons must be rendered');
  assert(shadows.every(item => item.options.strokeWeight === 0 && item.options.strokeOpacity === 0), 'Shadow polygon borders must be disabled');
  if (!guided) {
    assert(walkways.some(item => item.options.strokeColor === '#166534'), 'Green shaded walkway lines must render');
    assert(walkways.some(item => item.options.strokeColor === '#fde047'), 'Nearby walkway yellow outline must render');
    assert(walkways.some(item => item.options.strokeColor === '#15803d'), 'Nearby walkway green center must render');
  }
  assertToggle(afternoon, 'show-buildings', buildings);
  assertToggle(afternoon, 'show-shadows', shadows);
  assertToggle(afternoon, 'show-walkways', guided ? guidanceOverlays(afternoon) : walkways);

  const map = afternoon.records.maps[0];
  const fits = map.fitCalls.length;
  const initialBounds = map.fitCalls[0];
  afternoon.elements.get('home').click();
  assert.equal(map.fitCalls.length, fits + 1, 'Home button must refit campus bounds');
  assert.equal(map.fitCalls.at(-1), initialBounds);
  if (!guided) {
    const centers = map.centerCalls.length;
    assert.equal(afternoon.elements.get('my-location').disabled, false);
    afternoon.elements.get('my-location').click();
    assert.equal(map.centerCalls.length, centers + 1, 'My location button must focus the accepted fixture location');
    assert.equal(map.zoomCalls.at(-1), 17);
    assert.equal(map.centerCalls.at(-1).lat(), afternoon.payload.userLocation.latitude);
    assert.equal(map.centerCalls.at(-1).lng(), afternoon.payload.userLocation.longitude);
  }

  const noon = executeMapHtml(noonHtml);
  assertReady(noon);
  assert.equal(noon.payload.buildings.length, 74);
  assert.equal(noon.payload.shadedWalkways.features.length, 0, 'Noon fixture must cover an empty walkway result');
  assert.equal(noon.payload.nearbyWalkways.features.length, 0);
  assert.equal(noon.elements.get('my-location').disabled, !noon.payload.userLocation);
  if (!noon.payload.userLocation) assert.equal(noon.elements.get('my-location').onclick, null);
  assertToggle(noon, 'show-walkways', noon.payload.guidance ? guidanceOverlays(noon) : []);
  const guidanceVariants = guided ? runGuidanceVariants(afternoonHtml) : null;
  const destinationVariants = guided ? runDestinationVariants(afternoonHtml) : null;

  // Reintroduce the original bug. The ungrouped campus border must fail before
  // any building/shadow polygon is drawn and leave the controls disabled.
  const originalBug = afternoonHtml.replace(/if\s*\(\s*group\s*\)\s*group\.push\(path\);/, 'group.push(path);');
  assert.notEqual(originalBug, afternoonHtml, 'Locate the drawLineGeometry group guard before mutation');
  const broken = executeMapHtml(originalBug);
  assert.throws(() => assertReady(broken), /initialize\(\) must complete/);
  assert.equal(broken.evaluate('loaded'), false);
  assert.equal(broken.elements.get('map-controls').disabled, true);
  assert.equal(broken.records.polygons.length, 0, 'Legacy failure must occur before polygons render');
  assert.equal(broken.records.polylines.length, 1, 'Legacy failure must occur on the first ungrouped border dash');
  assert(broken.elements.get('status').innerHTML.includes('/?map=osm'), 'Legacy failure must expose the fallback link');
  assert(broken.elements.get('status').textContent.includes('그늘 표시를 불러오지 못했어요.'), 'Map-ready failure must identify the overlay initialization');

  return { passed: true, afternoon: { buildings: afternoon.payload.buildings.length,
    polygons: afternoon.records.polygons.length, shadedWalkways: afternoon.payload.shadedWalkways.features.length,
    nearbyWalkways: afternoon.payload.nearbyWalkways.features.length, borderDashes: border.length },
    guidance: guided ? { status: afternoon.payload.guidance.status, isDemo: afternoon.payload.guidance.is_demo,
      destination: afternoon.payload.guidance.destination_name || null,
      distance_m: afternoon.payload.guidance.distance_m,
      routeFeatures: afternoon.payload.guidance.route.features.length,
      shadedRouteFeatures: afternoon.payload.guidance.shaded_route.features.length,
      sunnyRouteFeatures: afternoon.payload.guidance.sunny_route.features.length } : null,
    noonEmptyWalkways: true, guidanceVariants, destinationVariants, controlsAndToggles: true, originalBugMutationDetected: true,
    limitation: 'SDK and DOM are mocked; this does not prove live TMAP SDK or key compatibility.' };
}


export async function runFromFiles(afternoonPath = new URL('.test_tmp/tmap_runtime_afternoon.html', import.meta.url),
                                   noonPath = new URL('.test_tmp/tmap_runtime_noon.html', import.meta.url)) {
  const [afternoonHtml, noonHtml] = await Promise.all([readFile(afternoonPath, 'utf8'), readFile(noonPath, 'utf8')]);
  return runTmapRuntimeTests({ afternoonHtml, noonHtml });
}


const direct = typeof process !== 'undefined' && process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url;
if (direct) {
  try {
    const args = process.argv.slice(2);
    let result;
    if (args[0] === '--stdin') {
      let input = '';
      for await (const chunk of process.stdin) {
        input += chunk;
        if (input.length > 2000000) throw new Error('Fixture input is unexpectedly large');
      }
      result = runTmapRuntimeTests(JSON.parse(input));
    } else if (args.length === 0) result = await runFromFiles();
    else if (args.length === 2) result = await runFromFiles(args[0], args[1]);
    else throw new Error('Usage: node test_tmap_runtime.js [afternoon.html noon.html] or --stdin');
    console.log(JSON.stringify(result));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

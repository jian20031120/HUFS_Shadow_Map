export default function locationControls(component) {
  return renderLocationControls(component, { navigator, window, now: () => Date.now() });
}

// Explicit browser dependencies allow permission-flow tests without requesting
// a real user's location or mounting a browser page.
export function renderLocationControls(component, { navigator, window, now }) {
  const { data = {}, setStateValue, parentElement } = component;
  const root = parentElement.querySelector('[data-location-controls]');
  if (!root) return () => {};
  const locate = root.querySelector('[data-locate]');
  const locateLabel = root.querySelector('[data-locate-label]');
  const clear = root.querySelector('[data-clear-location]');
  const timeSelect = root.querySelector('[data-time-mode]');
  const status = root.querySelector('[data-location-status]');
  const modes = new Set(['current', 'morning', 'noon', 'afternoon']);
  let disposed = false;
  let requestToken = 0;
  let pending = false;
  let location = data.location || null;
  let viewportFrame = null;
  let lastViewport = Number.isFinite(data.viewport_height) ? data.viewport_height : null;

  const message = (text, kind = '') => {
    status.textContent = text;
    status.hidden = !text;
    status.dataset.kind = kind;
  };
  const updateButtons = () => {
    locate.disabled = pending;
    locateLabel.textContent = pending ? '위치 확인 중…' : location?.status === 'success' ? '위치 갱신' : '내 위치로 찾기';
    clear.disabled = !pending && (!location || location.status === 'cleared');
  };
  const event = (state, text = '') => ({
    status: state, latitude: null, longitude: null, accuracy: null,
    timestamp: now(), ...(text ? { message: text } : {})
  });
  const publishLocation = (value) => {
    location = value;
    pending = false;
    updateButtons();
    setStateValue('location', value);
  };
  timeSelect.value = modes.has(data.time_mode) ? data.time_mode : 'current';
  if (location?.status === 'success') message('현재 위치를 확인했어요.');
  else if (location?.status === 'denied') message('위치 사용을 허용하지 않았어요.', 'denied');
  else if (location?.status === 'error') message(location.message || '위치를 확인하지 못했어요. 다시 눌러 주세요.', 'error');
  else message('');
  updateButtons();

  const onLocate = () => {
    if (disposed || pending) return;
    const token = ++requestToken;
    if (!navigator.geolocation) {
      const text = '이 브라우저에서는 위치 확인을 사용할 수 없어요.';
      message(text, 'error');
      publishLocation(event('error', text));
      return;
    }
    pending = true;
    updateButtons();
    message('브라우저에서 위치 사용을 허용해 주세요.');
    const success = (position) => {
      if (disposed || token !== requestToken) return;
      const coords = position.coords || {};
      const values = [coords.latitude, coords.longitude, coords.accuracy, position.timestamp];
      if (!values.every(value => typeof value === 'number' && Number.isFinite(value)) ||
          Math.abs(coords.latitude) > 90 || Math.abs(coords.longitude) > 180 ||
          coords.accuracy < 0 || coords.accuracy > 100000) {
        const text = '위치를 정확히 확인하지 못했어요. 다시 눌러 주세요.';
        message(text, 'error');
        publishLocation(event('error', text));
        return;
      }
      message('현재 위치를 확인했어요.');
      publishLocation({ status: 'success', latitude: coords.latitude, longitude: coords.longitude,
        accuracy: coords.accuracy, timestamp: position.timestamp });
    };
    const failure = (error) => {
      if (disposed || token !== requestToken) return;
      const denied = error?.code === 1;
      const text = denied ? '위치 사용을 허용하지 않았어요.' : error?.code === 3 ?
        '위치 확인 시간이 초과됐어요. 다시 눌러 주세요.' : '위치를 확인하지 못했어요. 다시 눌러 주세요.';
      message(text, denied ? 'denied' : 'error');
      publishLocation(event(denied ? 'denied' : 'error', text));
    };
    try {
      navigator.geolocation.getCurrentPosition(success, failure,
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 15000 });
    } catch (_) {
      failure({ code: 2 });
    }
  };
  const onClear = () => {
    if (disposed) return;
    ++requestToken;
    message('');
    publishLocation(event('cleared'));
  };
  const onTime = () => {
    if (!disposed && modes.has(timeSelect.value)) setStateValue('time_mode', timeSelect.value);
  };
  const publishViewport = () => {
    viewportFrame = null;
    if (disposed) return;
    const rawHeight = window.visualViewport?.height || window.innerHeight || 800;
    const height = Math.min(2400, Math.max(240, Math.round(rawHeight)));
    if (height !== lastViewport) {
      lastViewport = height;
      setStateValue('viewport_height', height);
    }
  };
  const scheduleViewport = () => {
    if (!disposed && viewportFrame === null) viewportFrame = window.requestAnimationFrame(publishViewport);
  };
  locate.addEventListener('click', onLocate);
  clear.addEventListener('click', onClear);
  timeSelect.addEventListener('change', onTime);
  window.addEventListener('resize', scheduleViewport);
  window.visualViewport?.addEventListener('resize', scheduleViewport);
  scheduleViewport();
  return () => {
    disposed = true;
    ++requestToken;
    locate.removeEventListener('click', onLocate);
    clear.removeEventListener('click', onClear);
    timeSelect.removeEventListener('change', onTime);
    window.removeEventListener('resize', scheduleViewport);
    window.visualViewport?.removeEventListener('resize', scheduleViewport);
    if (viewportFrame !== null) window.cancelAnimationFrame(viewportFrame);
  };
}

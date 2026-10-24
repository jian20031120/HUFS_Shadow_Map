"""Session-only browser location and compact map time controls.

The component requests browser permission only after its location button is
clicked. Coordinates are never written to disk, URLs, or application logs.
"""
from functools import lru_cache
import math
from numbers import Real
from pathlib import Path
import time

import streamlit as st


ROOT = Path(__file__).parent
TIME_MODES = ('current', 'morning', 'noon', 'afternoon')
LOCATION_STATUSES = ('success', 'denied', 'error', 'cleared')


def _finite_number(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def validate_location(value, now_ms=None, max_age_ms=300000):
    """Return a clean, recent successful fix, or None for untrusted values.

    Numbers must arrive as numbers, not strings or booleans. Browser fixes in
    the future, older than max_age_ms, or outside coordinate/accuracy ranges
    are rejected. This does not determine whether the fix is on campus.
    """
    if not isinstance(value, dict) or value.get('status') != 'success':
        return None
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    if not _finite_number(now_ms) or not _finite_number(max_age_ms) or max_age_ms < 0:
        return None
    latitude, longitude = value.get('latitude'), value.get('longitude')
    accuracy, timestamp = value.get('accuracy'), value.get('timestamp')
    if not all(_finite_number(v) for v in (latitude, longitude, accuracy, timestamp)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 0 <= accuracy <= 100000):
        return None
    if timestamp < 0 or timestamp > now_ms or now_ms - timestamp > max_age_ms:
        return None
    return {'status': 'success', 'latitude': float(latitude), 'longitude': float(longitude),
            'accuracy': float(accuracy), 'timestamp': float(timestamp)}


def _event_state(value):
    if not isinstance(value, dict) or value.get('status') not in LOCATION_STATUSES:
        return None
    # Only the component's defined fields enter the next mount's data.
    result = {key: value.get(key) for key in ('status', 'latitude', 'longitude', 'accuracy', 'timestamp')}
    if result['status'] != 'success':
        result.update(latitude=None, longitude=None, accuracy=None)
    if isinstance(value.get('message'), str):
        result['message'] = value['message'][:120]
    return result


def _viewport(value):
    if not _finite_number(value):
        return 800
    return min(2400, max(240, round(value)))


@lru_cache(maxsize=1)
def _component_renderer():
    assets = ROOT / 'components'
    return st.components.v2.component(
        'hufs_location_controls',
        html=(assets/'location_controls.html').read_text(encoding='utf-8'),
        css=(assets/'location_controls.css').read_text(encoding='utf-8'),
        js=(assets/'location_controls.js').read_text(encoding='utf-8'),
        isolate_styles=True,
    )


def location_controls(key='location_controls'):
    """Mount controls and return location, time_mode, viewport_height.

    Use validate_location(result['location']) before geofencing or drawing a
    location marker. Denied/error/cleared events remain available to callers.
    Streamlit component state is confined to the active browser session.
    """
    previous = st.session_state.get(key, {})
    previous = previous if isinstance(previous, dict) else {}
    mode = previous.get('time_mode', 'current')
    defaults = {'location': _event_state(previous.get('location')),
                'time_mode': mode if mode in TIME_MODES else 'current',
                'viewport_height': _viewport(previous.get('viewport_height', 800))}
    result = _component_renderer()(
        key=key, data=defaults, default=defaults,
        on_location_change=lambda: None,
        on_time_mode_change=lambda: None,
        on_viewport_height_change=lambda: None,
    )
    values = dict(result)
    mode = values.get('time_mode', defaults['time_mode'])
    return {'location': _event_state(values.get('location', defaults['location'])),
            'time_mode': mode if mode in TIME_MODES else 'current',
            'viewport_height': _viewport(values.get('viewport_height', defaults['viewport_height']))}

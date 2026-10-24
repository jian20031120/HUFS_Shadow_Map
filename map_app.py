"""Current-location to campus-building routing with shade-first costs."""
from pathlib import Path
import html
import os

from dotenv import dotenv_values
import folium
import streamlit as st
from streamlit_folium import st_folium
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from browser_location import location_controls, validate_location
from campus_access import campus_access
from campus_scene import load_campus_scene, scene_signature, sun_and_shade, display_moment
from destination_catalog import build_destination_catalog
from public_buildings import PublicDataError
from shade_guidance import build_shade_guidance, build_destination_guidance
from shadow_model import TO_M, TO_G
from tmap_view import render_tmap
from web_theme import apply_theme

ROOT = Path(__file__).parent


@st.cache_data(show_spinner=False, max_entries=2)
def _scene(signature):
    return load_campus_scene(ROOT)


@st.cache_data(show_spinner=False, max_entries=48)
def _shade(signature, moment):
    return sun_and_shade(_scene(signature), moment)


def _collection(features=()):
    return {'type': 'FeatureCollection', 'features': list(features)}


def _demo_origin(scene):
    """A fixed, explicitly labelled sample start; never a device location."""
    ground = transform(TO_M, scene['campus']).difference(unary_union([
        transform(TO_M, geometry) for geometry in scene['all_building_footprints']]).buffer(.1))
    point = transform(TO_G, ground.representative_point())
    return {'latitude': point.y, 'longitude': point.x}


def _guide(scene, shade, origin, is_demo=False):
    origin = {'latitude': origin['latitude'], 'longitude': origin['longitude']}
    result = build_shade_guidance(scene['campus'], scene['all_building_footprints'],
                                  shade['shadow_metric'], origin)
    return {**result, 'is_demo': is_demo, 'origin': origin}


def _destination_guide(scene, shade, origin, destination):
    """Device coordinates and their route never enter the shared caches."""
    origin = {'latitude': origin['latitude'], 'longitude': origin['longitude']}
    result = build_destination_guidance(scene['campus'], scene['all_building_footprints'],
                                       shade['shadow_metric'], origin, shape(destination['geometry']))
    return {**result, 'is_demo': False, 'origin': origin,
            'destination_id': destination['id'], 'destination_name': destination['name'],
            'target_label': '도착: '+destination['name'],
            'destination_geometry': destination['geometry']}


def _waiting_guidance(status, destination=None):
    result = {'status': status, 'is_demo': False, 'origin': None, 'target': None,
              'route': _collection(), 'shaded_route': _collection(), 'sunny_route': _collection(),
              'distance_m': 0, 'sunny_distance_m': 0, 'shaded_distance_m': 0}
    if destination:
        result.update(destination_id=destination['id'], destination_name=destination['name'],
                      destination_geometry=destination['geometry'], target_label='도착: '+destination['name'])
    return result


def _osm_map(scene, shade, user_location, guidance, height):
    campus = scene['campus']
    center = [campus.centroid.y, campus.centroid.x]
    if user_location:
        center = [user_location['latitude'], user_location['longitude']]
    elif guidance.get('is_demo'):
        center = [guidance['origin']['latitude'], guidance['origin']['longitude']]
    view = folium.Map(location=center, zoom_start=17 if user_location or guidance.get('is_demo') else 16,
                      tiles='OpenStreetMap', control_scale=True, max_zoom=20)
    if not user_location and not guidance.get('is_demo'):
        west, south, east, north = campus.bounds
        view.fit_bounds([[south, west], [north, east]])
    folium.GeoJson(mapping(campus), name='캠퍼스', control=False,
                   style_function=lambda _: {'color': '#94a3b8', 'weight': 1, 'fillOpacity': 0, 'dashArray': '5 5'}).add_to(view)
    folium.GeoJson(_collection(scene['features']), name='건물',
                   style_function=lambda _: {'color': '#64748b', 'weight': 1, 'fillOpacity': .10}).add_to(view)
    if not shape(shade['shadow']).is_empty:
        folium.GeoJson(shade['shadow'], name='예상 그늘',
                       style_function=lambda _: {'fillColor': '#83aa71', 'fillOpacity': .26, 'weight': 0}).add_to(view)
    guidance_layer = folium.FeatureGroup(name='그늘 안내선').add_to(view)
    if guidance.get('destination_geometry'):
        folium.GeoJson(guidance['destination_geometry'], name='도착 건물', control=False,
                       style_function=lambda _: {'color': '#2563eb', 'weight': 3, 'fillColor': '#2563eb',
                                                  'fillOpacity': .08}).add_to(guidance_layer)
    for collection, name, color, weight in (
            (guidance['route'], '안내선 테두리', '#ffffff', 11),
            (guidance['sunny_route'], '햇빛 구간', '#f59e0b', 5),
            (guidance['shaded_route'], '그늘 구간', '#166534', 7)):
        if collection['features']:
            folium.GeoJson(collection, name=name, control=False,
                           style_function=lambda _, color=color, weight=weight:
                               {'color': color, 'weight': weight, 'opacity': .95}).add_to(guidance_layer)
    if guidance.get('target'):
        longitude, latitude = guidance['target']['geometry']['coordinates']
        folium.Marker([latitude, longitude], tooltip=html.escape(guidance.get('target_label', '가까운 그늘')),
                      icon=folium.Icon(color='green', icon='flag')).add_to(guidance_layer)
    if guidance.get('is_demo'):
        origin = guidance['origin']
        folium.CircleMarker([origin['latitude'], origin['longitude']], radius=7, color='#2563eb',
                            weight=3, fill=True, fill_color='white', fill_opacity=1,
                            tooltip='시연 시작점').add_to(guidance_layer)
    if user_location:
        folium.Circle(center, radius=user_location['accuracy'], color='#2563eb', weight=1,
                      fill=True, fill_opacity=.08).add_to(view)
        folium.CircleMarker(center, radius=7, color='white', weight=2, fill=True,
                            fill_color='#2563eb', fill_opacity=1, tooltip='현재 위치').add_to(view)
    if guidance['route']['features']:
        route = unary_union([shape(feature['geometry']) for feature in guidance['route']['features']])
        west, south, east, north = route.bounds
        view.fit_bounds([[south-.00025, west-.0003], [north+.00025, east+.0003]])
    folium.LayerControl(collapsed=True).add_to(view)
    st_folium(view, height=height+60, use_container_width=True,
              returned_objects=[], key='public_campus_map')


def main():
    st.set_page_config(page_title='HUFS 그늘길', page_icon='🌿', layout='wide', initial_sidebar_state='collapsed')
    apply_theme(map_only=True)
    origin_column, destination_column = st.columns([1, 1.1], vertical_alignment='top')
    with origin_column:
        controls = location_controls()
    signature = scene_signature(ROOT)
    try:
        with st.spinner('캠퍼스 지도를 준비하고 있어요…'):
            scene = _scene(signature)
            moment = display_moment(controls['time_mode'])
            shade = _shade(signature, moment)
            destinations = build_destination_catalog(scene)
    except (PublicDataError, OSError, ValueError, KeyError):
        st.error('캠퍼스 지도를 준비하지 못했어요. 잠시 후 새로고침해 주세요.')
        return

    with destination_column:
        by_id = {item['id']: item for item in destinations}
        selected_id = st.selectbox('도착 · 학교 건물', options=list(by_id), index=None,
                                   format_func=lambda value: by_id[value]['label'],
                                   placeholder='건물 이름으로 검색해 주세요', key='destination_building')
    destination = by_id.get(selected_id)

    raw_location = controls['location']
    location = validate_location(raw_location)
    access = campus_access(scene['campus'], location)
    if destination and access['can_recommend']:
        with st.spinner('도착 건물까지 그늘을 우선하는 경로를 찾고 있어요…'):
            guidance = _destination_guide(scene, shade, location, destination)
    else:
        guidance = _waiting_guidance('choose_destination' if destination is None else 'waiting_location', destination)
    message = ''
    if isinstance(raw_location, dict) and raw_location.get('status') == 'success' and location is None:
        message = '위치 정보가 오래됐거나 불확실해요. 위치를 갱신해 주세요.'
    elif access['status'] not in ('inside', 'unavailable'):
        message = access['message']
    if destination is None:
        detail = '도착 건물을 검색해 선택해 주세요.'
    elif not access['can_recommend']:
        detail = '캠퍼스 안에서 내 위치를 허용하면 선택한 건물까지 안내해요.'
    elif guidance['status'] == 'ok':
        percent = 100*guidance['shaded_distance_m']/max(guidance['distance_m'], 1e-9)
        detail = f"{destination['name']}까지 {guidance['distance_m']:.0f}m · 예상 그늘 {percent:.0f}%"
        if shade['elevation'] < 3:
            detail += ' · 해가 낮거나 밤이라 낮 시간을 선택하면 그늘 경로가 달라져요.'
    elif guidance['status'] == 'arrived':
        detail = f"{destination['name']} 도착 지점에 있어요."
    else:
        detail = guidance.get('message') or '현재 위치에서 도착 건물까지 연결할 수 없어요.'
    message = (message + ' ' if message else '') + detail
    st.caption(f'{moment:%H:%M} · {message} | 녹색 면·선: 그늘 · 주황 선: 햇빛 구간 · 통행 미검증')

    # Device locations stay in this session, outside stored data and shared calculation caches.
    visible_location = location if access['can_recommend'] else None
    local_env = dotenv_values(ROOT/'.env', encoding='utf-8-sig', interpolate=False)
    app_key = (os.environ.get('TMAP_APP_KEY') or local_env.get('TMAP_APP_KEY') or '').strip()
    requested_map = st.query_params.get('map', '')
    viewport = controls.get('viewport_height', 800)
    height = min(1400, max(350, viewport-225))
    if app_key and requested_map != 'osm':
        center = [scene['campus'].centroid.y, scene['campus'].centroid.x]
        buildings = [{'geometry': feature['geometry'], 'color': '#64748b', 'showLabel': False,
                      'title': html.escape(feature['properties'].get('name') or '교내 건물')}
                     for feature in scene['features']]
        render_tmap(app_key, center, mapping(scene['campus']), buildings, shadow=shade['shadow'],
                    user_location=visible_location, guidance=guidance, map_height=height, allow_tree_edit=False)
    else:
        _osm_map(scene, shade, visible_location, guidance, height)


if __name__ == '__main__':
    main()

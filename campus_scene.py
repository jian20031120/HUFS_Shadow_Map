"""Offline campus model for the public map; device locations never enter this data."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pvlib
from shapely import make_valid
from shapely.geometry import shape, mapping, GeometryCollection
from shapely.ops import transform, unary_union

from building_matches import load_matching, apply_matching
from demo_scene import resolved_buildings
from gba_buildings import load_gba, match_gba, apply_gba, supplement_footprints
from gba_raster import load_height_raster, sample_all, apply_raster
from gis_buildings import load_snapshot
from gis_scene import build_scene, flat_shade
from shadow_model import TO_M, TO_G
from tree_model import load_trees, canopy_shadow
from walkway_model import load_walkways, shade_walkways

KST = ZoneInfo('Asia/Seoul')
EXPORT_MIN_PART_AREA_M2 = 1e-6
SCENE_FILES = ('campus_boundary.geojson', 'gis_buildings_cache.json', 'buildings.geojson',
               'gba_campus.geojson', 'gba_height_campus.npz', 'gba_height_campus_meta.json',
               'campus_walkways.geojson', 'manual_matches.csv', 'tree_canopies.geojson',
               'building_register/hufs_all_parcels_title.csv',
               'building_register/hufs_all_parcels_match_check.csv')


def scene_signature(root):
    root = Path(root)/'data'
    return (('scene_schema', 3, 0),) + tuple((name, (root/name).stat().st_mtime_ns, (root/name).stat().st_size)
                                           for name in SCENE_FILES if (root/name).exists())


def _polygon_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if geometry.geom_type in ('MultiPolygon', 'GeometryCollection'):
        return [polygon for part in geometry.geoms for polygon in _polygon_parts(part)]
    return []


def shadow_for_display(metric_geometry):
    """Export valid WGS84 faces, leaving the original metric model untouched.

    Sub-square-millimetre components are numerical fragments whose vertices
    can collapse during projection. The threshold is applied in metres, not
    angular degrees, and is not a minimum usable shade-area policy.
    """
    parts = [part for part in _polygon_parts(make_valid(metric_geometry))
             if part.area >= EXPORT_MIN_PART_AREA_M2]
    if not parts:
        return GeometryCollection()
    geographic = transform(TO_G, unary_union(parts))
    geographic = unary_union(_polygon_parts(make_valid(geographic)))
    if not geographic.is_valid:
        raise ValueError('The shadow display geometry could not be repaired')
    return geographic


def load_campus_scene(root):
    root = Path(root)
    folder = root/'data'
    campus = shape(json.loads((folder/'campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
    features = load_snapshot(folder/'gis_buildings_cache.json', campus)['normalized']['features']
    osm = json.loads((folder/'buildings.geojson').read_text(encoding='utf-8'))['features']
    features = features + supplement_footprints(features, osm, campus)
    gba = load_gba(folder/'gba_campus.geojson', campus)
    matches = match_gba(features, gba['features'])
    raster = load_height_raster(folder/'gba_height_campus.npz', folder/'gba_height_campus_meta.json', campus)
    samples = sample_all(features, raster)
    titles, automatic, manual = load_matching(root, features)
    features = apply_matching(features, titles, automatic, manual)
    features = apply_gba(features, matches, expanded=True)
    features = apply_raster(features, samples)
    buildings, records = build_scene(features, {}, 3.0, 15.0, include_unknown=False)
    active = resolved_buildings(buildings)
    active_features = [f for f, (_, height) in zip(features, buildings) if height is not None]
    return {'campus': campus, 'buildings': active, 'features': active_features,
            'all_building_features': features,
            'all_building_footprints': [shape(feature['geometry']) for feature in features],
            'records': records, 'excluded_count': len(buildings)-len(active),
            'trees': load_trees(folder/'tree_canopies.geojson', campus),
            'walkways': load_walkways(folder/'campus_walkways.geojson', campus)}


def sun_and_shade(scene, moment):
    if moment.tzinfo is None:
        raise ValueError('Timezone-aware time is required')
    campus = scene['campus']
    center = campus.centroid
    solar = pvlib.solarposition.get_solarposition(pd.DatetimeIndex([moment]), center.y, center.x).iloc[0]
    elevation, azimuth = float(solar.apparent_elevation), float(solar.azimuth)
    buildings = scene['buildings']
    building_shade = flat_shade(campus, buildings, elevation, azimuth)
    tree_shade = canopy_shadow(scene['trees'], campus, elevation, azimuth, buildings)
    combined = unary_union([building_shade, tree_shade])
    footprints = unary_union([transform(TO_M, geom) for geom, _ in buildings])
    paths = shade_walkways(scene['walkways'], combined, building_footprints=footprints)
    return {'elevation': elevation, 'azimuth': azimuth,
            'shadow_metric': combined,
            'shadow': mapping(shadow_for_display(combined)), 'shaded_walkways': paths,
            'tree_shadow': mapping(shadow_for_display(tree_shade)), 'shade_area_m2': combined.area}


def display_moment(time_mode, now=None):
    now = now or datetime.now(KST)
    now = now.astimezone(KST)
    hour = {'morning': 9, 'noon': 12, 'afternoon': 15}.get(time_mode)
    if hour is not None:
        return now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return now.replace(second=0, microsecond=0)

"""Searchable campus building names tied to existing footprint geometry.

OSM names are transferred only through polygon overlap. Names, parcel IDs,
registry PKs, and nearest-centroid distance never establish a spatial link.
Grouped wings keep the union of their actual polygons, including gaps/holes.
"""
import copy
import json
import re
import unicodedata
from collections import defaultdict

from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from .shadow_model import TO_M

from .paths import ROOT
MIN_FOOTPRINT_COVERAGE = .65
MIN_SOURCE_FRACTION = .05
MIN_GROUP_SOURCE_COVERAGE = .60
AMBIGUITY_MARGIN = .15
NAME_FIELDS = ('name', 'name:ko', 'official_name', 'short_name', 'alt_name', 'loc_name')
GENERIC_NAMES = {'이름미등록', '이름미등록건물', '미등록', '무명', '건물', '학교',
                 '한국외국어대학교', '한국외국어대학교용인캠퍼스', '한국외국어대학교글로벌캠퍼스'}


def _name(value):
    if not isinstance(value, str):
        return ''
    value = ' '.join(unicodedata.normalize('NFC', value).split())
    compact = value.replace(' ', '')
    if not value or len(value) > 100 or compact in GENERIC_NAMES or compact.startswith('이름미등록'):
        return ''
    if re.fullmatch(r'(?:\d+|(?:PK|GIS|OSM)[-_:]?\d{6,})', compact, flags=re.IGNORECASE):
        return ''
    if re.fullmatch(r'(?:[A-Za-z]|\d+|[가-하])동', compact):
        return ''  # An unqualified letter/number wing would identify the wrong dorm.
    return value


def _names(properties):
    names = []
    for key in NAME_FIELDS:
        for value in str(properties.get(key) or '').split(';'):
            name = _name(value)
            if name and name not in names:
                names.append(name)
    dong = _name(properties.get('dong_name'))
    if dong and dong not in names:
        names.append(dong)
    return names


def _polygon(feature):
    try:
        geometry = shape(feature['geometry'])
    except (KeyError, TypeError, ValueError):
        return None
    if geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty or not geometry.is_valid:
        return None
    return geometry


def _load_osm_features():
    return json.loads((ROOT/'data/buildings.geojson').read_text(encoding='utf-8'))['features']


def _unique_labels(items):
    by_name = defaultdict(list)
    for item in items:
        # The original spelling remains in name/aliases; this spelling searches naturally in Korean.
        base = re.sub(r'(?<=\d)\s+(?=기숙사)', '', item['name'])
        aliases = item['aliases'][:3]
        item['label'] = base + (' · ' + ' / '.join(aliases) if aliases else '')
        by_name[base].append(item)
    for label, group in by_name.items():
        if len(group) <= 1:
            continue
        centers = [transform(TO_M, shape(item['geometry'])).centroid for item in group]
        use_east_west = max(p.x for p in centers)-min(p.x for p in centers) >= max(p.y for p in centers)-min(p.y for p in centers)
        order = sorted(range(len(group)), key=lambda index: ((centers[index].x if use_east_west else centers[index].y), group[index]['id']))
        for rank, index in enumerate(order):
            if len(group) == 2:
                suffix = ('서쪽' if rank == 0 else '동쪽') if use_east_west else ('남쪽' if rank == 0 else '북쪽')
            else:
                suffix = f"{'서→동' if use_east_west else '남→북'} {rank+1}"
            group[index]['label'] += f' · {suffix}'


def build_destination_catalog(scene):
    """Return stable named destinations whose geometry is from this scene.

    Required scene input is ``all_building_features`` (preferred) or ``features``.
    IDs are source-based; labels never expose registry PKs or unnamed GIS IDs.
    ``footprint_ids`` records each original member even if union joins outlines.
    ``aliases`` contains only names present in spatially linked local features.
    """
    source_features = scene.get('all_building_features', scene.get('features', []))
    footprints = []
    for feature in source_features:
        geometry = _polygon(feature)
        identifier = str(feature.get('properties', {}).get('public_id') or feature.get('id') or '')
        if geometry is not None and identifier:
            footprints.append({'id': identifier, 'feature': feature, 'geometry': geometry,
                               'metric': transform(TO_M, geometry)})
    footprints.sort(key=lambda item: item['id'])
    named_osm = []
    for feature in _load_osm_features():
        geometry = _polygon(feature)
        names = _names(feature.get('properties', {}))
        identifier = str(feature.get('properties', {}).get('osm_id') or feature.get('id') or '')
        if geometry is not None and names and identifier:
            named_osm.append({'id': identifier, 'names': names, 'geometry': geometry,
                              'metric': transform(TO_M, geometry),
                              'source_url': feature['properties'].get('source_url', '')})
    named_osm.sort(key=lambda item: item['id'])

    assigned = defaultdict(list)
    for footprint in footprints:
        target = footprint['metric']
        candidates = []
        for source in named_osm:
            intersection = target.intersection(source['metric']).area
            if intersection <= 0:
                continue
            coverage = intersection/target.area
            source_fraction = intersection/source['metric'].area
            iou = intersection/(target.area+source['metric'].area-intersection)
            if coverage >= MIN_FOOTPRINT_COVERAGE and source_fraction >= MIN_SOURCE_FRACTION:
                candidates.append({'source': source, 'coverage': coverage,
                                   'source_fraction': source_fraction, 'iou': iou})
        candidates.sort(key=lambda item: (-item['iou'], -item['coverage'], item['source']['id']))
        if not candidates:
            continue
        best = candidates[0]
        if len(candidates) > 1:
            second = candidates[1]
            same_name = best['source']['names'][0] == second['source']['names'][0]
            if (not same_name and best['iou']-second['iou'] < AMBIGUITY_MARGIN
                    and best['coverage']-second['coverage'] < AMBIGUITY_MARGIN):
                continue
        assigned[best['source']['id']].append((footprint, best))

    items, used = [], set()
    for source in named_osm:
        members = assigned[source['id']]
        if not members:
            continue
        metric_union = unary_union([member['metric'] for member, _ in members])
        covered = metric_union.intersection(source['metric']).area/source['metric'].area
        if covered < MIN_GROUP_SOURCE_COVERAGE:
            continue
        geometry = unary_union([member['geometry'] for member, _ in members])
        aliases = []
        for candidate in source['names'] + [name for member, _ in members for name in _names(member['feature']['properties'])]:
            if candidate != source['names'][0] and candidate not in aliases:
                aliases.append(candidate)
        identifiers = sorted(member['id'] for member, _ in members)
        used.update(identifiers)
        items.append({'id': f"DEST-OSM-{source['id']}", 'name': source['names'][0],
                      'aliases': aliases, 'geometry': mapping(geometry), 'footprint_ids': identifiers,
                      'name_source': 'OSM polygon overlap', 'source_url': source['source_url'],
                      'source_coverage': min(1.0, covered),
                      'overlap_evidence': [{'footprint_id': member['id'], 'footprint_coverage': evidence['coverage'],
                                            'source_fraction': evidence['source_fraction'], 'iou': evidence['iou']}
                                           for member, evidence in members]})

    # Keep meaningful original GIS names when no OSM geometry established a name.
    for footprint in footprints:
        if footprint['id'] in used:
            continue
        properties = footprint['feature']['properties']
        # A campus-wide parent name plus a dong string is not enough to name
        # an unmatched small outline; the historical GIS contains such a case.
        if properties.get('name') and not _name(properties['name']):
            continue
        names = _names(properties)
        if not names:
            continue
        items.append({'id': f"DEST-GIS-{footprint['id']}", 'name': names[0],
                      'aliases': names[1:], 'geometry': copy.deepcopy(footprint['feature']['geometry']),
                      'footprint_ids': [footprint['id']], 'name_source': 'original footprint name',
                      'source_url': footprint['feature']['properties'].get('source_url', '')})
    _unique_labels(items)
    return sorted(items, key=lambda item: (item['label'], item['id']))

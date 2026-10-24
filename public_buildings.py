"""VWorld official LT_C_BLDGINFO adapter; OSM geometry is never replaced.
Schema: https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=bldginfo&apiVer=2
Only documented height/grnd_flr/bld_nm/dong_nm and GeoJSON geometry/id are used.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import re
import tempfile

import requests
from shapely.geometry import shape
from shapely.ops import transform
from shadow_model import TO_M

ENDPOINT = 'https://api.vworld.kr/req/data'
DOC_URL = 'https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=bldginfo&apiVer=2'
SOURCE = '국토교통부 · VWorld 건축물정보 (LT_C_BLDGINFO)'
SCHEMA_VERSION = 1
MATCH_RULE = {'iou_min': 0.60, 'each_coverage_min': 0.70,
              'centroid_distance_max_m': 20, 'runner_up_iou_margin': 0.20,
              'nearby_candidate_distance_m': 30}


class PublicDataError(ValueError):
    """Safe user-facing error: never include request URL or credential."""


def positive(value):
    if isinstance(value, bool):
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:m)?\s*', str(value))
    number = float(match.group(1)) if match else None
    return number if number is not None and math.isfinite(number) and 0 < number <= 300 else None


def floors(value):
    number = positive(value)
    return int(number) if number is not None and number.is_integer() and number <= 100 else None


def campus_id(campus):
    return hashlib.sha256(campus.wkb).hexdigest()


def save_json(path, obj):
    """Atomic write; this function must only receive credential-free data."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(prefix='.public-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def normalize(features, campus):
    result = []
    skipped = 0
    seen = set()
    for feature in features:
        try:
            geom = shape(feature['geometry'])
            props = feature['properties']
            if not isinstance(props, dict):
                raise ValueError()
            if not {'height', 'grnd_flr'}.intersection(props):
                raise PublicDataError('높이·층수 필드가 공식 명세와 다릅니다. 캐시를 갱신하지 않았습니다.')
            if geom.geom_type not in ('Polygon', 'MultiPolygon') or not geom.is_valid or geom.is_empty:
                raise ValueError()
            west, south, east, north = geom.bounds
            if not (124 < west <= east < 132 and 33 < south <= north < 39):
                raise PublicDataError('공공데이터 좌표계가 EPSG:4326인지 확인할 수 없습니다.')
            # Fetch intersects campus; keep only buildings whose interior point is in it.
            if not campus.covers(geom.representative_point()):
                continue
            public_id = str(feature.get('id') or '')
            # A source feature without an ID remains traceable by its content hash.
            if not public_id:
                public_id = 'content-sha256:' + hashlib.sha256(
                    json.dumps(feature, sort_keys=True).encode()).hexdigest()
            if public_id in seen:
                raise PublicDataError('공공데이터 식별자가 중복되었습니다. 불완전한 결과는 적용하지 않습니다.')
            seen.add(public_id)
            result.append({'type': 'Feature', 'id': public_id, 'geometry': feature['geometry'],
                           'properties': {'public_id': public_id, 'name': props.get('bld_nm') or '',
                                          'dong_name': props.get('dong_nm') or '',
                                          'height_m': positive(props.get('height')),
                                          'aboveground_floors': floors(props.get('grnd_flr')),
                                          'source': SOURCE, 'source_url': DOC_URL,
                                          'height_field': 'height', 'floors_field': 'grnd_flr'}})
        except PublicDataError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError):
            skipped += 1
    return result, skipped


def fetch_campus(key, domain, campus, cache_path, get=requests.get):
    if not key.strip() or not domain.strip():
        raise PublicDataError('브이월드 인증키와 발급 시 등록한 URL을 입력해 주세요.')
    if campus.is_empty or not campus.is_valid or transform(TO_M, campus).area > 10_000_000:
        raise PublicDataError('조회 범위가 캠퍼스 크기를 벗어났습니다.')
    params = {'service': 'data', 'version': '2.0', 'request': 'GetFeature',
              'data': 'LT_C_BLDGINFO', 'format': 'json', 'errorFormat': 'json',
              'geometry': 'true', 'attribute': 'true', 'crs': 'EPSG:4326',
              'geomFilter': campus.wkt, 'size': 1000}
    pages, features, expected_total = [], [], None
    for page in range(1, 11):
        try:
            response = get(ENDPOINT, params={**params, 'page': page, 'key': key.strip(),
                                            'domain': domain.strip()}, timeout=(10, 30))
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError):
            raise PublicDataError('공공데이터 서버 연결 또는 응답 오류입니다. 기존 캐시를 유지합니다.') from None
        try:
            data = body['response']
            status = data['status']
            if status == 'NOT_FOUND' and page == 1:
                pages.append(body)
                break
            if status != 'OK':
                # Do not echo server messages: they can contain the key or full URL.
                raise PublicDataError('브이월드 조회가 거부되었습니다. 키·등록 URL·이용 권한을 확인해 주세요.')
            total = int(data['record']['total'])
            page_total = int(data['page']['total'])
            if total < 0 or total > 10_000 or not 1 <= page_total <= 10:
                raise PublicDataError('조회 결과가 캠퍼스 조회 한도를 초과했습니다.')
            if expected_total is not None and expected_total != total:
                raise PublicDataError('조회 중 자료 건수가 변경되었습니다. 다시 조회해 주세요.')
            expected_total = total
            collection = data['result']['featureCollection']
            chunk = collection['features']
            if collection['type'] != 'FeatureCollection' or not isinstance(chunk, list):
                raise ValueError()
            if int(data['page']['current']) != page or not chunk:
                raise ValueError()
            pages.append(body)
            features.extend(chunk)
            if page == page_total:
                if len(features) != total:
                    raise PublicDataError('페이지별 자료가 누락되었습니다. 기존 캐시를 유지합니다.')
                break
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, PublicDataError):
                raise
            raise PublicDataError('API 응답 구조가 공식 명세와 다릅니다. 기존 캐시를 유지합니다.') from None
    else:
        raise PublicDataError('조회 페이지 한도를 초과했습니다.')
    # Responses are retained for provenance, with credentials redacted if echoed.
    pages = json.loads(json.dumps(pages, ensure_ascii=False).replace(key.strip(), '[REDACTED]'))
    normalized, skipped = normalize(features, campus)
    cache = {'schema_version': SCHEMA_VERSION, 'campus_id': campus_id(campus),
             'metadata': {'source': SOURCE, 'source_url': DOC_URL, 'endpoint': ENDPOINT,
                          'retrieved_at': datetime.now(timezone.utc).isoformat(),
                          'request_without_credentials': params,
                          'raw_count': len(features), 'campus_count': len(normalized),
                          'invalid_geometry_count': skipped,
                          'notes': '등록 자료이며 현장 실측 보증 아님. 0/결측 높이는 미등록 처리.'},
             'raw_api_responses': pages,
             'normalized': {'type': 'FeatureCollection', 'features': normalized}}
    save_json(cache_path, cache)
    return cache


def load_cache(path, campus):
    path = Path(path)
    if not path.exists():
        return None
    try:
        cache = json.loads(path.read_text(encoding='utf-8'))
        if cache['schema_version'] != SCHEMA_VERSION or cache['campus_id'] != campus_id(campus):
            raise ValueError()
        # Derive normalized data from saved raw pages; avoid trusting stale processed fields.
        raw = [f for page in cache['raw_api_responses']
               for f in page.get('response', {}).get('result', {}).get('featureCollection', {}).get('features', [])]
        normalized, skipped = normalize(raw, campus)
        cache['normalized'] = {'type': 'FeatureCollection', 'features': normalized}
        return cache
    except (OSError, ValueError, KeyError, TypeError):
        raise PublicDataError('공공데이터 캐시를 읽을 수 없거나 캠퍼스 범위가 달라졌습니다. 다시 조회해 주세요.') from None


def match_buildings(osm_features, public_features):
    """Conservative, mutual one-to-one polygon match in metres; never name-only."""
    public = [(f, transform(TO_M, shape(f['geometry']))) for f in public_features]
    candidates = []
    for feature in osm_features:
        geom = transform(TO_M, shape(feature['geometry']))
        options = []
        if geom.is_valid and not geom.is_empty:
            for index, (pub, other) in enumerate(public):
                if geom.distance(other) > MATCH_RULE['nearby_candidate_distance_m']:
                    continue
                intersection = geom.intersection(other).area
                union = geom.area + other.area - intersection
                iou = intersection / union if union else 0
                coverage = min(intersection / geom.area, intersection / other.area)
                distance = geom.centroid.distance(other.centroid)
                options.append({'index': index, 'iou': iou, 'coverage': coverage, 'distance_m': distance})
        candidates.append(sorted(options, key=lambda o: o['iou'], reverse=True))
    matches = {}
    for feature, options in zip(osm_features, candidates):
        match = {'status': '자료 없음', 'public': None, 'iou': None, 'distance_m': None,
                 'candidate_ids': [], 'reason': '캠퍼스 공공자료에서 주변 건물 후보 없음'}
        if options:
            top = options[0]
            match.update(status='매칭 불확실', iou=round(top['iou'], 4),
                         distance_m=round(top['distance_m'], 2),
                         candidate_ids=[public[o['index']][0]['id'] for o in options[:3]],
                         reason='겹침·거리·유일성 기준을 모두 충족하지 않음')
            runner_up = options[1]['iou'] if len(options) > 1 else 0
            # Reject a public footprint strongly competing for another OSM footprint.
            competing = max((o['iou'] for other in candidates if other is not options
                             for o in other if o['index'] == top['index']), default=0)
            if (top['iou'] >= MATCH_RULE['iou_min'] and
                    top['coverage'] >= MATCH_RULE['each_coverage_min'] and
                    top['distance_m'] <= MATCH_RULE['centroid_distance_max_m'] and
                    top['iou'] - runner_up >= MATCH_RULE['runner_up_iou_margin'] and
                    top['iou'] - competing >= MATCH_RULE['runner_up_iou_margin']):
                match.update(status='매칭 확인', public=public[top['index']][0]['properties'],
                             reason='윤곽 겹침·양쪽 면적·중심점 거리·양방향 유일성 통과')
        matches[str(feature['properties']['osm_id'])] = match
    return matches


def resolve_height(properties, manual, match, floor_height=3., fallback=15., include_unknown=True):
    public = match.get('public') or {}
    is_gis = public.get('source_kind') == 'local_gis'
    choices = [(positive(manual), '사용자 입력'),
               (positive(public.get('height_m')), 'GIS 실제 높이' if is_gis else '공공데이터 높이'),
               ((floors(public.get('aboveground_floors')) or 0) * floor_height, 'GIS 층수 기반 추정' if is_gis else '공공데이터 층수 기반 추정'),
               (positive(properties.get('height')), 'OSM 높이'),
               ((positive(properties.get('levels')) or 0) * floor_height, 'OSM 층수 기반 추정')]
    for value, source in choices:
        if value and math.isfinite(value) and value > 0:
            return float(value), source
    return (float(fallback), '미등록 · 가정 높이') if include_unknown else (None, '높이 미등록 · 계산 제외')

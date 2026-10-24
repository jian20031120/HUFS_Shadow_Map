"""Local AL_D010 SHP reader: inspect headers, bbox-filter in native CRS, cache subset."""
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib

import pandas as pd
import pyogrio
from pyproj import CRS, Transformer
from shapely.geometry import mapping
from public_buildings import PublicDataError, campus_id, positive, floors, save_json

STEMS = ('AL_D010_41_20260909', 'AL_D010_41_20260909(2)', 'AL_D010_41_20260909(3)')
FIELDS = {'id': 'A1', 'height_m': 'A16', 'aboveground_floors': 'A26',
          'name': 'A24', 'dong_name': 'A25', 'data_date': 'A22'}
COLUMNS = ['A0', 'A1', 'A4', 'A5', 'A16', 'A22', 'A24', 'A25', 'A26', 'A28']
DEFINITION = 'https://www.ktdb.go.kr/DATA/pblcte/20250805093928585.pdf'
SOURCE = '국토교통부 · VWorld 경기도 GIS건물통합정보 SHP'
VERSION = 2
MAX_LOCAL_ROWS = 10000


def scalar(value):
    if pd.isna(value):
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value.item() if hasattr(value, 'item') else value


def manifest(folder):
    folder = Path(folder)
    entries = []
    for stem in STEMS:
        for ext in ('.shp', '.dbf', '.shx', '.prj', '.fix'):
            path = folder / (stem + ext)
            if not path.is_file():
                raise PublicDataError(f'SHP 묶음의 파일이 없습니다: {path.name} (data/public_buildings 폴더 확인)')
            stat = path.stat()
            entries.append({'file': path.name, 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
    return entries


def load_gis(folder, campus, cache_path, refresh=False):
    """Never read a province-wide GeoDataFrame. At most MAX_LOCAL_ROWS+1 per bbox."""
    files = manifest(folder)
    signature = hashlib.sha256(json.dumps({'files': files, 'campus': campus_id(campus),
                                          'version': VERSION}, sort_keys=True).encode()).hexdigest()
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            if cached['signature'] == signature:
                return cached
        except (OSError, ValueError, KeyError):
            pass  # Rebuild from local files, never interpret an incompatible cache.
    reports, raw_subsets, normalized = [], [], []
    ids = {}
    duplicates = 0
    invalid = 0
    for stem in STEMS:
        path = Path(folder) / (stem + '.shp')
        try:
            info = pyogrio.read_info(path, encoding='CP949')
            if not info['crs']:
                raise PublicDataError(f'{path.name}: CRS가 없습니다.')
            crs = CRS.from_user_input(info['crs'])
            fields = list(info['fields'])
            missing = set(FIELDS.values()) - set(fields)
            if missing:
                raise PublicDataError(f'{path.name}: 확인된 AL_D010 필드가 없습니다: {sorted(missing)}')
            bounds = Transformer.from_crs(4326, crs, always_xy=True).transform_bounds(*campus.bounds)
            frame = pyogrio.read_dataframe(path, bbox=bounds, columns=COLUMNS,
                                            max_features=MAX_LOCAL_ROWS + 1, encoding='CP949')
            if len(frame) > MAX_LOCAL_ROWS:
                raise PublicDataError(f'{path.name}: 캠퍼스 bbox 조회 한도를 초과했습니다.')
            reports.append({'file': path.name, 'crs': crs.to_string(), 'encoding': 'CP949',
                            'fields': fields, 'dtypes': [str(t) for t in info['dtypes']],
                            'source_feature_count': int(info['features']),
                            'bbox_native_crs': list(bounds), 'bbox_count': len(frame)})
            # Small original-coordinate subset, explicitly labelled with its source CRS.
            raw_subsets.append({'file': path.name, 'crs': crs.to_string(),
                                'records': [{'geometry': mapping(row.geometry) if row.geometry is not None else None,
                                             'properties': {k: scalar(row[k]) for k in COLUMNS}}
                                            for _, row in frame.iterrows()]})
            frame = frame.to_crs(4326)
            for _, row in frame.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty or not geom.is_valid or geom.geom_type not in ('Polygon', 'MultiPolygon'):
                    invalid += 1
                    continue
                if not campus.intersects(geom):
                    continue
                identifier = scalar(row['A1'])
                if not identifier:
                    invalid += 1
                    continue
                identifier = str(identifier)
                props = {'public_id': identifier, 'name': scalar(row['A24']) or '',
                         'dong_name': scalar(row['A25']) or '',
                         'A16': scalar(row['A16']), 'A26': scalar(row['A26']),
                         'height_m': positive(scalar(row['A16'])),
                         'aboveground_floors': floors(scalar(row['A26'])),
                         'source': SOURCE, 'source_kind': 'local_gis', 'source_url': DEFINITION,
                         'source_file': path.name, 'height_field': 'A16', 'floors_field': 'A26',
                         'data_date': scalar(row['A22'])}
                if identifier in ids:
                    previous = ids[identifier]
                    if (previous['geometry'] == mapping(geom) and
                        previous['properties']['height_m'] == props['height_m'] and
                        previous['properties']['aboveground_floors'] == props['aboveground_floors']):
                        duplicates += 1
                        continue
                    # Keep conflicting versions as competing candidates, never select one arbitrarily.
                    identifier = f'{identifier}@{path.stem}:{scalar(row["A0"])}'
                    props['public_id'] = identifier
                feature = {'type': 'Feature', 'id': identifier, 'geometry': mapping(geom), 'properties': props}
                ids[identifier] = feature
                normalized.append(feature)
        except PublicDataError:
            raise
        except Exception as error:
            raise PublicDataError(f'{path.name}: SHP 읽기에 실패했습니다 ({type(error).__name__}). 묶음 파일과 인코딩을 확인하세요.') from None
    result = {'signature': signature, 'schema_version': VERSION,
              'metadata': {'source': SOURCE, 'source_url': DEFINITION,
                           'retrieved_at': datetime.now(timezone.utc).isoformat(),
                           'field_mapping': FIELDS, 'source_files': files, 'inspection': reports,
                           'bbox_wgs84': list(campus.bounds), 'campus_id': campus_id(campus),
                           'raw_count': sum(r['bbox_count'] for r in reports),
                           'campus_count': len(normalized), 'invalid_geometry_count': invalid,
                           'duplicates_removed': duplicates,
                           'notes': '원본 좌표의 bbox 부분집합과 WGS84 가공 자료를 분리. 높이 0은 미등록.'},
              'raw_bbox_subsets': raw_subsets,
              'normalized': {'type': 'FeatureCollection', 'features': normalized}}
    save_json(cache_path, result)
    return result

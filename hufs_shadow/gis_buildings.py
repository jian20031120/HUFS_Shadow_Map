"""Read the bundled campus GIS snapshot without importing GIS file drivers."""
import json
from pathlib import Path
from .data_utils import PublicDataError, campus_id

VERSION = 2


def load_snapshot(cache_path, campus):
    """Explicit offline mode; never claim the source manifest was verified."""
    try:
        cached = json.loads(Path(cache_path).read_text(encoding='utf-8'))
        if cached['schema_version'] != VERSION or cached['metadata']['campus_id'] != campus_id(campus):
            raise ValueError('캠퍼스 또는 스키마가 다릅니다.')
        from shapely.geometry import shape
        features = cached['normalized']['features']
        if not features:
            raise ValueError('건물 자료가 없습니다.')
        for feature in features:
            geom = shape(feature['geometry'])
            if geom.is_empty or not geom.is_valid or geom.geom_type not in ('Polygon','MultiPolygon') or not geom.intersects(campus):
                raise ValueError('유효하지 않은 캠퍼스 건물입니다.')
            if not feature['properties']['public_id']:
                raise ValueError('건물 ID가 없습니다.')
        cached['metadata']['load_mode'] = 'bundled_snapshot_unverified_source'
        return cached
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PublicDataError(f'캠퍼스 스냅샷을 읽을 수 없습니다: {error}') from error

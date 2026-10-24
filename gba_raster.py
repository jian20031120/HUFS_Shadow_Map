"""Area-weighted sampling of the local 3 m GBA height estimate raster.

Pixel dispersion describes the sampled image; it is not a confidence interval.
Small polygons can share a mixed pixel with ground, trees or nearby structures.
"""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.ops import transform

from public_buildings import PublicDataError, campus_id
from shadow_model import TO_M


def load_height_raster(path, meta_path, campus):
    try:
        meta = json.loads(Path(meta_path).read_text(encoding='utf-8'))
        if (meta['schema_version'] != 1 or meta['campus_id'] != campus_id(campus)
                or meta['crs'] != 'EPSG:32652' or meta['resolution_m'] != 3
                or meta['height_kind'] != 'machine_learning_estimate_not_survey'):
            raise ValueError('GBA 높이 격자 캠퍼스·좌표계 불일치')
        path = Path(path)
        if path.stat().st_size > 10_000_000 or hashlib.sha256(path.read_bytes()).hexdigest() != meta['npz_sha256']:
            raise ValueError('GBA 격자 파일 크기 또는 해시 불일치')
        with np.load(path, allow_pickle=False) as data:
            height, affine = data['height'].copy(), data['transform'].copy()
        if height.ndim != 2 or height.size > 1_000_000 or list(height.shape) != meta['shape']:
            raise ValueError('GBA 높이 격자 배열 크기 오류')
        a, b, c, d, e, f = affine
        if a != 3 or e != -3 or b != 0 or d != 0 or not np.all(np.isfinite(affine)):
            raise ValueError('지원하지 않는 GBA 격자 변환')
        return {'height': height, 'transform': affine, 'metadata': meta}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PublicDataError(f'GBA 높이 격자를 읽을 수 없습니다: {error}') from error


def weighted_quantile(values, weights, probability):
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    index = min(int(np.searchsorted(cumulative, probability * cumulative[-1])), len(order)-1)
    return float(values[order[index]])


def sample_height(feature, raster):
    geom = transform(TO_M, shape(feature['geometry']))
    grid = raster['height']
    a, _, origin_x, _, e, origin_y = raster['transform']
    west, south, east, north = geom.bounds
    col0, col1 = max(0, int(np.floor((west-origin_x)/a))), min(grid.shape[1], int(np.ceil((east-origin_x)/a)))
    row0, row1 = max(0, int(np.floor((north-origin_y)/e))), min(grid.shape[0], int(np.ceil((south-origin_y)/e)))
    result = {'public_id': feature['properties']['public_id'], 'accepted': False,
              'height_m': None, 'status': '격자 범위 밖', 'pixel_count': 0,
              'valid_area_ratio': 0.0, 'positive_area_ratio': 0.0,
              'pixel_p10_m': None, 'pixel_p90_m': None,
              'pixel_median_m': None,
              'footprint_area_m2': geom.area, 'resolution_m': 3,
              'confidence': '미확인', 'max_pixel_purity': 0.0}
    if col0 >= col1 or row0 >= row1:
        return result
    columns, rows = np.meshgrid(np.arange(col0, col1), np.arange(row0, row1))
    x, y = origin_x + a*columns.ravel(), origin_y + e*rows.ravel()
    cells = shapely.box(x, y+e, x+a, y)
    weights = shapely.area(shapely.intersection(cells, geom))
    values = grid[row0:row1, col0:col1].ravel()
    inside = weights > 1e-8
    valid = inside & np.isfinite(values) & (values >= 0) & (values <= 200)
    positive = valid & (values >= 1)
    result.update(pixel_count=int(inside.sum()),
                  valid_area_ratio=min(1.0, float(weights[valid].sum()/geom.area)),
                  positive_area_ratio=min(1.0, float(weights[positive].sum()/geom.area)),
                  max_pixel_purity=float(weights.max()/9))
    if result['valid_area_ratio'] < 0.80:
        result['status'] = '유효 격자 면적 부족 · 적용 안 함'
        return result
    median = weighted_quantile(values[valid], weights[valid], 0.5)
    result.update(pixel_median_m=median,
                  pixel_p10_m=weighted_quantile(values[valid], weights[valid], 0.1),
                  pixel_p90_m=weighted_quantile(values[valid], weights[valid], 0.9))
    if result['positive_area_ratio'] < 0.50:
        result['status'] = '1m 이상 높이가 도형의 절반 미만 · 적용 안 함'
        return result
    if median < 1:
        result['status'] = '높이 중앙값 1m 미만 · 적용 안 함'
        return result
    result.update(accepted=True, height_m=median,
                  pixel_p10_m=weighted_quantile(values[valid], weights[valid], 0.1),
                  pixel_p90_m=weighted_quantile(values[valid], weights[valid], 0.9),
                  confidence='매우 낮음 · 작은 도형/혼합 픽셀' if geom.area < 36 or result['max_pixel_purity'] < 0.5 else '낮음 · 위성 추정',
                  status='3m 격자 면적 가중 중앙값 · 실물 높이 검증 전')
    return result


def sample_all(features, raster):
    return {f['properties']['public_id']: sample_height(f, raster) for f in features}


def apply_raster(features, samples, enabled=True):
    result = copy.deepcopy(features)
    for feature in result:
        props = feature['properties']
        sample = samples.get(props['public_id'])
        props.pop('gba_raster_height_m', None)
        props['gba_raster_sample'] = copy.deepcopy(sample)
        if enabled and sample and sample['accepted']:
            props['gba_raster_height_m'] = sample['height_m']
    return result

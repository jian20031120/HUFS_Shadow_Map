"""Download a campus subset of the public GBA LoD1 GeoParquet distribution.

Uses HTTP byte ranges and row-group bounding boxes, never the viewer's WFS.
Run explicitly; the Streamlit app only reads the resulting local file.
"""
import io
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
import requests
from shapely import from_wkb
from shapely.geometry import mapping, shape

from public_buildings import campus_id, save_json

ROOT = Path(__file__).parent
TILE_URL = 'https://data.source.coop/tge-labs/globalbuildingatlas-lod1/e125_n40_e130_n35.parquet'
SOURCE_PAGE = 'https://source.coop/tge-labs/globalbuildingatlas-lod1'


def feature_id(geometry, source, source_id):
    # Some source rows all use id=0. Keep that original id in properties.
    key = geometry.wkb + str(source).encode() + b':' + str(source_id).encode()
    return 'GBA-' + hashlib.sha256(key).hexdigest()[:24]


class HTTPRangeFile(io.RawIOBase):
    """Seekable, bounded HTTP reader for PyArrow. Rejects full-file responses."""
    def __init__(self, url, budget=80 * 1024 * 1024, probe_range=False, range_cache_key=False):
        self.url, self.budget = url, budget
        self.range_cache_key = range_cache_key
        self.session = requests.Session()
        self.etag = None
        self.pos = self.downloaded = 0
        length = None
        if not probe_range:
            response = self.session.head(url, timeout=45, allow_redirects=True)
            response.raise_for_status()
            self.etag = response.headers.get('ETag')
            length = response.headers.get('Content-Length')
            response.close()
        if length:
            self.size = int(length)
        else:
            # Public Nextcloud downloads can omit Content-Length on HEAD.
            with self.session.get(self.range_url(0, 99), headers={'Range': 'bytes=0-99', 'Accept-Encoding': 'identity'},
                                  stream=True, timeout=45) as probe:
                probe.raise_for_status()
                match = re.fullmatch(r'bytes 0-99/(\d+)', probe.headers.get('Content-Range', ''))
                if probe.status_code != 206 or not match or len(probe.raw.read(101)) != 100:
                    raise ValueError('Server does not support bounded range access')
                self.size = int(match.group(1))
                self.etag = probe.headers.get('ETag', self.etag)
                self.downloaded = 100

    def range_url(self, start, end):
        # Some download caches reuse the first Range response for the same URL.
        # The public server ignores this query argument; every response is still
        # checked against the exact requested Content-Range before any bytes are used.
        return self.url + ('&' if '?' in self.url else '?') + f'byte_range={start}-{end}' if self.range_cache_key else self.url

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        target = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        if whence not in (0, 1, 2) or target < 0:
            raise ValueError('Invalid seek')
        self.pos = target
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n < 0 else min(n, self.size - self.pos)
        if n <= 0:
            return b''
        if n + self.downloaded > self.budget:
            raise ValueError('Download budget exceeded; refusing a large regional download')
        headers = {'Range': f'bytes={self.pos}-{self.pos + n - 1}', 'Accept-Encoding': 'identity'}
        if self.etag:
            headers['If-Match'] = self.etag
        with self.session.get(self.range_url(self.pos, self.pos + n - 1), headers=headers, timeout=60, stream=True) as response:
            response.raise_for_status()
            expected = f'bytes {self.pos}-{self.pos + n - 1}/{self.size}'
            if response.status_code != 206 or response.headers.get('Content-Range') != expected:
                raise ValueError('Server did not honor the requested byte range')
            content = response.raw.read(n + 1)
            if len(content) != n:
                raise ValueError('Incomplete or oversized byte range')
        self.pos += n
        self.downloaded += n
        return content

    def close(self):
        self.session.close()
        super().close()


def intersects_bounds(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def select_row_groups(parquet, bounds):
    selected = []
    for index in range(parquet.num_row_groups):
        group = parquet.metadata.row_group(index)
        stats = {group.column(i).path_in_schema: group.column(i).statistics
                 for i in range(group.num_columns)}
        columns = ['bbox.xmin', 'bbox.ymin', 'bbox.xmax', 'bbox.ymax']
        if not all(stats.get(name) and stats[name].has_min_max for name in columns):
            raise ValueError('Spatial statistics unavailable; refusing a full scan')
        group_bounds = (stats[columns[0]].min, stats[columns[1]].min,
                        stats[columns[2]].max, stats[columns[3]].max)
        if intersects_bounds(group_bounds, bounds):
            selected.append(index)
    return selected


def download_campus(campus, output_path):
    bounds = campus.bounds
    if not (125 <= bounds[0] < bounds[2] <= 130 and 35 <= bounds[1] < bounds[3] <= 40):
        raise ValueError('This downloader is restricted to the HUFS regional tile')
    with HTTPRangeFile(TILE_URL) as remote:
        parquet = pq.ParquetFile(remote)
        geo = json.loads(parquet.schema_arrow.metadata[b'geo'])
        # This distributor reprojects to WGS84; upstream GeoJSON is EPSG:3857.
        column = geo['columns']['geometry']
        if 'crs' in column:
            from pyproj import CRS
            if not CRS.from_user_input(column['crs']).equals(CRS.from_epsg(4326), ignore_axis_order=True):
                raise ValueError('Unexpected coordinate reference system')
        groups = select_row_groups(parquet, bounds)
        if sum(parquet.metadata.row_group(i).num_rows for i in groups) > 200000:
            raise ValueError('Campus query exceeds the row limit')
        print(f'Reading {len(groups)}/{parquet.num_row_groups} spatial row groups', flush=True)
        features = []
        for index in groups:
            table = parquet.read_row_group(index)
            for row in table.to_pylist():
                box = row['bbox']
                if not intersects_bounds((box['xmin'], box['ymin'], box['xmax'], box['ymax']), bounds):
                    continue
                geom = from_wkb(row['geometry'])
                if geom.is_empty or not geom.is_valid or geom.geom_type not in ('Polygon', 'MultiPolygon'):
                    continue
                if not geom.intersects(campus):
                    continue
                features.append({'type': 'Feature', 'id': feature_id(geom, row['source'], row['id']), 'geometry': mapping(geom),
                                 'properties': {k: row[k] for k in ('id', 'source', 'height', 'var', 'region')}})
            print(f'Row group {index}: {len(features)} campus polygons so far', flush=True)
        result = {'type': 'FeatureCollection', 'features': features,
                  'metadata': {'schema_version': 1, 'dataset': 'GlobalBuildingAtlas LoD1',
                               'distribution': SOURCE_PAGE, 'tile_url': TILE_URL,
                               'tile_etag': remote.etag, 'crs': 'OGC:CRS84',
                               'campus_id': campus_id(campus), 'bbox_wgs84': list(bounds),
                               'retrieved_at': datetime.now(timezone.utc).isoformat(),
                               'downloaded_bytes': remote.downloaded, 'row_groups': groups,
                               'upstream': 'https://github.com/zhu-xlab/GlobalBuildingAtlas',
                               'paper': 'https://doi.org/10.5194/essd-17-6647-2025',
                               'height_kind': 'machine_learning_estimate_not_survey',
                               'imagery_years': [2018, 2019],
                               'license_note': 'Height/LoD1: CC BY-NC 4.0; OSM/Microsoft footprint sources: ODbL. See upstream split-data license notice.'}}
    if not features:
        raise ValueError('No campus features returned; existing data left unchanged')
    save_json(output_path, result)
    print(f'Saved {len(features)} features; transferred {result["metadata"]["downloaded_bytes"]:,} bytes', flush=True)
    return result


if __name__ == '__main__':
    campus = shape(json.loads((ROOT / 'data/campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
    download_campus(campus, ROOT / 'data/gba_campus.geojson')

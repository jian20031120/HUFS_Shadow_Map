"""Fetch one GBA.Height ZIP member, then retain a small HUFS raster subset.

The 84 GB regional ZIP is never downloaded. HTTP ranges select a ~198 MB
compressed member using the ZIP central directory; zipfile checks its CRC.
"""
import json
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from shapely.geometry import shape

from fetch_gba import HTTPRangeFile
from public_buildings import campus_id, save_json

ROOT = Path(__file__).parent
URL = 'https://dataserv.ub.tum.de/s/m1782307/download?path=%2FHeight%2Fasiaeast&files=e125_n40_e130_n35.zip'
MEMBER = '127.2_37.4_127.4_37.2_sr_ss.tif'


def fetch():
    campus = shape(json.loads((ROOT/'data/campus_boundary.geojson').read_text(encoding='utf-8'))['geometry'])
    folder = ROOT/'.test_tmp'
    folder.mkdir(exist_ok=True)
    tile = folder/'gba_height_tile.tif'
    download_info = folder/'gba_height_download.json'
    if not tile.exists():
        with HTTPRangeFile(URL, budget=260_000_000, probe_range=True, range_cache_key=True) as remote:
            with zipfile.ZipFile(remote) as archive:
                item = archive.getinfo(MEMBER)
                if item.compress_size > 240_000_000 or item.file_size > 260_000_000:
                    raise ValueError('Unexpectedly large campus member; download refused')
                print(f'Downloading campus member: {item.compress_size:,} compressed bytes', flush=True)
                payload = archive.read(item)  # verifies decompression and ZIP member CRC
                tile.write_bytes(payload)
                info = {'zip_url': URL, 'zip_bytes': remote.size, 'zip_etag': remote.etag,
                        'member': MEMBER, 'member_bytes': item.file_size, 'member_crc32': f'{item.CRC:08x}',
                        'member_sha256': hashlib.sha256(payload).hexdigest(),
                        'downloaded_bytes': remote.downloaded,
                        'retrieved_at': datetime.now(timezone.utc).isoformat()}
                save_json(download_info, info)
                del payload
                print('Member downloaded and CRC checked', flush=True)
    info = json.loads(download_info.read_text(encoding='utf-8'))
    if tile.stat().st_size != info['member_bytes'] or hashlib.sha256(tile.read_bytes()).hexdigest() != info['member_sha256']:
        raise ValueError('Cached source tile does not match its verified download metadata')
    with rasterio.open(tile) as dataset:
        if dataset.count != 1 or dataset.crs.to_epsg() != 32652 or dataset.res != (3.0, 3.0):
            raise ValueError(f'Unexpected raster schema: {dataset.count}, {dataset.crs}, {dataset.res}')
        bounds = transform_bounds('EPSG:4326', dataset.crs, *campus.buffer(0.0005).bounds)
        window = from_bounds(*bounds, transform=dataset.transform).round_offsets().round_lengths()
        heights = dataset.read(1, window=window)
        affine = dataset.window_transform(window)
        path = ROOT/'data/gba_height_campus.npz'
        np.savez_compressed(path, height=heights, transform=np.array(tuple(affine)[:6]))
        info.update(schema_version=1, dataset='GlobalBuildingAtlas Height',
                    crs='EPSG:32652', resolution_m=3, nodata=dataset.nodata,
                    shape=list(heights.shape), campus_id=campus_id(campus),
                    height_kind='machine_learning_estimate_not_survey', imagery_years=[2018, 2019],
                    paper='https://doi.org/10.5194/essd-17-6647-2025',
                    official_release='https://mediatum.ub.tum.de/1782307',
                    license='CC BY-NC 4.0', npz_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        save_json(ROOT/'data/gba_height_campus_meta.json', info)
        print(json.dumps({'shape': info['shape'], 'nodata': info['nodata'],
                          'min': float(np.nanmin(heights)), 'max': float(np.nanmax(heights)),
                          'subset_bytes': path.stat().st_size, 'downloaded_bytes': info['downloaded_bytes']}), flush=True)


if __name__ == '__main__':
    fetch()

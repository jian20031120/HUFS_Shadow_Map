"""공개 API 원본을 캠퍼스 경계로 필터링하고 로컬 스냅샷을 저장."""
import json, time, re
from pathlib import Path
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import numpy as np
import requests
from shapely.geometry import Polygon, mapping
from shapely.ops import transform
from pyproj import Transformer

OUT=Path(__file__).parent / 'data'
OUT.mkdir(exist_ok=True)
response=requests.get('https://api.openstreetmap.org/api/0.6/map',
    params={'bbox':'127.253,37.331,127.279,37.342'},timeout=60)
response.raise_for_status()
r=ET.fromstring(response.content)
nodes={n.get('id'):(float(n.get('lon')),float(n.get('lat'))) for n in r.findall('node')}
def tags(e):
    return {t.get('k'):t.get('v') for t in e.findall('tag')}
def polygon(e):
    refs=[n.get('ref') for n in e.findall('nd')]
    if len(refs)<4 or refs[0]!=refs[-1] or any(n not in nodes for n in refs):
        return None
    p=Polygon([nodes[n] for n in refs])
    return p if p.is_valid else p.buffer(0)
campus_way=next(w for w in r.findall('way') if tags(w).get('name')=='한국외국어대학교 글로벌캠퍼스')
campus=polygon(campus_way)
features=[]
for w in r.findall('way'):
    t=tags(w)
    if t.get('building') in (None,'no'):
        continue
    p=polygon(w)
    if p is None or p.is_empty or not campus.covers(p.representative_point()):
        continue
    features.append({'type':'Feature','geometry':mapping(p),'properties':{
        'osm_id':w.get('id'),'name':t.get('name',f'이름 미등록 건물 {w.get("id")}'),
        'height':t.get('height'),'levels':t.get('building:levels'),
        'source_url':f'https://www.openstreetmap.org/way/{w.get("id")}',
        'osm_updated':w.get('timestamp')}})
stamp=datetime.now(timezone.utc).isoformat()
data={'type':'FeatureCollection','features':features,'campus':mapping(campus),
      'metadata':{'retrieved_at':stamp,'source':'https://api.openstreetmap.org/api/0.6/map?bbox=127.253,37.331,127.279,37.342',
                  'license':'ODbL 1.0 / © OpenStreetMap contributors','boundary_osm_id':campus_way.get('id')}}
(OUT/'buildings.geojson').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print('Buildings:',len(features),flush=True)
to_m=Transformer.from_crs(4326,32652,always_xy=True).transform
to_g=Transformer.from_crs(32652,4326,always_xy=True).transform
xmin,ymin,xmax,ymax=transform(to_m,campus).bounds
# 60m 표본 간격. 건물 단위 고정밀 지형으로 오해하지 않도록 앱에 표시합니다.
xs=np.arange(np.floor((xmin-300)/60)*60, xmax+360,60)
ys=np.arange(np.floor((ymin-300)/60)*60, ymax+360,60)
xx,yy=np.meshgrid(xs,ys)
lon,lat=to_g(xx.ravel(),yy.ravel())
values=[]
session=requests.Session()
for start in range(0,len(lon),100):
    locations='|'.join(f'{a:.6f},{b:.6f}' for a,b in zip(lat[start:start+100],lon[start:start+100]))
    res=session.get('https://api.opentopodata.org/v1/aster30m',params={'locations':locations},timeout=30)
    res.raise_for_status()
    payload=res.json()
    if payload.get('status')!='OK':
        raise RuntimeError(payload)
    batch=[v['elevation'] for v in payload['results']]
    if len(batch)!=len(lon[start:start+100]) or any(v is None for v in batch):
        raise RuntimeError('Missing elevations')
    values.extend(batch)
    print('Elevation',len(values),'/',len(lon),flush=True)
    time.sleep(1.1)
np.savez_compressed(OUT/'terrain.npz',x=xs,y=ys,z=np.array(values).reshape(xx.shape))
(OUT/'terrain_meta.json').write_text(json.dumps({'source':'https://api.opentopodata.org/v1/aster30m',
    'dataset':'ASTER GDEM v3','nominal_resolution_m':30,'sample_spacing_m':60,
    'retrieved_at':stamp,'note':'거친 지형 근사. 수목·건물 표면 오차 및 관측 시기 차이 가능.'},ensure_ascii=False,indent=2))
